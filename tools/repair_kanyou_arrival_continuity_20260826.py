#!/usr/bin/env python3
"""Repair the revision-2 Kanyou arrival continuity defect without advancing time.

Provenance: the committed travel already placed Tang Wei and all 19 formations at
Kanyou at 244-BCE-09-11T12:22:48+08:00. The pre-fix movement layer failed to move
co-located zero-body headquarters personnel and failed to run the saved campaign
arrival handoff. This repair derives both corrections from the exact current owners.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from sword_runtime.campaign_briefing import reconcile_campaign_arrival
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner

OPERATION_REF = "operation_arc_131572c4e8a2892bbc"
DESTINATION = "loc_kanyou"
EXPECTED_REVISION = 2
EXPECTED_TIME = "244-BCE-09-11T12:22:48+08:00"
REPAIR_REF = "repair_kanyou_arrival_continuity_20260826"


def save(path: Path, document) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    meta = json.loads((ROOT / "state/meta.json").read_text(encoding="utf-8"))
    if int(meta.get("revision", -1)) != EXPECTED_REVISION or str(meta.get("time", "")) != EXPECTED_TIME:
        raise RuntimeError("repair applies only to the known revision-2 Kanyou arrival boundary")

    planner = ProductionCampaignPlanner(ROOT)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()

    player = planner.read("state/player.json")
    if str(player.get("location", "")) != DESTINATION:
        raise RuntimeError("Tang Wei is not at the committed Kanyou arrival location")

    op_path = planner.read("state/operations/index.json")["operations"][OPERATION_REF]
    operation = planner.read(op_path)
    opposing = {str(ref) for ref in operation.get("opposing_formation_refs", []) if isinstance(ref, str)}
    participants = [str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str) and ref not in opposing]
    if len(participants) != 19:
        raise RuntimeError("expected the committed 19-formation field army")
    for ref in participants:
        formation = planner.read(planner.owner_path(ref))
        if str(formation.get("location_ref", "")) != DESTINATION:
            raise RuntimeError(f"formation did not reach Kanyou: {ref}")

    staff_reconciled: list[str] = []
    moved_groups = planner._reconcile_command_group_locations(
        participants,
        DESTINATION,
        staff_reconciled=staff_reconciled,
    )

    # The groups themselves were already reconciled by the pre-fix movement code,
    # so replay the same exact co-location rule for their attached people. Only a
    # person still at the known origin of this committed march is eligible.
    group_index = planner.read("state/cmd/command-groups/index.json")
    candidate_groups = set()
    for ref in participants:
        current = group_index.get("primary_formation_group", {}).get(ref)
        seen = set()
        while isinstance(current, str) and current and current not in seen:
            seen.add(current)
            candidate_groups.add(current)
            group = planner.read(f"state/cmd/command-groups/{current}.json")
            parent = group.get("parent_command_group_ref") if isinstance(group, dict) else None
            current = parent if isinstance(parent, str) and parent else None

    origin = "loc_qin_eastern_depot"
    for group_ref in sorted(candidate_groups):
        group = planner.read(f"state/cmd/command-groups/{group_ref}.json")
        if str(group.get("location", "")) != DESTINATION:
            continue
        for person_ref in planner._command_group_person_refs(group):
            try:
                path = planner.owner_path(person_ref)
                person0 = planner.read(path)
            except (KeyError, ValueError, FileNotFoundError):
                continue
            if not isinstance(person0, dict):
                continue
            person = copy.deepcopy(person0)
            if planner._person_location(person) != origin:
                continue
            planner._set_person_location(person, DESTINATION)
            history = person.setdefault("repair_history", [])
            if not any(isinstance(row, dict) and row.get("repair_ref") == REPAIR_REF for row in history):
                history.append({
                    "repair_ref": REPAIR_REF,
                    "at": EXPECTED_TIME,
                    "reason": "co-located command headquarters omitted from committed escorted travel",
                    "from_location_ref": origin,
                    "to_location_ref": DESTINATION,
                    "evidence_ref": OPERATION_REF,
                })
            planner.put(path, person)
            staff_reconciled.append(person_ref)

    report = reconcile_campaign_arrival(
        planner,
        OPERATION_REF,
        destination_ref=DESTINATION,
        at=EXPECTED_TIME,
        unit_duties=[],
    )
    if report is None:
        operation = planner.read(op_path)
        if str(operation.get("order_status", "")) != "awaiting_entry_authority":
            raise RuntimeError("campaign arrival handoff did not reconcile")
        info_ref = operation.get("last_phase_information_ref")
    else:
        info_ref = report.get("information_ref")

    repair_log_path = ROOT / "state/history/repairs/kanyou-arrival-continuity-20260826.json"
    repair_log_path.parent.mkdir(parents=True, exist_ok=True)
    save(repair_log_path, {
        "schema": "sword-campaign-repair-provenance.v1",
        "authority": False,
        "repair_ref": REPAIR_REF,
        "campaign_revision": EXPECTED_REVISION,
        "world_time": EXPECTED_TIME,
        "operation_ref": OPERATION_REF,
        "destination_ref": DESTINATION,
        "evidence": {
            "player_location_ref": DESTINATION,
            "formation_count": len(participants),
            "all_participants_at_destination": True,
        },
        "corrected": {
            "command_group_refs": sorted(set(moved_groups)),
            "command_staff_refs": sorted(set(staff_reconciled)),
            "phase_information_ref": info_ref,
        },
        "rule": "repair only omitted consequences of the already-committed march; do not advance time, create manpower, or change authority",
    })

    # Flush planner writes into the working tree without creating a gameplay revision.
    planner._flush()
    print(json.dumps({
        "repair_ref": REPAIR_REF,
        "staff_reconciled": sorted(set(staff_reconciled)),
        "phase_information_ref": info_ref,
    }, indent=2))


if __name__ == "__main__":
    main()
