#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))

def fail(msg):
    raise SystemExit(msg)

reg = load("state/force/household-military-networks.json")
if reg.get("schema") != "household-military-network-registry":
    fail("household_network_schema")
policy = reg.get("policy", {})
for key in (
    "state_command_separate_from_household",
    "profile_only_noncombat",
    "exact_manpower_requires_source_conservation",
    "exact_equipment_requires_source_conservation",
    "quality_requires_training_resources_history",
    "royal_state_boundary_must_be_resolved",
):
    if policy.get(key) is not True:
        fail("household_network_policy:" + key)

char_index = load("state/index/owners/char.json").get("owners", {})
seen_force_refs = set()
networks = reg.get("networks", {})
if not networks:
    fail("household_networks_empty")

for network_id, rec in networks.items():
    forbidden = {"headcount", "composition", "training", "loadout", "capability", "manpower", "equipment"}
    overlap = forbidden.intersection(rec)
    if overlap:
        fail(f"household_profile_invents_exact_state:{network_id}:{sorted(overlap)}")
    anchors = rec.get("anchor_refs", [])
    if not anchors:
        fail("household_network_missing_anchor:" + network_id)
    for anchor in anchors:
        if anchor not in char_index:
            fail(f"household_network_unknown_anchor:{network_id}:{anchor}")
    force_refs = rec.get("force_refs", [])
    state = rec.get("materialization_state")
    if state == "profile_only" and force_refs:
        fail("profile_only_has_force_refs:" + network_id)
    if state == "materialized" and not force_refs:
        fail("materialized_missing_force_refs:" + network_id)
    for ref in force_refs:
        if ref.startswith("force_pool_"):
            fail(f"household_network_uses_state_pool_as_private_force:{network_id}:{ref}")
        if ref in seen_force_refs:
            fail("household_force_double_claim:" + ref)
        seen_force_refs.add(ref)

royal = networks.get("royal_qin")
if royal and royal.get("ownership_scope") != "crown_state_boundary":
    fail("royal_household_boundary_not_explicit")

print("HOUSEHOLD MILITARY NETWORK TEST OK")
print(f"networks={len(networks)} materialized={sum(1 for r in networks.values() if r.get('materialization_state') == 'materialized')} profile_only={sum(1 for r in networks.values() if r.get('materialization_state') == 'profile_only')}")
