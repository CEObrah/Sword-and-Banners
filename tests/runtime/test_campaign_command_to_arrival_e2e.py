from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

from sword_runtime.commands import CommandEnvelope
from sword_runtime.service_runtime import ProductionSwordRuntime
from sword_runtime.vitality import summarize_playability_vitality


OPERATION_REF = "operation_arc_131572c4e8a2892bbc"
ORIGIN_REF = "loc_qin_eastern_depot"
DESTINATION_REF = "loc_sanyou"
ORDER_REF = "operational_order_test_command_to_arrival_e2e"


def _read(root: Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _write(root: Path, rel: str, value: dict) -> None:
    (root / rel).write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _seed_pre_arrival_actionable_order(campaign: Path) -> tuple[str, list[str]]:
    owners = _read(campaign, "state/index/owner-index.json")["owners"]
    operation_path = _read(campaign, "state/operations/index.json")["operations"][OPERATION_REF]
    operation = _read(campaign, operation_path)
    opposing = {
        str(ref)
        for ref in operation.get("opposing_formation_refs", [])
        if isinstance(ref, str) and ref
    }
    formation_refs = [
        str(ref)
        for ref in operation.get("formation_refs", [])
        if isinstance(ref, str) and ref and str(ref) not in opposing
    ]
    assert formation_refs

    player = _read(campaign, "state/player.json")
    player["location"] = ORIGIN_REF
    player["current_location"] = ORIGIN_REF
    player.setdefault("career_state", {})["appointments"] = [{
        "kind": "qin_field_command",
        "office": "field_command:test_command_to_arrival_e2e",
        "state_ref": "state_qin",
        "formation_ref": formation_refs[0],
        "formation_refs": list(formation_refs),
        "operation_ref": OPERATION_REF,
        "status": "active",
    }]
    _write(campaign, "state/player.json", player)

    for formation_ref in formation_refs:
        formation_path = str(owners[formation_ref])
        formation = _read(campaign, formation_path)
        formation["location_ref"] = ORIGIN_REF
        formation["command_authority"] = "char_tang_wei"
        _write(campaign, formation_path, formation)

    world_time = str(_read(campaign, "state/runtime.json")["world_time"])
    order = {
        "order_ref": ORDER_REF,
        "issued_at": world_time,
        "issuer_ref": "state_qin",
        "arc_ref": str(
            operation.get("arc_ref")
            or operation.get("campaign_arc_ref")
            or "arc_ryo_fui_northern_wei_campaign"
        ),
        "target_ref": "state_wei",
        "objective": "march to Sanyou and join the northern Wei campaign",
        "status": "staff_briefed_awaiting_commander_execution",
        "actionability_status": "actionable",
        "applies_to_formation_refs": list(formation_refs),
        "mission_packet": {
            "mission_phase": "campaign_concentration_and_advance",
            "destination_ref": DESTINATION_REF,
            "strategic_target_ref": DESTINATION_REF,
            "hostile_entry_authorized": True,
            "entry_status": "authorized",
            "phase_status": "ready_for_commander_execution",
            "agency_rule": "Proceed to the assigned operational area under current Qin authority.",
        },
    }
    operation = copy.deepcopy(operation)
    operation["operational_orders"] = list(operation.get("operational_orders", [])) + [order]
    operation["last_operational_order_ref"] = ORDER_REF
    operation["order_status"] = order["status"]
    operation["campaign_phase"] = "campaign_concentration_and_advance"
    operation["location_ref"] = ORIGIN_REF
    _write(campaign, operation_path, operation)

    subprocess.run(["git", "-C", str(campaign), "add", "state"], check=True)
    subprocess.run(
        ["git", "-C", str(campaign), "commit", "--quiet", "-m", "Seed command-to-arrival regression"],
        check=True,
    )
    return str(operation_path), formation_refs


def test_actionable_campaign_order_reaches_operational_area_without_command_loop(campaign: Path, tmp_path: Path) -> None:
    operation_path, formation_refs = _seed_pre_arrival_actionable_order(campaign)
    runtime = ProductionSwordRuntime(campaign, runtime_root=tmp_path / "runtime-command-to-arrival")
    meta = runtime.store.read_json("state/meta.json")

    command = CommandEnvelope(
        campaign_id=meta["campaign_id"],
        request_id="test-command-to-arrival-e2e",
        actor_id=meta["player_id"],
        command_type="travel",
        expected_revision=meta["revision"],
        submitted_at=meta["time"],
        payload={
            "destination_ref": DESTINATION_REF,
            "formation_refs": list(formation_refs),
            "mode": "foot",
        },
        mode="gameplay",
    )
    result = runtime.execute(command).receipt.result

    owners = runtime.store.read_json("state/index/owner-index.json")["owners"]
    assert result["destination"] == DESTINATION_REF
    assert {
        runtime.store.read_json(str(owners[formation_ref]))["location_ref"]
        for formation_ref in formation_refs
    } == {DESTINATION_REF}

    operation = runtime.store.read_json(operation_path)
    assert operation["campaign_phase"] in {"operational_area_arrival", "enemy_contact"}
    assert operation["order_status"] not in {
        "awaiting_operational_briefing",
        "staff_briefed_awaiting_commander_execution",
    }

    meta_after = runtime.store.read_json("state/meta.json")
    runtime_after = runtime.store.read_json("state/runtime.json")
    assert meta_after["time"] == runtime_after["world_time"] == result["world_time"]

    vitality = summarize_playability_vitality(runtime.store)
    assert vitality["blocked_pending_qin_operational_briefings"] == 0
    assert vitality["campaign_command_decisions_exposed_before_delivery"] == 0
    assert vitality["pending_qin_operational_briefing_responses_without_actionability"] == 0
    assert vitality["diagnostics"] == []
