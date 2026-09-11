from pathlib import Path

from sword_runtime.api.gm_scene_context import build_gm_scene_context

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/SKILL.md"
SCENE = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/scene-craft.md"
NARRATION = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/narration.md"
CHOICES = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/choices.md"
PROJECT = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/assets/project-instructions.md"


def test_skill_hard_rejects_polished_state_dump_and_default_six_menu():
    skill = SKILL.read_text(encoding="utf-8").lower()
    scene = SCENE.read_text(encoding="utf-8").lower()
    narration = NARRATION.read_text(encoding="utf-8").lower()
    choices = CHOICES.read_text(encoding="utf-8").lower()
    assert "hard narrative quality gate" in skill
    assert "serialized lived saga, not a turn report" in skill
    assert "hard anti-briefing gate" in scene
    assert "polished briefing prose" in scene
    assert "goal is not to empty the context packet into prose" in scene
    assert "narrative focus beats informational completeness" in narration
    assert "raw summaries" in narration and "research notes" in narration
    assert "2 to 4 materially distinct choices" in choices
    assert "more than 5 should be exceptional" in choices


def test_runtime_marks_fresh_people_process_scene_as_high_paraphrase_risk():
    context = {
        "campaign": {"world_time": "244-BCE-10-04T06:00:00+08:00", "player_id": "char_tang_wei"},
        "player": {"location": "loc_wei_regional_02"},
        "scene": {
            "location": "loc_wei_regional_02",
            "scene_cast": {"present_people": [
                {"person_id": "char_tang_wei", "name": "Tang Wei", "role": "General"},
                {"person_id": "char_test_commander", "name": "Test Commander", "role": "Commander", "scene_basis": ["campaign_command_event"]},
            ]},
        },
        "active_scene_session": None,
        "controlled_operations": [{"operation_ref": "operation.test", "status": "active"}],
    }
    gm = build_gm_scene_context(context)
    direction = gm["scene_direction"]
    assert direction["fresh_scene_entry"] is True
    assert direction["narrative_stage_hint"] == "approach_or_anticipation"
    assert direction["raw_context_paraphrase_risk"] == "high"
    assert gm["writer_contract"]["serial_scene_not_turn_summary"] is True
    assert gm["writer_contract"]["raw_summaries_are_reference_not_prose"] is True
    assert gm["writer_contract"]["anti_state_dump_gate"] is True


