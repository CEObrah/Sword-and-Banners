from __future__ import annotations

import json
from pathlib import Path

from conftest import activate_operation, execute, execute_internal
from sword_runtime.engine import RepositoryCommandPlanner


def _owner_doc(root: Path, ref: str):
    owners = json.load(open(root / "state/index/owner-index.json"))["owners"]
    path = root / owners[ref]
    return path, json.load(open(path))


def _repair(root: Path, path: str, changes: dict, reason: str) -> None:
    execute(
        root,
        "repair",
        {"path": path, "changes": changes, "reason": reason},
        actor=RepositoryCommandPlanner.INTERNAL_ACTOR,
        mode="maintenance",
    )


def test_named_ranged_hero_spends_and_persists_personal_ammunition(campaign):
    champion_ref = "formation_tang_champions_first"
    champion_path, champion = _owner_doc(campaign, champion_ref)
    battle_location = str(champion["location_ref"])

    # Materialize Tang Wei as a named local participant without changing formation
    # personnel ownership.  Raise only his Bow skill in this disposable fixture so
    # the bounded hero window lawfully selects ranged intervention.
    player = json.load(open(campaign / "state/player.json"))
    skills = dict(player["skills"])
    skills["Bow"] = 500
    for melee_skill in ("Sword", "Spear", "Glaive", "Axe", "Mace", "Staff", "Dagger"):
        if melee_skill in skills:
            skills[melee_skill] = 1
    _repair(
        campaign,
        "state/player.json",
        {"skills": skills},
        "disposable named-ranged-hero ammunition persistence fixture",
    )
    notable = list(champion.get("notable_person_refs", []))
    if "char_tang_wei" not in notable:
        notable.append("char_tang_wei")
    _repair(
        campaign,
        str(champion_path.relative_to(campaign)),
        {"notable_person_refs": notable},
        "disposable named-ranged-hero formation participation fixture",
    )

    enemy_commander = "char_named_ammo_enemy_commander"
    enemy_formation = "formation_named_ammo_enemy"
    execute_internal(
        campaign,
        "person_materialize",
        {
            "state": "qin",
            "person_ref": enemy_commander,
            "name": "Named Ammo Enemy Commander",
            "birth_date": "270-BCE-01-01",
            "role": "command_personnel",
            "source_location_ref": battle_location,
        },
    )
    execute_internal(
        campaign,
        "formation_create",
        {
            "state": "qin",
            "formation_ref": enemy_formation,
            "role": "line_infantry",
            "personnel": 500,
            "location_ref": battle_location,
            "commander_ref": enemy_commander,
        },
    )
    execute_internal(
        campaign,
        "resupply",
        {"formation_ref": enemy_formation, "food_kg": 1000, "war_arrows": 2000},
    )
    execute_internal(campaign, "formation_mobilize", {"formation_ref": enemy_formation})

    manifest_path = campaign / "state/player-detail/equipment-manifest.json"
    manifest_before = json.load(open(manifest_path))
    arrow_before = next(
        int(row["quantity"])
        for row in manifest_before["equipment_manifest"]
        if row.get("item_id") == "ammo_arrow_war"
    )
    formation_arrows_before = int(_owner_doc(campaign, champion_ref)[1]["logistics"]["war_arrows"])

    operation = activate_operation(
        campaign,
        "operation_named_hero_ammunition",
        [champion_ref, enemy_formation],
        location=battle_location,
    )
    result = execute_internal(
        campaign,
        "battle_resolve",
        {
            "attacker_formation_refs": [champion_ref],
            "defender_formation_refs": [enemy_formation],
            "operation_ref": operation,
            "objective": "verify exact named projectile custody",
        },
    ).receipt.result

    named = result["named_person_outcomes"]["char_tang_wei"]
    ammo = named["named_ammunition"]
    assert named["named_intervention"] is True
    assert ammo["projectile_item_id"] == "ammo_arrow_war"
    assert ammo["before"] == arrow_before
    assert 0 < ammo["fired"] <= arrow_before
    assert 0 <= ammo["recovered"] <= ammo["fired"]
    assert ammo["after"] == ammo["before"] - ammo["fired"] + ammo["recovered"]

    player_after = json.load(open(campaign / "state/player.json"))
    assert player_after["combat_state"]["projectile_ammunition"]["ammo_arrow_war"] == ammo["after"]
    manifest_after = json.load(open(manifest_path))
    arrow_after = next(
        int(row["quantity"])
        for row in manifest_after["equipment_manifest"]
        if row.get("item_id") == "ammo_arrow_war"
    )
    assert arrow_after == ammo["after"]

    # Exact-person shots are not also charged to the formation's aggregate stock.
    # Any formation-stock change is therefore only its cohort ammunition plan.
    champion_after = _owner_doc(campaign, champion_ref)[1]
    losses = result["material_losses"][champion_ref]
    cohort_consumed = int(losses["ammunition_consumed"].get("war_arrows", 0))
    cohort_recovered = int(losses["ammunition_recovered"].get("war_arrows", 0))
    assert int(champion_after["logistics"]["war_arrows"]) == formation_arrows_before - cohort_consumed + cohort_recovered
