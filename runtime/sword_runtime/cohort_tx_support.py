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
    PROFESSIONAL_SKILLS,
    cohort_merged_skill_means,
    ensure_cohort_ledger,
    ensure_formation_composition,
    cohort_spread_value,
    stable_fraction,
    validate_cohort_ledger,
)
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_instructors import exact_person_drill_access, instructor_contexts_for_program
from sword_runtime.training_facilities import training_environment
from sword_runtime.training_programs import (
    formation_training_ref_for_role,
    REGISTRY_PATH as TRAINING_PROGRAM_REGISTRY_PATH,
    resolve_program_ref,
    formation_drill_access,
    settle_cohort_program,
    settle_exact_program,
    settle_person_lite_program,
)

_COMMAND_PERSON_INDEX_PATH = "state/cmd/command-personnel.json"


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
        # common deterministic latent component. This prevents implausibly
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


def project_person_lite_stats(
    cohort: Mapping[str, Any],
    person_ref: str,
    *,
    command_rank: str | None = None,
    loadout_id: str | None = None,
) -> dict[str, Any]:
    """Deterministically project one already-conserved person-lite body.

    A 1,000/500 commander is selected for a command billet rather than sampled as
    an arbitrary rank-and-file soldier. Billet selection raises only command and
    actual-loadout competencies to the current command standard; unrelated weapon
    skills remain secondary. This changes representation, not manpower or elapsed
    training.
    """
    attrs = cohort.get("attribute_means", {}) if isinstance(cohort.get("attribute_means"), Mapping) else {}
    skills = cohort.get("skill_means", {}) if isinstance(cohort.get("skill_means"), Mapping) else {}
    professional_skills = cohort.get("professional_skill_means", {}) if isinstance(cohort.get("professional_skill_means"), Mapping) else {}
    projected = {
        "attributes": {
            key: _sample_metric(cohort, person_ref=person_ref, kind="attribute", key=key, mean=float(attrs.get(key, 50.0)), sd=cohort_spread_value(cohort, "attribute", key, 8.0))
            for key in ATTRIBUTE_ORDER
        } if attrs else {},
        "skills": {
            key: _sample_metric(cohort, person_ref=person_ref, kind="skill", key=key, mean=float(skills.get(key, 0.0)), sd=cohort_spread_value(cohort, "skill", key, 4.0))
            for key in SKILL_ORDER
        } if skills else {},
        "professional_skills": {
            key: _sample_metric(cohort, person_ref=person_ref, kind="skill", key=key, mean=float(professional_skills.get(key, 0.0)), sd=cohort_spread_value(cohort, "skill", key, 4.0))
            for key in PROFESSIONAL_SKILLS if key in professional_skills and float(professional_skills.get(key, 0.0)) != 0.0
        },
        "aptitude": {str(key): int(round(float(value))) for key, value in cohort.get("aptitude_means", {}).items()} if isinstance(cohort.get("aptitude_means"), Mapping) else {},
    }
    rank = str(command_rank or "")
    if rank in {"internal_1000_commander", "1000_commander"}:
        command_sigma = 2.5
        loadout_sigma = 1.0
        attribute_sigma = 1.5
    elif rank in {"internal_500_commander", "500_commander"}:
        command_sigma = 2.0
        loadout_sigma = 0.75
        attribute_sigma = 1.0
    elif rank in {"internal_100_commander", "100_commander"}:
        command_sigma = 1.5
        loadout_sigma = 0.5
        attribute_sigma = 0.75
    else:
        return projected

    out_skills = projected["skills"]
    out_attrs = projected["attributes"]
    command_skills = {
        "Formation Command", "Leadership", "Tactics", "Strategy", "Logistics",
        "Formation Fighting",
    }
    command_attrs = {"Awareness", "Composure", "Coordination", "Intelligence", "Presence"}
    loadout_key = str(loadout_id or "").lower()
    mounted = any(token in loadout_key for token in ("cavalry", "mounted"))
    loadout_skills = {"Polearms", "Shield", "Sword", "Bow", "Formation Fighting"}
    if mounted:
        loadout_skills.add("Riding")

    # Command selection is relative to the actual source cohort. A billet selects
    # unusually suitable members of that rank or troop type; it does not grant
    # free veteran capability detached from the cohort they came from.
    for key in command_skills:
        if key not in out_skills:
            continue
        mean = float(skills.get(key, 0.0))
        sd = cohort_spread_value(cohort, "skill", key, 0.0)
        floor = int(round(mean + command_sigma * sd))
        out_skills[key] = max(int(out_skills.get(key, 0)), floor)
    for key in loadout_skills:
        if key not in out_skills:
            continue
        mean = float(skills.get(key, 0.0))
        sd = cohort_spread_value(cohort, "skill", key, 0.0)
        floor = int(round(mean + loadout_sigma * sd))
        out_skills[key] = max(int(out_skills.get(key, 0)), floor)
    for key in command_attrs:
        if key not in out_attrs:
            continue
        mean = float(attrs.get(key, 0.0))
        sd = cohort_spread_value(cohort, "attribute", key, 0.0)
        floor = int(round(mean + attribute_sigma * sd))
        out_attrs[key] = max(int(out_attrs.get(key, 0)), floor)

    # Infantry commanders keep whatever ordinary Riding experience their source
    # cohort actually has, but the command billet does not inflate it. Likewise,
    # unrelated weapon families remain bounded around the source cohort instead
    # of becoming accidental specialties. Lance is handled as Polearms by the combat
    # weapon-family mapping.
    primary_keys = ["Polearms", "Sword", "Shield", "Bow"] + (["Riding"] if mounted else [])
    primary_values = [int(out_skills[key]) for key in primary_keys if key in out_skills]
    secondary_role_ceiling = int(round((sum(primary_values) / len(primary_values)) * 0.45)) if primary_values else 0
    if not mounted and "Riding" in out_skills:
        mean = float(skills.get("Riding", 0.0))
        sd = cohort_spread_value(cohort, "skill", "Riding", 0.0)
        out_skills["Riding"] = min(
            int(out_skills["Riding"]),
            int(round(mean + sd)),
            secondary_role_ceiling,
        )
    for key in {"Heavy Weapons", "Crossbow", "Sword", "Polearms"}:
        if key not in out_skills:
            continue
        mean = float(skills.get(key, 0.0))
        sd = cohort_spread_value(cohort, "skill", key, 0.0)
        ceiling = min(int(round(mean + sd)), secondary_role_ceiling)
        out_skills[key] = min(int(out_skills[key]), ceiling)
    return projected


