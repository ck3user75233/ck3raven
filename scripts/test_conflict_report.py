#!/usr/bin/env python3
"""Test the conflict analyzer and report generator."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.db.schema import get_connection
from ck3raven.resolver.report import ConflictsReportGenerator, report_summary_cli

def main():
    db_path = Path.home() / '.ck3raven' / 'ck3raven.db'
    print(f"Database: {db_path}")
    
    conn = get_connection(db_path)
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    
    # Get active playset
    playset = conn.execute("SELECT playset_id, name FROM playsets WHERE is_active = 1").fetchone()
    print(f"Playset: {playset['playset_id']} - {playset['name']}")
    
    # Test 1: Generate conflicts report (file-level only for now since we haven't populated contribution_units)
    print("\n" + "="*60)
    print("TEST 1: Generate conflicts report")
    print("="*60)
    
    generator = ConflictsReportGenerator(conn)
    report = generator.generate(
        playset_id=playset['playset_id'],
        paths_filter="common/on_action%",  # Focus on on_action for test
        min_candidates=2,
    )
    
    print(f"\nFile-level conflicts: {report.summary.file_conflicts if report.summary else 0}")
    print(f"ID-level conflicts: {report.summary.id_conflicts if report.summary else 0}")
    
    # Show a few file conflicts
    if report.file_level:
        print(f"\nTop 5 file conflicts:")
        for fc in report.file_level[:5]:
            print(f"  - {fc.vpath}")
            print(f"    Candidates: {len(fc.candidates)}")
            print(f"    Winner: {fc.winner_by_load_order.source_name if fc.winner_by_load_order else 'N/A'}")
            print(f"    Risk: {fc.risk.bucket if fc.risk else 'N/A'} ({fc.risk.score if fc.risk else 0})")
    
    # Test 2: CLI summary output
    print("\n" + "="*60)
    print("TEST 2: CLI summary output")
    print("="*60)
    print(report_summary_cli(report))
    
    # Test 3: JSON output (just show structure, not full content)
    print("\n" + "="*60)
    print("TEST 3: JSON output structure")
    print("="*60)
    report_dict = report.to_dict()
    print(f"Schema: {report_dict['schema']}")
    print(f"Generated at: {report_dict['generated_at']}")
    print(f"Context keys: {list(report_dict['context'].keys()) if report_dict['context'] else []}")
    print(f"File conflicts: {len(report_dict['file_level']['items'])}")
    print(f"ID conflicts: {len(report_dict['id_level']['items'])}")
    
    print("\n✅ All tests passed!")
    conn.close()

if __name__ == "__main__":
    main()
