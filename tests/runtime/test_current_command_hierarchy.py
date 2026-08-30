from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def load_route(route: str):
    base, sep, fragment = route.partition("#")
    value = load(base)
    if not sep or not fragment:
        return value
    current = value
    for raw in fragment.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        current = current[token] if isinstance(current, dict) else current[int(token)]
    return current


def group(ref: str):
    return load(f"state/cmd/command-groups/{ref}.json")


def test_tang_wei_army_is_one_9500_zero_manpower_command_umbrella():
    field = group("cmdgrp.tang_wei.field_army")
    assert field["commander_ref"] == "char_tang_wei"
    assert field["role_assignments"] == {"char_lin_zhen": "strategist"}
    assert field["successor_refs"] == ["char_lin_zhen"]
    assert field["organizational_state"]["authorized_strength"] == 9500
    assert field["organizational_state"]["current_recursive_strength"] == 9500
    assert field["units"] == [
        {"kind": "nested_army", "ref": "cmdgrp.tang_wei.red_lance"},
        {"kind": "nested_army", "ref": "cmdgrp.tang_wei.high_guard"},
        {"kind": "nested_army", "ref": "cmdgrp.tang_wei.black_banner"},
    ]


def test_red_lance_is_1000_house_cavalry_with_distinct_commanders():
    owners = load("state/index/owner-index.json")["owners"]
    red = group("cmdgrp.tang_wei.red_lance")
    assert red["parent_command_group_ref"] == "cmdgrp.tang_wei.field_army"
    assert red["organizational_state"]["authorized_strength"] == 1000
    assert red["commander_ref"] == "char_tang_command_red_lance_1000"
    leaves = [row["ref"] for row in red["units"]]
    assert leaves == ["formation_red_lance_a", "formation_red_lance_b"]
    commanders = {red["commander_ref"]}
    total = 0
    for ref in leaves:
        formation = load(owners[ref])
        assert formation["personnel"] == 500
        assert formation["owner_force_ref"] == "force_house_tang"
        assert formation["composition"] == {"house_cavalry": 500}
        commanders.add(formation["commander_ref"])
        total += formation["personnel"]
    assert total == 1000
    assert commanders == {"char_tang_command_red_lance_1000", "char_duan_jin", "char_shen_rui"}


def test_high_guard_is_4500_with_fixed_house_core_and_qin_reserve():
    owners = load("state/index/owner-index.json")["owners"]
    high = group("cmdgrp.tang_wei.high_guard")
    lin = load("state/char/lin-zhen.json")
    assert high["commander_ref"] == "char_lin_zhen"
    assert high["organizational_state"]["authorized_strength"] == 4500
    assert lin["military_command"]["level"] == "4500_commander"
    assert lin["command_assignment"]["command_group_ref"] == "cmdgrp.tang_wei.high_guard"

    refs = []
    stack = ["cmdgrp.tang_wei.high_guard"]
    seen = set()
    while stack:
        ref = stack.pop()
        if ref in seen:
            continue
        seen.add(ref)
        g = group(ref)
        for row in g.get("units", []):
            if row["kind"] == "nested_army":
                stack.append(row["ref"])
            else:
                refs.append(row["ref"])
    house_infantry = house_cavalry = qin = 0
    for ref in refs:
        f = load(owners[ref])
        if f["owner_force_ref"] == "force_house_tang":
            house_infantry += int(f.get("composition", {}).get("house_infantry", 0))
            house_cavalry += int(f.get("composition", {}).get("house_cavalry", 0))
        elif f["owner_force_ref"] == "force_state_qin":
            qin += int(f["personnel"])
    assert (house_infantry, house_cavalry, qin) == (3000, 500, 1000)
    assert sum(load(owners[ref])["personnel"] for ref in refs) == 4500


