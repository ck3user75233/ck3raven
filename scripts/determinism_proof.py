"""Determinism proof script."""
from tools.compliance.linter_lock import create_lock

# Run twice
lock1 = create_lock()
lock2 = create_lock()

print("=== DETERMINISM PROOF ===")
print()
print(f"Run 1 lock_hash: {lock1.lock_hash}")
print(f"Run 2 lock_hash: {lock2.lock_hash}")
print()
print(f"Hashes identical: {lock1.lock_hash == lock2.lock_hash}")
print()
print("File hashes comparison:")
for f1, f2 in zip(lock1.files, lock2.files):
    match = "MATCH" if f1.sha256 == f2.sha256 else "DIFFER"
    print(f"  [{match}] {f1.path}")
