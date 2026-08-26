from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.api.equipment_operations import EquipmentAwareCampaignOperations
from sword_runtime.commands import CommandEnvelope
from sword_runtime.engine import SwordRuntime


def _ops(campaign):
    return EquipmentAwareCampaignOperations(SwordRuntime(campaign))


def _present_people(context):
    cast = context.get("scene", {}).get("scene_cast", {})
    return {
        row["person_id"]: row
        for row in cast.get("present_people", [])
        if isinstance(row, dict) and isinstance(row.get("person_id"), str)
    }



def _co_locate_parents(campaign):
    player_path = Path(campaign) / "state/player.json"
    player = json.loads(player_path.read_text())
    location = "loc_tang_manor_inner_citadel_family_hall"
    player["location"] = location
    player_path.write_text(json.dumps(player, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    for filename in ("tang-zhu.json", "tang-ling.json"):
        path = Path(campaign) / "state/char" / filename
        person = json.loads(path.read_text())
        person["current_location"] = location
        path.write_text(json.dumps(person, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

def test_co_located_parents_are_direct_scene_contacts(campaign):
    _co_locate_parents(campaign)
    operations = _ops(campaign)
    context = operations.play_context()
    present = _present_people(context)

    assert present["char_tang_zhu"]["relation"] == "parent"
    assert present["char_tang_ling"]["relation"] == "parent"
    assert present["char_tang_zhu"]["location"] == context["player"]["location"]
    assert present["char_tang_ling"]["location"] == context["player"]["location"]
    assert {"char_tang_zhu", "char_tang_ling"} <= set(context["permitted_person_ids"])

    contract = context["scene"]["scene_local_narration_contract"]
    assert contract["mode"] == "presentation_only_reversible"
    assert contract["persistent_consequences_require_runtime"] is True
    seek_rule = context["commands"]["command_types"]["interaction_action"]["input_guidance"]["seek_contact_rule"]
    assert "Do not use seek_contact" in seek_rule


def test_present_parent_can_receive_a_real_consequential_interaction(campaign):
    _co_locate_parents(campaign)
    operations = _ops(campaign)
    context = operations.play_context()
    command = CommandEnvelope(
        campaign_id=context["campaign"]["campaign_id"],
        request_id="test-present-parent-proposal",
        actor_id=context["campaign"]["player_id"],
        command_type="interaction_action",
        expected_revision=context["campaign"]["revision"],
        submitted_at=context["campaign"]["world_time"],
        payload={
            "target_ref": "char_tang_zhu",
            "action": "present",
            "player_statement": "I want to discuss the House Guard field-preparation proposal with you.",
        },
        mode="gameplay",
    )

    operations._validate_interaction_authority(command)


def test_household_residence_does_not_fake_presence(campaign):
    _co_locate_parents(campaign)
    father_path = Path(campaign) / "state/char/tang-zhu.json"
    father = json.loads(father_path.read_text())
    father["current_location"] = "loc_kanyou"
    father_path.write_text(json.dumps(father, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    context = _ops(campaign).play_context()
    present = _present_people(context)

    assert "char_tang_zhu" not in present
    assert "char_tang_ling" in present


def test_skill_forbids_turning_present_family_into_an_audience_request():
    root = Path(__file__).resolve().parents[2]
    playbook = (
        root
        / "plugins/sword-and-banners/skills/sword-and-banners-game-master/references/scene-playbook.md"
    ).read_text()
    assert "ordinary intent such as `talk to my parents`" in playbook
    assert "Do not translate it into an audience request" in playbook
    assert "Never manufacture gatekeeping" in playbook
