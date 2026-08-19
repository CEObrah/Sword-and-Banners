"""Routed offscreen named-person development for production living-world play.

Named people retain their annual person hosts for mortality, family, and other
life-course settlement. Routine standing activity uses bounded recurring scheduler shards over explicit
routed-person lists so campaign scale never becomes a lifetime person ceiling. The router discovers only
exact people already represented by the scheduler's person-host registry; it
never scans character directories and never gives the player autonomous training.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_event_planner import CampaignEventPlayerGroupActionPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_rates import resolved_activity_regimen, verified_activity_hours_per_cycle
from sword_runtime.fatigue import RULES_PATH as FATIGUE_RULES_PATH, settle_person_idle_fatigue
from sword_runtime.training_instructors import exact_person_drill_access, instructor_contexts_for_program
from sword_runtime.training_promotion import exact_promotion_facts
from sword_runtime.training_programs import (
    REGISTRY_PATH as TRAINING_PROGRAM_REGISTRY_PATH,
    drill_record,
    program_record,
    resolve_program_ref,
    settle_exact_program,
    settle_person_lite_program,
)

_RUNTIME_PATH = "state/runtime.json"
_PROFILES_PATH = "game/data/mil/recruitment-cohort-profiles.json"
_SESSION_RULES_PATH = "game/data/mechanics/training-session.json"
_COMMAND_PERSONNEL_INDEX = "state/cmd/command-personnel.json"
_ACTIVITY_HOST_ID = "host_named_person_activity"
_ACTIVITY_EVENT_ID = "event_host_named_person_activity_review"
_ACTIVITY_CADENCE_SECONDS = 30 * 86400
_ACTIVITY_DEFAULT_VERIFIED_HOURS = 48
_ACTIVITY_HISTORY_LIMIT = 24
_ACTIVITY_FATIGUE_BLOCK = 80
_ACTIVITY_SHARD_SIZE = 512
_ELIGIBLE_HEALTH = frozenset({"healthy", "fit", "stable"})


class ActivityCampaignEventPlanner(CampaignEventPlayerGroupActionPlanner):
    """Production planner with bounded exact-person standing-activity catch-up."""

    @staticmethod
    def _person_skills(person: Mapping[str, Any]) -> Mapping[str, Any]:
        skills = person.get("skills")
        if isinstance(skills, Mapping):
            return skills
        stats = person.get("stats")
        if isinstance(stats, Mapping) and isinstance(stats.get("skills"), Mapping):
            return stats["skills"]
        return {}

    def _activity_training_context(
        self, person: Mapping[str, Any], contract: Mapping[str, Any]
    ) -> tuple[str, str, str]:
        """Resolve program, formation training ref, and dominant role from saved owners."""
        registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
        training_ref = ""
        role = "command_personnel" if str(person.get("schema", "")) == "person-lite" else ""
        assignment = person.get("command_assignment") if isinstance(person.get("command_assignment"), Mapping) else {}
        formation_ref = str(assignment.get("formation_ref", "")).strip()
        if formation_ref:
            try:
                _path, formation = self._load_formation(formation_ref)
            except (KeyError, ValueError, FileNotFoundError):
                formation = {}
            if isinstance(formation, Mapping):
                training_ref = str(formation.get("training_ref", "") or "")
                composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
                if composition:
                    role = str(max(composition.items(), key=lambda row: (int(row[1]), str(row[0])))[0])
        explicit_program = str(contract.get("training_program_ref", "") or "")
        program_ref = resolve_program_ref(
            registry,
            role=role or None,
            training_ref=training_ref or None,
            person=person,
            explicit_program_ref=explicit_program or None,
        )
        return program_ref, training_ref, role

    def _activity_focuses(self, person: Mapping[str, Any], contract: Mapping[str, Any]) -> list[str]:
        """Return the registered program's trainable saved skills for routing only."""
        registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
        program_ref, _training_ref, _role = self._activity_training_context(person, contract)
        skills = self._person_skills(person)
        focuses: list[str] = []
        seen: set[str] = set()
        for row in program_record(registry, program_ref).get("rotation", []):
            if not isinstance(row, Mapping):
                continue
            drill = drill_record(registry, str(row.get("drill_ref", "")))
            for skill in drill.get("skills", []):
                name = str(skill)
                if name in skills and name not in seen:
                    seen.add(name)
                    focuses.append(name)
        return focuses

    @classmethod
    def _derived_activity_contract(cls, person: Mapping[str, Any]) -> dict[str, Any] | None:
        """Derive routine development from a saved role, never current stat ranking."""
        schema = str(person.get("schema", ""))
        if schema == "person-lite":
            role_text = " ".join(str(person.get(k, "")) for k in ("role", "rank", "current_goal")).strip()
        else:
            role_text = " ".join(str(person.get(k, "")) for k in ("role_archetype", "role", "rank")).strip()
        if not role_text:
            return None
        military = (
            schema == "person-lite"
            or isinstance(person.get("command_assignment"), Mapping)
            or any(token in role_text.lower() for token in (
                "general", "commander", "warrior", "archer", "scout", "assassin",
                "officer", "brute", "martial", "marshal", "guard", "cavalry",
            ))
        )
        return {
            "mode": "standing_role_training",
            "autonomous_enabled": True,
            "training_regimen_ref": "regular_army" if military else "civilian_skilled",
            "growth_rule": "verified elapsed hours settle only through the finite deterministic training-program registry selected from saved role/billet; current stat ranking and prose-created focuses are non-authoritative",
            "derived_activity_contract": True,
        }

    @classmethod
    def _effective_activity_contract(cls, person: Mapping[str, Any]) -> Mapping[str, Any] | None:
        explicit = person.get("activity_contract")
        if isinstance(explicit, Mapping):
            return explicit
        return cls._derived_activity_contract(person)

    def _activity_person(self, person_ref: str) -> tuple[str, dict[str, Any]]:
        try:
            return self._exact_person(person_ref, active=False)
        except ValueError:
            path = self.owner_path(person_ref)
            person = copy.deepcopy(self.read(path))
            if str(person.get("schema", "")) != "person-lite":
                raise ValueError(f"{person_ref} is not an activity-eligible saved person")
            return path, person

    def _person_lite_force_owned(self, person_ref: str, person: Mapping[str, Any]) -> bool:
        owner_ref = str(person.get("owner", ""))
        if not owner_ref:
            return False
        try:
            owner_path = self.owner_path(owner_ref)
            owner = self.read(owner_path)
        except (KeyError, ValueError, FileNotFoundError):
            return False
        materialized = owner.get("materialized_people") if isinstance(owner, Mapping) else None
        return isinstance(materialized, Mapping) and person_ref in materialized

    @staticmethod
    def _activity_shard_ids(index: int) -> tuple[str, str]:
        if index <= 0:
            return _ACTIVITY_HOST_ID, _ACTIVITY_EVENT_ID
        suffix = f"{index + 1:04d}"
        return f"{_ACTIVITY_HOST_ID}_{suffix}", f"{_ACTIVITY_EVENT_ID}_{suffix}"

    @classmethod
    def _activity_hosts(cls, hosts: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        rows: list[tuple[str, dict[str, Any]]] = []
        for host_id, host in hosts.items():
            if not isinstance(host_id, str) or not isinstance(host, dict):
                continue
            if host.get("kind") != "person_activity":
                continue
            if host_id != _ACTIVITY_HOST_ID and not host_id.startswith(_ACTIVITY_HOST_ID + "_"):
                continue
            rows.append((host_id, host))
        def key(row: tuple[str, dict[str, Any]]) -> tuple[int, str]:
            host_id = row[0]
            if host_id == _ACTIVITY_HOST_ID:
                return (0, host_id)
            tail = host_id.rsplit("_", 1)[-1]
            return (int(tail) if tail.isdigit() else 10**9, host_id)
        return sorted(rows, key=key)

    @classmethod
    def _ensure_activity_shard(
        cls,
        hosts: dict[str, Any],
        events: list[Any],
        *,
        index: int,
        now: CampaignTime,
        now_text: str,
    ) -> dict[str, Any]:
        host_id, event_id = cls._activity_shard_ids(index)
        host = hosts.get(host_id)
        if host is None:
            first_due = now.add_seconds(_ACTIVITY_CADENCE_SECONDS)
            host = {
                "kind": "person_activity",
                "owner_ref": "runtime_named_person_activity",
                "route_shard": index,
                "next_due": str(first_due),
                "recurrence_seconds": _ACTIVITY_CADENCE_SECONDS,
                "resolved_through": now_text,
                "safe_through": str(first_due.add_seconds(-1)),
                "routed_person_refs": [],
            }
            hosts[host_id] = host
            events.append({
                "due_at": str(first_due),
                "event_id": event_id,
                "kind": "person_activity_review",
                "priority": 96,
                "target_host": host_id,
            })
        if not isinstance(host, dict) or host.get("kind") != "person_activity":
            raise ValueError("named-person activity host is invalid")
        refs = host.setdefault("routed_person_refs", [])
        if not isinstance(refs, list):
            raise ValueError("named-person activity route list is invalid")
        if len(refs) > _ACTIVITY_SHARD_SIZE:
            raise ValueError("named-person activity shard exceeds its routing page size")
        return host

    def _ensure_activity_routes(self) -> None:
        """Reconcile scheduler-known standing-activity people through bounded hosts.

        The scheduler host registry is already the causal routing surface. Exact
        people are reclassified from their current saved role/contract each scan so
        a role or regimen change cannot leave a permanent stale cache. Activity
        routes are paged across deterministic scheduler shards instead of failing
        after a lifetime total of routed people.
        """
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")

        now_text = str(runtime.get("world_time"))
        now = CampaignTime.parse(now_text)
        profiles = self.read(_PROFILES_PATH)
        newly_routed: list[str] = []
        classified = 0

        for host_id, host in sorted(hosts.items()):
            if not isinstance(host_id, str) or not isinstance(host, dict) or host.get("kind") != "person":
                continue
            # Re-evaluate the bounded person-host registry on every route scan. Roles,
            # activity contracts, representation, health policy, and training programs
            # can lawfully change after the first classification. ``classified_at`` is
            # diagnostic evidence, never a permanent cache lock. Existing route shards
            # remain idempotent because registration below de-duplicates exact refs.
            person_ref = host.get("owner_ref")
            if not isinstance(person_ref, str):
                raise ValueError("person causal host lost exact owner_ref")
            classified += 1
            status = "inactive"
            if person_ref != self.PLAYER_ACTOR:
                try:
                    person_path, person = self._exact_person(person_ref, active=False)
                except ValueError:
                    person = None
                if isinstance(person, dict):
                    contract = self._effective_activity_contract(person)
                    focuses = self._activity_focuses(person, contract) if isinstance(contract, Mapping) else []
                    if (
                        isinstance(contract, Mapping)
                        and contract.get("autonomous_enabled") is not False
                        and focuses
                    ):
                        activity = person.setdefault("autonomous_activity_state", {})
                        if not isinstance(activity, dict):
                            raise ValueError("exact person autonomous_activity_state is invalid")
                        cadence = max(1, int(activity.get("cadence_seconds", _ACTIVITY_CADENCE_SECONDS)))
                        cycle_hours = verified_activity_hours_per_cycle(
                            person,
                            contract,
                            profiles,
                            cadence,
                            fallback_hours=_ACTIVITY_DEFAULT_VERIFIED_HOURS,
                        )
                        if cycle_hours > 0:
                            activity.setdefault("enabled", True)
                            activity.setdefault("routed_at", now_text)
                            activity["cadence_seconds"] = cadence
                            activity["verified_hours_per_cycle"] = round(cycle_hours, 6)
                            activity.setdefault("focus_cursor", 0)
                            activity.setdefault("next_due", str(now.add_seconds(cadence)))
                            activity[
                                "verification_rule"
                            ] = "structured causal cycles derive verified hours from the registered exact/institution/career/role/billet standard; allegiance never caps or multiplies training; planned opportunity prose never creates hours"
                            self.put(person_path, person)
                            newly_routed.append(person_ref)
                            status = "routed"
            host["activity_route"] = {
                "status": status,
                "classified_at": now_text,
            }

        # Individually named command staff can exist as person-lite records without
        # their own annual exact-person host. The command-personnel index is the
        # bounded current routing surface for those identities. Force-owned
        # materialized officers are deliberately excluded because their exact force
        # training clock owns their development and double credit is forbidden.
        command_lite_classified = 0
        command_index = self.read_optional(_COMMAND_PERSONNEL_INDEX) or {}
        record_index = command_index.get("record_index", {}) if isinstance(command_index, Mapping) else {}
        if isinstance(record_index, Mapping):
            for person_ref in sorted(str(ref) for ref in record_index):
                if person_ref == self.PLAYER_ACTOR:
                    continue
                try:
                    person_path = self.owner_path(person_ref)
                    person = copy.deepcopy(self.read(person_path))
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                if str(person.get("schema", "")) != "person-lite":
                    continue
                command_lite_classified += 1
                if self._person_lite_force_owned(person_ref, person):
                    continue
                contract = self._effective_activity_contract(person)
                focuses = self._activity_focuses(person, contract) if isinstance(contract, Mapping) else []
                if not isinstance(contract, Mapping) or contract.get("autonomous_enabled") is False or not focuses:
                    continue
                activity = person.setdefault("autonomous_activity_state", {})
                if not isinstance(activity, dict):
                    raise ValueError("person-lite autonomous_activity_state is invalid")
                cadence = max(1, int(activity.get("cadence_seconds", _ACTIVITY_CADENCE_SECONDS)))
                cycle_hours = verified_activity_hours_per_cycle(
                    person, contract, profiles, cadence, fallback_hours=_ACTIVITY_DEFAULT_VERIFIED_HOURS
                )
                if cycle_hours <= 0:
                    continue
                desired_rule = "named person-lite command staff use verified elapsed role development only; force-owned materialized officers remain on their force training clock"
                activity_changed = not isinstance(activity.get("routed_at"), str)
                if activity_changed:
                    activity.setdefault("enabled", True)
                    activity.setdefault("routed_at", now_text)
                    activity["cadence_seconds"] = cadence
                    activity["verified_hours_per_cycle"] = round(cycle_hours, 6)
                    activity.setdefault("focus_cursor", 0)
                    activity.setdefault("next_due", str(now.add_seconds(cadence)))
                    activity["verification_rule"] = desired_rule
                    self.put(person_path, person)
                newly_routed.append(person_ref)

        shards = self._activity_hosts(hosts)
        existing_refs: set[str] = set()
        for _host_id, shard in shards:
            refs = shard.get("routed_person_refs")
            if not isinstance(refs, list):
                raise ValueError("named-person activity route list is invalid")
            if len(refs) > _ACTIVITY_SHARD_SIZE:
                raise ValueError("named-person activity shard exceeds its routing page size")
            existing_refs.update(str(ref) for ref in refs if isinstance(ref, str))

        actual_registrations: list[str] = []
        for person_ref in sorted(set(newly_routed)):
            if person_ref in existing_refs:
                continue
            shards = self._activity_hosts(hosts)
            shard_index = 0
            if shards:
                last_id, last = shards[-1]
                refs = last.get("routed_person_refs", [])
                if len(refs) < _ACTIVITY_SHARD_SIZE:
                    target = last
                else:
                    shard_index = len(shards)
                    target = self._ensure_activity_shard(hosts, events, index=shard_index, now=now, now_text=now_text)
            else:
                target = self._ensure_activity_shard(hosts, events, index=0, now=now, now_text=now_text)
            refs = target.setdefault("routed_person_refs", [])
            refs.append(person_ref)
            refs[:] = sorted(set(str(ref) for ref in refs if isinstance(ref, str)))
            existing_refs.add(person_ref)
            actual_registrations.append(person_ref)

        shards = self._activity_hosts(hosts)
        routed_count = sum(len(shard.get("routed_person_refs", [])) for _host_id, shard in shards)
        routing = runtime.setdefault("person_activity_routing", {})
        if not isinstance(routing, dict):
            raise ValueError("person_activity_routing is invalid")
        routing.update({
            "last_route_scan_at": now_text,
            "routed_count": routed_count,
            "route_shards": len(shards),
            "shard_size": _ACTIVITY_SHARD_SIZE,
            "rule": "scheduler-known exact named people use explicit or saved-role-derived standing activity; named person-lite command staff use the bounded command-personnel index unless their exact force owns training; House Tang adults keep their explicit canonical regimen; child household development and the player are excluded",
        })
        metrics = runtime.setdefault("metrics", {})
        if actual_registrations:
            metrics["person_activity_route_registrations"] = int(metrics.get("person_activity_route_registrations", 0)) + len(actual_registrations)
        metrics["person_activity_route_classifications"] = int(metrics.get("person_activity_route_classifications", 0)) + classified + command_lite_classified
        self.put(_RUNTIME_PATH, runtime)

    @staticmethod
    def _activity_skip_reason(person: Mapping[str, Any], contract: Mapping[str, Any]) -> str | None:
        life = str(person.get("life_status", person.get("status", "active"))).lower()
        if life in {"dead", "deceased"}:
            return "dead"
        if contract.get("autonomous_enabled") is False:
            return "contract_disabled"
        custody = person.get("custody_state")
        if isinstance(custody, Mapping) and str(custody.get("status", "")).lower() == "captured":
            return "captured"
        health_value = person.get("health", person.get("health_status", "healthy"))
        if isinstance(health_value, Mapping):
            health = str(health_value.get("status", "healthy")).lower()
            fatigue_value = health_value.get("fatigue", person.get("fatigue", 0))
        else:
            health = str(health_value).lower()
            fatigue_value = person.get("fatigue", 0)
        if health not in _ELIGIBLE_HEALTH:
            return "health_unavailable"
        try:
            fatigue = int(fatigue_value)
        except (TypeError, ValueError):
            fatigue = 0
        if fatigue >= _ACTIVITY_FATIGUE_BLOCK:
            return "fatigue_unavailable"
        return None

    def _settle_activity_host(self, host: Mapping[str, Any], due_text: str) -> None:
        refs = host.get("routed_person_refs")
        if not isinstance(refs, list):
            raise ValueError("named-person activity host lost routed_person_refs")
        if len(refs) > _ACTIVITY_SHARD_SIZE:
            raise ValueError("named-person activity shard exceeds its routing page size")
        due = CampaignTime.parse(due_text)
        training = self.read("game/data/mechanics/training.json")
        session_rules = self.read(_SESSION_RULES_PATH)
        profiles = self.read(_PROFILES_PATH)
        for person_ref in refs:
            if not isinstance(person_ref, str) or person_ref == self.PLAYER_ACTOR:
                continue
            try:
                person_path, person = self._activity_person(person_ref)
            except (KeyError, ValueError, FileNotFoundError):
                continue
            if str(person.get("schema", "")) == "person-lite" and self._person_lite_force_owned(person_ref, person):
                continue
            contract = self._effective_activity_contract(person)
            if not isinstance(contract, Mapping):
                continue
            focuses = self._activity_focuses(person, contract)
            if not focuses:
                continue
            activity = person.setdefault("autonomous_activity_state", {})
            if not isinstance(activity, dict):
                raise ValueError("exact person autonomous_activity_state is invalid")
            cadence = max(1, int(activity.get("cadence_seconds", _ACTIVITY_CADENCE_SECONDS)))
            cycle_hours = verified_activity_hours_per_cycle(
                person,
                contract,
                profiles,
                cadence,
                fallback_hours=_ACTIVITY_DEFAULT_VERIFIED_HOURS,
            )
            if cycle_hours <= 0:
                activity["verified_hours_per_cycle"] = 0.0
                activity["resolved_through"] = due_text
                self.put(person_path, person)
                continue
            # Exact-person development settles whole hours, while the universal
            # 48h/week clock maps to a fractional number of hours for a 30-day
            # activity cadence. Carry the remainder across *successful* cycles so
            # 205/206-hour settlements conserve 48h/week exactly over time. A
            # skipped cycle neither mints its fractional share nor consumes prior
            # credit.
            fractional_credit = max(0.0, float(activity.get("fractional_training_hour_credit", 0.0) or 0.0))
            next_due_text = activity.get("next_due")
            if not isinstance(next_due_text, str):
                routed_at = CampaignTime.parse(str(activity.get("routed_at", due_text)))
                next_due = routed_at.add_seconds(cadence)
            else:
                next_due = CampaignTime.parse(next_due_text)
            cursor = max(0, int(activity.get("focus_cursor", 0)))
            processed = 0
            changed = False
            while next_due <= due:
                processed += 1
                if processed > 64:
                    raise ValueError("named-person activity catch-up exceeds bounded per-review cycle limit")
                program_ref, training_ref, resolved_role = self._activity_training_context(person, contract)
                cycle_at = str(next_due)
                fatigue_rules = self.read(FATIGUE_RULES_PATH)
                fatigue_recovery = settle_person_idle_fatigue(
                    person, current=next_due, rules=fatigue_rules, state="ordinary"
                )
                reason = self._activity_skip_reason(person, contract)
                if reason is None:
                    is_person_lite = str(person.get("schema", "")) == "person-lite"
                    if is_person_lite:
                        # Person-lite EDU banks are fractional, so they can settle the
                        # universal clock exactly without whole-hour carry.
                        settlement_hours = max(0.0, float(cycle_hours))
                        next_fractional_credit = 0.0
                    else:
                        available_cycle_hours = max(0.0, float(cycle_hours)) + fractional_credit
                        settlement_hours = max(0, int(available_cycle_hours + 1e-9))
                        next_fractional_credit = max(0.0, available_cycle_hours - settlement_hours)
                    resolved_regimen_ref, regimen = resolved_activity_regimen(person, contract, profiles)
                    activity["resolved_training_regimen_ref"] = resolved_regimen_ref or None
                    activity["training_regimen_resolution_rule"] = "exact_specialized_contract_then_institution_then_professional_path_then_role_then_billet_then_generic_fallback"
                    registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
                    trainee_skills = (person.get("stats", {}).get("skills", {}) if str(person.get("schema", "")) == "person-lite" and isinstance(person.get("stats"), Mapping) else person.get("skills", {}))
                    if not isinstance(trainee_skills, Mapping):
                        trainee_skills = {}
                    person_location = str(person.get("current_location", person.get("location_ref", person.get("location", ""))) or "")
                    cycle_start = next_due.add_seconds(-cadence)
                    cycle_evidence = f"named_activity:{cycle_at}:{person_ref}"
                    instructor_contexts = instructor_contexts_for_program(
                        self, registry=registry, training_rules=training, program_ref=program_ref,
                        trainee_skills=trainee_skills, student_count=1, location_ref=person_location, trainee_ref=person_ref,
                        scheduled_hours=float(cycle_hours), window_start=str(cycle_start), window_end=cycle_at,
                        evidence_ref=cycle_evidence, reserve_duty=True,
                    )
                    drill_access = exact_person_drill_access(self, registry=registry, program_ref=program_ref, person=person)
                    promotion_facts = exact_promotion_facts(self, person)
                    if str(person.get("schema", "")) == "person-lite":
                        exposure_monthly = float(regimen.get("role_exposure_hours_per_30d", 0.0) or 0.0)
                        role_exposure = exposure_monthly * cadence / _ACTIVITY_CADENCE_SECONDS
                        development = settle_person_lite_program(
                            person, registry=self.read(TRAINING_PROGRAM_REGISTRY_PATH),
                            program_ref=program_ref, deliberate_hours=float(settlement_hours),
                            role_exposure_hours=role_exposure, training_rules=training,
                            facility_grade=str(regimen.get("facility_grade", "adequate")),
                            equipment_grade=str(regimen.get("equipment_grade", "adequate")),
                            recovery_grade=str(regimen.get("recovery_grade", "adequate")),
                            evidence_ref=cycle_evidence,
                            promotion_facts=promotion_facts,
                            instructor_context_by_drill=instructor_contexts,
                            drill_access=drill_access,
                            time_window_start=str(cycle_start), time_window_end=cycle_at,
                        )
                    else:
                        exact_ds = person.setdefault("development_state", {})
                        verified_before = int(exact_ds.get(
                            "verified_deliberate_training_hours",
                            exact_ds.get("settled_training_hours", 0),
                        ) or 0)
                        development = settle_exact_program(
                            person, registry=self.read(TRAINING_PROGRAM_REGISTRY_PATH),
                            program_ref=program_ref, hours=settlement_hours, at=next_due,
                            training_rules=training, session_rules=session_rules,
                            facility_grade=str(regimen.get("facility_grade", "adequate")),
                            equipment_grade=str(regimen.get("equipment_grade", "adequate")),
                            recovery_grade=str(regimen.get("recovery_grade", "adequate")),
                            feedback_grade=str(regimen.get("feedback_grade", "ordinary")),
                            cursor_key="autonomous_deterministic_training_cursor",
                            promotion_facts=promotion_facts,
                            instructor_context_by_drill=instructor_contexts,
                            drill_access=drill_access,
                            time_window_start=str(cycle_start), time_window_end=cycle_at,
                            time_evidence_ref=cycle_evidence,
                        )
                        exact_ds["verified_deliberate_training_hours"] = verified_before + settlement_hours
                    person.setdefault("autonomous_development_history", []).append({
                        "at": cycle_at,
                        "program_ref": program_ref,
                        "training_ref": training_ref or None,
                        "resolved_role": resolved_role or None,
                        "scheduled_hours": round(float(cycle_hours), 6),
                        "settled_whole_hours": settlement_hours,
                        "hours": settlement_hours,
                        "development": development,
                        "fatigue_recovery": fatigue_recovery,
                        "verification_basis": "registered_deterministic_program_v1",
                        "planned_opportunity_hours_used": False,
                    })
                    person["autonomous_development_history"] = person["autonomous_development_history"][-_ACTIVITY_HISTORY_LIMIT:]
                    activity["completed_cycles"] = int(activity.get("completed_cycles", 0)) + 1
                    cursor += int(settlement_hours)
                    fractional_credit = next_fractional_credit
                    activity["fractional_training_hour_credit"] = round(fractional_credit, 6)
                    activity["last_completed_at"] = cycle_at
                    activity.pop("last_skip_reason", None)
                else:
                    activity["skipped_cycles"] = int(activity.get("skipped_cycles", 0)) + 1
                    activity["last_skip_reason"] = reason
                    activity["last_skipped_at"] = cycle_at
                    if reason == "dead":
                        activity["enabled"] = False
                activity["reviewed_cycles"] = int(activity.get("reviewed_cycles", 0)) + 1
                activity["last_cycle_at"] = cycle_at
                next_due = next_due.add_seconds(cadence)
                changed = True
                if reason == "dead":
                    break
            if changed:
                activity.update({
                        "cadence_seconds": cadence,
                    "verified_hours_per_cycle": round(cycle_hours, 6),
                    "focus_cursor": cursor,
                    "next_due": str(next_due),
                    "resolved_through": due_text,
                })
                self.put(person_path, person)

    def _autonomy_person(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        """Keep base life-course logic while suppressing duplicate annual training settlement."""
        person_ref = str(host.get("owner_ref", ""))
        if not person_ref or person_ref == self.PLAYER_ACTOR:
            super()._autonomy_person(host, occurrences, at)
            return
        try:
            person_path, person = self._exact_person(person_ref, active=False)
        except ValueError:
            super()._autonomy_person(host, occurrences, at)
            return
        contract = person.get("activity_contract")
        if not isinstance(contract, Mapping):
            super()._autonomy_person(host, occurrences, at)
            return
        original_contract = copy.deepcopy(contract)
        guarded = copy.deepcopy(person)
        guarded_contract = guarded.setdefault("activity_contract", {})
        existing_rule = str(guarded_contract.get("growth_rule", "")).strip()
        guard_rule = "not automatic progress; routed standing activity owns routine development"
        guarded_contract["growth_rule"] = f"{existing_rule}; {guard_rule}" if existing_rule else guard_rule
        self.put(person_path, guarded)
        super()._autonomy_person(host, occurrences, at)
        after = copy.deepcopy(self.read(person_path))
        after["activity_contract"] = original_contract
        self.put(person_path, after)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") == "person_activity":
            self._settle_activity_host(host, due_text)
            self._pending_wake_created = None
            return
        super()._run_due_host(host, due_text)

    def _activity_route_scan_required(self, target_text: str) -> bool:
        """Return whether the bounded activity router must reconcile before advance.

        Activity routes only own 30-day gain-bearing settlement. Re-reading every
        exact/person-lite command record before every one-hour or four-hour
        chronology step is unnecessary and becomes campaign-scale I/O churn. A
        full reconcile is therefore mandatory when no prior scan exists, when the
        previous scan is at least one campaign day old, or whenever this advance
        can wake a person-activity host. Direct callers of ``_ensure_activity_routes``
        still receive an immediate full reconciliation.
        """
        runtime = self.read(_RUNTIME_PATH)
        if not isinstance(runtime, Mapping):
            return True
        now_text = runtime.get("world_time")
        if not isinstance(now_text, str):
            return True
        now = CampaignTime.parse(now_text)
        target = CampaignTime.parse(target_text)
        routing = runtime.get("person_activity_routing")
        last_scan_text = routing.get("last_route_scan_at") if isinstance(routing, Mapping) else None
        if not isinstance(last_scan_text, str):
            return True
        try:
            last_scan = CampaignTime.parse(last_scan_text)
        except (TypeError, ValueError):
            return True
        if now >= last_scan.add_seconds(86400):
            return True
        events = runtime.get("events")
        if not isinstance(events, list):
            return True
        for event in events:
            if not isinstance(event, Mapping) or event.get("kind") != "person_activity_review":
                continue
            due_text = event.get("due_at")
            if not isinstance(due_text, str):
                return True
            if CampaignTime.parse(due_text) <= target:
                return True
        return False

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        if getattr(self, "_central_scheduler_reconciliation_active", False):
            return super()._advance_runtime(target_text)
        if self._activity_route_scan_required(target_text):
            self._ensure_activity_routes()
        return super()._advance_runtime(target_text)


__all__ = ["ActivityCampaignEventPlanner"]