def test_black_banner_has_exact_4000_2000_1000_500_hierarchy():
    owners = load("state/index/owner-index.json")["owners"]
    black = group("cmdgrp.tang_wei.black_banner")
    assert black["organizational_state"]["authorized_strength"] == 4000
    wings = [row["ref"] for row in black["units"]]
    assert len(wings) == 2
    commander_refs = {black["commander_ref"]}
    leaf_refs = []
    for wing_ref in wings:
        wing = group(wing_ref)
        assert wing["organizational_state"]["authorized_strength"] == 2000
        commander_refs.add(wing["commander_ref"])
        units = [row["ref"] for row in wing["units"]]
        assert len(units) == 2
        for unit_ref in units:
            unit = group(unit_ref)
            assert unit["organizational_state"]["authorized_strength"] == 1000
            commander_refs.add(unit["commander_ref"])
            leaves = [row["ref"] for row in unit["units"]]
            assert len(leaves) == 2
            leaf_refs.extend(leaves)
    assert len(leaf_refs) == 8
    for ref in leaf_refs:
        formation = load(owners[ref])
        assert formation["personnel"] == 500
        assert formation["owner_force_ref"] == "force_state_qin"
        assert sum(int(v) for v in formation["composition"].values()) == 500
        commander_refs.add(formation["commander_ref"])
    assert len(commander_refs) == 15  # 1x4000 + 2x2000 + 4x1000 + 8x500


def test_all_tang_wei_command_people_route_to_exact_current_characters():
    owners = load("state/index/owner-index.json")["owners"]
    command_people = load("state/cmd/command-personnel.json")["record_index"]
    refs = set()
    for path in (ROOT / "state/cmd/command-groups").glob("cmdgrp.tang_wei*.json"):
        g = json.loads(path.read_text())
        if isinstance(g.get("commander_ref"), str):
            refs.add(g["commander_ref"])
        refs.update(str(x) for x in g.get("role_assignments", {}) if isinstance(x, str))
    for path in (ROOT / "state/formations").glob("*.json"):
        f = json.loads(path.read_text())
        if f.get("command_authority") == "char_tang_wei" and isinstance(f.get("commander_ref"), str):
            refs.add(f["commander_ref"])
    for ref in sorted(refs):
        assert ref in owners
        assert ref in command_people
        person = load_route(owners[ref])
        assert person["schema"] == "sab_character"
        assert str(person.get("life_status", "active")) != "dead"


def test_every_persistent_500_plus_formation_has_one_full_exact_commander():
    owners = load("state/index/owner-index.json")["owners"]
    for path in (ROOT / "state/formations").glob("*.json"):
        f = json.loads(path.read_text())
        strength = int(f.get("authorized_strength", f.get("personnel", 0)) or 0)
        if strength < 500 or f.get("status") in {"disbanded", "destroyed"}:
            continue
        commander = f.get("commander_ref")
        assert isinstance(commander, str) and commander in owners, f.get("formation_ref")
        person = load_route(owners[commander])
        assert person["schema"] == "sab_character", (f.get("formation_ref"), commander)


def test_no_parent_child_command_group_double_hat():
    groups = {}
    for path in (ROOT / "state/cmd/command-groups").glob("*.json"):
        d = json.loads(path.read_text())
        if isinstance(d.get("id"), str):
            groups[d["id"]] = d
    for ref, parent in groups.items():
        if not ref.startswith("cmdgrp.tang_wei."):
            continue
        pcommander = parent.get("commander_ref")
        for row in parent.get("units", []):
            if row.get("kind") != "nested_army" or row.get("ref") not in groups:
                continue
            child = groups[row["ref"]]
            assert child.get("parent_command_group_ref") == ref
            assert child.get("commander_ref") != pcommander, (ref, row["ref"], pcommander)


