from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import ensure_cohort_ledger, seed_cohort_capability


class HouseTangBaselineMixin:
    """Seed only evidence-backed pre-cohort Tang/Sword capability distributions."""

    def _seed_house_tang_baselines(self, force: dict[str, Any]) -> None:
        owner = str(force.get("owner_id", ""))
        if owner == "force_house_tang":
            path = "game/data/mil/house-tang-cohort-baselines.json"
        elif owner == "institution_sword_manor":
            path = "game/data/mil/sword-manor-cohort-baselines.json"
        else:
            return
        registry = self.read(path)
        attr_order = [str(x) for x in registry.get("attribute_order", [])]
        skill_order = [str(x) for x in registry.get("skill_order", [])]
        records = registry.get("records", {})
        ledger = ensure_cohort_ledger(force)
        for cohort in ledger.get("cohorts", {}).values():
            if not isinstance(cohort, MutableMapping):
                continue
            if cohort.get("attribute_means") or cohort.get("skill_means"):
                continue
            row = records.get(str(cohort.get("role", ""))) if isinstance(records, Mapping) else None
            if not isinstance(row, Mapping):
                continue
            seed_cohort_capability(
                cohort,
                attribute_means=dict(zip(attr_order, row.get("attribute_values", []))),
                skill_means=dict(zip(skill_order, row.get("skill_values", []))),
                attribute_sd=float(row.get("attribute_sd", 8.0)),
                skill_sd=float(row.get("skill_sd", 10.0)),
                aptitude_means=row.get("aptitude", {}),
                service_months_mean=float(row.get("service_months_mean", 0.0)),
                evidence_ref=str(row.get("evidence", path)),
            )

    def _fc_train(self, force: dict[str, Any], regimen: str, months: float, ref: str) -> None:
        self._seed_house_tang_baselines(force)
        return super()._fc_train(force, regimen, months, ref)


__all__ = ["HouseTangBaselineMixin"]
