from sword_runtime.api.warfare_operations import _gm_private_character_truth, _gm_private_goal_cognition


def test_private_goal_cognition_is_bounded_and_explicitly_not_player_knowledge():
    person = {
        "goal_state": {
            "current_goals": ["earn command credibility through service"],
            "institutional_duties": ["obey lawful Qin campaign authority"],
            "personal_desires": ["rise through merit"],
        }
    }
    projected = _gm_private_goal_cognition(person)
    assert projected["current_goals"] == ["earn command credibility through service"]
    assert projected["privacy"] == "gm_private_cognition_not_player_knowledge"
    assert "never narrate" in projected["use_rule"].lower()
    assert "mechanical" in projected["use_rule"].lower()


def test_private_goal_cognition_does_not_invent_missing_characterization():
    assert _gm_private_goal_cognition({}) == {}
    assert _gm_private_goal_cognition({"goal_state": {"current_goals": []}}) == {}


def test_private_character_truth_gives_gm_scene_truth_without_making_it_player_knowledge():
    projected = _gm_private_character_truth(
        {
            "name": "Han",
            "attributes": {"strength": 78, "agility": 71},
            "skills": {"sword": 64},
            "health": {"status": "wounded", "injuries": [{"zone": "left_arm", "severity": 28}]},
            "fatigue": 440,
            "military_rank": "1000-man commander",
            "goal_state": {"current_goals": ["hold the road"]},
        }
    )

    assert projected["attributes"]["strength"] == 78
    assert projected["skills"]["sword"] == 64
    assert projected["health"]["status"] == "wounded"
    assert projected["privacy"] == "gm_private_scene_bounded_omniscient_truth_not_player_knowledge"
    assert "do not state" in projected["use_rule"].lower()
    assert "wei's knowledge" in projected["use_rule"].lower()
