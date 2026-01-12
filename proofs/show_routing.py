#!/usr/bin/env python3
"""
Routing Table Validation Proof

Demonstrates that the routing table properly maps file types to envelopes.
Run this to generate proofs/routing_table_validation.txt
"""

import json
import sys
from pathlib import Path


def validate_routing_table():
    """Validate routing table structure and coverage."""
    routing_path = Path(__file__).parent.parent / 'qbuilder' / 'routing_table.json'
    
    if not routing_path.exists():
        print(f"ERROR: Routing table not found at {routing_path}")
        return False
    
    with open(routing_path, 'r') as f:
        routing = json.load(f)
    
    print("=" * 70)
    print("ROUTING TABLE VALIDATION PROOF")
    print("=" * 70)
    print()
    
    # 1. Structure validation
    print("1. STRUCTURE VALIDATION")
    print("-" * 40)
    
    required_keys = ['extension_to_type', 'type_to_envelope', 'envelope_steps']
    missing = [k for k in required_keys if k not in routing]
    
    if missing:
        print(f"  ERROR: Missing required keys: {missing}")
        return False
    
    print(f"  [OK] All required keys present: {required_keys}")
    print()
    
    ext_to_type = routing['extension_to_type']
    type_to_env = routing['type_to_envelope']
    env_steps = routing['envelope_steps']
    
    print(f"  Extensions mapped: {len(ext_to_type)}")
    print(f"  File types: {len(type_to_env)}")
    print(f"  Envelopes defined: {len(env_steps)}")
    print()
    
    # 2. Extension to type mapping
    print("2. EXTENSION TO TYPE MAPPING")
    print("-" * 40)
    
    for ext, ftype in sorted(ext_to_type.items()):
        status = "[OK]" if ftype in type_to_env else "[WARN: no envelope]"
        print(f"  {ext:10} -> {ftype:15} {status}")
    print()
    
    # 3. Type to envelope mapping
    print("3. TYPE TO ENVELOPE MAPPING")
    print("-" * 40)
    
    for ftype, envelope in sorted(type_to_env.items()):
        status = "[OK]" if envelope in env_steps else "[WARN: no steps]"
        print(f"  {ftype:15} -> {envelope:15} {status}")
    print()
    
    # 4. Envelope step definitions
    print("4. ENVELOPE STEP DEFINITIONS")
    print("-" * 40)
    
    for envelope, steps in sorted(env_steps.items()):
        if steps:
            print(f"  {envelope}:")
            for step in steps:
                print(f"    - {step}")
        else:
            print(f"  {envelope}: (no steps - skip envelope)")
    print()
    
    # 5. Sample routing decisions
    print("5. SAMPLE ROUTING DECISIONS")
    print("-" * 40)
    
    test_files = [
        'common/traits/00_traits.txt',
        'events/story_events.txt',
        'localization/english/custom_l_english.yml',
        'gfx/portraits/some_file.dds',
        'gui/window.gui',
        'random/unknown.xyz',
    ]
    
    skip_exts = set(routing.get('skip_extensions', []))
    
    def get_envelope(filepath: str) -> str:
        """Resolve filepath to envelope via routing table."""
        ext = '.' + filepath.split('.')[-1] if '.' in filepath else ''
        
        if ext in skip_exts:
            return 'E_SKIP (binary)'
        
        ftype = ext_to_type.get(ext, 'unknown')
        return type_to_env.get(ftype, 'E_SKIP (unknown)')
    
    for path in test_files:
        envelope = get_envelope(path)
        print(f"  {path}")
        print(f"    -> {envelope}")
    
    print()
    print("=" * 70)
    print("VALIDATION COMPLETE")
    print("=" * 70)
    
    return True


def main():
    # Run validation
    success = validate_routing_table()
    
    # Save to proof file
    proof_dir = Path(__file__).parent
    proof_file = proof_dir / 'routing_table_validation.txt'
    
    import io
    from contextlib import redirect_stdout
    
    # Capture output
    output = io.StringIO()
    with redirect_stdout(output):
        validate_routing_table()
    
    # Write proof
    with open(proof_file, 'w', encoding='utf-8') as f:
        f.write(f"Generated: {__import__('datetime').datetime.now().isoformat()}\n")
        f.write(f"Script: {Path(__file__).name}\n\n")
        f.write(output.getvalue())
    
    print(f"\n[Proof saved to {proof_file}]")
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
