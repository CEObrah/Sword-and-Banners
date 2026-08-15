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
    assert "omitting it means" in activity["rule"]
    assert activity["fields"]["player_standing_training"]["type"] == "boolean"
    assert "explicitly ordered to train" in activity["fields"]["formation_refs"]["rule"]
    assert "standing_training_settle" in activity["settlement_rule"]
    assert "stop_on_player_event" in activity["event_boundary_rule"]


def test_non_time_contract_is_not_enriched() -> None:
    original = {"command_type": "travel", "input_guidance": {"mode": {"default": "foot"}}}
    assert enrich_command_contract("travel", original) == original
