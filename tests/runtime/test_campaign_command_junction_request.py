from __future__ import annotations

from sword_runtime.campaign_command_requests import _request_topics, _response_for
from sword_runtime.production_planner import ProductionCampaignPlanner


OPERATION_PATH = "state/operations/operation_arc_131572c4e8a2892bbc.json"


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()
    return planner


def test_legacy_junction_request_statement_resolves_to_semantic_topic() -> None:
    attempt = {
        "player_statement": (
            "Request General Mou Gou's exact present junction plan and the point "
            "at which my army is to join the main body."
        )
    }
    assert _request_topics(attempt) == ("junction_plan",)
    assert _request_topics({"topic": "campaign_command:junction_plan"}) == ("junction_plan",)


def test_junction_plan_response_uses_exact_campaign_authority_without_inventing_a_point(campaign) -> None:
    planner = _planner(campaign)
    operation = planner.read(OPERATION_PATH)
    cycle_ref = str(operation["campaign_command_cycle_ref"])
    cycle = planner.read(planner.owner_path(cycle_ref))

    response = _response_for(planner, cycle, ("junction_plan",))
    assert response is not None
    summary, dispositions = response
    assert dispositions["junction_plan"] in {
        "confirmed_current_junction_order",
        "no_separate_current_junction_order",
    }
    assert "junction" in summary.lower() or "rendezvous" in summary.lower()
    assert "invent" in summary.lower() or "exact order" in summary.lower()
