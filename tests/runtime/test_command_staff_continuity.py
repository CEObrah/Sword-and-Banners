from __future__ import annotations

import json
import subprocess

from sword_runtime.api.equipment_operations import EquipmentAwareCampaignOperations
from sword_runtime.commands import CommandEnvelope
from sword_runtime.service_runtime import ProductionSwordRuntime


def _write_json(path, document) -> None:
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _commit_fixture_state(campaign, *paths: str) -> None:
    subprocess.run(["git", "-C", str(campaign), "add", *paths], check=True)
    subprocess.run(
        ["git", "-C", str(campaign), "commit", "--quiet", "-m", "Arrange command staff movement fixture"],
        check=True,
    )


def _routed_person(campaign, person_ref: str):
    index = json.loads((campaign / "state/index/owner-index.json").read_text(encoding="utf-8"))["owners"]
    route = str(index[person_ref])
    rel_path, _, fragment = route.partition("#")
    document = json.loads((campaign / rel_path).read_text(encoding="utf-8"))
    if fragment:
        assert fragment == f"/records/{person_ref}"
        return rel_path, document, document["records"][person_ref]
    return rel_path, document, document


def test_registered_command_group_staff_survives_player_surface_projection(campaign):
    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-command-staff-surface")
    operations = EquipmentAwareCampaignOperations(runtime)
    context = operations.play_context()

    # The compact play-context window is intentionally truncated; older controlled
    # leaves must remain discoverable through the paged controlled-formation surface.
    leaf_commander = "char_duan_jin"
    assert context["controlled_formations_truncated"] is True
    assert "char_lin_zhen" in context["permitted_person_ids"]

    field = next(row for row in context["controlled_command_groups"] if row["command_group_ref"] == "cmdgrp.tang_wei.field_army")
    assert field["role_assignments"] == {"char_lin_zhen": "strategist"}
    assert field["successor_refs"] == ["char_lin_zhen"]
    assert field["integrity_status"] == "ok"

    inspected = operations.inspect_game_object("formation_red_lance_a")["object"]
    assert inspected["commander_ref"] == leaf_commander

    paged = next(row for row in operations.list_controlled_formations(limit=64)["formations"] if row["formation_ref"] == "formation_red_lance_a")
    assert paged["commander_ref"] == leaf_commander


def test_escorted_formation_travel_musters_only_its_actual_top_commander(campaign):
    formation_ref = "formation_red_lance_a"
    formation_path = campaign / "state/formations/red-lance-a.json"
    player_path = campaign / "state/player.json"
    formation = json.loads(formation_path.read_text(encoding="utf-8"))
    commander_ref = str(formation["commander_ref"])
    rel_path, person_document, commander = _routed_person(campaign, commander_ref)

    origin = str(formation["location_ref"])
    destination = "loc_kanyou" if origin != "loc_kanyou" else "loc_tang_manor_garrison_yard"
    detached_candidates = ("loc_tang_manor_training_ground", "loc_tang_manor_garrison_yard", "loc_kanyou")
    detached = next(ref for ref in detached_candidates if ref not in {origin, destination})

    player = json.loads(player_path.read_text(encoding="utf-8")); player["location"] = origin; _write_json(player_path, player)
    if "location" in commander:
        commander["location"] = detached
    else:
        commander["current_location"] = detached
    commander.setdefault("command_assignment", {})["formation_ref"] = formation_ref
    _write_json(campaign / rel_path, person_document)
    _commit_fixture_state(campaign, "state/player.json", rel_path)

    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-command-staff-movement")
    meta = runtime.store.read_json("state/meta.json")
    command = CommandEnvelope(
        campaign_id=meta["campaign_id"], request_id="test-command-staff-detached-escorted-travel",
        actor_id=meta["player_id"], command_type="travel", expected_revision=meta["revision"], submitted_at=meta["time"],
        payload={"destination_ref": destination, "formation_refs": [formation_ref], "mode": "foot"}, mode="gameplay",
    )
    result = runtime.execute(command).receipt.result
    assert result["destination"] == destination
    assert result["command_staff_muster_hours"] > 0
    assert set(result["command_staff_mustered"]) == {commander_ref}
    assert set(result["command_staff_reconciled"]) == {commander_ref}
    assert result["duration_hours"] == result["column_duration_hours"] + result["command_staff_muster_hours"]
    assert runtime.store.read_json("state/player.json")["location"] == destination
    assert runtime.store.read_json("state/formations/red-lance-a.json")["location_ref"] == destination
    _, moved_document, moved = _routed_person(campaign, commander_ref)
    assert (moved.get("location") or moved.get("current_location")) == destination
    meta_after = runtime.store.read_json("state/meta.json"); runtime_after = runtime.store.read_json("state/runtime.json")
    assert meta_after["time"] == runtime_after["world_time"] == result["world_time"]


