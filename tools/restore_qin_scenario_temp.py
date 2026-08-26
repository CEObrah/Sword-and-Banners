from __future__ import annotations

import json
import subprocess
from pathlib import Path

OLD = "cfcf67b0fc3e3b4ca58bb5dbcdad50e03b150eee"
OP_REF = "operation_arc_131572c4e8a2892bbc"
OP_PATH = f"state/operations/{OP_REF}.json"
INFO_REF = "information.qin_campaign_briefing.b4554e2a86b4c3edae39"
INFO_PATH = f"state/information/{INFO_REF}.json"
ARC_REF = "arc_ryo_fui_northern_wei_campaign"
START = "244-BCE-09-09T20:22:48+08:00"


def read(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path: str, value: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def old_json(path: str) -> dict:
    raw = subprocess.check_output(["git", "show", f"{OLD}:{path}"], text=True)
    return json.loads(raw)


def restore_operation() -> None:
    operation = old_json(OP_PATH)
    operation["created_at"] = "244-BCE-07-26T06:23:48+08:00"
    operation["status"] = "active"
    operation["campaign_phase"] = "campaign_concentration"
    operation["briefing_information_ref"] = INFO_REF
    operation["order_status"] = "staff_briefed_awaiting_commander_execution"
    authority_basis = operation.get("authority_basis")
    if isinstance(authority_basis, dict):
        authority_basis["source_event_ref"] = "event_story_qin_command_offer_17220ee53f8f08820e41"
    for order in operation.get("operational_orders", []):
        if not isinstance(order, dict):
            continue
        order["status"] = "staff_briefed_awaiting_commander_execution"
        order["actionability_status"] = "actionable"
        order["staff_briefed_at"] = START
        packet = order.get("mission_packet")
        if isinstance(packet, dict):
            # The fresh start keeps only Wei's executable operation owner. Other Qin
            # armies can remain known in the Bureau force picture without reviving
            # deleted peer-operation IDs as active campaign authority.
            packet["friendly_participant_operation_refs"] = []
            packet["issued_at"] = START
            packet["phase_status"] = "ready_for_commander_execution"
            packet["hostile_entry_authorized"] = False
            packet["entry_status"] = "awaiting_war_or_entry_authority"
    write(OP_PATH, operation)

    op_index = read("state/operations/index.json")
    op_index["operations"] = {OP_REF: OP_PATH}
    op_index["active_battlefield_operation_refs"] = []
    write("state/operations/index.json", op_index)


def restore_current_briefing() -> None:
    briefing = old_json(INFO_PATH)
    briefing["created_at"] = START
    briefing["evidence_refs"] = [OP_REF]
    context = briefing.get("campaign_context")
    if isinstance(context, dict):
        for row in context.get("other_friendly_participants", []):
            if isinstance(row, dict):
                row.pop("operation_ref", None)
    for key in ("claim", "fact"):
        text = briefing.get(key)
        if not isinstance(text, str):
            continue
        text = text.replace(
            "Other Qin forces formally tied to this campaign:",
            "Other Qin forces identified by the Bureau for this campaign:",
        )
        text = text.replace(
            "Combined Qin strength represented by those current operation owners is 176,800.",
            "Combined Qin strength represented by this current Bureau campaign force picture is 176,800.",
        )
        text = text.replace(
            "Executable staff packet: phase campaign_muster_and_staging; concentrate/report at Qin Eastern Military Depot, then operate toward Kanyou when the commander executes the order.",
            "Executable staff packet: phase campaign_muster_and_staging; the field command is assembled at Qin Eastern Military Depot and is to march to Kanyou when the commander executes the order.",
        )
        briefing[key] = text
    write(INFO_PATH, briefing)

    info_index = read("state/information/index.json")
    info_index["claims"] = {INFO_REF: INFO_PATH}
    info_index["by_holder"] = {"char_tang_wei": [INFO_REF]}
    write("state/information/index.json", info_index)

    subject_index = read("state/information/subject-index.json")
    subject_index["subjects"] = {ARC_REF: [INFO_REF]}
    write("state/information/subject-index.json", subject_index)

    delivery = read("state/index/qin-command-support-delivery.json")
    delivery["by_operation"] = {OP_REF: {"information_ref": INFO_REF}}
    write("state/index/qin-command-support-delivery.json", delivery)

    owner_index = read("state/index/owner-index.json")
    owners = owner_index.setdefault("owners", {})
    owners[OP_REF] = OP_PATH
    owners[INFO_REF] = INFO_PATH
    write("state/index/owner-index.json", owner_index)


def reconnect_command_tree() -> None:
    for path in (
        "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json",
        "state/cmd/command-groups/cmdgrp.tang_wei.red_lance.json",
        "state/cmd/command-groups/cmdgrp.tang_wei.high_guard.json",
        "state/cmd/command-groups/cmdgrp.tang_wei.black_banner.json",
    ):
        doc = read(path)
        doc["active_context_ref"] = OP_REF
        write(path, doc)


def restore_curated_history() -> None:
    history = read("state/history/events/index.json")
    history["archives"] = []
    history["archived_event_count"] = 0
    history["events"] = [
        {
            "at": "244-BCE-07-22T21:22:48+08:00",
            "event_id": "event_story_qin_command_offer_17220ee53f8f08820e41",
            "kind": "qin_field_command_offer",
            "metadata": {
                "actor_ref": "char_ei_sei",
                "recipient_ref": "char_tang_wei",
                "state_ref": "state_qin",
                "scenario_background": True,
            },
            "summary": "King Ei Sei issued Tang Wei a formal Qin field-command appointment for the coming campaign against Wei.",
        },
        {
            "at": "244-BCE-07-22T22:22:48+08:00",
            "event_id": "event_qin_command_briefing_0e6b6351a9b0f0835f44",
            "kind": "qin_field_command_briefing",
            "metadata": {
                "recipient_ref": "char_tang_wei",
                "report_to_location_ref": "loc_qin_eastern_depot",
                "state_ref": "state_qin",
                "scenario_background": True,
            },
            "summary": "Tang Wei was briefed to report to the Qin Eastern Military Depot and take command of the Qin component assigned beneath his field army.",
        },
        {
            "at": "244-BCE-07-26T06:23:48+08:00",
            "event_id": "event_story_qin_command_assumed_223a49b16c582f730229",
            "kind": "qin_field_command_assumption",
            "metadata": {
                "actor_ref": "char_tang_wei",
                "command_group_ref": "cmdgrp.tang_wei.field_army",
                "location_ref": "loc_qin_eastern_depot",
                "scenario_background": True,
            },
            "summary": "Tang Wei reported to the Qin Eastern Military Depot and formally assumed the field command under Qin Military Bureau coordination.",
        },
        {
            "at": "244-BCE-08-20T06:22:48+08:00",
            "event_id": "event_campaign_order_operation_arc_131572c4e8a2892bbc",
            "kind": "qin_campaign_order_issued",
            "metadata": {
                "operation_ref": OP_REF,
                "state_ref": "state_qin",
                "target_state_ref": "state_wei",
                "scenario_background": True,
            },
            "summary": "Qin issued Tang Wei an operational assignment for the northern Wei campaign; Qin-owned formations under his command were placed under the campaign order while his private House forces remained his decision.",
        },
        {
            "at": "244-BCE-08-26T18:22:48+08:00",
            "event_id": "event_background_tang_wei_campaign_preparation_244_08_26",
            "kind": "player_campaign_preparation",
            "metadata": {
                "actor_ref": "char_tang_wei",
                "location_ref": "loc_qin_eastern_depot",
                "source_interaction_refs": [
                    "interaction_attempt_caf40768468db0e97df41016",
                    "interaction_attempt_940200018c376952bb8cefee",
                    "interaction_attempt_81540dbb9be36cbd1e76f50f",
                ],
                "scenario_background": True,
                "player_authored_intent_only": True,
            },
            "summary": "At the Eastern Depot, Tang Wei insisted that the army have adequate provisions and current actionable intelligence, and ordered march preparations while holding until those preparations were satisfactory.",
        },
        {
            "at": "244-BCE-09-02T20:22:48+08:00",
            "event_id": "event_background_tang_wei_family_departure_244_09_02",
            "kind": "player_family_notice",
            "metadata": {
                "actor_ref": "char_tang_wei",
                "source_interaction_ref": "interaction_attempt_9c1f768b0c970cb7716867f7",
                "scenario_background": True,
                "player_authored_intent_only": True,
            },
            "summary": "Tang Wei told his younger brother that Qin had placed him in field command for the northern campaign against Wei and that he intended to return after the war.",
        },
        {
            "at": START,
            "event_id": "event_background_qin_kanyou_staging_order_244_09_09",
            "kind": "qin_campaign_staff_briefing",
            "metadata": {
                "information_ref": INFO_REF,
                "operation_ref": OP_REF,
                "destination_ref": "loc_kanyou",
                "strategic_target_ref": "loc_sanyou",
                "scenario_background": True,
            },
            "summary": "The Qin Military Bureau delivered the actionable staging packet: Tang Wei is to march his assembled field command to Kanyou and report there; Sanyou remains the strategic objective, but Qin has not authorized a frontier crossing or battle commitment.",
        },
    ]
    write("state/history/events/index.json", history)


def isolate_synthetic_world_arc_fixture() -> None:
    path = Path("tests/runtime/test_world_arcs.py")
    text = path.read_text(encoding="utf-8")
    old = (
        '    operation_index = copy.deepcopy(planner.read("state/operations/index.json"))\n'
        '    operation_index.setdefault("operations", {})[op_ref] = op_path\n'
        '    planner.put("state/operations/index.json", operation_index)\n'
    )
    new = (
        '    operation_index = copy.deepcopy(planner.read("state/operations/index.json"))\n'
        '    operation_index["operations"] = {op_ref: op_path}\n'
        '    operation_index["active_battlefield_operation_refs"] = []\n'
        '    planner.put("state/operations/index.json", operation_index)\n'
    )
    if old not in text:
        raise RuntimeError("expected synthetic-operation fixture block not found")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def verify_boundary() -> None:
    meta = read("state/meta.json")
    assert meta["revision"] == 1
    assert meta["time"] == START
    assert read("state/operations/index.json")["operations"] == {OP_REF: OP_PATH}
    assert read("state/information/index.json")["claims"] == {INFO_REF: INFO_PATH}
    assert len(read("state/history/events/index.json")["events"]) == 7
    for path in (
        "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json",
        "state/cmd/command-groups/cmdgrp.tang_wei.red_lance.json",
        "state/cmd/command-groups/cmdgrp.tang_wei.high_guard.json",
        "state/cmd/command-groups/cmdgrp.tang_wei.black_banner.json",
    ):
        assert read(path).get("active_context_ref") == OP_REF


def main() -> None:
    restore_operation()
    restore_current_briefing()
    reconnect_command_tree()
    restore_curated_history()
    isolate_synthetic_world_arc_fixture()
    verify_boundary()
    print(
        json.dumps(
            {
                "restored_operation": OP_REF,
                "restored_information": INFO_REF,
                "background_events": 7,
                "revision": 1,
                "time": START,
                "synthetic_world_arc_fixture_isolated": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
