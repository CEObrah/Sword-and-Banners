from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import activate_operation, execute, execute_internal


def _owner_doc(root: Path, ref: str):
    owners = json.load(open(root / "state/index/owner-index.json"))["owners"]
    path = root / owners[ref]
    return path, json.load(open(path))


def _fixture_update(root: Path, path: str, changes: dict) -> None:
    target = root / path
    doc = json.load(open(target))
    doc.update(changes)
    target.write_text(json.dumps(doc, indent=2) + "\n")
    subprocess.run(["git", "-C", str(root), "add", path], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "--quiet", "-m", "Disposable combat fixture"], check=True)


def test_named_ranged_hero_spends_and_persists_personal_ammunition(campaign):
    champion_ref = "formation_red_lance_a"
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
    _fixture_update(campaign, "state/player.json", {"skills": skills})
    notable = list(champion.get("notable_person_refs", []))
    if "char_tang_wei" not in notable:
        notable.append("char_tang_wei")
    _fixture_update(campaign, str(champion_path.relative_to(campaign)), {"notable_person_refs": notable})

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
        {"formation_ref": enemy_formation, "war_arrows": 2000},
    )
    execute_internal(campaign, "formation_mobilize", {"formation_ref": enemy_formation})

    manifest_path = campaign / "state/player-detail/equipment-manifest.json"
    manifest_before = json.load(open(manifest_path))
    arrow_before = next(
        int(row["quantity"])
        for row in manifest_before["equipment_manifest"]
        if row.get("item_id") == "ammo_arrow"
    )
    formation_arrows_before = int(_owner_doc(campaign, champion_ref)[1]["logistics"]["war_arrows"])
    health_before = player.get("health") if isinstance(player.get("health"), dict) else {}
    fatigue_before = int(health_before.get("fatigue", player.get("fatigue", 0)) or 0)

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
    fatigue_result = named.get("fatigue", {})
    assert int(fatigue_result.get("fatigue_gain", 0)) > 0
    assert int(fatigue_result.get("fatigue_after", 0)) > fatigue_before
    ammo = named["named_ammunition"]
    assert named["named_intervention"] is True
    assert ammo["projectile_item_id"] == "ammo_arrow"
    assert ammo["before"] == arrow_before
    assert 0 < ammo["fired"] <= arrow_before
    assert 0 <= ammo["recovered"] <= ammo["fired"]
    assert ammo["after"] == ammo["before"] - ammo["fired"] + ammo["recovered"]

    player_after = json.load(open(campaign / "state/player.json"))
    health_after = player_after.get("health") if isinstance(player_after.get("health"), dict) else {}
    assert int(health_after.get("fatigue", player_after.get("fatigue", 0)) or 0) == int(fatigue_result["fatigue_after"])
    assert player_after["combat_state"]["projectile_ammunition"]["ammo_arrow"] == ammo["after"]
    manifest_after = json.load(open(manifest_path))
    arrow_after = next(
        int(row["quantity"])
        for row in manifest_after["equipment_manifest"]
        if row.get("item_id") == "ammo_arrow"
    )
    assert arrow_after == ammo["after"]

    # Exact-person shots are not also charged to the formation's aggregate stock.
    # Any formation-stock change is therefore only its cohort ammunition plan.
    champion_after = _owner_doc(campaign, champion_ref)[1]
    losses = result["material_losses"][champion_ref]
    cohort_consumed = int(losses["ammunition_consumed"].get("war_arrows", 0))
    cohort_recovered = int(losses["ammunition_recovered"].get("war_arrows", 0))
    assert int(champion_after["logistics"]["war_arrows"]) == formation_arrows_before - cohort_consumed + cohort_recovered
