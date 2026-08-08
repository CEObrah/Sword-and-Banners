#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATORS = [
    "tools/audit.py",
    "tools/test_development.py",
    "tools/test_mechanics.py",
    "tools/test_living_world.py",
    "tools/test_owner_liveness.py",
    "tools/test_runtime.py",
    "tools/test_runtime_integrity.py",
    "tools/test_semantics.py",
    "tools/test_unit_model.py",
    "tools/test_support_classification.py",
    "tools/test_reputation.py",
    "tools/test_family.py",
    "tools/test_templates.py",
    "tools/test_routing.py",
    "tools/test_current_identities.py",
    "tools/test_tang_champions.py",
    "tools/test_recruitment_representation.py",
    "tools/test_population_sources.py",
]

failed = []
for rel in VALIDATORS:
    print(f"\n=== {rel} ===", flush=True)
    result = subprocess.run([sys.executable, rel], cwd=ROOT)
    if result.returncode:
        failed.append((rel, result.returncode))

print("\n=== VALIDATOR SUMMARY ===")
if failed:
    for rel, code in failed:
        print(f"FAIL {rel} exit={code}")
    print(f"{len(failed)} of {len(VALIDATORS)} validators failed")
    sys.exit(1)

for rel in VALIDATORS:
    print(f"PASS {rel}")
print(f"all {len(VALIDATORS)} validators passed")
