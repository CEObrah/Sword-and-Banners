#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []
legacy_release_id = re.compile(r"(?:\.v|_v)(?:38|39)$")
legacy_path = re.compile(r"(?:[-._]v(?:38|39))(?=[.-])")


def read_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

idx = read_json(ROOT / "data/runtime/template-index.json")
mutable = {}
for rel in idx.get("shards", {}).values():
    doc = read_json(ROOT / rel)
    for schema_id, ent in doc.get("templates", {}).items():
        if ent.get("scope") != "mutable_state":
            continue
        mutable[schema_id] = ent
        if legacy_release_id.search(schema_id):
            errors.append(f"legacy mutable schema id: {schema_id}")
        for key in ("path", "source_schema"):
            value = ent.get(key)
            if isinstance(value, str) and legacy_path.search(value):
                errors.append(f"legacy mutable authority path: {schema_id}:{key}:{value}")

registry = read_json(ROOT / "schemas/registry.json")
for schema_id in mutable:
    if schema_id not in registry:
        errors.append(f"mutable schema missing formal registry entry: {schema_id}")
        continue
    target = registry[schema_id]
    if not (ROOT / "schemas" / target).exists():
        errors.append(f"mutable formal schema target missing: {schema_id}:{target}")
    if legacy_path.search(target):
        errors.append(f"legacy mutable formal schema path: {schema_id}:{target}")

preview_token = "PRE" + "VIEW:"
order_token = "OR" + "DER:"
for rel in ("RUNTIME.md", "PLAYER_INTERFACE.md", "tests/interface-intent.json"):
    text = (ROOT / rel).read_text(encoding="utf-8")
    for token in (preview_token, order_token):
        if token in text:
            errors.append(f"obsolete interface token in {rel}: {token}")

runtime = (ROOT / "RUNTIME.md").read_text(encoding="utf-8")
for phrase in (
    "Creating a mutable owner is deterministic template instantiation, never free-form JSON authorship.",
    "Ordinary maintenance that preserves a formal structural contract updates current semantic IDs and files in place.",
    "Do not mint versioned gameplay IDs, clone rules, or bump campaign/system versions merely to mark an edit.",
):
    if phrase not in runtime:
        errors.append(f"runtime current-identity guard missing: {phrase}")

if errors:
    print("CURRENT IDENTITY TEST FAILED")
    for item in errors:
        print("-", item)
    sys.exit(1)

print("CURRENT IDENTITY TEST OK")
print(f"mutable_schemas={len(mutable)}; legacy release-line mutable IDs and obsolete command-prefix machinery absent")
