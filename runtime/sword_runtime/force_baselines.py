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

    def _baseline_role_candidates(self, force: Mapping[str, Any], cohort: Mapping[str, Any]) -> set[str]:
        """Return exact saved role evidence for an otherwise legacy ``unknown`` cohort.

        Older release-baseline ledgers sometimes preserved the bodies and their
        formation allocation but lost the role label itself.  Those cohorts can
        then accumulate verified training hours forever without any capability
        means, because no standing baseline can be selected.  Recover the role
        only from current exact military authority.  Never guess from a House
        name, commander, or prose label.
        """

        formation_candidates: set[str] = set()
        allocated = cohort.get("allocated_by_formation", {})
        if isinstance(allocated, Mapping) and hasattr(self, "_load_formation"):
            for formation_ref, raw_count in allocated.items():
                try:
                    count = int(raw_count)
                except (TypeError, ValueError):
                    continue
                if count <= 0:
                    continue
                try:
                    _path, formation = self._load_formation(str(formation_ref))
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                if not isinstance(formation, Mapping):
                    continue
                composition = formation.get("composition", {})
                if isinstance(composition, Mapping):
                    formation_candidates.update(
                        str(role)
                        for role, value in composition.items()
                        if str(role).strip()
                        and str(role).lower() != "unknown"
                        and int(value or 0) > 0
                    )

        # Formation allocation is the narrowest current authority for an
        # allocated cohort.  Do not pollute that evidence with every other role
        # the parent force happens to contain.
        if formation_candidates:
            return formation_candidates

        candidates: set[str] = set()
        by_role = force.get("available_by_role", {})
        if isinstance(by_role, Mapping):
            candidates.update(
                str(role)
                for role in by_role
                if str(role).strip() and str(role).lower() != "unknown"
            )

        by_location = force.get("available_by_location", {})
        if isinstance(by_location, Mapping):
            for roles in by_location.values():
                if not isinstance(roles, Mapping):
                    continue
                candidates.update(
                    str(role)
                    for role in roles
                    if str(role).strip() and str(role).lower() != "unknown"
                )

        return candidates

    def _resolve_baseline_role(
        self,
        force: Mapping[str, Any],
        cohort: MutableMapping[str, Any],
        records: Mapping[str, Any],
    ) -> str | None:
        current_role = str(cohort.get("role", ""))
        key = self._baseline_role_key(current_role, records)
        if key:
            return key

        # Only legacy/unresolved roles may be reconstructed.  A real current
        # role that lacks a registered baseline must remain unresolved rather
        # than being silently remapped to a convenient profile.
        if current_role.strip().lower() not in {"", "unknown"}:
            return None

        candidates = self._baseline_role_candidates(force, cohort)
        exact_candidates = {
            role for role in candidates if self._baseline_role_key(role, records)
        }
        if len(exact_candidates) == 1:
            resolved_role = next(iter(exact_candidates))
            cohort["role"] = resolved_role
            tags = cohort.setdefault("tags", [])
            if "baseline_role_resolved" not in tags:
                tags.append("baseline_role_resolved")
            return self._baseline_role_key(resolved_role, records)

        # Several exact role labels may legitimately map to the same standing
        # capability family.  That is enough to seed capability, but not enough
        # evidence to rewrite the cohort's exact role identity.
        baseline_keys = {
            key
            for role in candidates
            if (key := self._baseline_role_key(role, records))
        }
        if len(baseline_keys) == 1:
            return next(iter(baseline_keys))
        return None

    @staticmethod
    def _baseline_role_key(role: str, records: Mapping[str, Any]) -> str | None:
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
            ("guard", "line_infantry"), ("infantry", "line_infantry"),
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
            key = self._resolve_baseline_role(force, cohort, records)
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
