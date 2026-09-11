from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.cohort_personnel import advance_service_months

ROOT = Path(__file__).resolve().parents[2]


def test_unknown_standing_cohort_age_seeds_from_service_tenure_before_advancing() -> None:
    cohort = {"service_months_mean": 36.0, "age_distribution": {}}
    advance_service_months(cohort, 1.0, unknown_entry_age_mean=24.0)
    assert cohort["service_months_mean"] == 37.0
    assert cohort["age_distribution"]["mean"] == 27.083


def test_known_recruit_age_advances_without_reseeding() -> None:
    cohort = {"service_months_mean": 6.0, "age_distribution": {"mean": 29.0, "sd": 7.0}}
    advance_service_months(cohort, 6.0, unknown_entry_age_mean=24.0)
    assert cohort["service_months_mean"] == 12.0
    assert cohort["age_distribution"]["mean"] == 29.5
    assert cohort["age_distribution"]["sd"] == 7.0


def test_every_active_saved_force_cohort_has_current_age_mean() -> None:
    missing: list[str] = []
    for path in sorted((ROOT / "state" / "forces").glob("*.json")):
        force = json.loads(path.read_text())
        for cohort_id, cohort in force.get("cohort_ledger", {}).get("cohorts", {}).items():
            active = (
                sum(max(0, int(v)) for v in cohort.get("reserve_by_location", {}).values())
                + sum(max(0, int(v)) for v in cohort.get("allocated_by_formation", {}).values())
                + sum(max(0, int(v)) for v in cohort.get("allocated_external_by_formation", {}).values())
            )
            if active > 0 and "mean" not in cohort.get("age_distribution", {}):
                missing.append(f"{path.name}:{cohort_id}")
    assert missing == []
