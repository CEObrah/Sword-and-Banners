from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import execute_internal, meta
from sword_runtime.startup_integrity import validate_startup_integrity


def _owner(root: Path, ref: str) -> dict:
    owners = json.load(open(root / "state/index/owner-index.json"))["owners"]
    path = str(owners[ref])
    base, _, fragment = path.partition("#/records/")
    doc = json.load(open(root / base))
    return doc["records"][fragment] if fragment else doc


def _materialize_lite(campaign: Path, ref: str) -> None:
    execute_internal(
        campaign,
        "person_materialize",
        {
            "state": "qin",
            "person_ref": ref,
            "name": "Test Detachment Officer",
            "birth_date": "267-BCE-01-01",
            "role": "command_personnel",
            "source_location_ref": "loc_qin_eastern_depot",
            "representation": "person_lite",
        },
    )


def test_person_lite_may_command_sub_500_detachment(campaign: Path) -> None:
    commander_ref = "officer.test.detachment.commander"
    formation_ref = "formation_test_lite_detachment"
    _materialize_lite(campaign, commander_ref)

    execute_internal(
        campaign,
        "formation_create",
        {
            "state": "qin",
            "formation_ref": formation_ref,
            "role": "line_infantry",
            "personnel": 100,
            "authorized_strength": 100,
            "formation_class": "detachment",
            "location_ref": "loc_qin_eastern_depot",
            "commander_ref": commander_ref,
        },
    )

    formation = _owner(campaign, formation_ref)
    commander = _owner(campaign, commander_ref)
    assert formation["commander_ref"] == commander_ref
    assert commander["schema"] == "person-lite"
    assert commander["command_assignment"]["formation_ref"] == formation_ref
    assert commander["command_assignment"]["current_command_span"] == 100
    assert validate_startup_integrity(campaign)["ok"] is True


def test_person_lite_cannot_command_500_plus_persistent_unit(campaign: Path) -> None:
    commander_ref = "officer.test.unit.commander"
    formation_ref = "formation_test_lite_unit"
    _materialize_lite(campaign, commander_ref)
    before = meta(campaign)

    with pytest.raises(ValueError, match="500\\+ command requires a full exact character"):
        execute_internal(
            campaign,
            "formation_create",
            {
                "state": "qin",
                "formation_ref": formation_ref,
                "role": "line_infantry",
                "personnel": 500,
                "authorized_strength": 500,
                "formation_class": "unit",
                "location_ref": "loc_qin_eastern_depot",
                "commander_ref": commander_ref,
            },
        )

    assert meta(campaign) == before
    owners = json.load(open(campaign / "state/index/owner-index.json"))["owners"]
    assert formation_ref not in owners
