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


def test_registered_deputy_survives_player_surface_projection(campaign):
    runtime = ProductionSwordRuntime(
        campaign,
        runtime_root=campaign.parent / "runtime-command-staff-surface",
    )
    operations = EquipmentAwareCampaignOperations(runtime)
    context = operations.play_context()

    champions = next(
        row
        for row in context["controlled_formations"]
        if row["formation_ref"] == "formation_tang_champions_first"
    )
    assert champions["commander_ref"] == "char_duan_jin"
    assert champions["deputy_ref"] == "char_shen_rui"
    assert "char_duan_jin" in context["permitted_person_ids"]
    assert "char_shen_rui" in context["permitted_person_ids"]

    inspected = operations.inspect_game_object("formation_tang_champions_first")
    assert inspected["object"]["commander_ref"] == "char_duan_jin"
    assert inspected["object"]["deputy_ref"] == "char_shen_rui"

    page = operations.list_controlled_formations(limit=20)
    paged = next(
        row
        for row in page["formations"]
        if row["formation_ref"] == "formation_tang_champions_first"
    )
    assert paged["deputy_ref"] == "char_shen_rui"


def test_escorted_travel_physically_musters_detached_commander_and_deputy(campaign):
    formation_path = campaign / "state/formations/tang-champions-first.json"
    player_path = campaign / "state/player.json"
    duan_path = campaign / "state/char/duan-jin.json"
    shen_path = campaign / "state/char/shen-rui.json"

    formation = json.loads(formation_path.read_text(encoding="utf-8"))
    origin = str(formation["location_ref"])
    destination = "loc_kanyou" if origin != "loc_kanyou" else "loc_tang_manor_garrison_yard"
    detached_candidates = (
        "loc_tang_manor_training_ground",
        "loc_tang_manor_garrison_yard",
        "loc_kanyou",
    )
    detached = next(ref for ref in detached_candidates if ref not in {origin, destination})

    player = json.loads(player_path.read_text(encoding="utf-8"))
    player["location"] = origin
    _write_json(player_path, player)

    for person_path in (duan_path, shen_path):
        person = json.loads(person_path.read_text(encoding="utf-8"))
        person["current_location"] = detached
        person["current_formation_id"] = "formation_tang_champions_first"
        _write_json(person_path, person)

    _commit_fixture_state(
        campaign,
        "state/player.json",
        "state/char/duan-jin.json",
        "state/char/shen-rui.json",
    )

    runtime = ProductionSwordRuntime(
        campaign,
        runtime_root=campaign.parent / "runtime-command-staff-movement",
    )
    meta = runtime.store.read_json("state/meta.json")
    assert runtime.store.read_json("state/char/duan-jin.json")["current_location"] == detached
    assert runtime.store.read_json("state/char/shen-rui.json")["current_location"] == detached

    command = CommandEnvelope(
        campaign_id=meta["campaign_id"],
        request_id="test-command-staff-detached-escorted-travel",
        actor_id=meta["player_id"],
        command_type="travel",
        expected_revision=meta["revision"],
        submitted_at=meta["time"],
        payload={
            "destination_ref": destination,
            "formation_refs": ["formation_tang_champions_first"],
            "mode": "foot",
        },
        mode="gameplay",
    )
    execution = runtime.execute(command)
    result = execution.receipt.result

    assert result["destination"] == destination
    assert result["command_staff_muster_hours"] > 0
    assert set(result["command_staff_mustered"]) == {"char_duan_jin", "char_shen_rui"}
    assert set(result["command_staff_reconciled"]) == {"char_duan_jin", "char_shen_rui"}
    assert result["duration_hours"] == result["column_duration_hours"] + result["command_staff_muster_hours"]

    assert runtime.store.read_json("state/player.json")["location"] == destination
    assert runtime.store.read_json("state/formations/tang-champions-first.json")["location_ref"] == destination
    for person_path in ("state/char/duan-jin.json", "state/char/shen-rui.json"):
        person = runtime.store.read_json(person_path)
        assert person["current_location"] == destination
        assert person["current_formation_id"] == "formation_tang_champions_first"

    meta_after = runtime.store.read_json("state/meta.json")
    runtime_after = runtime.store.read_json("state/runtime.json")
    assert meta_after["time"] == runtime_after["world_time"] == result["world_time"]


def test_autonomous_move_preserves_person_lite_command_staff(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    formation_ref = "formation_qin_kankoku_central_gate"
    formation_path, formation = planner._load_formation(formation_ref)
    commander_ref = str(formation["commander_ref"])
    deputy_ref = str(formation["deputy_ref"])
    origin = str(formation["location_ref"])

    command_path, commander = planner._validate_person_location_for_formation(commander_ref, formation)
    deputy_path, deputy = planner._validate_person_location_for_formation(deputy_ref, formation)
    assert commander["schema"] == deputy["schema"] == "person-lite"
    assert planner._person_location(commander) == planner._person_location(deputy) == origin

    formation = dict(formation)
    formation["logistics"] = dict(formation.get("logistics", {}))
    formation["logistics"]["food_kg"] = 10**9
    formation["logistics"]["fodder_kg"] = 10**9
    planner.put(formation_path, formation)

    result = planner._autonomy_move_formation_step(
        formation_ref,
        "loc_kanyou",
        str(planner._world_time()),
    )
    assert result["status"] in {"arrived", "marching"}

    _after_path, after = planner._load_formation(formation_ref)
    reached = str(after["location_ref"])
    assert reached != origin
    assert after["commander_ref"] == commander_ref
    assert after["deputy_ref"] == deputy_ref
    assert set(result.get("command_staff_reconciled", [])) == {commander_ref, deputy_ref}
    assert planner._person_location(planner.read(command_path)) == reached
    assert planner._person_location(planner.read(deputy_path)) == reached


def test_autonomous_move_does_not_delete_detached_exact_commander(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    formation_ref = "formation_zhao_mobile_reserve"
    formation_path, formation = planner._load_formation(formation_ref)
    commander_ref = str(formation["commander_ref"])
    origin = str(formation["location_ref"])
    _person_path, commander = planner._command_person(commander_ref)
    assert planner._person_location(commander) != origin

    formation = dict(formation)
    formation["logistics"] = dict(formation.get("logistics", {}))
    formation["logistics"]["food_kg"] = 10**9
    formation["logistics"]["fodder_kg"] = 10**9
    planner.put(formation_path, formation)

    result = planner._autonomy_move_formation_step(
        formation_ref,
        "loc_kantan",
        str(planner._world_time()),
    )
    assert result["status"] == "commander_detached"
    _after_path, after = planner._load_formation(formation_ref)
    assert after["commander_ref"] == commander_ref
    assert after["location_ref"] == origin
    assert after["status"] == "commander_detached"
