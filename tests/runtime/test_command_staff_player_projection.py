from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sword_runtime.api.warfare_operations import WarfareCampaignOperations
from sword_runtime.service_runtime import ProductionSwordRuntime


def _operations(campaign: Path, suffix: str) -> WarfareCampaignOperations:
    runtime = ProductionSwordRuntime(
        campaign,
        runtime_root=campaign.parent / suffix,
    )
    return WarfareCampaignOperations(runtime)


def test_controlled_formation_inspection_exposes_command_and_troop_capability(campaign: Path) -> None:
    operations = _operations(campaign, "runtime-command-staff-projection")
    context = operations.play_context()
    formations = context.get("controlled_formations", [])
    assert formations

    for row in formations:
        formation_ref = row["formation_ref"]
        inspected = operations.inspect_game_object(formation_ref)
        formation = inspected["object"]

        command_structure = formation.get("command_structure")
        assert isinstance(command_structure, dict)
        assert command_structure.get("projection_kind") == "formation_command_structure_v5"
        assert command_structure.get("fighting_establishment") == formation.get("personnel")

        troop_capability = formation.get("troop_capability")
        assert isinstance(troop_capability, dict)
        assert troop_capability.get("formation_personnel") == formation.get("personnel")
        assert int(troop_capability.get("cohort_personnel", 0)) >= 0
        assert int(troop_capability.get("unprojected_personnel", 0)) >= 0
        assert isinstance(troop_capability.get("cohorts", []), list)

    hint = context.get("read_hints", {}).get("controlled_formation_command_detail", {})
    assert "Inspect one exact controlled formation_ref" in hint.get("rule", "")


def test_controlled_named_officer_gets_bounded_command_service_sheet(campaign: Path) -> None:
    operations = _operations(campaign, "runtime-command-service-sheet")
    context = operations.play_context()
    player_id = context["campaign"]["player_id"]

    officer_ref = None
    for row in context.get("controlled_formations", []):
        for field in ("commander_ref",):
            value = row.get(field)
            if isinstance(value, str) and value.startswith("char_") and value != player_id:
                officer_ref = value
                break
        if officer_ref:
            break
    if officer_ref is None:
        pytest.skip("fixture has no exact non-player controlled-formation officer")

    assert officer_ref in context["permitted_person_ids"]
    sheet = operations.person_sheet(officer_ref)
    assert sheet["visibility"] == "player_visible_command_service_sheet"
    assert sheet["person"]["person_id"] == officer_ref
    assert sheet["person"].get("name")
    assert "relationships" not in sheet["person"]
    assert "behavior" not in sheet["person"]
    assert "private" not in sheet["person"]


