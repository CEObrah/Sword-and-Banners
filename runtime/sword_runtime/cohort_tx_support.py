from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from statistics import NormalDist
from typing import Any

from sword_runtime.cohort_personnel import (
    ATTRIBUTE_ORDER,
    SKILL_ORDER,
    advance_cohort_training,
    ensure_cohort_ledger,
    ensure_formation_composition,
    stable_fraction,
    validate_cohort_ledger,
)


def _sample_metric(cohort: Mapping[str, Any], *, person_ref: str, kind: str, key: str, mean: float, sd: float) -> int:
    independent_u=min(.999999,max(.000001,stable_fraction(person_ref,kind,key)))
    independent_z=NormalDist().inv_cdf(independent_u)
    shared_z: list[float] = []
    groups=cohort.get("correlation_groups", [])
    if isinstance(groups, (list, tuple)):
        for index, group in enumerate(groups):
            if not isinstance(group, (list, tuple)) or key not in {str(x) for x in group}:
                continue
            u=min(.999999,max(.000001,stable_fraction(person_ref,"correlation",index)))
            shared_z.append(NormalDist().inv_cdf(u))
    if shared_z:
        # Keep personal variation while giving related background capabilities a
        # common deterministic latent component.  This prevents implausibly
        # independent hunter/rider/etc. draws without storing thousands of people.
        rho=0.55
        group_z=sum(shared_z)/len(shared_z)
        z=rho*group_z+math.sqrt(max(0.0,1.0-rho*rho))*independent_z
    else:
        z=independent_z
    value=float(mean)+z*max(0.0,float(sd))
    lo_map=cohort.get(f"{kind}_min", {}) if isinstance(cohort.get(f"{kind}_min"), Mapping) else {}
    hi_map=cohort.get(f"{kind}_max", {}) if isinstance(cohort.get(f"{kind}_max"), Mapping) else {}
    if key in lo_map: value=max(float(lo_map[key]),value)
    if key in hi_map: value=min(float(hi_map[key]),value)
    return max(0,int(round(value)))


