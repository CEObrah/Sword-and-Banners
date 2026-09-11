from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_retired_house_military_authority_files_stay_deleted() -> None:
    retired = [
        "game/data/mechanics/bastion-corps.json",
        "game/data/mechanics/sword-manor-organization.json",
        "game/data/mil/house-tang-champion-progression.json",
        "game/data/mil/sword-manor-progression.json",
    ]
    assert all(not (ROOT / rel).exists() for rel in retired)


def test_retired_troop_roles_are_not_live_house_establishment_roles() -> None:
    force = _read("state/forces/house-tang.json")
    retired = {"house_guard", "guardian_cavalry", "tang_champion", "trainee", "junior_disciple", "general_disciple", "senior_disciple"}
    assert not (retired & set(force["authorized_by_role"]))
    assert not (retired & {str(v.get("role")) for v in force.get("materialized_people", {}).values() if isinstance(v, dict)})


def test_house_mount_pool_keeps_exact_100000_spare_horses_without_retired_allocations() -> None:
    pool = _read("state/mounts/house-tang.json")
    assert pool["total"] == 112000
    assert pool["regional_reserve"]["loc_tang_manor_garrison_yard"]["horse"] == 100000
    owners = _read("state/index/owner-index.json")["owners"]
    for ref, roles in pool.get("allocated_to_formations", {}).items():
        if sum(int(v) for v in roles.values()) <= 0:
            continue
        assert ref in owners
        assert str(owners[ref]).startswith("state/formations/")
