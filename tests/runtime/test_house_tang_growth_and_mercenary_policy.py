from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_force_policy_defines_direct_recruitment_into_two_real_roles() -> None:
    policy = _read("game/data/mechanics/house-tang-force-policy.json")
    roles = policy["recruitment"]["roles"]
    assert set(roles) == {"house_infantry", "house_cavalry"}
    assert roles["house_cavalry"]["requires_mount"] is True
    assert "no troop-rank promotion ladder" in policy["recruitment"]["rule"]


def test_house_mercenary_contingency_never_transfers_manpower_ownership() -> None:
    policy = _read("game/data/mechanics/house-tang-force-policy.json")
    rule = policy["contingency_mercenary_procurement"]["rule"]
    assert "remain independent manpower owners" in rule
    assert policy["contingency_mercenary_procurement"]["minimum_threat_severity"] > 0


def test_unified_house_force_strength_is_exact_and_not_growth_padding() -> None:
    force = _read("state/forces/house-tang.json")
    assert force["headcount"] == 176060
    assert force["authorized_strength"] == 176060
    assert sum(force["authorized_by_role"].values()) == 176060


def test_house_equipment_reserve_uses_current_role_names_only() -> None:
    force = _read("state/forces/house-tang.json")
    legal = {"house_infantry", "house_cavalry"}
    assert set(force.get("available_equipment_units_by_role", {})) <= legal
    for pool in force.get("available_equipment_by_location", {}).values():
        assert set(pool) <= legal
