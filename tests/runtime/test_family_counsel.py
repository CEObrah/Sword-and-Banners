from sword_runtime.family_counsel import (
    FamilyCounselMixin,
    _classify_family_counsel,
    _counsel_summary,
)
from sword_runtime.production_planner import ProductionCampaignPlanner


def _attempt(**overrides):
    row = {
        "actor_id": "char_tang_wei",
        "target_ref": "char_tang_ling",
        "action": "ask",
        "process_ref": "event_world_arc_example.report",
        "player_statement": "We have this report. What could we do about it?",
    }
    row.update(overrides)
    return row


def test_exact_parent_report_counsel_is_classified():
    assert _classify_family_counsel(_attempt()) is True
    assert _classify_family_counsel(_attempt(target_ref="char_tang_zhu")) is True


def test_counsel_requires_exact_parent_exact_report_and_counsel_language():
    assert _classify_family_counsel(_attempt(target_ref="char_duan_jin")) is False
    assert _classify_family_counsel(_attempt(process_ref=None)) is False
    assert _classify_family_counsel(_attempt(player_statement="I have brought you the report.")) is False
    assert _classify_family_counsel(_attempt(actor_id="char_other")) is False


def test_parent_counsel_is_advisory_and_role_distinct():
    ling = _counsel_summary("char_tang_ling", "hidden source details must not be echoed")
    zhu = _counsel_summary("char_tang_zhu", "hidden source details must not be echoed")
    assert "Tang Ling" in ling
    assert "Tang Zhu" in zhu
    assert "hidden source details" not in ling
    assert "hidden source details" not in zhu
    assert "spending new House silver" in ling
    assert "do not march House forces" in zhu
    assert ling != zhu


def test_family_counsel_is_in_production_mro_before_household_admin():
    assert FamilyCounselMixin in ProductionCampaignPlanner.__mro__
    assert ProductionCampaignPlanner.__mro__.index(FamilyCounselMixin) < ProductionCampaignPlanner.__mro__.index(
        __import__("sword_runtime.household_request_flow", fromlist=["HouseholdRequestFlowMixin"]).HouseholdRequestFlowMixin
    )
