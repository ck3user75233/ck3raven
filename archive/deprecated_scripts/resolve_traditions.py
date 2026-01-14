#!/usr/bin/env python3
"""
Resolve tradition conflicts between vanilla and mods.

Usage:
    python resolve_traditions.py --vanilla <path> --mods <mod1> <mod2> ...
"""

import argparse
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.parser import parse_file


def main():
    parser = argparse.ArgumentParser(description="Resolve CK3 tradition conflicts")
    parser.add_argument("--vanilla", required=True, help="Path to vanilla traditions folder")
    parser.add_argument("--mods", nargs="+", help="Paths to mod folders (in load order)")
    parser.add_argument("--output", "-o", default="resolved_traditions.txt", help="Output file")
    
    args = parser.parse_args()
    
    print(f"ck3raven Tradition Resolver")
    print(f"Vanilla: {args.vanilla}")
    print(f"Mods: {args.mods or 'None'}")
    print()
    
    # TODO: Implement full resolver
    print("Resolver not yet implemented. Coming soon!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
