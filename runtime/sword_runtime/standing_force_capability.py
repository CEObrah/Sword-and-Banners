from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import ensure_cohort_ledger, seed_cohort_capability


class StandingForceCapabilityMixin:
    """Seed current standing-force capability without inventing recruitment ancestry.

    Existing forces use registered current capability profiles when a conserved
    cohort has not yet accumulated explicit capability means. New recruitment is
    separate and always derives from registered recruitment-background profiles.
    """

    def _capability_registry_for_force(self, force: Mapping[str, Any]) -> Mapping[str, Any]:
        owner = str(force.get("owner_id", ""))
        if owner == "force_house_tang":
            return self.read("game/data/mil/house-tang-cohort-profiles.json")
        if owner == "force_sword_manor":
            return self.read("game/data/mil/sword-manor-cohort-profiles.json")
        return self.read("game/data/mil/standing-force-capability-profiles.json")

    @staticmethod
    def _capability_role_key(role: str, records: Mapping[str, Any]) -> str | None:
        """Map an exact current role to one registered capability family."""
        if role in records:
            return role
        text = role.lower()
        for needle, fallback in (
            ("cavalry", "cavalry"), ("rider", "cavalry"), ("mounted", "cavalry"),
            ("crossbow", "missile_crossbow"), ("missile", "missile_crossbow"), ("archer", "archer"),
            ("chariot", "chariot"), ("engineer", "siege_engineering"), ("sapper", "siege_engineering"),
            ("logistics", "logistics"), ("supply", "logistics"), ("signal", "signal"),
            ("scout", "signal"), ("command", "command_personnel"), ("officer", "command_personnel"),
            ("retainer", "household_retainer"),
            ("guard", "line_infantry"), ("infantry", "line_infantry"), ("line", "line_infantry"),
        ):
            if needle in text and fallback in records:
                return fallback
        return None

    def _seed_standing_force_capability(self, force: dict[str, Any]) -> None:
        registry = self._capability_registry_for_force(force)
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
            role = str(cohort.get("role", "")).strip()
            if not role or role.lower() == "unknown":
                # Current state must carry exact role identity. Missing role is an
                # integrity defect, not a cue to reconstruct discarded history.
                continue
            key = self._capability_role_key(role, records)
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
                evidence_ref=str(row.get("evidence", "game/data/mil/standing-force-capability-profiles.json")),
            )

    def _fc_train(self, force: dict[str, Any], regimen: str, months: float, ref: str) -> None:
        self._seed_standing_force_capability(force)
        return super()._fc_train(force, regimen, months, ref)


__all__ = ["StandingForceCapabilityMixin"]
