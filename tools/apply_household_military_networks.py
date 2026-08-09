#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))

def save(rel, obj):
    (ROOT / rel).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

# Guard the canonical maintenance base represented on this branch.
meta = load("state/meta.json")
if meta.get("revision") != 20 or meta.get("time") != "245-BCE-12-04T07:22:48+08:00":
    raise SystemExit("unexpected campaign base for household-network migration")

# Schema registry.
schema_registry = load("schemas/registry.json")
schema_registry["household-military-network-registry"] = "household-military-network-registry.schema.json"
save("schemas/registry.json", schema_registry)

# Template lookup.
template_shard = load("data/runtime/template-index-shards/h.json")
template_shard.setdefault("templates", {})["household-military-network-registry"] = {
    "path": "data/runtime/templates/household-military-network-registry.template.json",
    "source_schema": "schemas/household-military-network-registry.schema.json",
    "scope": "mutable_state",
}
save("data/runtime/template-index-shards/h.json", template_shard)

# System contract owns the new registry and its invariants.
forces = load("data/runtime/system-contracts/forces_institutions.json")
owner_templates = forces["owner_templates"]
if "household-military-network-registry" not in owner_templates:
    owner_templates.append("household-military-network-registry")
new_invariants = [
    "State-issued command and state manpower remain separate from private household or personal-retainer ownership.",
    "Profile-only household military networks own no exact manpower, equipment or combat capability and cannot fight.",
    "Exact household forces require conserved population/manpower, wealth/support, equipment, horses and supplies before materialization.",
    "Household military quality derives from source population, selection, training, resources and history; House Tang is not a default quality template.",
    "Royal household forces must resolve crown/state manpower versus genuinely dynastic/private ownership before materialization.",
]
for inv in new_invariants:
    if inv not in forces["invariants"]:
        forces["invariants"].append(inv)
save("data/runtime/system-contracts/forces_institutions.json", forces)

# Routing: one direct owner, never preload all forces/houses.
repo_map = load("data/runtime/repository-map.json")
repo_map["route_index"]["household_military_network"] = "military"
save("data/runtime/repository-map.json", repo_map)

military = load("data/runtime/repository-routes/military.json")
military["routes"]["household_military_network"] = {
    "r": ["state/force/household-military-networks.json", "rules/org.md"],
    "note": "Load one network entry. Profile-only networks cannot fight; materialize exact household forces only from conserved lawful sources and keep them distinct from state command.",
}
save("data/runtime/repository-routes/military.json", military)

# Derived owner routing.
force_index = load("state/index/owners/force.json")
force_index["owners"]["force.household_military_networks"] = "state/force/household-military-networks.json"
save("state/index/owners/force.json", force_index)

owners = load("state/index/owners.json")
actual_count = 0
for rel in owners["prefix_index"].values():
    shard = load(rel)
    actual_count += len(shard.get("owners", {}))
owners["owner_count"] = actual_count
save("state/index/owners.json", owners)

# Current gameplay law only; no migration history.
org_path = ROOT / "rules/org.md"
org = org_path.read_text(encoding="utf-8")
section = """
## Household and personal military networks

State command, household ownership, and personal-retainer loyalty are separate authorities. A general may command state troops while also belonging to or maintaining a smaller enduring household or personal-retainer network; commanding state manpower never converts it into private property.

`state/force/household-military-networks.json` owns recognized household/personal-network profiles and references to any exact materialized private forces. A `profile_only` network records existence/classification only: it has no exact headcount, composition, training, equipment, horses, supplies or combat capability and cannot fight. Exact forces materialize only through lawful population/manpower sources, wealth or treasury support, equipment/horse/supply sources, political/legal authority, elapsed organization/training where required, and normal conservation transactions. Missing source evidence fails closed.

Household military quality is derived from real source population, selection, training, equipment, resources and history. No noble house receives House Tang capability by analogy. Royal households must resolve crown/palace state manpower separately from genuinely dynastic/private retainers before ownership is persisted. Personal troops, house troops, state troops, mercenaries and allies remain distinct ownership classes even when temporarily combined under one command tree.
"""
if "## Household and personal military networks" not in org:
    org = org.rstrip() + "\n\n" + section.lstrip()
org_path.write_text(org, encoding="utf-8")

# Validator stack.
runner_path = ROOT / "tools/run_validators.py"
runner = runner_path.read_text(encoding="utf-8")
needle = '    "tools/test_offscreen_scaling.py",\n'
addition = needle + '    "tools/test_household_military_networks.py",\n'
if '"tools/test_household_military_networks.py"' not in runner:
    if needle not in runner:
        raise SystemExit("validator insertion point missing")
    runner = runner.replace(needle, addition)
runner_path.write_text(runner, encoding="utf-8")

# Structural state change advances revision once; time is unchanged.
meta["revision"] = 21
save("state/meta.json", meta)

print("household military network migration staged")
