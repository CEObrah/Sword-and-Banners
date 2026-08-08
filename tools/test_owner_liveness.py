#!/usr/bin/env python3
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def fail(message):
    print("OWNER LIVENESS TEST FAILED")
    print("-", message)
    sys.exit(1)


def time_key(value):
    match = re.match(r"(\d+)-BCE-(\d+)-(\d+)T(\d+):(\d+):(\d+)", value or "")
    if not match:
        return None
    year, month, day, hour, minute, second = map(int, match.groups())
    return (-year, month, day, hour, minute, second)


frontier = load("state/time/frontier.json")
registry = load("state/reg/registry-processes.json").get("processes", {})
contract_registry = load("state/reg/registry-process-contracts.json")
state_index = load("state/process-state/index.json")
state_entries = {entry.get("process_id"): entry for entry in state_index.get("entries", [])}

contract_dir = ROOT / "state/reg/process-contracts"
contract_files = list(contract_dir.glob("*.json"))
if contract_registry.get("record_count") != len(contract_files):
    fail(f"process_contract_count:{contract_registry.get('record_count')}:{len(contract_files)}")

for process in frontier.get("processes", []):
    if process.get("status") != "active":
        continue
    pid = process.get("id")
    reg = registry.get(pid)
    if not isinstance(reg, dict):
        fail("active_process_missing_registry:" + str(pid))
    contract_id = reg.get("contract_id")
    if not contract_id:
        fail("active_process_missing_contract_id:" + str(pid))
    if reg.get("contract_registry_owner_id") != "registry_process_contracts":
        fail("active_process_bad_contract_registry:" + str(pid))
    contract_path = ROOT / "state/reg/process-contracts" / f"{pid}.json"
    if not contract_path.exists():
        fail("active_process_missing_contract_file:" + str(pid))
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("schema") != "process-contract.v1":
        fail("active_process_bad_contract_schema:" + str(pid))
    if contract.get("owner_id") != pid or contract.get("contract_id") != contract_id:
        fail("active_process_contract_identity:" + str(pid))
    entry = state_entries.get(pid)
    if not isinstance(entry, dict):
        fail("active_process_missing_state_index:" + str(pid))
    state_path = ROOT / entry.get("path", "")
    if not state_path.exists():
        fail("active_process_missing_state_file:" + str(pid))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("process_id") != pid:
        fail("active_process_state_identity:" + str(pid))

heartbeat = next((p for p in frontier.get("processes", []) if p.get("id") == "process_autonomous_world_heartbeat"), None)
if not heartbeat or heartbeat.get("status") != "active":
    fail("autonomous_heartbeat_missing")
recurrence = heartbeat.get("recurrence", {})
if recurrence.get("kind") != "fixed_interval" or recurrence.get("interval_seconds") != 86400 or recurrence.get("accrual_mode") != "boundary_only":
    fail("autonomous_heartbeat_recurrence")
if time_key(heartbeat.get("next_due")) <= time_key(frontier.get("world_time")):
    fail("autonomous_heartbeat_overdue")

player = load("state/player.json")
if (ROOT / "state/player-detail/combat-tendencies.json").exists():
    fail("duplicate_player_combat_owner")
if "combat_tendencies_ref" in player:
    fail("player_combat_ref_not_consolidated")
behavior = player.get("behavior", {})
if not behavior.get("combat_identity") or not behavior.get("combat_agency_constraints"):
    fail("player_inline_combat_behavior_missing")
if not player.get("equipment_manifest_ref"):
    fail("player_inventory_authority_ref_missing")

first = load("state/unit/tang-champions-first.json")
second = load("state/unit/tang-champions-second.json")
covered = set(load("state/time/coverage/process_personal_force_life_weekly.json").get("owner_ids", []))
required_personal = {"char_tang_wei"}
required_personal.update(first.get("personnel", {}).get("member_ids", []))
required_personal.update(second.get("personnel", {}).get("member_ids", []))
missing_personal = sorted(required_personal - covered)
if missing_personal:
    fail("personal_force_coverage_missing:" + ",".join(missing_personal))

faction_index = load("state/reg/living-factions.json")
frontier_ids = {p.get("id") for p in frontier.get("processes", [])}
for faction_id, rel in faction_index.get("record_index", {}).items():
    faction_path = ROOT / rel
    if not faction_path.exists():
        fail("faction_owner_missing:" + faction_id)
    faction = json.loads(faction_path.read_text(encoding="utf-8")).get("faction", {})
    for key in ("goals", "resources", "constraints", "current_plan"):
        if not faction.get(key):
            fail(f"thin_faction:{faction_id}:{key}")
    process_id = faction.get("development_process_id")
    if process_id not in frontier_ids or process_id not in registry:
        fail("faction_process_missing:" + faction_id + ":" + str(process_id))

print("OWNER LIVENESS TESTS OK")