def test_off_page_non_char_promoted_commander_uses_saved_full_character_schema(campaign: Path) -> None:
    """Hot-window omission must not demote a promoted officer back to Person Lite."""
    operations = _operations(campaign, "runtime-command-service-promoted-off-page")
    context = operations.play_context()
    formation_ref = context["controlled_formations"][0]["formation_ref"]

    owners_path = campaign / "state/index/owner-index.json"
    owners_doc = json.loads(owners_path.read_text())
    formation_path = campaign / owners_doc["owners"][formation_ref]
    formation = json.loads(formation_path.read_text())

    person_ref = "officer.test.promoted.full"
    person_path = campaign / "state/person/promoted-full-command-test.json"
    source = json.loads((campaign / "state/char/han-shou.json").read_text())
    source["id"] = person_ref
    source["name"] = "Promoted Full Command Test"
    source["current_formation_id"] = formation_ref
    source["current_location"] = formation.get("location_ref")
    person_path.write_text(json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    owners_doc["owners"][person_ref] = str(person_path.relative_to(campaign))
    owners_path.write_text(json.dumps(owners_doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    command_index_path = campaign / "state/cmd/command-personnel.json"
    command_index = json.loads(command_index_path.read_text())
    command_index.setdefault("record_index", {})[person_ref] = str(person_path.relative_to(campaign))
    command_index_path.write_text(json.dumps(command_index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    embedded = list(formation.get("embedded_person_refs", []))
    embedded.append(person_ref)
    formation["embedded_person_refs"] = embedded
    formation_path.write_text(json.dumps(formation, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    operations = _operations(campaign, "runtime-command-service-promoted-off-page-after")
    real_context = operations.play_context()
    assert person_ref in real_context["permitted_person_ids"]
    hidden_context = copy.deepcopy(real_context)
    hidden_context["permitted_person_ids"] = [ref for ref in hidden_context["permitted_person_ids"] if ref != person_ref]
    hidden_context["controlled_formations"] = [
        row for row in hidden_context["controlled_formations"] if row.get("formation_ref") != formation_ref
    ]
    operations.play_context = lambda: copy.deepcopy(hidden_context)  # type: ignore[method-assign]

    sheet = operations.person_sheet(person_ref)
    assert sheet["visibility"] == "player_visible_command_service_sheet"
    assert sheet["person"]["person_id"] == person_ref
    assert sheet["person"]["representation"] == "full_character"
    assert sheet["person"]["name"] == "Promoted Full Command Test"


def test_formation_inspection_uses_owner_schema_when_command_projection_is_missing(campaign: Path) -> None:
    """A stale bounded command index must not demote a real full person to Person Lite."""
    operations = _operations(campaign, "runtime-command-inspect-owner-schema")
    context = operations.play_context()
    formation_ref = context["controlled_formations"][0]["formation_ref"]

    owners_path = campaign / "state/index/owner-index.json"
    owners_doc = json.loads(owners_path.read_text())
    formation_path = campaign / owners_doc["owners"][formation_ref]
    formation = json.loads(formation_path.read_text())

    person_ref = "officer.test.full.owner.only"
    person_path = campaign / "state/person/full-command-owner-only.json"
    source = json.loads((campaign / "state/char/han-shou.json").read_text())
    source["id"] = person_ref
    source["name"] = "Owner Schema Full Command Test"
    source["current_formation_id"] = formation_ref
    source["current_location"] = formation.get("location_ref")
    person_path.write_text(json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    owners_doc["owners"][person_ref] = str(person_path.relative_to(campaign))
    owners_path.write_text(json.dumps(owners_doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    formation["embedded_person_refs"] = list(formation.get("embedded_person_refs", [])) + [person_ref]
    formation_path.write_text(json.dumps(formation, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    operations = _operations(campaign, "runtime-command-inspect-owner-schema-after")
    inspected = operations.inspect_game_object(formation_ref)["object"]
    full_refs = {row["person_ref"] for row in inspected.get("full_command_officers", [])}
    lite_refs = {row["person_ref"] for row in inspected.get("person_lite_officers", [])}
    assert person_ref in full_refs
    assert person_ref not in lite_refs


def test_materialized_exact_command_officer_gets_full_service_sheet(campaign: Path) -> None:
    """Dynamic exact people must stay full people through the command read surface."""
    operations = _operations(campaign, "runtime-command-service-materialized-exact")
    context = operations.play_context()
    formation_ref = context["controlled_formations"][0]["formation_ref"]

    owners_path = campaign / "state/index/owner-index.json"
    owners_doc = json.loads(owners_path.read_text())
    formation_path = campaign / owners_doc["owners"][formation_ref]
    formation = json.loads(formation_path.read_text())

    person_ref = "officer.test.materialized.exact.read"
    person_path = campaign / "state/person/materialized-exact-command-read-test.json"
    source = json.loads((campaign / "state/char/han-shou.json").read_text())
    source["schema"] = "sword-materialized-person"
    source["owner_id"] = person_ref
    source["id"] = person_ref
    source["name"] = "Materialized Exact Read Test"
    source["current_formation_id"] = formation_ref
    source["current_location"] = formation.get("location_ref")
    person_path.write_text(json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    owners_doc["owners"][person_ref] = str(person_path.relative_to(campaign))
    owners_path.write_text(json.dumps(owners_doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    command_index_path = campaign / "state/cmd/command-personnel.json"
    command_index = json.loads(command_index_path.read_text())
    command_index.setdefault("record_index", {})[person_ref] = str(person_path.relative_to(campaign))
    command_index_path.write_text(json.dumps(command_index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    formation["embedded_person_refs"] = list(formation.get("embedded_person_refs", [])) + [person_ref]
    formation_path.write_text(json.dumps(formation, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    operations = _operations(campaign, "runtime-command-service-materialized-exact-after")
    assert person_ref in operations.play_context()["permitted_person_ids"]
    sheet = operations.person_sheet(person_ref)
    assert sheet["visibility"] == "player_visible_command_service_sheet"
    assert sheet["person"]["person_id"] == person_ref
    assert sheet["person"]["representation"] == "full_character"
    assert sheet["person"]["name"] == "Materialized Exact Read Test"


def test_visible_materialized_command_person_uses_same_service_projection_as_other_command_people(campaign: Path) -> None:
    """Warfare read routing must not demote sword-materialized-person to identity-only."""
    operations = _operations(campaign, "runtime-visible-materialized-command-person")
    context = operations.play_context()

    owners_path = campaign / "state/index/owner-index.json"
    owners_doc = json.loads(owners_path.read_text())
    person_ref = "officer.test.materialized.visible.command"
    person_path = campaign / "state/person/materialized-visible-command-test.json"
    source = json.loads((campaign / "state/char/han-shou.json").read_text())
    source["schema"] = "sword-materialized-person"
    source["owner_id"] = person_ref
    source["id"] = person_ref
    source["name"] = "Visible Materialized Command Test"
    source.pop("current_formation_id", None)
    source["current_location"] = context["player"]["location"]
    person_path.write_text(json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    owners_doc["owners"][person_ref] = str(person_path.relative_to(campaign))
    owners_path.write_text(json.dumps(owners_doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    command_index_path = campaign / "state/cmd/command-personnel.json"
    command_index = json.loads(command_index_path.read_text())
    command_index.setdefault("record_index", {})[person_ref] = str(person_path.relative_to(campaign))
    command_index_path.write_text(json.dumps(command_index, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    meta_doc = json.loads((campaign / "state/meta.json").read_text())
    scene_path = campaign / "state/scene.json"
    scene = json.loads(scene_path.read_text())
    scene["world_time"] = meta_doc["time"]
    scene["projection_revision"] = meta_doc["revision"]
    scene["relevant_owner_ids"] = sorted(set(scene.get("relevant_owner_ids", [])) | {person_ref})
    scene_path.write_text(json.dumps(scene, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    operations = _operations(campaign, "runtime-visible-materialized-command-person-after")
    assert person_ref in operations.play_context()["permitted_person_ids"]

    sheet = operations.person_sheet(person_ref)
    assert sheet["visibility"] == "player_visible_command_service_sheet"
    assert sheet["person"]["person_id"] == person_ref
    assert sheet["person"]["representation"] == "full_character"
    assert sheet["person"]["name"] == "Visible Materialized Command Test"