class CohortTxSupportMixin:
    def _ct_force(self, path: str) -> dict[str, Any]:
        staged = getattr(self, "_writes", {})
        # First touch isolates the owner from the read cache. Later touches in the
        # same command can safely reuse that already-isolated staged image instead
        # of cloning a potentially large cohort ledger again.
        force = staged[path] if isinstance(staged, dict) and path in staged else deepcopy(self.read(path))
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
        if hasattr(self, "_seed_standing_force_capability"):
            self._seed_standing_force_capability(force)
        self.put(path, force)
        return force

    def _ct_formation(self, ref: str) -> tuple[str, dict[str, Any], str]:
        path, formation0 = self._load_formation(ref)
        staged = getattr(self, "_writes", {})
        formation = staged[path] if isinstance(staged, dict) and path in staged else deepcopy(formation0)
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
            # This branch isolates only the anonymous fighting slice assigned to
            # the formation so its battle/training development can diverge. Unit
            # command bodies are separate external personnel allocations owned by
            # the source cohort. Copying them into the branch duplicates conserved
            # people while the source still retains the same command allocation.
            branch["allocated_external_by_formation"] = {}
            # The branch itself is the current authoritative capability slice. Its
            # ancestry/evidence does not affect later mechanics, so do not copy an
            # append-only training lineage into hot force state.
            branch.pop("development_branches", None)
            alloc.pop(ref, None)
            ledger[new_id] = branch
            isolated.append({"cohort_id": new_id, "count": count})
        formation["cohort_composition"] = isolated
        validate_cohort_ledger(force)

    def _ct_command_refs(self, formation: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
        """Return person-lite and exact command refs with scale-aware role labels.

        Representation is owned by the routed person record, never by identity
        syntax. A promoted full character may lawfully retain an ``officer.*``
        ref, while migration/fixture data can also contain unusual refs.
        """
        lite: dict[str, str] = {}
        exact: dict[str, str] = {}

        def representation(ref: str) -> str | None:
            try:
                path = self.owner_path(ref)
                row = self.read(path)
            except (FileNotFoundError, KeyError, TypeError, ValueError):
                path = None
                row = None
            if isinstance(row, Mapping):
                schema = str(row.get("schema", ""))
                if schema == "person-lite":
                    return "lite"
                if schema in {"sab_character", "sword-materialized-person"}:
                    return "exact"
            if isinstance(path, str) and (path == "state/player.json" or path.startswith("state/char/")):
                return "exact"
            return None

        def add(ref: Any, role: str) -> None:
            if not isinstance(ref, str) or not ref:
                return
            kind = representation(ref)
            if kind == "exact":
                exact.setdefault(ref, role)
            elif kind == "lite":
                lite.setdefault(ref, role)
            elif ref.startswith("char_"):
                # Fail-compatible for legacy detached fixtures whose exact owner
                # is intentionally absent from the bounded test surface.
                exact.setdefault(ref, role)
            else:
                # Never infer Person Lite from a non-character-looking ID.  A
                # missing owner is corrupt routing state, not a compressed
                # officer.  Production startup/transaction integrity rejects
                # this condition; keeping it out of the projection here also
                # prevents a stale embedded ref from becoming a phantom trainer
                # or command contributor in disposable/partial readers.
                raise ValueError(f"command person has no authoritative owner: {ref}")

        add(formation.get("commander_ref"), "persistent_unit_commander")
        saved_internal = formation.get("embedded_person_refs", []) if isinstance(formation.get("embedded_person_refs"), list) else []
        for ref in saved_internal:
            text = str(ref)
            role = (
                "internal_1000_commander" if ".1000." in text
                else "internal_500_commander" if ".500." in text
                else "internal_100_commander" if ".100." in text
                else "internal_commander"
            )
            add(ref, role)
        return lite, exact

    def _ct_train_person_lite_officers(
        self,
        force: dict[str, Any],
        formation: dict[str, Any],
        *,
        formation_ref: str,
        hours: float,
        evidence: str,
        training_rules: Mapping[str, Any],
        regimen: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Train already-materialized person-lite command officers in place.

        The command-personnel index is routing only. A missing logical officer
        route is an integrity defect; training must never manufacture a parallel
        command-person record as a fallback.
        """
        lite_refs, _exact_refs = self._ct_command_refs(formation)
        if not lite_refs or hours <= 0:
            return []
        index = self.read(_COMMAND_PERSON_INDEX_PATH)
        record_index = index.get("record_index", {}) if isinstance(index, Mapping) else {}
        results: list[dict[str, Any]] = []
        current = CampaignTime.parse(str(self.read("state/runtime.json").get("world_time")))
        window_start = current.add_seconds(-max(0, int(round(float(hours) * 3600.0))))
        for person_ref, role_label in sorted(lite_refs.items()):
            path = record_index.get(person_ref) if isinstance(record_index, Mapping) else None
            if not isinstance(path, str) or not path:
                results.append({"person_ref": person_ref, "role": role_label, "trained": False, "reason": "missing_person_lite_route"})
                continue
            record = deepcopy(self.read(path))
            if str(record.get("schema", "")) != "person-lite":
                results.append({"person_ref": person_ref, "role": role_label, "trained": False, "reason": "invalid_person_lite_owner"})
                continue
            registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
            program_ref = resolve_program_ref(
                registry,
                role="command_personnel",
                training_ref=formation_training_ref_for_role(formation, "command_personnel"),
                person=record,
            )
            officer_evidence = f"{evidence}:officer:{person_ref}"
            instructor_contexts = instructor_contexts_for_program(
                self, registry=registry, training_rules=training_rules, program_ref=program_ref,
                trainee_skills=(record.get("stats", {}).get("skills", {}) if isinstance(record.get("stats"), Mapping) else {}),
                student_count=1, location_ref=str(formation.get("location_ref", "")), formation=formation, trainee_ref=person_ref,
                scheduled_hours=float(hours), window_start=str(window_start), window_end=str(current),
                evidence_ref=officer_evidence, reserve_duty=True, hierarchical_delivery=True,
            )
            drill_access = exact_person_drill_access(self, registry=registry, program_ref=program_ref, person=record)
            trained = settle_person_lite_program(
                record,
                registry=registry,
                program_ref=program_ref,
                deliberate_hours=float(hours),
                role_exposure_hours=0.0,
                training_rules=training_rules,
                facility_grade=str(regimen.get("facility_grade", "home_garrison")),
                equipment_grade=str(regimen.get("equipment_grade", "adequate")),
                recovery_grade=str(regimen.get("recovery_grade", "adequate")),
                evidence_ref=officer_evidence,
                instructor_context_by_drill=instructor_contexts,
                drill_access=drill_access,
                time_window_start=str(window_start), time_window_end=str(current),
            )
            if trained.get("trained"):
                dev = record.setdefault("development_state", {})
                last_training = dev.get("last_training") if isinstance(dev.get("last_training"), Mapping) else {}
                dev["last_training"] = {**dict(last_training), "formation_ref": formation_ref}
                self.put(path, record)
            results.append({"person_ref": person_ref, "role": role_label, **trained})
        return results

    def _ct_train_exact_command_staff(
        self,
        formation: Mapping[str, Any],
        *,
        formation_ref: str,
        hours: float,
        evidence: str,
        training_rules: Mapping[str, Any],
        regimen: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Apply delegated standing drill to co-located exact command staff only."""
        if not evidence.startswith("standing_training_settle:"):
            return []
        _lite_refs, exact_refs = self._ct_command_refs(formation)
        whole = max(0, int(float(hours) + 1e-9))
        if not exact_refs or whole < 1:
            return []
        session_rules = self.read("game/data/mechanics/training-session.json")
        current = CampaignTime.parse(str(self.read("state/runtime.json").get("world_time")))
        window_start = current.add_seconds(-max(0, int(round(float(hours) * 3600.0))))
        formation_location = str(formation.get("location_ref", ""))
        results: list[dict[str, Any]] = []
        for person_ref, role_label in sorted(exact_refs.items()):
            if person_ref == getattr(self, "PLAYER_ACTOR", "char_tang_wei"):
                # Wei's own training remains player-owned and uses his saved standing plan.
                continue
            try:
                path = self.owner_path(person_ref)
                person = deepcopy(self.read(path))
            except Exception:
                results.append({"person_ref": person_ref, "trained": False, "reason": "missing_exact_person_owner"})
                continue
            location = str(person.get("current_location", person.get("location", person.get("location_ref", ""))))
            if location != formation_location:
                results.append({"person_ref": person_ref, "trained": False, "reason": "not_colocated"})
                continue
            health = person.get("health", person.get("health_status", "healthy"))
            if isinstance(health, Mapping):
                health = health.get("status", "healthy")
            if str(health).lower() not in {"healthy", "fit", "stable"}:
                results.append({"person_ref": person_ref, "trained": False, "reason": "not_fit"})
                continue
            registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
            program_ref = resolve_program_ref(
                registry,
                role="command_personnel",
                training_ref=formation_training_ref_for_role(formation, "command_personnel"),
                person=person,
            )
            staff_evidence = f"{evidence}:exact_staff:{person_ref}"
            instructor_contexts = instructor_contexts_for_program(
                self, registry=registry, training_rules=training_rules, program_ref=program_ref,
                trainee_skills=(person.get("skills", {}) if isinstance(person.get("skills"), Mapping) else {}),
                student_count=1, location_ref=formation_location, formation=formation, trainee_ref=person_ref,
                scheduled_hours=float(whole), window_start=str(window_start), window_end=str(current),
                evidence_ref=staff_evidence, reserve_duty=True, hierarchical_delivery=True,
            )
            drill_access = exact_person_drill_access(self, registry=registry, program_ref=program_ref, person=person)
            development = settle_exact_program(
                person,
                registry=registry,
                program_ref=program_ref,
                hours=whole,
                at=current,
                training_rules=training_rules,
                session_rules=session_rules,
                facility_grade=str(regimen.get("facility_grade", "home_garrison")),
                equipment_grade=str(regimen.get("equipment_grade", "adequate")),
                recovery_grade=str(regimen.get("recovery_grade", "adequate")),
                feedback_grade=str(regimen.get("feedback_grade", "ordinary")),
                cursor_key="formation_deterministic_training_cursor",
                instructor_context_by_drill=instructor_contexts,
                drill_access=drill_access,
                time_window_start=str(window_start), time_window_end=str(current),
                time_evidence_ref=staff_evidence,
            )
            selected = [row.get("skill") for row in development.get("development", []) if isinstance(row, Mapping)]
            dev = person.setdefault("development_state", {})
            last_training = dev.get("last_training") if isinstance(dev.get("last_training"), Mapping) else {}
            dev["last_training"] = {
                **dict(last_training),
                "completed_at": str(current),
                "formation_ref": formation_ref,
            }
            self.put(path, person)
            results.append({"person_ref": person_ref, "trained": True, "program_ref": program_ref, "focuses": selected, "development": development})
        return results

    def _ct_train_formation(self, ref: str, hours: float, evidence: str) -> None:
        path, formation0 = self._load_formation(ref)
        formation = deepcopy(formation0)
        force_path = self.owner_path(str(formation["owner_force_ref"]))
        force = self._ct_force(force_path)
        ensure_formation_composition(force, formation)
        self._ct_isolate_training(force, formation, evidence)
        profiles = self.read("game/data/mil/recruitment-cohort-profiles.json")
        rules = self.read("game/data/mechanics/training.json")
        regimen_name = "house_tang_max_sustainable" if str(force.get("owner_id")) in {"force_house_tang"} else "regular_army"
        regimen = profiles.get("training_regimens", {}).get(regimen_name, {})
        environment = training_environment(
            self,
            location_ref=str(formation.get("location_ref", "")),
            simultaneous_trainees=max(1, int(formation.get("personnel", 0))),
        )
        effective_hours = max(0.0, float(hours) * float(environment.get("capacity_factor", 0.0)))
        regimen = dict(regimen) if isinstance(regimen, Mapping) else {}
        regimen["facility_grade"] = str(environment.get("facility_grade", "none"))
        role_profiles = profiles.get("role_training_profiles", {})
        current = CampaignTime.parse(str(self.read("state/runtime.json").get("world_time")))
        window_start = current.add_seconds(-max(0, int(round(float(effective_hours) * 3600.0))))
        for item in formation.get("cohort_composition", []):
            cohort = force["cohort_ledger"]["cohorts"][str(item["cohort_id"])]
            role = str(cohort.get("role") or next(iter(formation.get("composition", {})), "line_infantry"))
            role_profile = role_profiles.get(role, {}) if isinstance(role_profiles, Mapping) else {}
            if cohort.get("attribute_means") or cohort.get("skill_means"):
                registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
                program_ref = resolve_program_ref(
                    registry,
                    role=role,
                    training_ref=formation_training_ref_for_role(formation, role),
                )
                drill_access = formation_drill_access(
                    registry,
                    program_ref,
                    formation,
                    role=role,
                    runtime=self,
                )
                cohort_evidence = f"{evidence}:cohort:{item.get('cohort_id', role)}"
                instructor_contexts = instructor_contexts_for_program(
                    self, registry=registry, training_rules=rules, program_ref=program_ref,
                    trainee_skills=cohort_merged_skill_means(cohort),
                    student_count=max(1, int(item.get("count", 0) or 0)), location_ref=str(formation.get("location_ref", "")),
                    formation=formation,
                    scheduled_hours=float(effective_hours), window_start=str(window_start), window_end=str(current),
                    evidence_ref=cohort_evidence, reserve_duty=True,
                )
                settle_cohort_program(
                    cohort,
                    registry=registry,
                    program_ref=program_ref,
                    deliberate_hours=float(effective_hours),
                    role_exposure_hours=0.0,
                    training_rules=rules,
                    facility_grade=str(regimen.get("facility_grade", "home_garrison")),
                    equipment_grade=str(regimen.get("equipment_grade", "adequate")),
                    recovery_grade=str(regimen.get("recovery_grade", "adequate")),
                    evidence_ref=cohort_evidence,
                    drill_access=drill_access,
                    instructor_context_by_drill=instructor_contexts,
                )
            else:
                cohort["verified_training_hours_per_person"] = round(float(cohort.get("verified_training_hours_per_person", 0.0)) + float(effective_hours), 3)
        officer_results = self._ct_train_person_lite_officers(
            force,
            formation,
            formation_ref=ref,
            hours=float(effective_hours),
            evidence=evidence,
            training_rules=rules,
            regimen=regimen if isinstance(regimen, Mapping) else {},
        )
        exact_results = self._ct_train_exact_command_staff(
            formation,
            formation_ref=ref,
            hours=float(effective_hours),
            evidence=evidence,
            training_rules=rules,
            regimen=regimen if isinstance(regimen, Mapping) else {},
        )
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
        if cohort.get("attribute_means") and not person.get("attributes"):
            means=cohort.get("attribute_means", {})
            person["attributes"] = {key: _sample_metric(cohort, person_ref=person_ref, kind="attribute", key=key, mean=float(means.get(key, 50.0)), sd=cohort_spread_value(cohort, "attribute", key, 8.0)) for key in ATTRIBUTE_ORDER}
        if cohort.get("skill_means") and not person.get("skills"):
            means=cohort.get("skill_means", {})
            person["skills"] = {key: _sample_metric(cohort, person_ref=person_ref, kind="skill", key=key, mean=float(means.get(key, 0.0)), sd=cohort_spread_value(cohort, "skill", key, 4.0)) for key in SKILL_ORDER}
        professional_means = cohort.get("professional_skill_means", {}) if isinstance(cohort.get("professional_skill_means"), Mapping) else {}
        if professional_means and not person.get("professional_skills"):
            person["professional_skills"] = {
                key: _sample_metric(cohort, person_ref=person_ref, kind="skill", key=key, mean=float(professional_means.get(key, 0.0)), sd=cohort_spread_value(cohort, "skill", key, 4.0))
                for key in PROFESSIONAL_SKILLS if key in professional_means and float(professional_means.get(key, 0.0)) != 0.0
            }
        if cohort.get("aptitude_means") and not person.get("aptitude"):
            person["aptitude"] = {str(k): int(round(float(v))) for k, v in cohort.get("aptitude_means", {}).items()}
        person["source_cohort_ref"] = cid

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
        # Reuse deterministic cohort-to-person sampling without consuming a reserve slot.
        if cohort.get("attribute_means") and not person.get("attributes"):
            means=cohort.get("attribute_means", {})
            person["attributes"] = {key: _sample_metric(cohort, person_ref=person_ref, kind="attribute", key=key, mean=float(means.get(key, 50.0)), sd=cohort_spread_value(cohort, "attribute", key, 8.0)) for key in ATTRIBUTE_ORDER}
        if cohort.get("skill_means") and not person.get("skills"):
            means=cohort.get("skill_means", {})
            person["skills"] = {key: _sample_metric(cohort, person_ref=person_ref, kind="skill", key=key, mean=float(means.get(key, 0.0)), sd=cohort_spread_value(cohort, "skill", key, 4.0)) for key in SKILL_ORDER}
        professional_means = cohort.get("professional_skill_means", {}) if isinstance(cohort.get("professional_skill_means"), Mapping) else {}
        if professional_means and not person.get("professional_skills"):
            person["professional_skills"] = {
                key: _sample_metric(cohort, person_ref=person_ref, kind="skill", key=key, mean=float(professional_means.get(key, 0.0)), sd=cohort_spread_value(cohort, "skill", key, 4.0))
                for key in PROFESSIONAL_SKILLS if key in professional_means and float(professional_means.get(key, 0.0)) != 0.0
            }
        if cohort.get("aptitude_means"):
            person["aptitude"] = {str(k): int(round(float(v))) for k,v in cohort.get("aptitude_means", {}).items()}
        person["source_cohort_ref"] = cid
        return cid


__all__ = ["CohortTxSupportMixin", "project_person_lite_stats"]