def test_autonomous_move_preserves_exact_top_commander(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign); planner._reset()
    formation_ref = "formation_qin_kankoku_central_gate"
    _formation_path, formation = planner._load_formation(formation_ref)
    commander_ref = str(formation["commander_ref"]); origin = str(formation["location_ref"])
    command_path, commander = planner._validate_person_location_for_formation(commander_ref, formation)
    assert commander["schema"] == "sab_character"
    assert planner._person_location(commander) == origin

    result = planner._autonomy_move_formation_step(formation_ref, "loc_kanyou", str(planner._world_time()))
    assert result["status"] in {"arrived", "marching"}
    _after_path, after = planner._load_formation(formation_ref); reached = str(after["location_ref"])
    assert reached != origin
    assert after["commander_ref"] == commander_ref
    assert set(result.get("command_staff_reconciled", [])) == {commander_ref}
    assert planner._person_location(planner.read(command_path)) == reached


def test_autonomous_move_reconciles_detached_exact_commander_without_deleting_it(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign); planner._reset()
    formation_ref = "formation_zhao_mobile_reserve"
    formation_path, formation = planner._load_formation(formation_ref)
    commander_ref = str(formation["commander_ref"])
    origin = str(formation["location_ref"])
    person_path, commander = planner._command_person(commander_ref)
    detached = "loc_kantan" if origin != "loc_kantan" else "loc_zhao_regional_02"
    commander = dict(commander)
    if "location" in commander:
        commander["location"] = detached
    else:
        commander["current_location"] = detached
    planner.put(person_path, commander)
    assert planner._person_location(planner.read(person_path)) != origin

    result = planner._autonomy_move_formation_step(
        formation_ref,
        "loc_kantan" if origin != "loc_kantan" else "loc_zhao_regional_01",
        str(planner._world_time()),
    )
    assert result["status"] in {"arrived", "marching"}
    _after_path, after = planner._load_formation(formation_ref)
    assert after["commander_ref"] == commander_ref
    assert after["location_ref"] != origin
    # The movement owner reconciles exact command staff physically rather than
    # dropping the commander or leaving a stale detached billet behind.
    _person_path, after_commander = planner._command_person(commander_ref)
    assert after_commander["life_status"] == "active"
    assert planner._person_location(after_commander) == detached
    assert planner._person_location(after_commander) != origin


def test_grouped_travel_reconciles_zero_body_child_army_location_only_when_whole_child_moves(campaign):
    formation_refs = ["formation_red_lance_a", "formation_red_lance_b"]
    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-command-group-location")
    meta = runtime.store.read_json("state/meta.json")
    command = CommandEnvelope(
        campaign_id=meta["campaign_id"], request_id="test-whole-child-grouped-travel-location",
        actor_id=meta["player_id"], command_type="travel", expected_revision=meta["revision"], submitted_at=meta["time"],
        payload={"destination_ref": "loc_kanyou", "formation_refs": formation_refs, "mode": "foot"}, mode="gameplay",
    )
    result = runtime.execute(command).receipt.result
    assert "cmdgrp.tang_wei.red_lance" in result.get("command_groups_reconciled", [])
    red = runtime.store.read_json("state/cmd/command-groups/cmdgrp.tang_wei.red_lance.json")
    field = runtime.store.read_json("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    assert red["location"] == "loc_kanyou"
    assert field["location"] == "loc_qin_eastern_depot"
    for ref in formation_refs:
        path = runtime.store.read_json("state/index/owner-index.json")["owners"][ref]
        assert runtime.store.read_json(path)["location_ref"] == "loc_kanyou"
