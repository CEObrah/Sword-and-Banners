from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.production_planner import ProductionCampaignPlanner

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_production_planner_has_no_retired_bastion_personnel_lifecycle() -> None:
    assert not hasattr(ProductionCampaignPlanner, "_settle_bastion_personnel")
    assert not hasattr(ProductionCampaignPlanner, "_bastion_retirements")


def test_runtime_has_no_bastion_or_sword_manor_autonomy_host() -> None:
    runtime = _read("state/runtime.json")
    active = [h for h in runtime["hosts"].values() if isinstance(h, dict)]
    assert not any(h.get("kind") in {"bastion_personnel", "sword_manor"} for h in active)
    assert any(h.get("kind") == "house_tang_training" for h in active)


def test_retired_bastion_policy_file_is_absent() -> None:
    assert not (ROOT / "game/data/mechanics/bastion-corps.json").exists()