def test_behavior_profile_index_registers_every_authored_profile():
    import json
    index = json.loads((ROOT / "game/data/people/behavior-profile-index.json").read_text(encoding="utf-8"))
    authored = {}
    for path in (ROOT / "game/data/people/behavior-profiles").glob("*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        authored[row["person_id"]] = path.relative_to(ROOT).as_posix()
    assert index["count"] == len(authored)
    assert index["profiles"] == dict(sorted(authored.items()))
    for ref in ("char_lin_zhen", "char_ren_qiao", "char_han_shou", "char_pei_rong", "char_deng_kai", "char_lu_cheng"):
        assert ref in index["profiles"]


def test_recurring_tang_wei_commanders_have_names_and_behavior_profiles():
    index = __import__("json").loads((ROOT / "game/data/people/behavior-profile-index.json").read_text(encoding="utf-8"))
    refs = [
        "char_tang_command_black_banner_4000",
        "char_tang_command_red_lance_1000",
        "char_tang_command_high_guard_foot_core",
    ]
    for ref in refs:
        path = ROOT / "state/char" / (ref.removeprefix("char_").replace("_", "-") + ".json")
        person = __import__("json").loads(path.read_text(encoding="utf-8"))
        assert not person["name"].startswith("Tang Black Banner")
        assert not person["name"].startswith("Tang Red Lance")
        assert not person["name"].startswith("Tang High Guard")
        profile_path = index["profiles"][ref]
        profile = __import__("json").loads((ROOT / profile_path).read_text(encoding="utf-8"))
        assert profile["person_id"] == ref
        assert profile["behavior"].get("core_traits")
        assert profile["behavior"].get("speech_pattern")


def test_authored_commander_behavior_profiles_remain_available_without_forcing_a_daily_command_scene(campaign, tmp_path):
    from sword_runtime.api.warfare_operations import WarfareCampaignOperations
    from sword_runtime.service_runtime import ProductionSwordRuntime

    operations = WarfareCampaignOperations(
        ProductionSwordRuntime(campaign, runtime_root=tmp_path / "runtime-narrative-profile")
    )
    lin = operations._gm_private_behavior_profile("char_lin_zhen")
    black = operations._gm_private_behavior_profile("char_tang_command_black_banner_4000")
    red = operations._gm_private_behavior_profile("char_tang_command_red_lance_1000")
    assert lin["behavior"]["speech_pattern"]
    assert black["behavior"]["speech_pattern"]
    assert "formation integrity" in black["behavior"]["values"]
    assert red["behavior"]["speech_pattern"]
    assert "mobility" in red["behavior"]["values"]


def test_evidence_limited_behavior_profile_reaches_gm_private_direction(campaign, tmp_path):
    from sword_runtime.api.warfare_operations import WarfareCampaignOperations
    from sword_runtime.service_runtime import ProductionSwordRuntime

    operations = WarfareCampaignOperations(
        ProductionSwordRuntime(campaign, runtime_root=tmp_path / "runtime-evidence-profile")
    )
    profile = operations._gm_private_behavior_profile("char_mou_gou")
    assert profile["mode"] == "evidence_limited_role_driven"
    assert profile["known_anchors"]["career_anchor"]
    assert profile["dialogue_constraints"]
    assert profile["mechanical_authority"] is False


def test_compact_writer_packet_keeps_report_prose_and_static_director_doctrine_cold(campaign):
    from sword_runtime.api.campaign_planning_operations import CampaignPlanningAwareOperations
    from sword_runtime.api.command_discovery import compact_play_context
    from sword_runtime.engine import SwordRuntime

    compact = compact_play_context(CampaignPlanningAwareOperations(SwordRuntime(campaign)).play_context())
    gm = compact["gm_scene_context"]
    director_context = gm["gm_private_scene_truth"]["director_context"]
    private_context = director_context.get("present_people_context")
    if private_context is not None:
        assert "director_rule" not in private_context
        assert "selection_rule" not in private_context
        assert "performance_cues_rule" not in private_context
    assert all("summary" not in row for row in gm["world_pressure"])
    assert all("summary" not in row for row in compact.get("interaction_handles", []))

    operation = next(
        row for row in compact["controlled_operations"]
        if row.get("operation_ref") == "operation_arc_131572c4e8a2892bbc"
    )
    command = operation["campaign_command"]
    assert "recent_upward_reports" not in command
    assert command.get("upward_report_count", 0) >= 1
    assert "directive_text" not in command.get("current_superior_directive", {})


def test_campaign_narration_uses_real_local_command_echelons_and_nonblocking_daily_ticks():
    combat = (ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/combat-and-warfare.md").read_text(encoding="utf-8").lower()
    assert "player-facing scene or turn boundary" in combat
    assert "local_field_command_posts" in combat
    assert "physically present formation commander" in combat
    assert "preserve that target" in combat and "courier" in combat
    assert "use one physical communications law" in combat
    assert "prepared` is not `received" in combat or "prepared`, `written`, or `sent` is not `received" in combat


def test_live_turn_qa_footer_is_mandatory_but_must_not_invent_defects():
    skill = SKILL.read_text(encoding="utf-8")
    review = (ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/live-play-review.md").read_text(encoding="utf-8")
    project = PROJECT.read_text(encoding="utf-8")
    scene = SCENE.read_text(encoding="utf-8")
    assert "after **every live gameplay turn**" in skill
    assert "`PASS`, `WARN`, or `FAIL`" in skill
    assert "append exactly one compact `OOC QA:` line" in review
    assert "never invent" in review.lower()
    assert "after every live gameplay turn" in project.lower()
    assert "do not append an `ooc qa:` footer" not in project.lower()
    assert "pass — no material defect observed this turn" in scene.lower()
