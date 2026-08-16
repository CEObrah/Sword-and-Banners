from sword_runtime.house_field_preparation_gate import _is_explicit_field_preparation_attempt
from sword_runtime.production_planner import ProductionCampaignPlanner


def test_old_generic_family_military_request_does_not_become_field_preparation() -> None:
    attempt = {
        "actor_id": "char_tang_wei",
        "action": "request",
        "target_ref": "char_tang_ling",
        "player_statement": "Prepare the House for the campaign and review military equipment.",
    }
    assert _is_explicit_field_preparation_attempt(attempt) is False


def test_explicit_current_field_preparation_request_is_routed() -> None:
    attempt = {
        "actor_id": "char_tang_wei",
        "action": "request",
        "target_ref": "char_tang_ling",
        "player_statement": (
            "I accepted Qin field command. Decide whether Kai stays home for valid training. "
            "Prepare my Great Bow Guard and Tang Champions for the campaign, report armor and equipment, "
            "and stage food and fodder for departure."
        ),
    }
    assert _is_explicit_field_preparation_attempt(attempt) is True


def test_production_planner_uses_explicit_field_preparation_gate() -> None:
    names = [cls.__name__ for cls in ProductionCampaignPlanner.__mro__]
    assert "ExplicitHouseFieldPreparationFlowMixin" in names
    assert names.index("ExplicitHouseFieldPreparationFlowMixin") < names.index("HouseFieldPreparationFlowMixin")