class CohortTxSupportMixin:
    def _ct_force(self, path: str) -> dict[str, Any]:
        force = deepcopy(self.read(path))
        # Cohort access can occur inside chronological causal settlement after
        # runtime.world_time has advanced to the due instant but before meta.time
        # is committed. Do not call the global chronology consistency accessor
        # merely to read an already-existing ledger. If an old/current-only force
        # genuinely needs baseline seeding, use the scheduler's exact runtime
        # frontier as provenance rather than manufacturing a second clock.
        ledger = force.get("cohort_ledger")
        has_cohorts = isinstance(ledger, Mapping) and isinstance(ledger.get("cohorts"), Mapping) and bool(ledger.get("cohorts"))
        at = None if has_cohorts else str(self.read("state/runtime.json").get("world_time") or "") or None
        ensure_cohort_ledger(force, at=at)
        if hasattr(self, "_seed_force_baselines"):
            self._seed_force_baselines(force)
        self.put(path, force)
        return force

    def _ct_formation(self, ref: str) -> tuple[str, dict[str, Any], str]:
        path, formation0 = self._load_formation(ref)
        formation = deepcopy(formation0)
        force_path = self.owner_path(str(formation["owner_force_ref"]))
        force = self._ct_force(force_path)
        ensure_formation_composition(force, formation)
        validate_cohort_ledger(force)
        self.put(force_path, force)
        self.put(path, formation)
        return path, formation, force_path

    @staticmethod
    def _ct_branch_id(force: Mapping[str, Any], cohort_id: str, formation_ref: str, evidence: str) -> str:
        owner = str(force.get("owner_id", "force"))
        digest = hashlib.sha256(f"{owner}|{cohort_id}|{formation_ref}|{evidence}".encode()).hexdigest()[:12]
        return f"cohort_{owner.replace('-', '_')}_training_{digest}"

    def _ct_isolate_training(self, force: dict[str, Any], formation: dict[str, Any], evidence: str) -> None:
        ensure_formation_composition(force, formation)
        ledger = force["cohort_ledger"]["cohorts"]
        ref = str(formation["formation_ref"])
        isolated: list[dict[str, Any]] = []
        for item in formation.get("cohort_composition", []):
            cid = str(item["cohort_id"])
            count = int(item["count"])
            cohort = ledger.get(cid)
            if not isinstance(cohort, MutableMapping):
                raise ValueError("formation references an unknown cohort")
            alloc = cohort.setdefault("allocated_by_formation", {})
            reserve = sum(int(v) for v in cohort.get("reserve_by_location", {}).values())
            other = sum(int(v) for key, v in alloc.items() if str(key) != ref)
            if reserve == 0 and other == 0:
                isolated.append({"cohort_id": cid, "count": count})
                continue
            if int(alloc.get(ref, 0)) != count:
                raise ValueError("formation cohort allocation mismatch before training")
            new_id = self._ct_branch_id(force, cid, ref, evidence)
            suffix = 2
            base = new_id
            while new_id in ledger:
                new_id = f"{base}_{suffix}"
                suffix += 1
            branch = deepcopy(cohort)
            branch["cohort_id"] = new_id
            branch["reserve_by_location"] = {}
            branch["allocated_by_formation"] = {ref: count}
            branch.setdefault("development_branches", []).append({"from_cohort_id": cid, "formation_ref": ref, "count": count, "evidence_ref": evidence})
            alloc.pop(ref, None)
            ledger[new_id] = branch
            isolated.append({"cohort_id": new_id, "count": count})
        formation["cohort_composition"] = isolated
        validate_cohort_ledger(force)

    def _ct_train_formation(self, ref: str, hours: float, evidence: str) -> None:
        path, formation0 = self._load_formation(ref)
        formation = deepcopy(formation0)
        force_path = self.owner_path(str(formation["owner_force_ref"]))
        force = self._ct_force(force_path)
        ensure_formation_composition(force, formation)
        self._ct_isolate_training(force, formation, evidence)
        profiles = self.read("game/data/mil/recruitment-cohort-profiles.json")
        rules = self.read("game/data/mechanics/training.json")
        regimen_name = "house_tang_max_sustainable" if str(force.get("owner_id")) in {"force_house_tang", "institution_sword_manor"} else "regular_army"
        regimen = profiles.get("training_regimens", {}).get(regimen_name, {})
        role_profiles = profiles.get("role_training_profiles", {})
        for item in formation.get("cohort_composition", []):
            cohort = force["cohort_ledger"]["cohorts"][str(item["cohort_id"])]
            role = str(cohort.get("role") or next(iter(formation.get("composition", {})), "line_infantry"))
            focus = role_profiles.get(role, {}) if isinstance(role_profiles, Mapping) else {}
            if cohort.get("attribute_means") or cohort.get("skill_means"):
                advance_cohort_training(
                    cohort,
                    deliberate_hours=float(hours),
                    role_exposure_hours=0.0,
                    skill_focuses=focus.get("skills", []) if isinstance(focus, Mapping) else [],
                    attribute_focuses=focus.get("attributes", []) if isinstance(focus, Mapping) else [],
                    training_rules=rules,
                    facility_grade=str(regimen.get("facility_grade", "adequate")),
                    equipment_grade=str(regimen.get("equipment_grade", "adequate")),
                    recovery_grade=str(regimen.get("recovery_grade", "adequate")),
                    evidence_ref=evidence,
                )
            else:
                cohort["verified_training_hours_per_person"] = round(float(cohort.get("verified_training_hours_per_person", 0.0)) + float(hours), 3)
        self.put(force_path, force)
        self.put(path, formation)

    def _ct_materialize_from_cohort(self, force: dict[str, Any], role: str, location: str, person_ref: str, person: dict[str, Any]) -> None:
        rows = []
        for cid, cohort in force["cohort_ledger"]["cohorts"].items():
            if str(cohort.get("role")) == role and int(cohort.get("reserve_by_location", {}).get(location, 0)) > 0:
                rows.append((str(cohort.get("origin", {}).get("recruited_at") or ""), str(cid), cohort))
        rows.sort(key=lambda x: (x[0], x[1]))
        if not rows:
            raise ValueError("no conserved cohort body available for exact materialization")
        _, cid, cohort = rows[0]
        reserve = cohort.setdefault("reserve_by_location", {})
        reserve[location] = int(reserve.get(location, 0)) - 1
        if reserve[location] == 0:
            reserve.pop(location, None)
        cohort.setdefault("materialization_history", []).append({"person_ref": person_ref, "count": 1})
        if cohort.get("attribute_means") and not person.get("attributes"):
            means=cohort.get("attribute_means", {}); sds=cohort.get("attribute_sd", {})
            person["attributes"] = {key: _sample_metric(cohort, person_ref=person_ref, kind="attribute", key=key, mean=float(means.get(key, 50.0)), sd=float(sds.get(key, 8.0))) for key in ATTRIBUTE_ORDER}
        if cohort.get("skill_means") and not person.get("skills"):
            means=cohort.get("skill_means", {}); sds=cohort.get("skill_sd", {})
            person["skills"] = {key: _sample_metric(cohort, person_ref=person_ref, kind="skill", key=key, mean=float(means.get(key, 0.0)), sd=float(sds.get(key, 4.0))) for key in SKILL_ORDER}
        if cohort.get("aptitude_means"):
            person["aptitude"] = {str(k): int(round(float(v))) for k, v in cohort.get("aptitude_means", {}).items()}
        person["source_cohort_ref"] = cid
        person["source_cohort_provenance"] = deepcopy(cohort.get("origin", {}))

    def _ct_materialize_from_formation(
        self,
        force: dict[str, Any],
        formation: dict[str, Any],
        *,
        role: str,
        person_ref: str,
        person: dict[str, Any],
    ) -> str:
        """Convert one anonymous allocated cohort slot into one represented person."""
        ensure_formation_composition(force, formation)
        ledger = force["cohort_ledger"]["cohorts"]
        fref = str(formation.get("formation_ref"))
        candidates: list[tuple[str, MutableMapping[str, Any]]] = []
        for item in formation.get("cohort_composition", []):
            if not isinstance(item, Mapping) or int(item.get("count", 0)) <= 0:
                continue
            cid = str(item.get("cohort_id"))
            cohort = ledger.get(cid)
            if isinstance(cohort, MutableMapping) and (not role or str(cohort.get("role")) == role):
                candidates.append((cid, cohort))
        candidates.sort(key=lambda row: (str(row[1].get("origin", {}).get("recruited_at") or ""), row[0]))
        if not candidates:
            raise ValueError("no conserved cohort body available in formation for materialization")
        cid, cohort = candidates[0]
        allocated = cohort.setdefault("allocated_by_formation", {})
        held = int(allocated.get(fref, 0))
        if held <= 0:
            raise ValueError("materialization cohort has no allocated body in formation")
        if held == 1:
            allocated.pop(fref, None)
        else:
            allocated[fref] = held - 1
        new_comp = []
        consumed = False
        for item in formation.get("cohort_composition", []):
            if not isinstance(item, Mapping):
                continue
            row = dict(item)
            if not consumed and str(row.get("cohort_id")) == cid:
                row["count"] = int(row.get("count", 0)) - 1
                consumed = True
            if int(row.get("count", 0)) > 0:
                new_comp.append(row)
        formation["cohort_composition"] = new_comp
        cohort.setdefault("materialization_history", []).append({"person_ref": person_ref, "count": 1, "formation_ref": fref})
        # Reuse deterministic cohort-to-person sampling without consuming a reserve slot.
        if cohort.get("attribute_means") and not person.get("attributes"):
            means=cohort.get("attribute_means", {}); sds=cohort.get("attribute_sd", {})
            person["attributes"] = {key: _sample_metric(cohort, person_ref=person_ref, kind="attribute", key=key, mean=float(means.get(key, 50.0)), sd=float(sds.get(key, 8.0))) for key in ATTRIBUTE_ORDER}
        if cohort.get("skill_means") and not person.get("skills"):
            means=cohort.get("skill_means", {}); sds=cohort.get("skill_sd", {})
            person["skills"] = {key: _sample_metric(cohort, person_ref=person_ref, kind="skill", key=key, mean=float(means.get(key, 0.0)), sd=float(sds.get(key, 4.0))) for key in SKILL_ORDER}
        if cohort.get("aptitude_means"):
            person["aptitude"] = {str(k): int(round(float(v))) for k, v in cohort.get("aptitude_means", {}).items()}
        person["source_cohort_ref"] = cid
        person["source_cohort_provenance"] = deepcopy(cohort.get("origin", {}))
        return cid


__all__ = ["CohortTxSupportMixin"]
