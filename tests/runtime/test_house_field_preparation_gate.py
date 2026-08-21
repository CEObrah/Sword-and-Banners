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
            "Prepare my House Guard and Tang Champions for the campaign, report armor and equipment, "
            "and stage food and fodder for departure."
        ),
    }
    assert _is_explicit_field_preparation_attempt(attempt) is True


def test_explicit_all_troops_wording_routes_without_repeating_formation_names() -> None:
    attempt = {
        "actor_id": "char_tang_wei",
        "action": "request",
        "target_ref": "char_tang_zhu",
        "player_statement": (
            "Prepare food, fodder, arrows, replacement weapons, armor, shields, tack, and other field "
            "equipment that can lawfully be spared, so supplies can follow me when the route and authority "
            "allow it. I am taking all of my troops, commanders, and officers with me. Kai, keep training. "
            "I am going to war now."
        ),
    }
    assert _is_explicit_field_preparation_attempt(attempt) is True


def test_inclusive_troop_wording_still_requires_full_field_prep_bundle() -> None:
    attempt = {
        "actor_id": "char_tang_wei",
        "action": "request",
        "target_ref": "char_tang_zhu",
        "player_statement": "Kai stays home. Prepare all my troops for departure.",
    }
    assert _is_explicit_field_preparation_attempt(attempt) is False


def test_production_planner_uses_explicit_field_preparation_gate_and_material_handoff() -> None:
    names = [cls.__name__ for cls in ProductionCampaignPlanner.__mro__]
    assert "HouseFieldDeparturePreflightMixin" in names
    assert "CommandStaffMusterChronologyMixin" in names
    assert "CommandStaffMovementMixin" in names
    assert "HouseFieldPreparationIssueMixin" in names
    assert "ExplicitHouseFieldPreparationFlowMixin" in names
    assert "HouseFieldPreparationFlowMixin" in names
    assert names.index("HouseFieldDeparturePreflightMixin") < names.index("CommandStaffMovementMixin")
    assert names.index("CommandStaffMusterChronologyMixin") < names.index("CommandStaffMovementMixin")
    assert names.index("HouseFieldPreparationIssueMixin") < names.index("ExplicitHouseFieldPreparationFlowMixin")
    assert names.index("ExplicitHouseFieldPreparationFlowMixin") < names.index("HouseFieldPreparationFlowMixin")
