from __future__ import annotations

import copy
import json
from pathlib import Path

from sword_runtime.api.warfare_operations import WarfareCampaignOperations
from sword_runtime.engine import SwordRuntime
from sword_runtime.service_runtime import CommandRoutedProductionPlanner
from sword_runtime.warfare_depth import build_formation_command_structure

QIN_LEAVES = [
    ("formation_high_guard_qin_a", "char_gao_yun"),
    ("formation_high_guard_qin_b", "char_han_qiu"),
    ("formation_black_banner_01a", "char_qin_wei_unit_01_commander"),
    ("formation_black_banner_01b", "char_qin_wei_unit_02_commander"),
    ("formation_black_banner_02a", "char_qin_wei_unit_03_commander"),
    ("formation_black_banner_02b", "char_qin_wei_unit_04_commander"),
    ("formation_black_banner_03a", "char_han_shou"),
    ("formation_black_banner_03b", "char_pei_rong"),
    ("formation_black_banner_04a", "char_deng_kai"),
    ("formation_black_banner_04b", "char_lu_cheng"),
]


def _read(root: Path, path: str):
    return json.loads((root / path).read_text())


def _person_path(root: Path, person_ref: str) -> str:
    owners = _read(root, "state/index/owner-index.json").get("owners", {})
    path = owners.get(person_ref) if isinstance(owners, dict) else None
    if isinstance(path, str):
        return path
    records = _read(root, "state/cmd/command-personnel.json").get("record_index", {})
    path = records.get(person_ref) if isinstance(records, dict) else None
    assert isinstance(path, str), person_ref
    return path


def test_tang_wei_qin_detachment_uses_ten_exact_500_man_leaves_with_external_commanders(campaign):
    owners = _read(campaign, "state/index/owner-index.json")["owners"]
    total = 0
    commanders = set()
    for formation_ref, commander_ref in QIN_LEAVES:
        formation = _read(campaign, owners[formation_ref])
        assert formation["personnel"] == 500
        assert sum(int(v) for v in formation["composition"].values()) == 500
        assert set(formation["composition"]) == {"line_infantry", "archer", "light_cavalry", "heavy_cavalry"}
        embedded = set(formation.get("embedded_person_refs", []))
        assert sum(int(row["count"]) for row in formation["cohort_composition"]) + len(embedded) == 500
        assert formation["commander_ref"] == commander_ref
        assert commander_ref not in embedded
        person = _read(campaign, _person_path(campaign, commander_ref))
        assert person["schema"] == "sab_character"
        assert person["owner_id"] == commander_ref
        assert person["military_command"]["external_to_fighting_strength"] is True
        assert person["personal_loadout_ref"] == "loadout_tang_mounted"
        commanders.add(commander_ref)
        total += formation["personnel"]
    assert total == 5000
    assert len(commanders) == 10


def test_controlled_full_commander_resolves_through_bounded_command_registry(campaign):
    runtime = SwordRuntime(campaign)
    operations = WarfareCampaignOperations(runtime)
    sheet = operations.person_sheet("char_han_shou")
    assert sheet["visibility"] == "player_visible_command_service_sheet"
    assert sheet["person"]["representation"] == "full_character"
    assert sheet["person"]["name"] == "Han Shou"
    assert sheet["person"]["role"] == "500-man Commander, Black Banner 3A"


def test_movement_snapshot_includes_one_exact_top_commander_for_each_qin_leaf(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    refs_to_move = [formation_ref for formation_ref, _ in QIN_LEAVES]
    snapshots = planner._command_staff_snapshots(refs_to_move)
    refs = {person_ref for _formation_ref, person_ref, _path, _origin in snapshots}
    expected = {commander_ref for _, commander_ref in QIN_LEAVES}
    assert expected <= refs


def test_named_leaf_command_satisfies_one_external_top_command_billet(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    owners = _read(campaign, "state/index/owner-index.json")["owners"]
    formation = _read(campaign, owners["formation_black_banner_01a"])
    assert planner._named_unit_command_count(formation, 1) == 1
    missing = copy.deepcopy(formation)
    missing["commander_ref"] = None
    assert planner._named_unit_command_count(missing, 1) == 0


def test_red_lance_leaf_has_external_500_commander_over_five_hundred_fighting_strength(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    owners = _read(campaign, "state/index/owner-index.json")["owners"]
    formation = _read(campaign, owners["formation_red_lance_a"])
    assert formation["personnel"] == 500
    assert formation["commander_ref"] == "char_duan_jin"
    assert "command_structure" not in formation
    structure = build_formation_command_structure(formation, planner._warfare_depth_rules())
    assert structure["unit_command"]["outside_fighting_establishment"] is True
    assert structure["unit_command"]["target_bodies"] == 1
    hierarchy = structure["internal_hierarchy"]
    assert len(hierarchy) == 1
    assert hierarchy[0]["scale"] == 100
    assert hierarchy[0]["count"] == 5
    assert hierarchy[0]["authorized_count"] == 5
    assert hierarchy[0]["inside_fighting_establishment"] is True


def test_house_tang_owner_matches_current_campaign_authority(campaign):
    house = _read(campaign, "state/houses/house_tang.json")
    command = house["military_command"]
    assert command["force_ref"] == "force_house_tang"
    assert "army_commander_ref" not in command
    assert "administrative_requests" not in house
    assert "development_requests" not in house
    assert "house_equipment_production" not in house.get("administrative_programs", {})
    assert house["administrative_programs"]["wei_field_preparation"]["outfitting_rules_ref"] == "game/data/mechanics/outfitting.json"
    assert house["administrative_programs"]["wei_field_preparation"]["status"] == "issued_for_departure"


def test_current_command_records_are_external_and_match_exact_echelon(campaign):
    expected = {
        "char_duan_jin": "500_commander",
        "char_shen_rui": "500_commander",
        "char_gao_yun": "500_commander",
        "char_han_qiu": "500_commander",
        "char_lin_zhen": "4500_commander",
        "char_tang_command_red_lance_1000": "1000_commander",
        "char_tang_command_black_banner_4000": "4000_commander",
    }
    for ref, level in expected.items():
        person = _read(campaign, _person_path(campaign, ref))
        assert person["military_command"]["external_to_fighting_strength"] is True
        assert person["military_command"]["level"] == level
