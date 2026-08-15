from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import ensure_cohort_ledger, seed_cohort_capability


class ForceBaselineMixin:
    """Seed current standing-force capability without inventing demographic ancestry.

    New recruitment never uses this table: it always derives from registered
    recruitment-background profiles. This table exists only because the release
    starts with already-established forces whose older intake history was
    deliberately discarded during repository cleanup.
    """

    def _baseline_registry_for_force(self, force: Mapping[str, Any]) -> Mapping[str, Any]:
        owner = str(force.get("owner_id", ""))
        if owner == "force_house_tang":
            return self.read("game/data/mil/house-tang-cohort-baselines.json")
        if owner == "institution_sword_manor":
            return self.read("game/data/mil/sword-manor-cohort-baselines.json")
        return self.read("game/data/mil/standing-force-capability-baselines.json")

    @staticmethod
    def _baseline_role_key(role: str, records: Mapping[str, Any]) -> str | None:
        if role in records:
            return role
        text = role.lower()
        for needle, fallback in (
            ("cavalry", "cavalry"), ("retainer", "household_retainer"),
            ("guard", "household_retainer"), ("infantry", "line_infantry"),
            ("line", "line_infantry"),
        ):
            if needle in text and fallback in records:
                return fallback
        return None

    def _seed_force_baselines(self, force: dict[str, Any]) -> None:
        registry = self._baseline_registry_for_force(force)
        attr_order = [str(x) for x in registry.get("attribute_order", [])]
        skill_order = [str(x) for x in registry.get("skill_order", [])]
        records = registry.get("records", {})
        if not isinstance(records, Mapping):
            return
        ledger = ensure_cohort_ledger(force)
        for cohort in ledger.get("cohorts", {}).values():
            if not isinstance(cohort, MutableMapping):
                continue
            if cohort.get("attribute_means") and cohort.get("skill_means"):
                continue
            key = self._baseline_role_key(str(cohort.get("role", "")), records)
            row = records.get(key) if key else None
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
                evidence_ref=str(row.get("evidence", "game/data/mil/standing-force-capability-baselines.json")),
            )

    # Keep generic living-world training on the same seeded capability authority.
    def _fc_train(self, force: dict[str, Any], regimen: str, months: float, ref: str) -> None:
        self._seed_force_baselines(force)
        return super()._fc_train(force, regimen, months, ref)


__all__ = ["ForceBaselineMixin"]
