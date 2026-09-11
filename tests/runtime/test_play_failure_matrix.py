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