def test_exact_formation_commander_sheet_matches_live_billet_span_and_location():
    owners = load("state/index/owner-index.json")["owners"]
    for path in (ROOT / "state/formations").glob("*.json"):
        f = json.loads(path.read_text())
        strength = int(f.get("authorized_strength", f.get("personnel", 0)) or 0)
        if strength < 500 or not isinstance(f.get("commander_ref"), str):
            continue
        person = load_route(owners[f["commander_ref"]])
        assignment = person.get("command_assignment", {})
        assert assignment.get("formation_ref") == f.get("formation_ref")
        assert int(assignment.get("current_command_span", -1)) == int(f.get("personnel", 0))
        location = person.get("location") if isinstance(person.get("location"), str) else person.get("current_location")
        assert location == f.get("location_ref")


def test_house_tang_active_manpower_uses_only_two_troop_species():
    owners = load("state/index/owner-index.json")["owners"]
    roles = set()
    total = 0
    for ref, route in owners.items():
        if not str(ref).startswith("formation_"):
            continue
        f = load_route(route)
        if f.get("owner_force_ref") != "force_house_tang" or f.get("status") in {"disbanded", "destroyed"}:
            continue
        roles.update(str(k) for k, v in f.get("composition", {}).items() if int(v) > 0)
        total += int(f.get("personnel", 0))
    assert roles <= {"house_infantry", "house_cavalry"}
    # This is allocated active formation strength, not total force headcount/reserve.
    assert total > 0


def test_lin_zhen_is_strategist_and_real_4500_commander_with_mounted_loadout():
    lin = load("state/char/lin-zhen.json")
    field = group("cmdgrp.tang_wei.field_army")
    high = group("cmdgrp.tang_wei.high_guard")
    assert field["role_assignments"]["char_lin_zhen"] == "strategist"
    assert high["commander_ref"] == "char_lin_zhen"
    assert lin["military_command"]["level"] == "4500_commander"
    assert lin["military_command"]["higher_commander_ref"] == "char_tang_wei"
    assert lin["personal_loadout_ref"] == "loadout_tang_mounted"
    for key in ("Formation Command", "Leadership", "Tactics", "Strategy", "Logistics", "Formation Fighting"):
        assert int(lin["skills"][key]) > 0


def test_ordered_oob_can_reposition_black_banner_without_flattening(campaign):
    from conftest import execute_production_internal

    parent_ref = "cmdgrp.tang_wei.field_army"
    child_ref = "cmdgrp.tang_wei.black_banner"
    parent_path = campaign / "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json"
    child_path = campaign / "state/cmd/command-groups/cmdgrp.tang_wei.black_banner.json"
    before_child = json.loads(child_path.read_text())
    execute_production_internal(campaign, "command_group_action", {
        "action": "move_unit",
        "command_group_ref": parent_ref,
        "subordinate_group_ref": child_ref,
        "unit_slot": 1,
    })
    parent = json.loads(parent_path.read_text())
    child = json.loads(child_path.read_text())
    assert parent["units"][0] == {"kind": "nested_army", "ref": child_ref}
    assert child["units"] == before_child["units"]
    assert child["commander_ref"] == before_child["commander_ref"]


def test_field_army_children_remain_intact_nested_armies():
    field = group("cmdgrp.tang_wei.field_army")
    assert len(field["units"]) == 3
    for row in field["units"]:
        assert row["kind"] == "nested_army"
        child = group(row["ref"])
        assert child["parent_command_group_ref"] == field["id"]
        assert int(child["organizational_state"]["authorized_strength"]) > 0


