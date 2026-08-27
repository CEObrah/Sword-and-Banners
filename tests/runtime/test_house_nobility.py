from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import execute, execute_internal
from sword_runtime.house_nobility import derived_nobility_effects, next_grade


def _j(root: Path, path: str):
    return json.loads((Path(root) / path).read_text())


def _saved_evidence_ref(root: Path) -> str:
    hist = _j(root, "state/history/events/index.json")
    rows = hist.get("events", [])
    assert rows
    return str(rows[-1]["event_id"])


def test_all_current_houses_use_shared_nobility_ladder(campaign):
    rules = _j(campaign, "game/data/mechanics/nobility.json")
    valid = set(rules["grade_order"])
    for path in (Path(campaign) / "state/houses").glob("*.json"):
        house = json.loads(path.read_text())
        if house.get("schema") == "sword-house":
            assert house["nobility"]["grade"] in valid
            effects = derived_nobility_effects(house, rules)
            assert effects["court_precedence_points"] >= 0
            assert effects["faction_weight_points"] >= 0


def test_sovereign_nobility_grant_advances_one_grade_without_minting_assets(campaign):
    rules = _j(campaign, "game/data/mechanics/nobility.json")
    house_before = _j(campaign, "state/houses/house_tang.json")
    treasury_before = _j(campaign, "state/treasury/treasury-house-tang.json")
    force_before = _j(campaign, "state/forces/house-tang.json")
    evidence_ref = _saved_evidence_ref(campaign)
    current = house_before["nobility"]["grade"]
    target = next_grade(rules, current)
    assert target is not None

    result = execute_internal(
        campaign,
        "house_action",
        {
            "house_ref": "house_tang",
            "action": "grant_nobility",
            "target_grade": target,
            "grantor_ref": "char_ei_sei",
            "evidence_ref": evidence_ref,
        },
        request_id="test-sovereign-house-nobility-grant",
    )
    assert result.receipt.result["grade"] == target
    house_after = _j(campaign, "state/houses/house_tang.json")
    assert house_after["nobility"]["grade"] == target
    assert _j(campaign, "state/treasury/treasury-house-tang.json")["silver"] == treasury_before["silver"]
    assert _j(campaign, "state/forces/house-tang.json")["headcount"] == force_before["headcount"]
    assert "royal" not in house_after["nobility"]["grade"]


def test_house_cannot_self_award_nobility_without_sovereign_authority(campaign):
    evidence_ref = _saved_evidence_ref(campaign)
    with pytest.raises(PermissionError, match="lacks sovereign"):
        execute(
            campaign,
            "house_action",
            {
                "house_ref": "house_tang",
                "action": "grant_nobility",
                "target_grade": "minor_noble_house",
                "grantor_ref": "char_tang_wei",
                "evidence_ref": evidence_ref,
            },
            actor="char_tang_wei",
            request_id="test-illegal-self-nobility-grant",
        )


def test_normal_grant_cannot_skip_multiple_house_grades(campaign):
    evidence_ref = _saved_evidence_ref(campaign)
    with pytest.raises(ValueError, match="one registered grade"):
        execute_internal(
            campaign,
            "house_action",
            {
                "house_ref": "house_tang",
                "action": "grant_nobility",
                "target_grade": "noble_house",
                "grantor_ref": "char_ei_sei",
                "evidence_ref": evidence_ref,
            },
            request_id="test-skip-house-nobility-grade",
        )
