from __future__ import annotations

import copy
import json
from pathlib import Path

from sword_runtime.api.warfare_operations import WarfareCampaignOperations
from sword_runtime.engine import SwordRuntime
from sword_runtime.service_runtime import CommandRoutedProductionPlanner
from sword_runtime.warfare_depth import build_formation_command_structure


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


def test_qin_detachment_uses_four_2000_formations_with_external_full_command(campaign):
    formal_refs = set()
    total = 0
    for unit in range(1, 5):
        formation = _read(campaign, f"state/formations/qin-wei-unit-{unit:02d}.json")
        assert formation["personnel"] == 2000
        embedded = set(formation["embedded_person_refs"])
        assert len(embedded) == 6
        assert sum(int(row["count"]) for row in formation["cohort_composition"]) + len(embedded) == 2000
        pair = {formation["commander_ref"], formation["deputy_ref"]}
        assert len(pair) == 2
        assert pair.isdisjoint(embedded)
        formal_refs |= pair
        for person_ref in pair:
            person = _read(campaign, _person_path(campaign, person_ref))
            assert person["schema"] == "sab_character"
            assert person["owner_id"] == person_ref
            assert person["military_command"]["external_to_fighting_strength"] is True
            assert person["military_command"]["formation_scope"] == formation["formation_ref"]
        total += formation["personnel"]
    assert total == 8000
    assert len(formal_refs) == 8


def test_controlled_full_deputy_resolves_through_bounded_command_registry(campaign):
    runtime = SwordRuntime(campaign)
    operations = WarfareCampaignOperations(runtime)

    sheet = operations.person_sheet("char_qin_wei_unit_01_deputy")

    assert sheet["visibility"] == "player_visible_command_service_sheet"
    assert sheet["person"]["representation"] == "full_character"
    assert sheet["person"]["name"] == "Han Shou"
    assert sheet["person"]["role"] == "Qin Border Detachment Unit 1 Deputy Commander"


def test_movement_snapshot_includes_full_command_for_each_qin_unit(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    refs_to_move = [f"formation_qin_wei_unit_{unit:02d}" for unit in range(1, 5)]
    snapshots = planner._command_staff_snapshots(refs_to_move)
    refs = {person_ref for _formation_ref, person_ref, _path, _origin in snapshots}

    expected = set()
    for unit in range(1, 5):
        expected.add(f"char_qin_wei_unit_{unit:02d}_commander")
        expected.add(f"char_qin_wei_unit_{unit:02d}_deputy")

    assert expected <= refs
    assert not any(".1000." in ref or ".500." in ref for ref in refs)


def test_named_unit_command_satisfies_two_external_command_billets_per_qin_unit(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    formation = _read(campaign, "state/formations/qin-wei-unit-01.json")

    assert planner._named_unit_command_count(formation, 2) == 2
    missing = copy.deepcopy(formation)
    missing["deputy_ref"] = None
    assert planner._named_unit_command_count(missing, 2) == 1


def test_champions_command_pair_is_external_to_five_hundred_fighting_strength(campaign):
    planner = CommandRoutedProductionPlanner(campaign)
    formation = _read(campaign, "state/formations/tang-champions-first.json")

    assert formation["personnel"] == 500
    assert formation["commander_ref"] == "char_duan_jin"
    assert formation["deputy_ref"] == "char_shen_rui"
    assert "command_structure" not in formation
    structure = build_formation_command_structure(formation, planner._warfare_depth_rules())
    assert structure["unit_command"]["outside_fighting_establishment"] is True
    hierarchy = structure["internal_hierarchy"]
    assert len(hierarchy) == 1
    assert hierarchy[0]["scale"] == 100
    assert hierarchy[0]["count"] == 5
    assert hierarchy[0]["authorized_count"] == 5
    assert hierarchy[0]["representation"] == "person_lite"
    assert hierarchy[0]["inside_fighting_establishment"] is True


def test_house_tang_owner_matches_current_campaign_authority(campaign):
    house = _read(campaign, "state/houses/house_tang.json")
    command = house["military_command"]
    assert command["force_ref"] == "force_house_tang"
    assert "army_commander_ref" not in command
    assert "army_deputy_ref" not in command
    assert "administrative_requests" not in house
    assert "development_requests" not in house
    assert "house_equipment_production" not in house.get("administrative_programs", {})
    assert house["administrative_programs"]["wei_field_preparation"]["outfitting_rules_ref"] == "game/data/mechanics/outfitting.json"
    assert house["administrative_programs"]["wei_field_preparation"]["status"] == "issued_for_departure"


def test_champions_command_records_are_external_to_fighting_strength(campaign):
    for ref in ("char_duan_jin", "char_shen_rui"):
        person = _read(campaign, _person_path(campaign, ref))
        assert person["military_command"]["external_to_fighting_strength"] is True
