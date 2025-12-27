"""
Runtime Environment Management for ck3raven.

This module provides centralized handling of:
1. Python environment detection and command transformation
2. Dependency validation (installed packages)
3. External tool availability (git, etc.)
4. Startup validation for fail-fast behavior

The Problems This Solves:
- Windows Store Python stub can hang when invoked via subprocess
- Missing dependencies cause cryptic errors deep in call stacks
- External tools (git) may not be available
- No clear error messages for users on first run

Usage:
    from ck3lens.runtime_env import validate_startup, get_python_env
    
    # At MCP server startup
    result = validate_startup()
    if not result.is_ready:
        print(result.error_message)
        print(result.fix_instructions)
        sys.exit(1)
    
    # For command transformation
    env = get_python_env()
    safe_cmd = env.transform_command("python script.py")
"""

import sys
import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# =============================================================================
# Python Environment
# =============================================================================

@dataclass
class PythonEnvironment:
    """
    Python environment information and utilities.
    
    Handles:
    - Detecting the current Python interpreter
    - Transforming "python" commands to use explicit path
    - Checking if modules are available
    """
    executable: Path
    version: Tuple[int, int, int]
    is_venv: bool = False
    is_windows_store: bool = False
    _validation_error: Optional[str] = None
    
    @classmethod
    def detect(cls) -> "PythonEnvironment":
        """Detect the current Python environment from sys.executable."""
        exe = Path(sys.executable)
        
        is_venv = hasattr(sys, 'real_prefix') or (
            hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
        )
        is_windows_store = "WindowsApps" in str(exe)
        
        env = cls(
            executable=exe,
            version=sys.version_info[:3],
            is_venv=is_venv,
            is_windows_store=is_windows_store,
        )
        env._validate()
        return env
    
    def _validate(self) -> None:
        """Validate the Python environment."""
        if not self.executable.exists():
            self._validation_error = f"Python executable not found: {self.executable}"
            return
        
        if self.is_windows_store and not self.is_venv:
            logger.warning(
                "Using Windows Store Python directly. Consider using a venv."
            )
        
        if self.version < (3, 10):
            self._validation_error = f"Python {self.version_str} is below minimum (3.10)"
    
    @property
    def is_valid(self) -> bool:
        return self._validation_error is None
    
    @property
    def version_str(self) -> str:
        return ".".join(str(v) for v in self.version)
    
    def transform_command(self, command: str) -> str:
        """
        Transform a command to use the correct Python executable.
        
        "python script.py" -> '"C:/path/to/python.exe" script.py'
        """
        cmd = command.strip()
        
        patterns = [
            ("python3 ", 8),
            ("python ", 7),
            ("python.exe ", 11),
        ]
        
        for pattern, prefix_len in patterns:
            if cmd.startswith(pattern):
                rest = cmd[prefix_len:]
                return f'"{self.executable}" {rest}'
        
        if cmd in ("python", "python3", "python.exe"):
            return f'"{self.executable}"'
        
        return command
    
    def run_python(
        self,
        args: List[str],
        cwd: Optional[Path] = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess:
        """Run Python with the correct interpreter."""
        return subprocess.run(
            [str(self.executable)] + args,
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    
    def check_module(self, module_name: str) -> bool:
        """Check if a module can be imported."""
        try:
            result = self.run_python(["-c", f"import {module_name}"], timeout=10)
            return result.returncode == 0
        except Exception:
            return False
    
    def get_info(self) -> dict:
        """Get environment info as dictionary."""
        return {
            "executable": str(self.executable),
            "version": self.version_str,
            "is_venv": self.is_venv,
            "is_windows_store": self.is_windows_store,
            "is_valid": self.is_valid,
            "validation_error": self._validation_error,
        }


# =============================================================================
# Dependency Checker
# =============================================================================

@dataclass
class DependencyStatus:
    """Status of a single dependency."""
    name: str
    required: bool
    installed: bool
    version: Optional[str] = None
    error: Optional[str] = None


@dataclass 
class DependencyChecker:
    """
    Validates that required Python packages are installed.
    
    Checks both required and optional dependencies, providing
    clear instructions for installing missing ones.
    """
    python_env: PythonEnvironment
    
    # Core dependencies that MUST be present
    REQUIRED_PACKAGES: List[str] = field(default_factory=lambda: [
        "pyyaml",      # Builder config
    ])
    
    # Optional packages that enhance functionality
    OPTIONAL_PACKAGES: List[str] = field(default_factory=lambda: [
        "pytest",      # For testing
    ])
    
    def check_package(self, package: str) -> DependencyStatus:
        """Check if a package is installed and get its version."""
        # Normalize package name (pyyaml -> yaml for import)
        import_map = {
            "pyyaml": "yaml",
        }
        import_name = import_map.get(package.lower(), package.lower())
        
        try:
            result = self.python_env.run_python([
                "-c", 
                f"import {import_name}; print(getattr({import_name}, '__version__', 'unknown'))"
            ], timeout=10)
            
            if result.returncode == 0:
                return DependencyStatus(
                    name=package,
                    required=package in self.REQUIRED_PACKAGES,
                    installed=True,
                    version=result.stdout.strip(),
                )
            else:
                return DependencyStatus(
                    name=package,
                    required=package in self.REQUIRED_PACKAGES,
                    installed=False,
                    error=result.stderr.strip()[:100],
                )
        except Exception as e:
            return DependencyStatus(
                name=package,
                required=package in self.REQUIRED_PACKAGES,
                installed=False,
                error=str(e),
            )
    
    def check_all(self) -> List[DependencyStatus]:
        """Check all required and optional packages."""
        results = []
        for pkg in self.REQUIRED_PACKAGES:
            results.append(self.check_package(pkg))
        for pkg in self.OPTIONAL_PACKAGES:
            results.append(self.check_package(pkg))
        return results
    
    def get_missing_required(self) -> List[str]:
        """Get list of missing required packages."""
        missing = []
        for pkg in self.REQUIRED_PACKAGES:
            status = self.check_package(pkg)
            if not status.installed:
                missing.append(pkg)
        return missing
    
    def get_install_command(self, packages: List[str]) -> str:
        """Get pip install command for missing packages."""
        if not packages:
            return ""
        pkg_str = " ".join(packages)
        pip_path = self.python_env.executable.parent / "pip.exe"
        if pip_path.exists():
            return f'"{pip_path}" install {pkg_str}'
        return f'"{self.python_env.executable}" -m pip install {pkg_str}'


# =============================================================================
# External Tools Checker
# =============================================================================

@dataclass
class ExternalToolStatus:
    """Status of an external tool."""
    name: str
    required: bool
    available: bool
    path: Optional[str] = None
    version: Optional[str] = None
    error: Optional[str] = None


class ExternalToolsChecker:
    """
    Validates that required external tools are available.
    
    Checks for tools like git that are needed for full functionality.
    """
    
    # Tools and their version check commands
    TOOLS = {
        "git": {
            "required": True,
            "version_cmd": ["git", "--version"],
        },
    }
    
    def check_tool(self, name: str) -> ExternalToolStatus:
        """Check if a tool is available and get its version."""
        tool_config = self.TOOLS.get(name)
        if not tool_config:
            return ExternalToolStatus(
                name=name,
                required=False,
                available=False,
                error=f"Unknown tool: {name}",
            )
        
        # Check if tool exists in PATH
        tool_path = shutil.which(name)
        if not tool_path:
            return ExternalToolStatus(
                name=name,
                required=tool_config["required"],
                available=False,
                error=f"{name} not found in PATH",
            )
        
        # Get version
        try:
            result = subprocess.run(
                tool_config["version_cmd"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            version = result.stdout.strip().split('\n')[0] if result.returncode == 0 else None
            
            return ExternalToolStatus(
                name=name,
                required=tool_config["required"],
                available=True,
                path=tool_path,
                version=version,
            )
        except Exception as e:
            return ExternalToolStatus(
                name=name,
                required=tool_config["required"],
                available=False,
                path=tool_path,
                error=str(e),
            )
    
    def check_all(self) -> List[ExternalToolStatus]:
        """Check all configured tools."""
        return [self.check_tool(name) for name in self.TOOLS]
    
    def get_missing_required(self) -> List[str]:
        """Get list of missing required tools."""
        missing = []
        for name, config in self.TOOLS.items():
            if config["required"]:
                status = self.check_tool(name)
                if not status.available:
                    missing.append(name)
        return missing


# =============================================================================
# Startup Validation
# =============================================================================

@dataclass
class StartupValidationResult:
    """Result of startup validation."""
    is_ready: bool
    python_env: PythonEnvironment
    missing_packages: List[str] = field(default_factory=list)
    missing_tools: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    fix_instructions: Optional[str] = None
    
    def get_summary(self) -> dict:
        """Get validation summary as dictionary."""
        return {
            "is_ready": self.is_ready,
            "python": self.python_env.get_info(),
            "missing_packages": self.missing_packages,
            "missing_tools": self.missing_tools,
            "warnings": self.warnings,
            "error": self.error_message,
            "fix": self.fix_instructions,
        }


def validate_startup(check_optional: bool = False) -> StartupValidationResult:
    """
    Validate the runtime environment at startup.
    
    This should be called when the MCP server starts to fail fast
    with clear error messages if something is wrong.
    
    Args:
        check_optional: Also check optional dependencies
        
    Returns:
        StartupValidationResult with status and any issues found
    """
    python_env = PythonEnvironment.detect()
    warnings = []
    
    # Check Python environment
    if not python_env.is_valid:
        return StartupValidationResult(
            is_ready=False,
            python_env=python_env,
            error_message=f"Python environment invalid: {python_env._validation_error}",
            fix_instructions="Ensure Python 3.10+ is installed and accessible.",
        )
    
    # Warn about Windows Store Python
    if python_env.is_windows_store:
        warnings.append(
            "Using Windows Store Python. Commands may hang if PATH resolves to stub. "
            "Consider using a virtual environment."
        )
    
    # Check dependencies
    dep_checker = DependencyChecker(python_env=python_env)
    missing_pkgs = dep_checker.get_missing_required()
    
    if missing_pkgs:
        install_cmd = dep_checker.get_install_command(missing_pkgs)
        return StartupValidationResult(
            is_ready=False,
            python_env=python_env,
            missing_packages=missing_pkgs,
            warnings=warnings,
            error_message=f"Missing required packages: {', '.join(missing_pkgs)}",
            fix_instructions=f"Install missing packages:\n  {install_cmd}",
        )
    
    # Check external tools
    tools_checker = ExternalToolsChecker()
    missing_tools = tools_checker.get_missing_required()
    
    if missing_tools:
        return StartupValidationResult(
            is_ready=False,
            python_env=python_env,
            missing_tools=missing_tools,
            warnings=warnings,
            error_message=f"Missing required tools: {', '.join(missing_tools)}",
            fix_instructions="Install missing tools and ensure they are in PATH.",
        )
    
    # All good
    return StartupValidationResult(
        is_ready=True,
        python_env=python_env,
        warnings=warnings,
    )


# =============================================================================
# Module-level API
# =============================================================================

_env: Optional[PythonEnvironment] = None


def get_python_env() -> PythonEnvironment:
    """Get the Python environment (cached singleton)."""
    global _env
    if _env is None:
        _env = PythonEnvironment.detect()
    return _env


def transform_python_command(command: str) -> str:
    """Transform a command to use the correct Python executable."""
    return get_python_env().transform_command(command)


def get_python_executable() -> Path:
    """Get the path to the Python executable."""
    return get_python_env().executable


def check_dependencies() -> Tuple[bool, List[str]]:
    """
    Quick check if all required dependencies are installed.
    
    Returns:
        (all_ok, missing_list)
    """
    checker = DependencyChecker(python_env=get_python_env())
    missing = checker.get_missing_required()
    return len(missing) == 0, missing
