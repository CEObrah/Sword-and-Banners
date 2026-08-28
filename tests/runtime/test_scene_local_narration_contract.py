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
    assert "allowed_examples" not in contract
    assert "persistent_boundary_examples" not in contract
