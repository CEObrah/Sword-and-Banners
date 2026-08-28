from sword_runtime.api.warfare_operations import _safe_service_performance_cues


def test_service_performance_cues_rank_visible_capabilities_without_private_goal_leakage():
    projected = {
        "person_id": "char_example_general",
        "role": "General, Example Field Army",
        "skills": {
            "Tactics": 190,
            "Strategy": 180,
            "Leadership": 175,
            "Logistics": 45,
            "Scouting": 60,
        },
        # The helper must ignore anything outside the already-player-visible
        # projection even if a caller accidentally supplies it.
        "goal_state": {"current_goals": ["secret private objective"]},
    }

    cues = _safe_service_performance_cues(projected)

    assert cues["public_role_context"] == "General, Example Field Army"
    assert "military feasibility" in cues["role_lens"]
    assert [row["domain"] for row in cues["professional_lenses"]] == [
        "Tactics",
        "Strategy",
        "Leadership",
    ]
    assert all(row["basis"] == "player_visible_service_capability" for row in cues["professional_lenses"])
    assert "secret private objective" not in repr(cues)
    assert "do not establish" in cues["use_rule"].lower()


def test_identity_only_scene_people_still_receive_a_public_role_lens():
    cues = _safe_service_performance_cues({"role": "Legal ministerial office"})

    assert cues["public_role_context"] == "Legal ministerial office"
    assert "law" in cues["role_lens"]
    assert "authority" in cues["role_lens"]
    assert "professional_lenses" not in cues


def test_family_role_is_safe_context_without_synthetic_personality():
    cues = _safe_service_performance_cues({"family_role": "elder sibling"})

    assert cues["public_role_context"] == "elder sibling"
    assert cues["family_role_context"] == "elder sibling"
    assert "professional_lenses" not in cues
    assert "personality" in cues["use_rule"]
