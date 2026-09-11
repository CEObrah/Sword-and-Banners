from __future__ import annotations

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner


def _kill(planner: ProductionCampaignPlanner, person_ref: str) -> None:
    path, person = planner._command_person(person_ref)
    planner._settle_person_death(person_ref, path, person, str(planner._world_time()), "test death")


def test_designated_successor_replaces_dead_command_group_commander_without_parent_child_double_hat(campaign):
    planner = ProductionCampaignPlanner(campaign)
    group_ref = "cmdgrp.shin.hi_shin"
    child_ref = "formation_qin_kyoukai_command"
    _kill(planner, "char_shin")

    group = planner.read(f"state/cmd/command-groups/{group_ref}.json")
    child = planner.read(planner.owner_path(child_ref))
    index = planner.read("state/cmd/command-groups/index.json")
    commander_index = planner.read("state/index/commander-formation-index.json")
    successor = planner.read(planner.owner_path("char_kyoukai"))
    dead = planner.read(planner.owner_path("char_shin"))

    assert group["commander_ref"] == "char_kyoukai"
    assert "char_kyoukai" not in group.get("successor_refs", [])
    assert child["commander_ref"] is None
    assert child["status"] == "commander_vacant"
    assert child_ref not in commander_index.get("assignments", {}).get("char_kyoukai", [])
    assert group_ref in index["command_person_groups"]["char_kyoukai"]
    assert successor["command_assignment"]["command_group_ref"] == group_ref
    assert successor["command_assignment"]["formation_ref"] == group_ref
    assert successor["military_command"]["formation_scope"] == group_ref
    assert successor.get("current_formation_id") is None
    assert dead["command_assignment"]["billet"] == "deceased"
    assert "command_group_ref" not in dead["command_assignment"]

def test_npc_command_uses_explicit_successor_order_not_staff_role(campaign):
    planner = ProductionCampaignPlanner(campaign)
    group_ref = "cmdgrp.kankoku.defense_army"
    group = planner.read(f"state/cmd/command-groups/{group_ref}.json")
    commander = group["commander_ref"]
    assert group["successor_refs"]
    successor = group["successor_refs"][0]
    assert group.get("role_assignments", {}).get(successor) == "chief_of_staff"

    _kill(planner, commander)

    after = planner.read(f"state/cmd/command-groups/{group_ref}.json")
    index = planner.read("state/cmd/command-groups/index.json")
    assert after["commander_ref"] == successor
    assert successor not in after.get("role_assignments", {})
    assert successor not in after.get("direct_person_refs", [])
    assert index["primary_person_group"].get(commander) is None
    assert group_ref in index["command_person_groups"][successor]


def test_player_owned_command_does_not_invent_undesigned_succession(campaign):
    planner = ProductionCampaignPlanner(campaign)
    group_ref = "cmdgrp.tang_wei.red_lance"
    path = f"state/cmd/command-groups/{group_ref}.json"
    group = dict(planner.read(path))
    group["successor_refs"] = []
    planner.put(path, group)

    _kill(planner, "char_tang_command_red_lance_1000")

    after = planner.read(path)
    assert after["commander_ref"] is None
    assert after["organizational_state"]["status"] == "commander_vacant"


def test_exact_person_death_retires_scheduler_career_and_faction_routes(campaign):
    planner = ProductionCampaignPlanner(campaign)
    person_ref = "char_heki"
    runtime_before = planner.read("state/runtime.json")
    person_host_ids = [
        host_id for host_id, host in runtime_before.get("hosts", {}).items()
        if isinstance(host, dict) and host.get("kind") == "person" and host.get("owner_ref") == person_ref
    ]
    assert person_host_ids
    assert person_ref in planner.read("state/military/career-network/index.json")["people"]
    assert planner.read("state/index/faction-alignment-candidates.json")["member_state"].get(person_ref) == "qin"

    path, person = planner._command_person(person_ref)
    planner._settle_person_death(person_ref, path, person, str(planner._world_time()), "test route retirement")

    dead = planner.read(path)
    runtime = planner.read("state/runtime.json")
    career = planner.read("state/military/career-network/index.json")
    alignment = planner.read("state/index/faction-alignment-candidates.json")
    assert dead["life_status"] == "dead"
    assert dead["activity_contract"]["autonomous_enabled"] is False
    assert dead["autonomous_activity_state"]["enabled"] is False
    assert "next_due" not in dead["autonomous_activity_state"]
    assert all(host_id not in runtime["hosts"] for host_id in person_host_ids)
    assert all(
        person_ref not in host.get("routed_person_refs", [])
        for host in runtime["hosts"].values() if isinstance(host, dict)
    )
    assert all(event.get("target_host") not in person_host_ids for event in runtime["events"])
    assert person_ref not in career["people"]
    assert person_ref not in career.get("public_commander_refs", [])
    assert person_ref not in alignment["member_state"]
    assert person_ref not in alignment.get("by_state", {}).get("qin", {}).get("person_refs", [])


def test_nested_army_successor_cascade_preserves_both_armies(campaign):
    planner = ProductionCampaignPlanner(campaign)
    parent_ref = "cmdgrp.ouki.field_army"
    child_ref = "cmdgrp.tou.field_army"
    parent_before = planner.read(f"state/cmd/command-groups/{parent_ref}.json")
    child_before = planner.read(f"state/cmd/command-groups/{child_ref}.json")
    parent_units = list(parent_before["units"])
    child_units = list(child_before["units"])
    child_successor = child_before["successor_refs"][0]

    _kill(planner, "char_ouki")

    parent = planner.read(f"state/cmd/command-groups/{parent_ref}.json")
    child = planner.read(f"state/cmd/command-groups/{child_ref}.json")
    assert parent["commander_ref"] == "char_tou"
    assert child["commander_ref"] == child_successor
    assert parent["units"] == parent_units
    assert child["units"] == child_units
    assert child["parent_command_group_ref"] == parent_ref
    assert parent["organizational_state"]["current_recursive_strength"] == parent_before["organizational_state"]["current_recursive_strength"]
    assert child["organizational_state"]["current_recursive_strength"] == child_before["organizational_state"]["current_recursive_strength"]
