from __future__ import annotations

import json
import pytest

from sword_runtime.campaign_briefing import build_campaign_dossier, render_campaign_briefing
from sword_runtime.commands import CommandEnvelope
from sword_runtime.military_echelon import operation_echelon_summary
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.service_runtime import ProductionSwordRuntime

OPERATION = "operation_arc_131572c4e8a2892bbc"


def test_current_tang_wei_army_is_three_primary_commands_not_nineteen_peer_armies(campaign):
    planner = ProductionCampaignPlanner(campaign)
    operation = planner.read(f"state/operations/{OPERATION}.json")
    echelon = operation_echelon_summary(planner, operation)

    assert echelon["primary_command_count"] == 3
    assert echelon["tactical_formation_count"] == 19
    by_name = {row["name"]: row for row in echelon["primary_commands"]}
    assert by_name["High Guard"]["strength"] == 4500 and by_name["High Guard"]["tactical_leaf_count"] == 9
    assert by_name["Black Banner"]["strength"] == 4000 and by_name["Black Banner"]["tactical_leaf_count"] == 8
    assert by_name["Red Lance"]["strength"] == 1000 and by_name["Red Lance"]["tactical_leaf_count"] == 2

    dossier = build_campaign_dossier(planner, OPERATION)
    briefing = render_campaign_briefing(planner, dossier)
    assert "9,500 troops organized under 3 primary command" in briefing
    assert "9,500 troops in 19 formation" not in briefing
    assert "field body" in briefing


def test_current_revision_hold_can_cross_campaign_march_frontier_and_commit(campaign):
    """Replay the revision-7 standing-hold path across Ouki/Mou Gou march arrivals."""
    before = json.load(open(campaign / "state/meta.json"))
    if before.get("revision") != 7 or before.get("time") != "244-BCE-10-16T06:00:00+08:00":
        pytest.skip("historical revision-7 march-frontier replay requires its exact supplied save")
    runtime = ProductionSwordRuntime(campaign)
    command = CommandEnvelope(
        before["campaign_id"], "play-regression.hold-cross-march", before["player_id"],
        "advance_time", before["revision"], before["time"],
        {"target_time": "244-BCE-10-16T21:00:00+08:00", "stop_on_player_event": False},
        mode="gameplay",
    )
    preview = runtime.preview_for_execution(command)
    assert preview["status"] in {"ready", "ready_execute_only"}
    execution = runtime.execute(command)
    assert execution.status == "committed"

    after = json.load(open(campaign / "state/meta.json"))
    assert after["revision"] == before["revision"] + 1
    assert after["time"] == "244-BCE-10-16T21:00:00+08:00"
    owners = json.load(open(campaign / "state/index/owner-index.json"))["owners"]
    for ref in ("formation_qin_mou_gou_central", "formation_qin_ousen_central", "formation_qin_mobile_reserve"):
        formation = json.load(open(campaign / owners[ref]))
        assert formation["location_ref"] == "loc_sanyou"
