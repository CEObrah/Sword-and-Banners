from sword_runtime.api.contract_guidance import enrich_command_contract


def test_advance_time_contract_explains_standing_training_activity_policy() -> None:
    contract = enrich_command_contract(
        "advance_time",
        {
            "command_type": "advance_time",
            "accepted_payload_keys": ["activity_policy", "hours", "stop_on_player_event", "target_time"],
            "input_guidance": {"rule": "provide exactly one of hours or target_time"},
        },
    )

    activity = contract["input_guidance"]["activity_policy"]
    assert "continues by default" in activity["rule"]
    assert activity["fields"]["player_standing_training"]["type"] == "boolean"
    assert "set false to suspend" in activity["fields"]["player_standing_training"]["rule"]
    assert "explicitly ordered to train" in activity["fields"]["formation_refs"]["rule"]
    assert "scheduler-owned" in activity["fields"]["formation_refs"]["rule"]
    assert "automatically settles due Runtime-owned causal work" in activity["autonomy_rule"]
    assert "must not enumerate or replay" in activity["autonomy_rule"]
    assert "same advance_time transaction" in activity["settlement_rule"]
    assert "pre-existing or manually deferred credit" in activity["settlement_rule"]
    assert "informational campaign-event notices" in activity["event_boundary_rule"]
    assert "stop_on_player_event" in activity["event_boundary_rule"]


def test_travel_contract_explains_implicit_command_staff_muster() -> None:
    contract = enrich_command_contract(
        "travel",
        {
            "command_type": "travel",
            "input_guidance": {
                "mode": {"default": "foot"},
                "formation_refs": {"type": "array", "maximum_items": 128},
            },
        },
    )

    escort = contract["input_guidance"]["formation_refs"]
    assert escort["maximum_items"] == 128
    assert "implicitly includes its saved exact commander and deputy" in escort["rule"]
    assert "physically musters" in escort["rule"]
    assert "never teleporting staff" in escort["rule"]


def test_unrelated_contract_is_not_enriched() -> None:
    original = {"command_type": "market_purchase", "input_guidance": {"quantity": {"minimum": 1}}}
    assert enrich_command_contract("market_purchase", original) == original
