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


def test_current_exact_present_family_gets_private_director_context_before_conversation_session(campaign, tmp_path):
    from sword_runtime.api.warfare_operations import WarfareCampaignOperations
    from sword_runtime.service_runtime import ProductionSwordRuntime

    operations = WarfareCampaignOperations(
        ProductionSwordRuntime(campaign, runtime_root=tmp_path / "runtime-scene-director")
    )
    context = operations.play_context()
    packet = context["scene"]["gm_private_director_context"]["present_people_context"]
    refs = {row["person_ref"] for row in packet["present_people"]}

    assert {"char_tang_kai", "char_tang_ling"} <= refs
    assert packet["privacy"] == "gm_private_scene_bounded_omniscient_truth_not_player_knowledge"
    assert packet["mechanical_consequence_authority"] is False
    assert "before a formal conversation session" in packet["director_rule"]

    kai = operations.person_sheet("char_tang_kai")
    envelope = kai["npc_response_envelope"]
    assert envelope["scene_focus"]["kind"] == "established_scene"
    assert envelope["mechanical_consequence_authority"] is False
    assert "gm_private_character_truth" in envelope


def test_private_director_prioritizes_active_session_participant_over_cast_sort_order():
    from sword_runtime.api.warfare_operations import WarfareCampaignOperations

    refs = [f"npc.{idx:02d}" for idx in range(20)]
    people = {
        ref: {
            "schema": "sab_character",
            "owner_id": ref,
            "name": f"NPC {idx}",
            "current_location": "loc_test_hall",
            "hidden_goals": [f"goal-{idx}"],
        }
        for idx, ref in enumerate(refs)
    }

    class Store:
        def read_json(self, path):
            if path == "state/index/owner-index.json":
                return {"owners": {ref: f"state/char/{ref}.json" for ref in refs}}
            if path == "state/relationships.json":
                return {"edges": []}
            if path == "game/data/people/behavior-profiles/index.json":
                raise FileNotFoundError(path)
            if path.startswith("state/char/"):
                ref = path.removeprefix("state/char/").removesuffix(".json")
                return people[ref]
            raise FileNotFoundError(path)

    ops = object.__new__(WarfareCampaignOperations)
    ops.store = Store()
    context = {
        "campaign": {"player_id": "char_tang_wei"},
        "player": {"location": "loc_test_hall"},
        "scene": {
            "scene_cast": {"present_people": [{"person_id": ref, "name": people[ref]["name"]} for ref in refs]},
            "active_scene_session": {
                "session_ref": "scene.test",
                "participant_refs": ["char_tang_wei", refs[-1]],
            },
        },
    }

    projected = ops._with_gm_private_scene_director_context(context)
    packet = projected["scene"]["gm_private_director_context"]["present_people_context"]
    projected_refs = [row["person_ref"] for row in packet["present_people"]]
    assert refs[-1] in projected_refs
    assert projected_refs[0] == refs[-1]
    assert packet["candidate_present_people_count"] == 20
    assert packet["present_people_context_count"] == 16
    assert packet["present_people_context_truncated"] is True
