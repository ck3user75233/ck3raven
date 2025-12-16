"""
CLI entry point for ck3raven.
"""

import sys


def main():
    """Main CLI entry point."""
    print("ck3raven v0.1.0")
    print("CK3 Game State Emulator")
    print()
    print("Usage:")
    print("  ck3raven parse <file>          Parse a file and show AST summary")
    print("  ck3raven resolve <folder>      Resolve conflicts in a content folder")
    print("  ck3raven emulate <playset>     Emulate full game state from playset")
    print()
    print("See README.md for more information.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