def test_all_nested_command_group_parentage_is_bidirectionally_consistent():
    groups = {}
    for path in (ROOT / "state/cmd/command-groups").glob("*.json"):
        doc = load(str(path.relative_to(ROOT)))
        ref = doc.get("id")
        if isinstance(ref, str):
            groups[ref] = doc

    for parent_ref, parent in groups.items():
        for unit in parent.get("units", []):
            if not isinstance(unit, dict) or unit.get("kind") != "nested_army":
                continue
            child_ref = unit.get("ref")
            assert child_ref in groups, (parent_ref, child_ref)
            assert groups[child_ref].get("parent_command_group_ref") == parent_ref, (
                parent_ref,
                child_ref,
                groups[child_ref].get("parent_command_group_ref"),
            )

    for child_ref, child in groups.items():
        parent_ref = child.get("parent_command_group_ref")
        if not isinstance(parent_ref, str) or not parent_ref:
            continue
        assert parent_ref in groups, (child_ref, parent_ref)
        assert any(
            isinstance(unit, dict)
            and unit.get("kind") == "nested_army"
            and unit.get("ref") == child_ref
            for unit in groups[parent_ref].get("units", [])
        ), (child_ref, parent_ref)


def test_qin_organic_hierarchy_and_independent_commands_are_distinct():
    ouki = load("state/cmd/command-groups/cmdgrp.ouki.field_army.json")
    tou = load("state/cmd/command-groups/cmdgrp.tou.field_army.json")
    mou_gou = load("state/cmd/command-groups/cmdgrp.mou_gou.field_army.json")
    gaku = load("state/cmd/command-groups/cmdgrp.mou_ten.gaku_ka.json")
    ousen = load("state/cmd/command-groups/cmdgrp.ousen.field_army.json")
    gyoku = load("state/cmd/command-groups/cmdgrp.ou_hon.gyoku_hou.json")
    kanki = load("state/cmd/command-groups/cmdgrp.kanki.field_army.json")
    mou_bu = load("state/cmd/command-groups/cmdgrp.mou_bu.field_army.json")

    assert tou["parent_command_group_ref"] == ouki["id"]
    assert any(unit.get("ref") == tou["id"] for unit in ouki["units"])
    assert ouki["successor_refs"] == ["char_tou"]

    assert gaku["parent_command_group_ref"] is None
    assert not any(unit.get("ref") == gaku["id"] for unit in mou_gou["units"])
    assert gyoku["parent_command_group_ref"] is None
    assert not any(unit.get("ref") == gyoku["id"] for unit in ousen["units"])

    assert ousen["parent_command_group_ref"] == mou_gou["id"]
    assert kanki["parent_command_group_ref"] == mou_gou["id"]
    assert any(unit.get("ref") == ousen["id"] for unit in mou_gou["units"])
    assert any(unit.get("ref") == kanki["id"] for unit in mou_gou["units"])
    assert mou_bu["parent_command_group_ref"] is None


def test_deployed_tang_field_officers_no_longer_hold_inner_walls_duty_or_regimen():
    refs = [
        "char_ren_qiao",
        "char_sword_manor_trainee_commander",
        "char_sword_manor_trainee_training_officer",
        "char_sword_manor_junior_commander",
        "char_sword_manor_junior_training_officer",
        "char_sword_manor_general_commander",
        "char_sword_manor_general_training_officer",
    ]
    owners = load("state/index/owner-index.json")["owners"]
    for ref in refs:
        person = load_route(owners[ref])
        assert "Inner Walls" not in str(person.get("authority", ""))
        assert all("inner walls" not in str(duty).lower() for duty in person.get("goal_state", {}).get("institutional_duties", []))
        assert person.get("activity_contract", {}).get("training_regimen_ref") == "professional_officer"
        assert (person.get("location") or person.get("current_location")) == "loc_kanyou"


def test_inner_walls_home_formations_do_not_route_authority_through_deployed_field_officers():
    deployed = {
        "char_ren_qiao",
        "char_sword_manor_trainee_commander",
        "char_sword_manor_trainee_training_officer",
        "char_sword_manor_junior_commander",
        "char_sword_manor_junior_training_officer",
        "char_sword_manor_general_commander",
        "char_sword_manor_general_training_officer",
    }
    for path in (ROOT / "state/formations").glob("house-tang-inner-walls-*.json"):
        formation = json.loads(path.read_text())
        assert formation.get("command_authority") not in deployed, formation.get("formation_ref")
