from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.api.equipment_operations import EquipmentAwareCampaignOperations
from sword_runtime.engine import SwordRuntime


def _ops(campaign):
    return EquipmentAwareCampaignOperations(SwordRuntime(campaign))


def _cast(context, field):
    return {row["person_id"]: row for row in context.get("scene", {}).get("scene_cast", {}).get(field, []) if isinstance(row, dict) and row.get("person_id")}


def test_command_staff_at_current_staging_site_are_nearby_not_teleported_present(campaign):
    player_path=Path(campaign)/"state/player.json"; player=json.loads(player_path.read_text()); player["location"]="loc_kanyou"; player_path.write_text(json.dumps(player)+"\n")
    context=_ops(campaign).play_context()
    nearby=_cast(context,"nearby_people"); present=_cast(context,"present_people")
    refs = (
        "char_lin_zhen",
        "char_tang_command_black_banner_4000",
        "char_tang_command_high_guard_foot_core",
        "char_tang_command_high_guard_qin_reserve",
        "char_tang_command_red_lance_1000",
    )
    assert context["player"]["location"] == "loc_kanyou"
    for ref in refs:
        assert ref in nearby
        assert ref not in present
        assert nearby[ref]["location"] == context["player"]["location"]
    assert "house_or_command_duty" in nearby["char_tang_command_black_banner_4000"]["scene_basis"]


def test_inner_walls_commanders_surface_at_exact_training_ground(campaign):
    player_path=Path(campaign)/"state/player.json"; player=json.loads(player_path.read_text()); player["location"]="loc_tang_manor_training_ground"; player_path.write_text(json.dumps(player)+"\n")
    context=_ops(campaign).play_context(); present=_cast(context,"present_people")
    refs = ("char_cmd_house_tang_inner_walls_general_01", "char_cmd_house_tang_inner_walls_trainee_01")
    for ref in refs:
        assert ref in present
        assert present[ref]["location"] == "loc_tang_manor_training_ground"
        assert present[ref]["scene_basis"]


def test_house_command_routing_does_not_teleport_absent_person(campaign):
    player_path=Path(campaign)/"state/player.json"; player=json.loads(player_path.read_text()); player["location"]="loc_tang_manor_training_ground"; player_path.write_text(json.dumps(player)+"\n")
    context=_ops(campaign).play_context(); present=_cast(context,"present_people"); nearby=_cast(context,"nearby_people")
    assert "char_tang_zhu" not in present
    assert "char_tang_zhu" not in nearby


def test_scene_participants_become_bounded_permitted_people(campaign):
    player_path=Path(campaign)/"state/player.json"; player=json.loads(player_path.read_text()); player["location"]="loc_kanyou"; player_path.write_text(json.dumps(player)+"\n")
    context=_ops(campaign).play_context(); permitted=set(context["permitted_person_ids"])
    assert {"char_lin_zhen","char_tang_command_black_banner_4000","char_tang_command_high_guard_foot_core"} <= permitted
    rule=context["scene"]["scene_cast"]["generic_participation_rule"]
    assert "revalidated against exact current location" in rule


def test_institutional_identity_awareness_separates_recognition_from_relationship(campaign):
    ops=_ops(campaign)
    court=ops._institutional_identity_awareness('char_shou_bun_kun','char_tang_wei')
    general=ops._institutional_identity_awareness('char_ouki','char_tang_wei')
    foreign=ops._institutional_identity_awareness('char_riboku','char_tang_wei')
    ordinary=ops._institutional_identity_awareness('char_shin','char_tang_wei')
    assert court and 'audience:state_qin:court' in court['audience_refs']
    assert 'current_registered_qin_office' in court['known_fact_classes']
    assert general and 'audience:state_qin:military_officers' in general['audience_refs']
    assert foreign and 'house_affiliation' in foreign['known_fact_classes']
    assert 'confidential_current_command' in foreign['restricted_fact_classes']
    assert ordinary is None
    assert 'relationship' in court['relationship_rule']


def test_major_foreign_officer_knows_house_tang_exists_without_confidential_numbers(campaign):
    ops=_ops(campaign)
    awareness=ops._institutional_identity_awareness('char_riboku','house_tang')
    assert awareness
    assert 'institution_name' in awareness['known_fact_classes']
    assert 'exact_private_force_strength' in awareness['restricted_fact_classes']
