import json
from pathlib import Path

from sword_runtime.warfare_depth import build_formation_command_structure

ROOT = Path(__file__).resolve().parents[2]


def load(path: str):
    with (ROOT / path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def derived_command_structure(formation: dict) -> dict:
    return build_formation_command_structure(formation, load("game/data/mechanics/warfare-organization.json"))


def load_route(route: str):
    base, sep, fragment = route.partition("#")
    value = load(base)
    if not sep or not fragment:
        return value
    assert fragment.startswith("/")
    current = value
    for raw in fragment[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current[token]
        else:
            current = current[int(token)]
    return current


def test_wei_field_army_has_distinct_zero_manpower_command_hierarchy():
    army = load("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    personal = load("state/cmd/command-groups/cmdgrp.tang_wei.personal_force.json")
    deputy = load("state/char/lin-zhen.json")
    assert army["commander_ref"] == "char_tang_wei"
    assert army["deputy_ref"] == "char_lin_zhen"
    assert army["context"] == "field_army"
    assert personal["parent_command_group_ref"] == army["id"]
    assert deputy["role"] == "Tang Wei Field Army Deputy"
    assert deputy["military_command"]["commander_ref"] == "char_tang_wei"
    assert deputy["military_command"]["level"] == "army_deputy"
    assert deputy["military_command"]["external_to_fighting_strength"] is True
    assert "Field-army deputy" in deputy["authority"]


def test_house_guard_formal_command_is_external_and_embedded_command_is_conserved():
    formation = load("state/formations/tang-wei-house-guard.json")
    deputy = load("state/char/han-qiu.json")
    aggregate = sum(int(row["count"]) for row in formation["cohort_composition"])
    embedded = len(formation["embedded_person_refs"])
    assert formation["personnel"] == 3000
    assert aggregate == 2991
    assert embedded == 9
    assert aggregate + embedded == formation["personnel"]
    assert formation["commander_ref"] == "char_gao_yun"
    assert formation["deputy_ref"] == "char_han_qiu"
    assert "command_structure" not in formation
    assert derived_command_structure(formation)["unit_command"]["outside_fighting_establishment"] is True
    assert deputy["military_command"]["external_to_fighting_strength"] is True
    assert deputy["military_command"]["commander_ref"] == "char_gao_yun"
    assert deputy["attributes"] and deputy["skills"]
    assert deputy["owner_id"] == "char_han_qiu"
    assert not (ROOT / "state/person/officers/officer-house-tang-wei-guard-deputy.json").exists()



def test_house_tang_standing_command_chain_is_exact_and_distinct_from_wei_field_army():
    force = load("state/forces/house-tang.json")
    house = load("state/houses/house_tang.json")
    zhu = load("state/char/tang-zhu.json")
    ling = load("state/char/tang-ling.json")
    qiu = load("state/char/qiu-ren.json")
    zhao = load("state/char/zhao-fen.json")
    army = force["officer_establishment"]["army_command"]
    assert army["commander_ref"] == "char_tang_zhu"
    assert army["deputy_ref"] == "char_tang_ling"
    assert house["military_command"]["commander_ref"] == "char_tang_zhu"
    assert house["military_command"]["deputy_ref"] == "char_tang_ling"
    assert force["officer_establishment"]["house_guard"]["commander_ref"] == "char_qiu_ren"
    assert force["officer_establishment"]["guardian_cavalry"]["commander_ref"] == "char_zhao_fen"
    assert zhu["role"] == "House Tang Field Commander"
    assert ling["role"] == "House Tang Field Deputy and Chief Administrator"
    assert qiu["career_state"]["office_or_command"] == "House Guard Commander"
    assert zhao["career_state"]["office_or_command"] == "House Guardian Cavalry Commander"


def test_qin_detachment_is_four_real_2000_units_with_full_external_unit_command():
    field = load("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    unit_refs = [f"formation_qin_wei_unit_{i:02d}" for i in range(1, 5)]
    assert all(ref in [row["ref"] for row in field["units"] if row["kind"] == "formation"] for ref in unit_refs)
    assert "formation_qin_border_line" not in [row["ref"] for row in field["units"] if row["kind"] == "formation"]

    total = 0
    for index, formation_ref in enumerate(unit_refs, start=1):
        formation = load(f"state/formations/qin-wei-unit-{index:02d}.json")
        aggregate = sum(int(row["count"]) for row in formation["cohort_composition"])
        embedded = len(formation["embedded_person_refs"])
        assert formation["formation_ref"] == formation_ref
        assert formation["personnel"] == 2000
        assert aggregate == 1994
        assert embedded == 6
        assert aggregate + embedded == formation["personnel"]
        assert formation["command_authority"] == "char_tang_wei"
        assert formation["higher_command_ref"] == field["id"]
        assert "command_structure" not in formation
        hierarchy = {int(row["scale"]): int(row["count"]) for row in derived_command_structure(formation)["internal_hierarchy"]}
        assert hierarchy == {1000: 2, 500: 4, 100: 20}

        commander_ref = f"char_qin_wei_unit_{index:02d}_commander"
        deputy_ref = f"char_qin_wei_unit_{index:02d}_deputy"
        assert formation["commander_ref"] == commander_ref
        assert formation["deputy_ref"] == deputy_ref
        commander = load(f"state/char/qin-wei-unit-{index:02d}-commander.json")
        deputy = load(f"state/char/qin-wei-unit-{index:02d}-deputy.json")
        for person in (commander, deputy):
            assert person["schema"] == "sab_character"
            assert person["current_location"] == formation["location_ref"]
            assert person["military_command"]["external_to_fighting_strength"] is True
            assert person["equipment_loadout_id"] == "loadout_house_champion"
            assert person["attributes"] and person["skills"]
        assert commander["military_command"]["deputy_ref"] == deputy_ref
        assert commander["military_command"]["higher_commander_ref"] == "char_tang_wei"
        assert deputy["military_command"]["commander_ref"] == commander_ref
        assert deputy["military_command"]["higher_commander_ref"] == "char_tang_wei"
        total += formation["personnel"]
    assert total == 8000
    assert not (ROOT / "state/formations/qin-border-line.json").exists()

    operation = load("state/operations/operation_arc_131572c4e8a2892bbc.json")
    assert operation["formation_refs"] == unit_refs
    assert operation["administrative_authority"] == "char_tang_wei"
    assert operation["administrative_authorities"] == ["char_tang_wei"]
    assert operation["assignment_authority_ref"] == "char_tang_wei"
    assert operation["institutional_owner_ref"] == "state_qin"
    assert operation["source_force_ref"] == "force_state_qin"
    assert operation["command_group_ref"] == field["id"]
    assert operation["autonomous"] is False
    assert operation["kind"] == "assigned_qin_field_detachment_operation"


def test_command_person_index_routes_full_formal_deputies():
    index = load("state/cmd/command-personnel.json")
    records = index["record_index"]
    assert index["count"] == len(records)
    assert "officer.house_tang.wei_guard.deputy" not in records
    assert records["char_lin_zhen"] == "state/char/lin-zhen.json"
    assert records["char_han_qiu"] == "state/char/han-qiu.json"
    for i in range(1, 5):
        ref = f"char_qin_wei_unit_{i:02d}_deputy"
        assert records[ref] == f"state/char/qin-wei-unit-{i:02d}-deputy.json"
    for ref, rel_path in records.items():
        record = load_route(rel_path)
        assert isinstance(record, dict), f"stale command-person route: {ref} -> {rel_path}"


def test_lin_zhen_field_deputy_capability_is_peer_to_wei_jian_and_mounted_command_ready():
    lin = load("state/char/lin-zhen.json")
    jian = load("state/char/wei-jian.json")
    assert lin["military_command"]["level"] == "army_deputy"
    assert lin["equipment_loadout_id"] == "loadout_house_champion"
    for key in (
        "Formation Command", "Leadership", "Tactics", "Strategy", "Logistics",
        "Polearms", "Sword", "Shield", "Bow", "Riding", "Formation Fighting",
    ):
        assert abs(int(lin["skills"][key]) - int(jian["skills"][key])) <= 15, key
    for key in ("Awareness", "Composure", "Coordination", "Intelligence", "Presence", "Endurance", "Toughness"):
        assert abs(int(lin["attributes"][key]) - int(jian["attributes"][key])) <= 15, key


def _formal_command_refs():
    refs = set()
    field = load("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    refs.update(ref for ref in (field.get("commander_ref"), field.get("deputy_ref")) if ref)
    for index in range(1, 5):
        formation = load(f"state/formations/qin-wei-unit-{index:02d}.json")
        refs.update((formation["commander_ref"], formation["deputy_ref"]))
    for path in ("state/formations/tang-wei-house-guard.json", "state/formations/tang-champions-first.json"):
        formation = load(path)
        refs.update((formation["commander_ref"], formation["deputy_ref"]))
    for force_path in ("state/forces/house-tang.json", "state/forces/sword-manor.json"):
        establishment = load(force_path)["officer_establishment"]
        stack = [establishment]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"commander_ref", "deputy_ref"} and isinstance(child, str):
                        refs.add(child)
                    else:
                        stack.append(child)
            elif isinstance(value, list):
                stack.extend(value)
    return refs


def test_all_formal_command_billets_use_mounted_relevant_loadout_and_no_random_weapon_specialties():
    owners = load("state/index/owner-index.json")["owners"]
    refs = _formal_command_refs()
    # Tang Wei is the player owner; all subordinate/formal NPC command people are exact characters.
    npc_refs = refs - {"char_tang_wei"}
    assert len(npc_refs) == 31
    relevant = ("Polearms", "Sword", "Shield", "Bow", "Riding", "Formation Fighting")
    removed = ("Spear", "Axe", "Dagger", "Glaive", "Mace", "Staff", "Defense", "Mass Combat", "Training", "Navigation", "Intrigue")
    for ref in sorted(npc_refs):
        path = owners[ref]
        person = load(path)
        assert person["equipment_loadout_id"] == "loadout_house_champion", ref
        items = person["equipment_manifest"]["items"]
        assert items["mount"] == "horse", ref
        assert items["primary_melee_weapon"] == "weapon_spear", ref
        assert items["shield"] == "shield_standard", ref
        assert items["sidearm"] == "weapon_sword", ref
        assert all(int(person["skills"].get(key, 0)) >= 125 for key in relevant), ref
        assert all(key not in person["skills"] for key in removed), ref


def test_house_tang_and_sword_manor_have_complete_current_command_establishments():
    house = load("state/forces/house-tang.json")["officer_establishment"]
    assert house["army_command"]["commander_ref"] == "char_tang_zhu"
    assert house["army_command"]["deputy_ref"] == "char_tang_ling"
    expected_house = {
        "house_guard": (18, 36, 180),
        "guardian_cavalry": (8, 16, 80),
        "tang_champion": (3, 7, 35),
    }
    for role, (n1000, n500, n100) in expected_house.items():
        row = house[role]
        assert row["commander_ref"] and row["deputy_ref"]
        assert len(row["commanders_1000"]) == n1000
        assert len(row["commanders_500"]) == n500
        assert row["aggregate_100_man_commanders"] == n100

    sword = load("state/forces/sword-manor.json")["officer_establishment"]
    assert sword["army_command"]["commander_ref"] == "char_wei_jian"
    assert sword["army_command"]["deputy_ref"] == "char_ren_qiao"
    expected_sword = {
        "trainee": (20, 40, 200),
        "junior_disciple": (5, 10, 50),
        "general_disciple": (3, 7, 35),
        "senior_disciple": (1, 3, 15),
    }
    for role, (n1000, n500, n100) in expected_sword.items():
        row = sword["rank_commands"][role]
        assert row["commander_ref"] and row["deputy_ref"]
        assert len(row["commanders_1000"]) == n1000
        assert len(row["commanders_500"]) == n500
        assert row["aggregate_100_man_commanders"] == n100
        assert row["internal_loadout_ref"] == "loadout_house_guard"


def test_no_orphan_full_command_characters_in_wei_house_tang_sword_manor_scope():
    expected = _formal_command_refs() - {"char_tang_wei"}
    actual = set()
    for path in (ROOT / "state/char").glob("*.json"):
        person = json.loads(path.read_text())
        mc = person.get("military_command") or {}
        scope = str(mc.get("formation_scope", ""))
        role = str(person.get("role", "")).lower()
        in_scope = (
            scope == "cmdgrp.tang_wei.field_army"
            or scope.startswith("formation_tang_")
            or scope.startswith("formation_qin_wei_")
            or scope.startswith("force_house_tang")
            or scope.startswith("force_sword_manor")
            or ("house tang" in role and ("commander" in role or "deputy" in role))
            or ("sword manor" in role and ("commander" in role or "deputy" in role))
        )
        if in_scope:
            actual.add(person["owner_id"])
    assert actual == expected


def test_internal_1000_500_officers_use_troop_loadout_and_role_relative_stats():
    routes = load("state/cmd/command-personnel.json")["record_index"]
    probes = [
        ("officer.house_tang.house_guard.1000.004", "loadout_house_guard"),
        ("officer.house_tang.guardian_cavalry.1000.001", "loadout_house_champion"),
        ("officer.sword_manor.trainee.1000.001", "loadout_house_guard"),
        ("officer.sword_manor.senior_disciple.1000.001", "loadout_house_guard"),
        ("officer.qin.wei_designated.1000.001", "loadout_house_guard"),
    ]
    for ref, loadout in probes:
        officer = load_route(routes[ref])
        assert officer["equipment_standard"] == loadout
        assert "equipment_manifest" not in officer
        skills = officer["stats"]["skills"]
        assert skills["Formation Command"] > 0
        assert skills["Leadership"] > 0
        assert skills["Tactics"] > 0
        assert skills["Polearms"] > 0 and skills["Shield"] > 0 and skills["Sword"] > 0
        if loadout == "loadout_house_champion":
            assert skills["Riding"] > 0
            primary_keys = ("Polearms", "Sword", "Shield", "Bow", "Riding")
        else:
            primary_keys = ("Polearms", "Sword", "Shield", "Bow")
        assert all(int(skills[key]) > 0 for key in primary_keys)
        for key in ("Spear", "Axe", "Dagger", "Glaive", "Mace", "Staff", "Defense", "Mass Combat", "Training", "Navigation", "Intrigue"):
            assert key not in skills, (ref, key)


def test_current_location_refs_used_by_state_exist_in_canonical_geography():
    locations = {row["ref"] for row in load("game/data/world/locations.json")["locations"]}
    keys = {"current_location", "location_ref", "destination_ref", "source_location_ref", "target_location_ref", "origin_location_ref"}
    missing = []

    def visit(value, source):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in keys and isinstance(child, str) and child.startswith("loc_") and child not in locations:
                    missing.append((source, key, child))
                visit(child, source)
        elif isinstance(value, list):
            for child in value:
                visit(child, source)

    for path in (ROOT / "state").rglob("*.json"):
        visit(json.loads(path.read_text()), str(path.relative_to(ROOT)))
    assert missing == []


def test_person_lite_commanders_use_compact_shards_and_wei_scope_for_qin_assignment():
    assert not (ROOT / "state/person/officers").exists()
    assert not (ROOT / "state/person/lite").exists()
    shard_root = ROOT / "state/person/person-lite"
    shards = sorted(shard_root.glob("*.json"))
    assert len(shards) <= 12
    for shard in shards:
        doc = json.loads(shard.read_text())
        assert doc.get("schema") == "person-lite-roster-shard"
        assert doc.get("record_count") == len(doc.get("records", {}))
        assert int(doc.get("record_count", 0)) >= 1
        assert "representation" not in doc
        assert "shard_policy" not in doc

    qin = load("state/person/person-lite/wei-field-army-qin-assignment.json")
    assert qin["id"] == "person_lite_roster.wei_field_army_qin_assignment"
    assert qin["record_count"] == 24
    for ref, officer in qin["records"].items():
        assert ref.startswith("officer.qin.wei_designated.")
        assert officer["owner"] == "force_state_qin"
        assert officer["command_assignment"]["scope"] == "wei_field_army_qin_assignment"
        assert officer["command_assignment"]["formation_ref"].startswith("formation_qin_wei_unit_")


def test_recursive_command_group_attach_detach_preserves_subtree_and_zero_manpower(campaign):
    from conftest import execute_production_internal

    parent_ref = "cmdgrp.tang_wei.field_army"
    child_ref = "cmdgrp.tang_wei.personal_force"
    child_path = campaign / "state/cmd/command-groups/cmdgrp.tang_wei.personal_force.json"
    parent_path = campaign / "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json"

    before_child = json.loads(child_path.read_text())
    before_units = list([row for row in before_child.get("units", []) if row.get("kind") == "formation"])
    before_children = list([row for row in before_child.get("units", []) if row.get("kind") == "nested_army"])

    execute_production_internal(campaign, "command_group_action", {
        "action": "detach_command_group",
        "command_group_ref": parent_ref,
        "subordinate_group_ref": child_ref,
    })
    detached_child = json.loads(child_path.read_text())
    detached_parent = json.loads(parent_path.read_text())
    assert detached_child["parent_command_group_ref"] is None
    assert child_ref not in [row["ref"] for row in detached_parent["units"] if row["kind"] == "nested_army"]
    assert [row for row in detached_child.get("units", []) if row.get("kind") == "formation"] == before_units
    assert [row for row in detached_child.get("units", []) if row.get("kind") == "nested_army"] == before_children

    execute_production_internal(campaign, "command_group_action", {
        "action": "attach_command_group",
        "command_group_ref": parent_ref,
        "subordinate_group_ref": child_ref,
    })
    attached_child = json.loads(child_path.read_text())
    attached_parent = json.loads(parent_path.read_text())
    assert attached_child["parent_command_group_ref"] == parent_ref
    assert child_ref in [row["ref"] for row in attached_parent["units"] if row["kind"] == "nested_army"]
    assert [row for row in attached_child.get("units", []) if row.get("kind") == "formation"] == before_units
    assert [row for row in attached_child.get("units", []) if row.get("kind") == "nested_army"] == before_children


def test_operational_nesting_is_force_agnostic_and_preserves_child_command_ownership(campaign):
    from conftest import execute_production_internal

    parent_ref = "cmdgrp.tang_wei.field_army"
    parent_path = campaign / "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json"
    owner_index = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    child_refs = (
        "cmdgrp.ousen.field_army",
        "cmdgrp.go_hou_mei.field_army",
        "cmdgrp.karin.field_army",
        "cmdgrp.juuko.defense",
    )

    for child_ref in child_refs:
        child_path = campaign / f"state/cmd/command-groups/{child_ref}.json"
        before = json.loads(child_path.read_text())
        assert before.get("parent_command_group_ref") is None
        commander_before = before.get("commander_ref")
        units_before = list(before.get("units", []))
        formation_ownership_before = {}
        for row in units_before:
            if row.get("kind") != "formation":
                continue
            formation = json.loads((campaign / owner_index[row["ref"]]).read_text())
            formation_ownership_before[row["ref"]] = (
                formation.get("owner_force_ref"),
                formation.get("administrative_owner"),
                formation.get("command_authority"),
                formation.get("personnel"),
            )

        execute_production_internal(campaign, "command_group_action", {
            "action": "attach_command_group",
            "command_group_ref": parent_ref,
            "subordinate_group_ref": child_ref,
        })
        attached = json.loads(child_path.read_text())
        parent = json.loads(parent_path.read_text())
        assert attached["parent_command_group_ref"] == parent_ref
        assert attached.get("commander_ref") == commander_before
        assert attached.get("units", []) == units_before
        assert {"kind": "nested_army", "ref": child_ref} in parent.get("units", [])

        for formation_ref, ownership_before in formation_ownership_before.items():
            formation = json.loads((campaign / owner_index[formation_ref]).read_text())
            assert (
                formation.get("owner_force_ref"),
                formation.get("administrative_owner"),
                formation.get("command_authority"),
                formation.get("personnel"),
            ) == ownership_before

        execute_production_internal(campaign, "command_group_action", {
            "action": "detach_command_group",
            "command_group_ref": parent_ref,
            "subordinate_group_ref": child_ref,
        })
        detached = json.loads(child_path.read_text())
        parent_after = json.loads(parent_path.read_text())
        assert detached["parent_command_group_ref"] is None
        assert detached.get("commander_ref") == commander_before
        assert detached.get("units", []) == units_before
        assert child_ref not in [row.get("ref") for row in parent_after.get("units", []) if row.get("kind") == "nested_army"]


def test_formation_promotion_becomes_one_nested_army_unit_with_conserved_succession(campaign):
    from conftest import execute_production_internal

    parent_ref = "cmdgrp.tang_wei.field_army"
    formation_ref = "formation_tang_wei_house_guard"
    army_ref = "cmdgrp.gao_yun.promoted_army"
    parent_path = campaign / "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json"
    formation_path = campaign / "state/formations/tang-wei-house-guard.json"
    force_path = campaign / "state/forces/house-tang.json"

    before_parent = json.loads(parent_path.read_text())
    before_slots = [dict(row) for row in before_parent["units"]]
    old_slot = next(i for i, row in enumerate(before_slots) if row["ref"] == formation_ref)
    before_formation = json.loads(formation_path.read_text())
    old_commander = before_formation["commander_ref"]
    old_deputy = before_formation["deputy_ref"]
    old_internal = set(before_formation["embedded_person_refs"])

    result = execute_production_internal(campaign, "command_group_action", {
        "action": "promote_formation_to_army",
        "command_group_ref": parent_ref,
        "formation_ref": formation_ref,
        "subordinate_group_ref": army_ref,
        "display_name": "Gao Yun Army",
    })
    promoted = dict(result.receipt.result)
    assert promoted["promoted_army_ref"] == army_ref

    parent = json.loads(parent_path.read_text())
    assert len(parent["units"]) == len(before_slots)
    assert parent["units"][old_slot] == {"kind": "nested_army", "ref": army_ref}

    army = json.loads((campaign / "state/cmd/command-groups/cmdgrp.gao_yun.promoted_army.json").read_text())
    assert army["commander_ref"] == old_commander
    assert army["deputy_ref"] == old_deputy
    assert army["parent_command_group_ref"] == parent_ref
    assert army["units"] == [{"kind": "formation", "ref": formation_ref}]

    formation = json.loads(formation_path.read_text())
    assert formation["higher_command_ref"] == army_ref
    assert formation["commander_ref"] in old_internal
    assert formation["deputy_ref"] in old_internal
    assert formation["commander_ref"] != old_commander
    assert formation["deputy_ref"] != old_deputy
    assert formation["commander_ref"] not in formation["embedded_person_refs"]
    assert formation["deputy_ref"] not in formation["embedded_person_refs"]
    # This deployed House formation has no House Tang reserve bodies at the Qin depot.
    # Promotion therefore does not teleport replacements from Tang Manor.
    assert formation["personnel"] == before_formation["personnel"] - 2

    force = json.loads(force_path.read_text())
    for ref in promoted["replacement_embedded_officer_refs"]:
        assert force["materialized_assignments"][ref]["formation_ref"] == formation_ref
        assert ref in formation["embedded_person_refs"]
    for ref in (formation["commander_ref"], formation["deputy_ref"]):
        assert ref not in force["materialized_assignments"]
        assert ref in force["materialized_people"]

    available = sum(int(v) for v in force.get("available_by_role", {}).values())
    allocated = sum(int(v.get("personnel", 0)) if isinstance(v, dict) else int(v) for v in force.get("allocated_to_formations", {}).values())
    external_allocated = sum(
        max(0, int(count))
        for roles in force.get("external_personnel_allocations", {}).values()
        if isinstance(roles, dict)
        for count in roles.values()
    )
    assignments = force.get("materialized_assignments", {})
    internal_refs = set(assignments)
    external_materialized = sum(
        int(v.get("personnel", 1)) if isinstance(v, dict) else int(v)
        for ref, v in force.get("materialized_people", {}).items()
        if ref not in internal_refs
    )
    assert available + allocated + external_allocated + external_materialized == force["headcount"]


def test_ordered_unit_oob_can_reposition_nested_army_without_flattening(campaign):
    from conftest import execute_production_internal

    parent_ref = "cmdgrp.tang_wei.field_army"
    child_ref = "cmdgrp.tang_wei.personal_force"
    path = campaign / "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json"
    child_path = campaign / "state/cmd/command-groups/cmdgrp.tang_wei.personal_force.json"
    before_child = json.loads(child_path.read_text())

    execute_production_internal(campaign, "command_group_action", {
        "action": "move_unit",
        "command_group_ref": parent_ref,
        "subordinate_group_ref": child_ref,
        "unit_slot": 1,
    })
    parent = json.loads(path.read_text())
    child = json.loads(child_path.read_text())
    assert parent["units"][0] == {"kind": "nested_army", "ref": child_ref}
    assert child["units"] == before_child["units"]


def test_field_army_hq_commands_units_without_repeating_each_unit_top_echelon():
    field = load("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    direct_formations = [row["ref"] for row in field["units"] if row["kind"] == "formation"]
    assert field["commander_ref"] == "char_tang_wei"
    assert field["deputy_ref"] == "char_lin_zhen"
    assert direct_formations
    for formation_ref in direct_formations:
        route = load("state/index/owner-index.json")["owners"][formation_ref]
        unit = load(route)
        authorized = int(unit["authorized_strength"] or unit["personnel"])
        # The formation commander/deputy are already the top command of this Unit.
        assert unit.get("commander_ref")
        assert unit.get("deputy_ref")
        assert "command_structure" not in unit
        internal = derived_command_structure(unit)["internal_hierarchy"]
        assert all(int(row["scale"]) < authorized for row in internal)
        if authorized == 1000:
            assert not any(int(row["scale"]) == 1000 for row in internal)

