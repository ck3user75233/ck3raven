"""Create a fake baseline snapshot for testing D7 (new symbols)."""
import json
import hashlib
from pathlib import Path

# Read existing snapshot
snap_path = Path("artifacts/symbols/proof-b0-test-1_2026-01-20T08-42-41.symbols.json")
data = json.loads(snap_path.read_text())

# Remove some identities to simulate 'old baseline'
identities = data["identities"]
removed = identities[:5]  # Remove first 5 identities
data["identities"] = identities[5:]
data["identity_count"] = len(data["identities"])

# Also remove from provenance
prov = data["provenance"]
def make_key(p):
    return f"{p['symbol_type']}:{p.get('scope', '')}:{p['name']}"
removed_keys = {f"{r['symbol_type']}:{r.get('scope', '')}:{r['name']}" for r in removed}
data["provenance"] = [p for p in prov if make_key(p) not in removed_keys]
data["provenance_count"] = len(data["provenance"])

# Recalculate hash
sorted_keys = sorted(f"{i['symbol_type']}:{i.get('scope', '')}:{i['name']}" for i in data["identities"])
data["symbols_hash"] = "sha256:" + hashlib.sha256("\n".join(sorted_keys).encode()).hexdigest()

# Mark as fake baseline
data["snapshot_id"] = "test-d7-fake-baseline"
data["contract_id"] = "test-d7-fake-baseline"

# Save as fake baseline
fake_path = Path("artifacts/symbols/test-d7-fake-baseline.symbols.json")
fake_path.write_text(json.dumps(data, indent=2))

print(f"Created fake baseline with {data['identity_count']} identities")
print(f"Removed {len(removed)} identities:")
for r in removed:
    print(f"  - {r['symbol_type']}:{r.get('scope', '')}:{r['name']}")
