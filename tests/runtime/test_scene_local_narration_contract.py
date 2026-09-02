from sword_runtime.api.interaction_surface import fresh_runtime_projection


def test_fresh_projection_allows_reversible_scene_local_dialogue_without_persisting_world_outcomes():
    context = {
        "campaign": {"world_time": "245-BCE-12-05T06:22:48+08:00", "revision": 33},
        "player": {"location": "loc_kanyou", "health": "healthy", "fatigue": 0},
        "controlled_formations": [],
    }

    projection = fresh_runtime_projection(context, [], [])
    contract = projection["scene_local_narration_contract"]

    assert contract["mode"] == "presentation_only_reversible"
    assert contract["reversible_local_continuation"] is True
    assert contract["persistent_consequences_require_runtime"] is True
    assert contract["interaction_attempt_establishes_external_outcome"] is False
    assert contract["ai_authors_human_performance"] is True
    assert contract["llm_owns_moment_to_moment_scene_direction"] is True
    assert contract["llm_owns_narrative_scene_lifecycle"] is True
    assert contract["formal_scene_session_is_optional_continuity_tool"] is True
    assert contract["runtime_command_completion_is_not_scene_completion"] is True
    assert contract["present_people_are_active_agents"] is True
    assert contract["npc_initiative_requires_player_activation"] is False
    assert contract["player_action_should_receive_world_response_before_recap"] is True
    assert contract["repetition_without_new_human_practical_or_causal_information_is_not_progress"] is True
    assert "allowed_examples" not in contract
    assert "persistent_boundary_examples" not in contract
