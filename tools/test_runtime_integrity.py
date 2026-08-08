#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []

def load(rel):
    try:
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"json:{rel}:{exc}")
        return {}

def fail(msg):
    errors.append(msg)

meta = load("state/meta.json")
frontier = load("state/time/frontier.json")
process_index = load("state/process-state/index.json")
process_registry = load("state/reg/registry-processes.json").get("processes", {})
contract_registry = load("state/reg/registry-process-contracts.json")
directory_map = set(load("data/runtime/directory-map.json").get("dirs", {}))
autonomous = load("data/runtime/autonomous-world-simulation.json")

world_time = meta.get("time")
if frontier.get("world_time") != world_time:
    fail(f"frontier_world_time_mismatch:{frontier.get('world_time')}:{world_time}")

contract_dir = ROOT / "state/reg/process-contracts"
direct_contracts = {}
for path in contract_dir.glob("*.json"):
    data = load(str(path.relative_to(ROOT)))
    pid = data.get("owner_id")
    if not pid:
        fail(f"process_contract_missing_owner:{path.name}")
        continue
    if path.stem != pid:
        fail(f"process_contract_path_owner_mismatch:{path.name}:{pid}")
    if data.get("contract_id") != f"contract_{pid}":
        fail(f"process_contract_id_mismatch:{pid}:{data.get('contract_id')}")
    direct_contracts[pid] = data

if contract_registry.get("record_count") != len(direct_contracts):
    fail(f"process_contract_registry_count:{contract_registry.get('record_count')}:{len(direct_contracts)}")

indexed_process_states = set()
for entry in process_index.get("entries", []):
    pid = entry.get("process_id")
    rel = entry.get("path")
    if not pid or not rel:
        fail("process_state_index_bad_entry")
        continue
    if pid in indexed_process_states:
        fail(f"duplicate_process_state_index:{pid}")
    indexed_process_states.add(pid)
    path = ROOT / rel
    if not path.exists():
        fail(f"process_state_index_missing_file:{pid}:{rel}")
        continue
    state = load(rel)
    if state.get("process_id") != pid:
        fail(f"process_state_id_mismatch:{pid}:{state.get('process_id')}")
    if pid not in process_registry and pid not in direct_contracts:
        fail(f"process_state_without_registered_or_direct_contract:{pid}")

frontier_ids = set()
for process in frontier.get("processes", []):
    pid = process.get("id")
    if not pid:
        fail("frontier_process_missing_id")
        continue
    if pid in frontier_ids:
        fail(f"duplicate_frontier_process:{pid}")
    frontier_ids.add(pid)
    recurrence = process.get("recurrence", {})
    if process.get("status") == "active" and recurrence.get("accrual_mode") == "continuous":
        if process.get("settled_through") != world_time:
            fail(f"continuous_process_not_closed:{pid}:{process.get('settled_through')}:{world_time}")
    if process.get("status") == "completed" and process.get("next_due") is not None:
        fail(f"completed_process_has_next_due:{pid}:{process.get('next_due')}")
    # Coverage-only clocks need not own mutable process-state or a direct contract.
    # Runtime-created successors do: they must be registered and directly contracted before activation.
    if str(process.get("source", "")).startswith("successor:"):
        if pid not in process_registry:
            fail(f"successor_not_registered:{pid}")
        if pid not in direct_contracts:
            fail(f"successor_without_direct_contract:{pid}")

for pid in direct_contracts:
    if pid not in frontier_ids and pid not in process_registry:
        fail(f"orphan_direct_process_contract:{pid}")

for name, rel in autonomous.get("storage_targets", {}).items():
    norm = rel.rstrip("/")
    if (ROOT / rel).exists():
        continue
    if norm not in directory_map:
        fail(f"autonomous_storage_target_unmapped_or_missing:{name}:{rel}")

if errors:
    print("RUNTIME INTEGRITY TEST FAILED")
    for item in errors:
        print("-", item)
    sys.exit(1)

print("RUNTIME INTEGRITY TEST OK")
print(f"frontier_processes={len(frontier_ids)} direct_contracts={len(direct_contracts)} materialized_process_states={len(indexed_process_states)}")
