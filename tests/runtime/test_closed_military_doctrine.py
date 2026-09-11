from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.military_doctrine import (
    doctrine_compatibility,
    formation_doctrine_ref_for_role,
)

ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: str):
    return json.loads((ROOT / path).read_text())


def test_black_banner_combined_arms_keep_one_mission_doctrine_across_physical_roles() -> None:
    formation = _read_json("state/formations/black-banner-01a.json")
    assert formation["composition"] == {
        "archer": 62,
        "heavy_cavalry": 25,
        "light_cavalry": 38,
        "line_infantry": 375,
    }
    # Tang Wei Army doctrine is now attached to the persistent named formation,
    # while each physical arm's equipment/capability remains role-specific.
    # Do not resurrect the retired per-arm Tang Wei doctrine tree.
    for role in formation["composition"]:
        assert formation_doctrine_ref_for_role(_read_json, formation, role) == "doc.tang_wei.black_banner"


def test_qin_light_cavalry_cannot_execute_mounted_archery() -> None:
    formation = {
        "administrative_owner": "state_qin",
        "owner_force_ref": "force_state_qin",
        "composition": {"cavalry": 200},
    }
    result = doctrine_compatibility(
        _read_json,
        formation,
        "doc.external_state_force.mounted_archer",
        role="cavalry",
    )
    assert result["compatible"] is False
    assert set(result["missing"]["mounted_archery"]) >= {"bow", "arrows"}
    assert result["loadout_ref"] == "loadout_qin_cavalry"


def test_qin_heavy_cavalry_physically_supports_heavy_shock() -> None:
    formation = {
        "administrative_owner": "state_qin",
        "owner_force_ref": "force_state_qin",
        "composition": {"heavy_cavalry": 100},
    }
    result = doctrine_compatibility(
        _read_json,
        formation,
        "doc.external_state_force.heavy_cavalry",
        role="heavy_cavalry",
    )
    assert result["compatible"] is True
    assert result["loadout_ref"] == "loadout_qin_heavy_cavalry"
