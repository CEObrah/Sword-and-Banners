"""Political, personnel, and allegiance resolution for military career networks.

Career attraction remains informational until an institution approves a petition.
This overlay turns an approved handoff into a conserved, physically routed named-
officer movement without allowing career state to own formations, manpower, or
administrative custody.  It also resolves high-salience military allegiance
crises through formation loyalty, immediate officers, and exact conserved
materialized people rather than a player-specific conversion shortcut.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.commands import CommandEnvelope
from sword_runtime.cohort_personnel import (
    add_recruits,
    ensure_formation_composition,
    formation_materialized_assignments,
    formation_materialized_count,
    partition_formation_slices,
    record_recruitment_cohort,
    validate_cohort_ledger,
)
from sword_runtime.history_store import write_history_index
from sword_runtime.military_career_loyalty import (
    _PLAYER_REF,
    _RUNTIME_PATH,
    _clamp,
    _civilian_service_entry_eligible,
    _digest,
    _military_score,
    _slug,
)
from sword_runtime.military_career_loyalty_integrity import (
    MilitaryCareerLoyaltyIntegrityMixin,
    _service_state_ref,
)
from sword_runtime.campaign_communications import player_command_location
from sword_runtime.player_story_flow import _dispatch_player_story_message, _event_owner_write, _player_delivery
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.operation_routing import exact_operation_record, iter_exact_operation_records

_TRANSFER_INDEX_PATH = "state/military/personnel-transfers/index.json"
_TRANSFER_ACTIVE = {"ordered", "in_transit", "rerouted"}
_CRISIS_ACTIONS = {"rebel", "defect", "mutiny", "defy_state_order"}
_ACTIVE_OPERATION_STATES = {"planned", "mobilizing", "active", "engaged", "occupied"}


def _formation_state_ref(formation: Mapping[str, Any]) -> str | None:
    admin = formation.get("administrative_owner")
    if isinstance(admin, str) and admin.startswith("state_"):
        return admin
    force_ref = formation.get("owner_force_ref")
    if isinstance(force_ref, str) and force_ref.startswith("force_state_"):
        return force_ref.removeprefix("force_")
    return None


def _person_ref(person: Mapping[str, Any]) -> str:
    for key in ("owner_id", "id", "person_ref"):
        value = person.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


class MilitaryCareerLoyaltyPoliticsMixin(MilitaryCareerLoyaltyIntegrityMixin):
    """Complete military career, patronage, personnel movement, and allegiance flow."""

    # ------------------------------------------------------------------
    # Career-interest politics
    # ------------------------------------------------------------------

    def _create_petition(
        self,
        person: dict[str, Any],
        *,
        state_ref: str,
        desired_commander_ref: str | None,
        request_kind: str,
        attraction_milli: int,
        evidence_refs: list[str],
        at: str,
    ) -> str | None:
        petition_ref = super()._create_petition(
            person,
            state_ref=state_ref,
            desired_commander_ref=desired_commander_ref,
            request_kind=request_kind,
            attraction_milli=attraction_milli,
            evidence_refs=evidence_refs,
            at=at,
        )
        if petition_ref is None:
            return None
        petition_path = self._petition_path(petition_ref)
        petition = copy.deepcopy(self.read(petition_path))
        formation_ref, formation = self._person_current_formation(person)
        career_state = person.get("career_state") if isinstance(person.get("career_state"), Mapping) else {}
        assignment_ref = career_state.get("current_assignment_ref") if isinstance(career_state, Mapping) else None
        petition["service_authority_ref"] = (
            formation.get("administrative_owner")
            if isinstance(formation, Mapping) and isinstance(formation.get("administrative_owner"), str)
            else (str(assignment_ref) if isinstance(assignment_ref, str) and assignment_ref else state_ref)
        )
        petition["source_force_ref"] = (
            formation.get("owner_force_ref")
            if isinstance(formation, Mapping) and isinstance(formation.get("owner_force_ref"), str)
            else None
        )
        self.put(petition_path, petition)
        if not desired_commander_ref:
            return petition_ref
        network = self._career_network()
        interest = network.setdefault("career_interest", {}).setdefault(state_ref, {}).setdefault(desired_commander_ref, {})
        interest["petition_count"] = int(interest.get("petition_count", 0)) + 1
        interest["weighted_interest_milli"] = min(
            50000,
            int(interest.get("weighted_interest_milli", 0)) + max(100, int(attraction_milli) // 2),
        )
        interest["last_petition_at"] = at
        recent = interest.setdefault("recent_petition_refs", [])
        if petition_ref not in recent:
            recent.append(petition_ref)
        interest["recent_petition_refs"] = recent[-32:]
        self.put("state/military/career-network/index.json", network)
        return petition_ref

    def _political_concentration(self, state_ref: str, commander_ref: str | None) -> int:
        base = super()._political_concentration(state_ref, commander_ref)
        if not commander_ref:
            return base
        network = self._career_network()
        interest = network.get("career_interest", {}).get(state_ref, {}).get(commander_ref, {})
        if not isinstance(interest, Mapping):
            return base
        cumulative = min(700, int(interest.get("weighted_interest_milli", 0)) // 4)
        repeat = min(180, int(interest.get("petition_count", 0)) * 18)
        return _clamp(base + cumulative + repeat)

    def _career_concentration_event(
        self,
        *,
        state_ref: str,
        commander_ref: str,
        concentration_milli: int,
        at: str,
    ) -> None:
        rules = self._military_rules()["institutional_response"]
        soft = int(rules["political_concentration_soft_milli"])
        hard = int(rules["political_concentration_hard_milli"])
        if concentration_milli < soft:
            return
        network = self._career_network()
        state_pressure = network.setdefault("state_pressure", {}).setdefault(state_ref, {})
        previous = state_pressure.get(commander_ref)
        prior_level = str(previous.get("level", "none")) if isinstance(previous, Mapping) else "none"
        level = "hard" if concentration_milli >= hard else "soft"
        state_pressure[commander_ref] = {
            "level": level,
            "concentration_milli": int(concentration_milli),
            "last_observed_at": at,
            "basis": "saved military career petitions and propagated commander reputation",
        }
        self.put("state/military/career-network/index.json", network)
        if prior_level == level:
            return
        digest = hashlib.sha256(f"{state_ref}|{commander_ref}|{level}".encode("utf-8")).hexdigest()[:18]
        event_ref = f"event_military_following_pressure_{digest}"
        state_name = state_ref.removeprefix("state_")
        summary = (
            f"{state_ref}'s military administration has registered a {level} concentration of officer interest around "
            f"{commander_ref}. This is a political-personnel pressure signal, not a transfer of troop ownership, state allegiance, "
            "or command authority. Future personnel approvals may be restricted, redirected, or balanced by independent commands."
        )
        payload: dict[str, Any] = {
            "event_ref": event_ref,
            "kind": "military_following_political_pressure",
            "status": "triggered",
            "due_at": at,
            "triggered_at": at,
            "actor_ref": f"inst_{state_name}_military_bureau",
            "target_ref": commander_ref,
            "basis_goal": "prevent unhealthy concentration of personal military patronage",
            "process_kind": "military_personnel_politics",
            "process_stage": level,
            "summary": summary,
        }
        bureau_ref = f"inst_{state_name}_military_bureau"
        if commander_ref == _PLAYER_REF:
            _dispatch_player_story_message(
                self, event_ref=event_ref, at=at, actor_ref=bureau_ref, source_owner_ref=bureau_ref,
                event_kind="military_following_political_pressure", process_kind="military_personnel_politics",
                transit_stage=f"{level}_memorandum_in_transit", delivered_stage=level,
                delivered_summary=summary, route_label="military bureau memorandum",
                basis_goal="prevent unhealthy concentration of personal military patronage",
            )
            return
        _event_owner_write(self, event_ref, payload, at, source_owner_ref=bureau_ref)

    # ------------------------------------------------------------------
    # Exact personnel-transfer authority handoff
    # ------------------------------------------------------------------

    def _transfer_index(self) -> dict[str, Any]:
        raw = self.read_optional(_TRANSFER_INDEX_PATH)
        if raw is None:
            return {
                "schema": "sword-military-personnel-transfer-index",
                "authority": False,
                "orders": {},
                "active_by_state": {},
                "active_attachments_by_state": {},
                "completed_count": 0,
            }
        if not isinstance(raw, Mapping) or raw.get("schema") != "sword-military-personnel-transfer-index":
            raise ValueError("military personnel transfer index is invalid")
        return copy.deepcopy(dict(raw))

    @staticmethod
    def _transfer_order_path(order_ref: str) -> str:
        return f"state/military/personnel-transfers/{_slug(order_ref)}.json"

    @staticmethod
    def _set_force_allocation(force: MutableMapping[str, Any], formation_ref: str, delta: int, role: str) -> None:
        allocations = force.setdefault("allocated_to_formations", {})
        row = allocations.get(formation_ref)
        if isinstance(row, MutableMapping):
            comp = row.get("composition")
            if isinstance(comp, MutableMapping):
                comp[role] = max(0, int(comp.get(role, 0)) + int(delta))
                if comp[role] == 0:
                    comp.pop(role, None)
                row["personnel"] = sum(max(0, int(v)) for v in comp.values())
                row.pop("role", None)
                return
            existing_role = str(row.get("role") or role)
            existing_n = max(0, int(row.get("personnel", 0)))
            if existing_role == role:
                row["personnel"] = max(0, existing_n + int(delta))
                row["role"] = role
                return
            comp = {existing_role: existing_n, role: max(0, int(delta))}
            row.clear(); row.update({"personnel": sum(comp.values()), "composition": {k:v for k,v in comp.items() if v > 0}})
        elif row is not None:
            allocations[formation_ref] = {"personnel": max(0, int(row) + int(delta)), "role": role}
        else:
            allocations[formation_ref] = {"personnel": max(0, int(delta)), "role": role}

    @staticmethod
    def _remove_person_from_formation_lists(formation: MutableMapping[str, Any], person_ref: str) -> None:
        for field in ("embedded_person_refs", "notable_person_refs", "staff_refs", "specialist_refs"):
            rows = formation.get(field)
            if isinstance(rows, list) and person_ref in rows:
                formation[field] = [ref for ref in rows if str(ref) != person_ref]

    def _commander_target_formation(self, commander_ref: str, state_ref: str) -> str | None:
        candidates: list[tuple[int, str]] = []
        for formation_ref in self._authoritative_commander_formation_refs(commander_ref):
            try:
                _path, formation = self._load_formation(formation_ref)
            except ValueError:
                continue
            if _formation_state_ref(formation) != state_ref or int(formation.get("personnel", 0)) <= 0:
                continue
            candidates.append((int(formation.get("personnel", 0)), formation_ref))
        if not candidates:
            dossier = self._career_dossier(commander_ref)
            formation_ref = dossier.get("formation_ref") if isinstance(dossier, Mapping) else None
            if isinstance(formation_ref, str):
                try:
                    _path, formation = self._load_formation(formation_ref)
                except ValueError:
                    formation = None
                if isinstance(formation, Mapping) and _formation_state_ref(formation) == state_ref and int(formation.get("personnel", 0)) > 0:
                    candidates.append((int(formation.get("personnel", 0)), formation_ref))
        if not candidates:
            return None
        candidates.sort(key=lambda row: (-row[0], row[1]))
        return candidates[0][1]

    def _independent_command_vacancy(self, state_ref: str, officer_ref: str) -> str | None:
        force_ref = f"force_{state_ref}"
        try:
            force = self.read(self.owner_path(force_ref))
            _person_path, person = self._exact_person(officer_ref, active=False)
        except (KeyError, ValueError, FileNotFoundError):
            return None
        if not isinstance(force, Mapping):
            return None
        desired_scale = max(100, min(20000, _military_score(person) * 50))
        rows: list[tuple[int, int, str]] = []
        allocations = force.get("allocated_to_formations", {})
        if not isinstance(allocations, Mapping):
            return None
        for formation_ref in allocations:
            if not isinstance(formation_ref, str):
                continue
            try:
                _path, formation = self._load_formation(formation_ref)
            except ValueError:
                continue
            if _formation_state_ref(formation) != state_ref:
                continue
            if formation.get("commander_ref") or int(formation.get("personnel", 0)) <= 0:
                continue
            if str(formation.get("status", "")).lower() in {"destroyed", "dissolved"}:
                continue
            scale = int(formation.get("personnel", 0))
            rows.append((abs(scale - desired_scale), scale, formation_ref))
        rows.sort()
        return rows[0][2] if rows else None

    def _requeue_petition(self, petition: dict[str, Any], at: str, reason: str, *, days: int = 30) -> None:
        petition["status"] = "delayed"
        petition["execution_status"] = "waiting_for_lawful_assignment"
        petition["execution_blocker"] = reason
        petition["review_due_at"] = str(CampaignTime.parse(at).add_seconds(max(1, days) * 86400))
        self.put(self._petition_path(str(petition["petition_ref"])), petition)
        index = self._petition_index()
        rows = index.setdefault("pending_by_state", {}).setdefault(str(petition["state_ref"]), [])
        if petition["petition_ref"] not in rows:
            rows.append(petition["petition_ref"])
            rows.sort()
            index["resolved_count"] = max(0, int(index.get("resolved_count", 0)) - 1)
        self.put("state/military/career-petitions/index.json", index)

    def _detach_person_from_formation(
        self,
        person_ref: str,
        source_formation_ref: str | None,
        at: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        person_path, person0 = self._exact_person(person_ref, active=False)
        person = copy.deepcopy(dict(person0))
        result = {"included_in_force_headcount": False, "role": "command_personnel", "source_force_ref": None}
        if not source_formation_ref:
            provenance = person.get("population_provenance") if isinstance(person.get("population_provenance"), Mapping) else {}
            reserve_force_ref = provenance.get("force_ref") if isinstance(provenance.get("force_ref"), str) else None
            if str(provenance.get("service_stratum", "")) == "active_military" and reserve_force_ref:
                try:
                    reserve_force = self.read(self.owner_path(str(reserve_force_ref)))
                except (KeyError, ValueError, FileNotFoundError):
                    reserve_force = None
                materialized = reserve_force.get("materialized_people", {}) if isinstance(reserve_force, Mapping) else {}
                if isinstance(materialized, Mapping) and person_ref in materialized:
                    result["source_force_ref"] = str(reserve_force_ref)
                    result["included_in_force_headcount"] = True
                    result["role"] = str(provenance.get("entry_role") or "line_infantry")
                    person["current_formation_id"] = None
                    person["military_transfer_state"] = {"status": "detached_reserve", "at": at, "reason": reason}
                    self.put(person_path, person)
                    return result
            person["current_formation_id"] = None
            person["military_transfer_state"] = {"status": "detached", "at": at, "reason": reason}
            self.put(person_path, person)
            return result
        formation_path, formation0 = self._load_formation(source_formation_ref)
        formation = copy.deepcopy(dict(formation0))
        force_ref = str(formation.get("owner_force_ref", ""))
        result["source_force_ref"] = force_ref or None
        force = copy.deepcopy(self.read(self.owner_path(force_ref))) if force_ref else None
        assignment = None
        if isinstance(force, MutableMapping):
            assignments = force.setdefault("materialized_assignments", {})
            raw = assignments.get(person_ref)
            if isinstance(raw, Mapping) and str(raw.get("formation_ref", "")) == source_formation_ref:
                assignment = dict(raw)
        if assignment is not None and isinstance(force, MutableMapping):
            ensure_formation_composition(force, formation, at=at)
            role = str(assignment.get("role") or next(iter(formation.get("composition", {})), "command_personnel"))
            if int(formation.get("personnel", 0)) <= 0:
                raise ValueError("cannot detach a conserved officer from an empty formation")
            formation["personnel"] = int(formation.get("personnel", 0)) - 1
            composition = formation.setdefault("composition", {})
            composition[role] = max(0, int(composition.get(role, 0)) - 1)
            self._set_force_allocation(force, source_formation_ref, -1, role)
            force.setdefault("materialized_assignments", {}).pop(person_ref, None)
            result.update({"included_in_force_headcount": True, "role": role})
            person["equipment_custody"] = {
                "mode": "military_personnel_transfer",
                "source_force_ref": force_ref,
                "source_formation_ref": source_formation_ref,
                "role": role,
                "principle": "same conserved body remains in force headcount while unassigned during transfer",
            }
            validate_cohort_ledger(force)
            self.put(self.owner_path(force_ref), force)
        self._remove_person_from_formation_lists(formation, person_ref)
        if formation.get("commander_ref") == person_ref:
            formation["commander_ref"] = None
            self._release_commander_index(person_ref, source_formation_ref)
            if int(formation.get("personnel", 0)) > 0:
                formation["status"] = "commander_vacant"
        person["current_formation_id"] = None
        person["military_transfer_state"] = {"status": "detached", "at": at, "reason": reason, "source_formation_ref": source_formation_ref}
        self.put(formation_path, formation)
        self.put(person_path, person)
        return result

    def _attach_person_to_formation(
        self,
        person_ref: str,
        target_formation_ref: str,
        at: str,
        *,
        included_in_force_headcount: bool,
        source_force_ref: str | None,
        role: str,
        reason: str,
    ) -> None:
        person_path, person0 = self._exact_person(person_ref, active=False)
        person = copy.deepcopy(dict(person0))
        formation_path, formation0 = self._load_formation(target_formation_ref)
        formation = copy.deepcopy(dict(formation0))
        target_force_ref = str(formation.get("owner_force_ref", ""))
        if included_in_force_headcount:
            if not source_force_ref or target_force_ref != source_force_ref:
                raise ValueError("career transfer cannot silently move a conserved body between force owners")
            force_path = self.owner_path(target_force_ref)
            force = copy.deepcopy(self.read(force_path))
            assignment = force.setdefault("materialized_assignments", {}).get(person_ref)
            if isinstance(assignment, Mapping):
                raise ValueError("transferred officer is already assigned to a formation")
            formation["personnel"] = int(formation.get("personnel", 0)) + 1
            formation.setdefault("composition", {})[role] = int(formation.get("composition", {}).get(role, 0)) + 1
            self._set_force_allocation(force, target_formation_ref, 1, role)
            force.setdefault("materialized_assignments", {})[person_ref] = {
                "formation_ref": target_formation_ref,
                "role": role,
                "personnel": 1,
            }
            refs = formation.setdefault("embedded_person_refs", [])
            if person_ref not in refs:
                refs.append(person_ref)
            validate_cohort_ledger(force)
            self.put(force_path, force)
            person["equipment_custody"] = {
                "mode": "formation_issue_slot",
                "formation_ref": target_formation_ref,
                "role": role,
                "principle": "view of one already-counted formation issue slot; reassignment creates no equipment",
            }
        else:
            refs = formation.setdefault("staff_refs", [])
            if person_ref not in refs:
                refs.append(person_ref)
        person["current_formation_id"] = target_formation_ref
        self._set_person_location(person, str(formation.get("location_ref", "")))
        person["military_transfer_state"] = {"status": "assigned", "at": at, "reason": reason, "target_formation_ref": target_formation_ref}
        self.put(formation_path, formation)
        self.put(person_path, person)

    def _schedule_transfer_host(self, order: Mapping[str, Any]) -> None:
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        hosts = runtime.setdefault("hosts", {})
        events = runtime.setdefault("events", [])
        order_ref = str(order["order_ref"])
        token = _digest([order_ref, order["arrives_at"]])
        host_id = f"host_military_personnel_transfer_{token}"
        event_id = f"event_military_personnel_transfer_{token}"
        hosts[host_id] = {
            "kind": "military_personnel_transfer",
            "owner_ref": order_ref,
            "next_due": str(order["arrives_at"]),
            "recurrence_seconds": 0,
            "resolved_through": str(order["departed_at"]),
            "safe_through": str(CampaignTime.parse(str(order["arrives_at"])).add_seconds(-1)),
        }
        if not any(isinstance(row, Mapping) and row.get("event_id") == event_id for row in events):
            events.append({
                "due_at": str(order["arrives_at"]),
                "event_id": event_id,
                "kind": "military_personnel_transfer_arrival",
                "priority": 86,
                "target_host": host_id,
            })
        self.put(_RUNTIME_PATH, runtime)

    def _create_transfer_order(
        self,
        petition: Mapping[str, Any],
        *,
        target_formation_ref: str,
        at: str,
        request_kind: str | None = None,
        already_detached: bool = False,
        source_formation_ref: str | None = None,
        inherited_transfer: Mapping[str, Any] | None = None,
    ) -> str:
        officer_ref = str(petition["officer_ref"])
        person_path, person0 = self._exact_person(officer_ref, active=False)
        person = copy.deepcopy(dict(person0))
        target_path, target = self._load_formation(target_formation_ref)
        del target_path
        state_ref = str(petition["state_ref"])
        if _formation_state_ref(target) != state_ref:
            raise ValueError("career petition target must remain inside its approved state military context")
        source_ref = source_formation_ref
        if source_ref is None and not already_detached:
            source_ref, _source = self._person_current_formation(person)
        source_location = self._person_location(person)
        if not source_location and source_ref:
            try:
                _sp, source = self._load_formation(source_ref)
            except ValueError:
                source = None
            if isinstance(source, Mapping):
                source_location = str(source.get("location_ref", "")) or None
        destination = str(target.get("location_ref", ""))
        if not source_location or not destination:
            raise ValueError("personnel transfer requires exact source and destination locations")
        hours = max(1, int(self._route_travel_hours(str(source_location), destination, modes=("horse", "foot"))))
        arrives_at = str(CampaignTime.parse(at).add_seconds(hours * 3600))
        transfer_info = dict(inherited_transfer or {})
        if not already_detached:
            transfer_info = self._detach_person_from_formation(officer_ref, source_ref, at, reason="approved military career transfer")
        source_force_ref = transfer_info.get("source_force_ref")
        included = bool(transfer_info.get("included_in_force_headcount", False))
        role = str(transfer_info.get("role", "command_personnel"))
        if included and source_force_ref != target.get("owner_force_ref"):
            raise ValueError("approved career movement crosses force ownership and needs a separate ownership-transfer authority")
        order_ref = f"military_personnel_transfer_{_digest([petition.get('petition_ref'), officer_ref, target_formation_ref, at, request_kind])}"
        order = {
            "schema": "sword-military-personnel-transfer",
            "owner_id": order_ref,
            "order_ref": order_ref,
            "petition_ref": str(petition.get("petition_ref", "")),
            "officer_ref": officer_ref,
            "state_ref": state_ref,
            "request_kind": str(request_kind or petition.get("request_kind", "permanent_transfer")),
            "desired_commander_ref": petition.get("desired_commander_ref"),
            "source_formation_ref": source_ref,
            "target_formation_ref": target_formation_ref,
            "source_force_ref": source_force_ref,
            "target_force_ref": target.get("owner_force_ref"),
            "included_in_force_headcount": included,
            "role": role,
            "source_location_ref": source_location,
            "destination_location_ref": destination,
            "departed_at": at,
            "arrives_at": arrives_at,
            "travel_hours": hours,
            "status": "in_transit",
        }
        path = self._transfer_order_path(order_ref)
        self.put(path, order)
        self._register_owner(order_ref, path)
        index = self._transfer_index()
        index.setdefault("orders", {})[order_ref] = path
        active = index.setdefault("active_by_state", {}).setdefault(state_ref, [])
        if order_ref not in active:
            active.append(order_ref)
            active.sort()
        self.put(_TRANSFER_INDEX_PATH, index)
        person = copy.deepcopy(self.read(person_path))
        self._set_person_location(person, str(source_location))
        person["military_transfer_state"] = {
            "status": "in_transit",
            "order_ref": order_ref,
            "departed_at": at,
            "arrives_at": arrives_at,
            "destination_location_ref": destination,
        }
        self.put(person_path, person)
        self._schedule_transfer_host(order)
        return order_ref

    def _reroute_transfer(self, order: dict[str, Any], target_formation_ref: str, at: str, reason: str) -> str | None:
        officer_ref = str(order["officer_ref"])
        person_path, person0 = self._exact_person(officer_ref, active=False)
        person = copy.deepcopy(dict(person0))
        self._set_person_location(person, str(order.get("destination_location_ref", self._person_location(person) or "")))
        self.put(person_path, person)
        petition_path = self._petition_path(str(order.get("petition_ref", "")))
        petition = self.read_optional(petition_path)
        if not isinstance(petition, Mapping):
            petition = {
                "petition_ref": str(order.get("petition_ref", "")),
                "officer_ref": officer_ref,
                "state_ref": str(order["state_ref"]),
                "request_kind": str(order["request_kind"]),
                "desired_commander_ref": order.get("desired_commander_ref"),
            }
        try:
            new_ref = self._create_transfer_order(
                petition,
                target_formation_ref=target_formation_ref,
                at=at,
                request_kind=str(order["request_kind"]),
                already_detached=True,
                source_formation_ref=None,
                inherited_transfer={
                    "source_force_ref": order.get("source_force_ref"),
                    "included_in_force_headcount": order.get("included_in_force_headcount", False),
                    "role": order.get("role", "command_personnel"),
                },
            )
        except ValueError:
            order["status"] = "blocked_after_reroute"
            order["blocked_at"] = at
            order["blocked_reason"] = reason
            self.put(self._transfer_order_path(str(order["order_ref"])), order)
            return None
        order["status"] = "rerouted"
        order["rerouted_at"] = at
        order["reroute_reason"] = reason
        order["next_order_ref"] = new_ref
        self.put(self._transfer_order_path(str(order["order_ref"])), order)
        if isinstance(petition, Mapping) and petition.get("petition_ref"):
            updated = copy.deepcopy(dict(petition))
            updated["transfer_order_ref"] = new_ref
            updated["execution_status"] = "transfer_rerouted"
            self.put(petition_path, updated)
        return new_ref

    def _service_entry_posting_target(self, state_ref: str, role: str, source_location: str) -> str | None:
        """Choose one real understrength state formation for a new combat recruit.

        This is a posting, never a command grant. It prefers physically nearer
        formations that already use the recruit's accounting role, then the larger
        true vacancy. Full formations are never overfilled merely to give a named
        character somewhere to stand.
        """
        force_ref = f"force_{state_ref}"
        try:
            force = self.read(self.owner_path(force_ref))
        except (KeyError, ValueError, FileNotFoundError):
            return None
        allocations = force.get("allocated_to_formations", {}) if isinstance(force, Mapping) else {}
        if not isinstance(allocations, Mapping):
            return None
        rows: list[tuple[int, int, str]] = []
        for formation_ref in sorted(str(ref) for ref in allocations if isinstance(ref, str)):
            try:
                _path, formation = self._load_formation(formation_ref)
            except ValueError:
                continue
            if _formation_state_ref(formation) != state_ref:
                continue
            if str(formation.get("status", "")).lower() in {"destroyed", "dissolved"}:
                continue
            personnel = max(0, int(formation.get("personnel", 0)))
            authorized = max(personnel, int(formation.get("authorized_strength", personnel) or personnel))
            gap = max(0, authorized - personnel)
            if gap <= 0:
                continue
            composition = formation.get("composition") if isinstance(formation.get("composition"), Mapping) else {}
            if composition and role not in composition:
                continue
            destination = formation.get("location_ref")
            if not isinstance(destination, str) or not destination:
                continue
            try:
                travel = max(0, int(self._route_travel_hours(source_location, destination, modes=("horse", "foot"))))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            rows.append((travel, -gap, formation_ref))
        rows.sort()
        return rows[0][2] if rows else None

    def _execute_state_service_entry(self, petition: dict[str, Any], at: str) -> bool:
        """Reclassify one exact civilian into one conserved state-military reserve body."""
        officer_ref = str(petition.get("officer_ref", ""))
        state_ref = str(petition.get("state_ref", ""))
        state = state_ref.removeprefix("state_")
        person_path, person0 = self._exact_person(officer_ref, active=False)
        person = copy.deepcopy(dict(person0))
        provenance = person.get("population_provenance") if isinstance(person.get("population_provenance"), Mapping) else {}
        if str(provenance.get("service_stratum", "")) == "active_military" and provenance.get("force_ref") == f"force_state_{state}":
            petition["status"] = "completed"
            petition["execution_status"] = "already_in_state_military_service"
            petition["completed_at"] = at
            return True
        if not _civilian_service_entry_eligible(person):
            self._requeue_petition(petition, at, "applicant is no longer a civilian military-entry candidate", days=90)
            return False
        location = self._person_location(person)
        if not location:
            self._requeue_petition(petition, at, "military entry requires an exact current location", days=30)
            return False
        force_ref = f"force_state_{state}"
        try:
            force_path = self.owner_path(force_ref)
            force = copy.deepcopy(self.read(force_path))
            state_path = self.owner_path(state_ref)
            state_doc = copy.deepcopy(self.read(state_path))
            office = self.read(self.owner_path(f"inst_{state}_recruitment_office"))
        except (KeyError, ValueError, FileNotFoundError):
            self._requeue_petition(petition, at, "state military entry authority is unavailable", days=90)
            return False
        if int(office.get("capacity", 0) or 0) <= 0:
            self._requeue_petition(petition, at, "state recruitment office has no current intake capacity", days=30)
            return False
        population_path = f"state/population/{state}.json"
        population = copy.deepcopy(self.read(population_path))
        strata = population.get("strata") if isinstance(population.get("strata"), dict) else None
        entry_rules = self._military_rules().get("service_entry", {})
        entry_track = str(petition.get("service_entry_track", "combatant"))
        if entry_track not in {"combatant", "staff"}:
            entry_track = "combatant"
        source_stratum = str(entry_rules.get("staff_source_stratum", "household_and_service")) if entry_track == "staff" else str(entry_rules.get("combatant_source_stratum", "agricultural"))
        if not isinstance(strata, dict) or int(strata.get(source_stratum, 0)) <= 0:
            self._requeue_petition(petition, at, "no conserved civilian source body is available for this service track", days=90)
            return False
        max_fraction_milli = max(1, int(entry_rules.get("active_military_population_fraction_max_milli", 100)))
        total_population = max(1, int(population.get("population_total", 0)))
        if (int(strata.get("active_military", 0)) + 1) * 1000 > total_population * max_fraction_milli:
            self._requeue_petition(petition, at, "state active-military population ceiling leaves no current intake headroom", days=90)
            return False
        economy = self.read("game/data/mechanics/economy.json")
        unit_cost = max(0, int(economy.get("military_finance", {}).get("recruitment_and_basic_issue_cost_silver_per_person", 12)))
        if int(state_doc.get("treasury_silver", 0)) < unit_cost:
            self._requeue_petition(petition, at, "state treasury cannot fund recruitment and basic issue", days=30)
            return False
        try:
            _pp, _pop, local_row = self._local_population_row(state, str(location), population)
        except ValueError as exc:
            self._requeue_petition(petition, at, str(exc), days=90)
            return False
        local_civilians = local_row.get("civilian_strata") if isinstance(local_row.get("civilian_strata"), Mapping) else {}
        if int(local_civilians.get(source_stratum, 0)) <= 0:
            self._requeue_petition(petition, at, "local demographic owner has no civilian available for this service track", days=90)
            return False

        role = str(entry_rules.get("staff_entry_role", entry_rules.get("entry_role", "line_infantry"))) if entry_track == "staff" else str(entry_rules.get("entry_role", "line_infantry"))
        strata[source_stratum] = int(strata.get(source_stratum, 0)) - 1
        strata["active_military"] = int(strata.get("active_military", 0)) + 1
        moved = self._consume_local_recruitment(
            population, state, str(location), 1, service_key="native_military",
            source_stratum=source_stratum, service_owner_ref=force_ref,
        )
        if moved != 1:
            raise ValueError("exact military service entry failed local population conservation")
        add_recruits(force, role, 1, location_ref=str(location))
        cohort_ref = record_recruitment_cohort(
            force, role=role, count=1, location_ref=str(location),
            source_population_ref=f"population_{state}", source_stratum=source_stratum,
            recruited_at=at, profile_registry=self.read("game/data/mil/recruitment-cohort-profiles.json"),
            selection_profile="state_basic_military_screen", provenance_ref=str(petition.get("petition_ref", "")),
        )
        self._take_force_personnel(force, role, 1, str(location))
        self._ct_materialize_from_cohort(force, role, str(location), officer_ref, person)
        force.setdefault("materialized_people", {})[officer_ref] = {"personnel": 1, "role": role, "source_cohort_ref": str(cohort_ref or person.get("source_cohort_ref") or ""), "source_mode": "materialized_exact_service_entry"}
        force.setdefault("materialized_assignments", {}).pop(officer_ref, None)
        validate_cohort_ledger(force)

        person["population_provenance"] = {
            "population_ref": f"population_{state}",
            "service_stratum": "active_military",
            "force_ref": force_ref,
            "source_stratum": source_stratum,
            "source_cohort_ref": cohort_ref or person.get("source_cohort_ref"),
            "entry_role": role,
            "entered_service_at": at,
            "source_petition_ref": petition.get("petition_ref"),
            "principle": "this exact recruit reclassifies one already conserved civilian body into state military service",
        }
        career = person.setdefault("career_state", {})
        if not isinstance(career, dict):
            career = {}; person["career_state"] = career
        previous_service_authority = petition.get("service_authority_ref")
        if isinstance(previous_service_authority, str) and previous_service_authority and previous_service_authority != state_ref:
            career["current_assignment_ref"] = None
            for appointment in career.get("appointments", []) if isinstance(career.get("appointments"), list) else []:
                if isinstance(appointment, dict) and appointment.get("assignment_ref") == previous_service_authority and str(appointment.get("status", "active")) == "active":
                    appointment["status"] = "released"
                    appointment["released_at"] = at
        career["current_professional_path"] = "state_military_staff_candidate" if entry_track == "staff" else "state_military_recruit"
        career["office_or_command"] = (
            f"{state.title()} state military staff candidate; no command appointment"
            if entry_track == "staff" else f"{state.title()} state military recruit; no command appointment"
        )
        career["career_changes"] = int(career.get("career_changes", 0)) + 1
        career.setdefault("appointments", []).append({
            "kind": "state_military_service_entry", "state_ref": state_ref, "force_ref": force_ref,
            "at": at, "source_petition_ref": petition.get("petition_ref"), "status": "active",
        })
        career["appointments"] = career["appointments"][-32:]
        rank = person.setdefault("military_rank", {})
        if not isinstance(rank, dict):
            rank = {}; person["military_rank"] = rank
        rank["grade"] = str(entry_rules.get("entry_rank_grade", "recruit"))
        rank["durable"] = True
        rank["entered_service_at"] = at
        person["service_status"] = "active_state_military_staff_candidate" if entry_track == "staff" else "active_state_military_recruit"

        state_doc["treasury_silver"] = int(state_doc.get("treasury_silver", 0)) - unit_cost
        self.put(population_path, population)
        self.put(force_path, force)
        self.put(state_path, state_doc)
        self.put(person_path, person)
        petition["status"] = "completed"
        petition["execution_status"] = "entered_state_military_reserve"
        petition["completed_at"] = at
        petition["entry_force_ref"] = force_ref
        petition["entry_role"] = role
        petition["service_entry_track"] = entry_track
        petition["source_stratum"] = source_stratum
        petition["entry_cost_silver"] = unit_cost

        # A combat recruit should not remain an unassigned reserve body forever.
        # Post the same conserved person to a real understrength formation when one
        # exists; physical travel remains a scheduled transfer. Staff candidates
        # deliberately remain uncommanded until a separate staff billet is lawful.
        if entry_track == "combatant":
            target_ref = self._service_entry_posting_target(state_ref, role, str(location))
            if target_ref:
                order_ref = self._create_transfer_order(
                    petition,
                    target_formation_ref=target_ref,
                    at=at,
                    request_kind="initial_posting",
                    already_detached=True,
                    source_formation_ref=None,
                    inherited_transfer={
                        "source_force_ref": force_ref,
                        "included_in_force_headcount": True,
                        "role": role,
                    },
                )
                petition["initial_posting_order_ref"] = order_ref
                petition["initial_posting_formation_ref"] = target_ref
                petition["execution_status"] = "entered_state_military_awaiting_initial_posting"

        # Completed petitions are historical transaction detail, not active hot
        # career state. The petition owner remains available if exact provenance is
        # needed while the person carries only current active references.
        current_person = copy.deepcopy(dict(self.read(person_path)))
        military_career = current_person.get("military_career_state") if isinstance(current_person.get("military_career_state"), dict) else {}
        refs = military_career.get("active_petition_refs", []) if isinstance(military_career, dict) else []
        if isinstance(refs, list):
            military_career["active_petition_refs"] = [ref for ref in refs if ref != str(petition.get("petition_ref", ""))]
            current_person["military_career_state"] = military_career
            self.put(person_path, current_person)
        return True

    def _execute_authorized_petition(self, petition_ref: str, at: str) -> None:
        path = self._petition_path(petition_ref)
        raw = self.read_optional(path)
        if not isinstance(raw, Mapping) or raw.get("status") != "authorized_handoff":
            return
        petition = copy.deepcopy(dict(raw))
        if petition.get("transfer_order_ref"):
            return
        request_kind = str(petition.get("request_kind", ""))
        if request_kind == "service_entry":
            self._execute_state_service_entry(petition, at)
            self.put(path, petition)
            return
        if request_kind == "foreign_service_request":
            petition["execution_status"] = "awaiting_interstate_or_allegiance_authority"
            petition["execution_blocker"] = "foreign service cannot be converted into an intra-state personnel transfer"
            self.put(path, petition)
            return
        officer_ref = str(petition["officer_ref"])
        if request_kind == "independent_command":
            target = self._independent_command_vacancy(str(petition["state_ref"]), officer_ref)
            if target is None:
                self._requeue_petition(petition, at, "no lawful vacant command currently exists", days=60)
                return
        else:
            desired = petition.get("desired_commander_ref")
            target = self._commander_target_formation(str(desired), str(petition["state_ref"])) if isinstance(desired, str) else None
            if target is None:
                self._requeue_petition(petition, at, "prospective commander has no current formation inside the approving military authority", days=30)
                return
        person_path, person = self._exact_person(officer_ref, active=False)
        current_ref, _current = self._person_current_formation(person)
        if current_ref == target:
            petition["status"] = "completed"
            petition["execution_status"] = "already_serving_in_target_formation"
            petition["completed_at"] = at
            self.put(path, petition)
            return
        try:
            order_ref = self._create_transfer_order(petition, target_formation_ref=target, at=at)
        except ValueError as exc:
            self._requeue_petition(petition, at, str(exc), days=30)
            return
        petition["transfer_order_ref"] = order_ref
        petition["execution_status"] = "ordered_in_transit"
        handoff = petition.get("personnel_action_handoff")
        if isinstance(handoff, dict):
            handoff["executed_by"] = "military_personnel_transfer"
            handoff["transfer_order_ref"] = order_ref
            handoff["rule"] = "actual reassignment executes through conserved force/formation accounting and physical travel"
        self.put(path, petition)
        career = copy.deepcopy(dict(person.get("military_career_state", {})))
        career["last_authorized_transfer_order_ref"] = order_ref
        updated_person = copy.deepcopy(dict(self.read(person_path)))
        updated_person["military_career_state"] = career
        self.put(person_path, updated_person)

    def _settle_transfer_order(self, host: Mapping[str, Any], at: str) -> None:
        order_ref = str(host.get("owner_ref", ""))
        index = self._transfer_index()
        path = index.get("orders", {}).get(order_ref)
        order0 = self.read_optional(path) if isinstance(path, str) else None
        if not isinstance(order0, Mapping) or str(order0.get("status", "")) not in _TRANSFER_ACTIVE:
            return
        order = copy.deepcopy(dict(order0))
        officer_ref = str(order["officer_ref"])
        person_path, person0 = self._exact_person(officer_ref, active=False)
        person = copy.deepcopy(dict(person0))
        self._set_person_location(person, str(order.get("destination_location_ref", self._person_location(person) or "")))
        self.put(person_path, person)
        target_ref = str(order["target_formation_ref"])
        try:
            _target_path, target = self._load_formation(target_ref)
        except ValueError:
            order["status"] = "blocked_target_missing"
            order["blocked_at"] = at
            self.put(str(path), order)
            return
        current_target_location = str(target.get("location_ref", ""))
        if current_target_location != str(order.get("destination_location_ref", "")):
            self._reroute_transfer(order, target_ref, at, "target formation moved while officer was in transit")
            return
        request_kind = str(order.get("request_kind", ""))
        desired = order.get("desired_commander_ref")
        if request_kind not in {"independent_command", "attachment_return"} and isinstance(desired, str):
            if target.get("commander_ref") != desired:
                replacement = self._commander_target_formation(desired, str(order["state_ref"]))
                if replacement and replacement != target_ref:
                    self._reroute_transfer(order, replacement, at, "prospective commander changed formation")
                    return
        if request_kind == "independent_command" and target.get("commander_ref"):
            replacement = self._independent_command_vacancy(str(order["state_ref"]), officer_ref)
            if replacement and replacement != target_ref:
                self._reroute_transfer(order, replacement, at, "authorized command vacancy was filled before arrival")
                return
            order["status"] = "blocked_vacancy_filled"
            order["blocked_at"] = at
            self.put(str(path), order)
            return
        if request_kind == "independent_command":
            target_path, target0 = self._load_formation(target_ref)
            target = copy.deepcopy(dict(target0))
            target["commander_ref"] = officer_ref
            target["command_authority"] = str(target.get("administrative_owner", order["state_ref"]))
            target["command_last_changed_at"] = at
            target["status"] = "formed" if str(target.get("status")) == "commander_vacant" else target.get("status")
            self.put(target_path, target)
            self._assign_commander_index(officer_ref, target_ref, replace=True)
            person = copy.deepcopy(dict(self.read(person_path)))
            person["current_formation_id"] = target_ref
            self._set_person_location(person, str(target.get("location_ref", "")))
            appointment = {
                "kind": "independent_military_command",
                "state_ref": order["state_ref"],
                "formation_ref": target_ref,
                "appointed_at": at,
                "source_petition_ref": order.get("petition_ref"),
                "status": "active",
            }
            person.setdefault("career_state", {}).setdefault("appointments", []).append(appointment)
            person["career_state"]["appointments"] = person["career_state"]["appointments"][-32:]
            person["military_transfer_state"] = {"status": "completed", "order_ref": order_ref, "completed_at": at}
            self.put(person_path, person)
        else:
            self._attach_person_to_formation(
                officer_ref,
                target_ref,
                at,
                included_in_force_headcount=bool(order.get("included_in_force_headcount", False)),
                source_force_ref=(str(order.get("source_force_ref")) if order.get("source_force_ref") else None),
                role=str(order.get("role", "command_personnel")),
                reason=request_kind or "approved career reassignment",
            )
        person = copy.deepcopy(dict(self.read(person_path)))
        if request_kind == "campaign_attachment":
            operation_ref = None
            for candidate_ref, _candidate_path, operation in iter_exact_operation_records(self):
                if target_ref in operation.get("formation_refs", []) and str(operation.get("status", "")) in _ACTIVE_OPERATION_STATES:
                    operation_ref = str(candidate_ref)
                    break
            review_due = str(CampaignTime.parse(at).add_seconds(int(self._military_rules()["personnel_transfer"]["attachment_review_days"]) * 86400))
            person["military_attachment_state"] = {
                "status": "active",
                "source_formation_ref": order.get("source_formation_ref"),
                "target_formation_ref": target_ref,
                "operation_ref": operation_ref,
                "started_at": at,
                "review_due_at": review_due,
                "source_order_ref": order_ref,
            }
            active = index.setdefault("active_attachments_by_state", {}).setdefault(str(order["state_ref"]), [])
            if order_ref not in active:
                active.append(order_ref)
                active.sort()
        elif request_kind == "attachment_return":
            person["military_attachment_state"] = {"status": "completed_return", "completed_at": at, "return_order_ref": order_ref}
        self.put(person_path, person)
        order["status"] = "completed"
        order["completed_at"] = at
        self.put(str(path), order)
        active_orders = index.setdefault("active_by_state", {}).setdefault(str(order["state_ref"]), [])
        index["active_by_state"][str(order["state_ref"])] = [ref for ref in active_orders if ref != order_ref]
        index["completed_count"] = int(index.get("completed_count", 0)) + 1
        if request_kind == "attachment_return":
            rows = index.setdefault("active_attachments_by_state", {}).setdefault(str(order["state_ref"]), [])
            index["active_attachments_by_state"][str(order["state_ref"])] = [ref for ref in rows if ref != str(order.get("return_for_order_ref", order.get("petition_ref", "")))]
        self.put(_TRANSFER_INDEX_PATH, index)
        petition_path = self._petition_path(str(order.get("petition_ref", "")))
        petition = self.read_optional(petition_path)
        if isinstance(petition, Mapping):
            petition = copy.deepcopy(dict(petition))
            petition["status"] = "completed"
            petition["execution_status"] = "assignment_completed"
            petition["completed_at"] = at
            self.put(petition_path, petition)
        person = copy.deepcopy(dict(self.read(person_path)))
        career = person.get("military_career_state") if isinstance(person.get("military_career_state"), dict) else {}
        refs = career.get("active_petition_refs", []) if isinstance(career, dict) else []
        if isinstance(refs, list):
            career["active_petition_refs"] = [ref for ref in refs if ref != order.get("petition_ref")]
            person["military_career_state"] = career
            self.put(person_path, person)
        history = copy.deepcopy(self.read("state/history/events/index.json"))
        history.setdefault("events", []).append({
            "event_id": f"military_personnel_transfer_{_digest([order_ref, at])}",
            "kind": "military_personnel_transfer_completed",
            "at": at,
            "officer_ref": officer_ref,
            "source_formation_ref": order.get("source_formation_ref"),
            "target_formation_ref": target_ref,
            "request_kind": request_kind,
            "petition_ref": order.get("petition_ref"),
            "administrative_ownership_changed": False,
        })
        write_history_index(self, history)
        if order.get("desired_commander_ref") == _PLAYER_REF:
            event_ref = f"event_military_personnel_arrival_{_digest([order_ref, at])}"
            summary = (
                f"The approved military personnel movement for {officer_ref} has completed. The officer has physically reached "
                f"{target_ref}. This changes assignment only through the existing force/formation authority and does not transfer state ownership."
            )
            # The transfer completing at a remote formation is world truth, not
            # instantaneous player knowledge.  Dispatch the local arrival report
            # from the formation's actual location and let the shared courier
            # host chase Wei if he moves before receipt.
            _dispatch_player_story_message(
                self, event_ref=event_ref, at=at, actor_ref=target_ref, source_owner_ref=target_ref,
                event_kind="military_personnel_arrival", process_kind="military_career_petition",
                transit_stage="officer_arrival_report_in_transit", delivered_stage="officer_arrived",
                delivered_summary=summary, route_label="military personnel arrival report",
                source_event_ref=(str(order.get("petition_ref")) if order.get("petition_ref") else None),
                source_location_ref=current_target_location,
            )
            # Arrival is already resolved.  The report is informational and must
            # not freeze unrelated chronology merely because it was dispatched.
            self._pending_wake_created = None

    def _settle_temporary_attachments(self, state_ref: str, at: str) -> None:
        index = self._transfer_index()
        rows = list(index.get("active_attachments_by_state", {}).get(state_ref, []))
        now = CampaignTime.parse(at)
        for source_order_ref in rows:
            source_path = index.get("orders", {}).get(source_order_ref)
            source_order = self.read_optional(source_path) if isinstance(source_path, str) else None
            if not isinstance(source_order, Mapping):
                continue
            officer_ref = str(source_order.get("officer_ref", ""))
            try:
                person_path, person0 = self._exact_person(officer_ref, active=False)
            except ValueError:
                continue
            person = copy.deepcopy(dict(person0))
            attachment = person.get("military_attachment_state")
            if not isinstance(attachment, Mapping) or attachment.get("status") != "active":
                continue
            operation_ref = attachment.get("operation_ref")
            operation_active = False
            if isinstance(operation_ref, str):
                resolved = exact_operation_record(self, operation_ref)
                operation = resolved[1] if resolved is not None else None
                operation_active = isinstance(operation, Mapping) and str(operation.get("status", "")) in _ACTIVE_OPERATION_STATES
            review_due = CampaignTime.parse(str(attachment.get("review_due_at", at)))
            if operation_active and now < review_due:
                continue
            source_formation_ref = attachment.get("source_formation_ref")
            if not isinstance(source_formation_ref, str):
                updated = copy.deepcopy(dict(attachment))
                updated["status"] = "awaiting_state_reassignment"
                updated["reviewed_at"] = at
                person["military_attachment_state"] = updated
                self.put(person_path, person)
                continue
            try:
                self._load_formation(source_formation_ref)
            except ValueError:
                updated = copy.deepcopy(dict(attachment))
                updated["status"] = "awaiting_state_reassignment"
                updated["reviewed_at"] = at
                person["military_attachment_state"] = updated
                self.put(person_path, person)
                continue
            current_ref, _current = self._person_current_formation(person)
            synthetic = {
                "petition_ref": str(source_order.get("petition_ref", "")),
                "officer_ref": officer_ref,
                "state_ref": state_ref,
                "request_kind": "attachment_return",
                "desired_commander_ref": None,
            }
            try:
                return_ref = self._create_transfer_order(
                    synthetic,
                    target_formation_ref=source_formation_ref,
                    at=at,
                    request_kind="attachment_return",
                    source_formation_ref=current_ref,
                )
            except ValueError:
                continue
            return_path = self._transfer_order_path(return_ref)
            return_order = copy.deepcopy(self.read(return_path))
            return_order["return_for_order_ref"] = source_order_ref
            self.put(return_path, return_order)
            updated = copy.deepcopy(dict(attachment))
            updated["status"] = "returning"
            updated["return_order_ref"] = return_ref
            person = copy.deepcopy(dict(self.read(person_path)))
            person["military_attachment_state"] = updated
            self.put(person_path, person)

    # ------------------------------------------------------------------
    # Organic exact-officer emergence from conserved formation bodies
    # ------------------------------------------------------------------

    @staticmethod
    def _emergent_officer_name(person_ref: str) -> str:
        surnames = ("Li", "Wang", "Meng", "Zhang", "Zhao", "Bai", "Fan", "Huan", "Gao", "Lu", "Tian", "Sun", "Jing", "Du", "Xu", "Han")
        givens = ("Ren", "Sheng", "Jun", "An", "Yi", "Ke", "Rui", "Zhen", "Bo", "Qian", "Yong", "Lin", "Jie", "He", "Tao", "Cheng")
        raw = int(hashlib.sha256(person_ref.encode("utf-8")).hexdigest()[:12], 16)
        return f"{surnames[raw % len(surnames)]} {givens[(raw // len(surnames)) % len(givens)]}"

    def _materialize_emergent_officer(
        self,
        formation_ref: str,
        *,
        at: str,
        evidence_ref: str,
        alignment_ref: str,
        state_ref: str | None,
    ) -> str | None:
        formation_path, formation0 = self._load_formation(formation_ref)
        formation = copy.deepcopy(dict(formation0))
        force_ref = str(formation.get("owner_force_ref", ""))
        if not force_ref:
            return None
        force_path = self.owner_path(force_ref)
        force = copy.deepcopy(self.read(force_path))
        ensure_formation_composition(force, formation, at=at)
        anonymous = int(formation.get("personnel", 0)) - formation_materialized_count(force, formation_ref)
        if anonymous <= 0:
            return None
        token = _digest([formation_ref, evidence_ref, at, "emergent_officer"])
        person_ref = f"char_emergent_officer_{token}"
        if self.read("state/index/owner-index.json").get("owners", {}).get(person_ref):
            return person_ref
        review = CampaignTime.parse(at)
        seed = int(hashlib.sha256(person_ref.encode("utf-8")).hexdigest()[:12], 16)
        age = 20 + seed % 19
        birth_year = review.bce_year + age
        person = {
            "schema": "sword-materialized-person",
            "owner_id": person_ref,
            "owner_type": "character",
            "id": person_ref,
            "name": self._emergent_officer_name(person_ref),
            "state": state_ref or _formation_state_ref(formation),
            "affiliation": str(formation.get("administrative_owner", "military")),
            "birth_date": f"{birth_year}-BCE-{1 + (seed // 19) % 12:02d}-{1 + (seed // 229) % 28:02d}",
            "status": "alive",
            "life_status": "active",
            "health_status": "healthy",
            "current_location": str(formation.get("location_ref", "")),
            "current_formation_id": formation_ref,
            "role": "field-elevated officer",
            "authority": f"acting internal officer of {formation_ref}",
            "attributes": {},
            "skills": {},
            "aptitude": {"physical_learning": 100, "technical_learning": 100, "tactical_learning": 110, "academic_learning": 100, "social_learning": 100},
            "development_state": {},
            "military_career_state": {
                "schema": "sword-military-career-state",
                "emergence_evidence_ref": evidence_ref,
                "emerged_at": at,
            },
            "military_alignment_state": {
                "status": "field_elevation",
                "effective_authority_ref": alignment_ref,
                "at": at,
                "evidence_ref": evidence_ref,
            },
        }
        roles = [str(role) for role, count in formation.get("composition", {}).items() if int(count) > 0]
        materialized = False
        selected_role = None
        for role in roles:
            try:
                self._ct_materialize_from_formation(force, formation, role=role, person_ref=person_ref, person=person)
            except ValueError:
                continue
            selected_role = role
            materialized = True
            break
        if not materialized or selected_role is None:
            return None
        formation.setdefault("embedded_person_refs", []).append(person_ref)
        formation["embedded_person_refs"] = list(dict.fromkeys(str(ref) for ref in formation["embedded_person_refs"]))
        force.setdefault("materialized_people", {})[person_ref] = {"personnel": 1, "role": selected_role, "source_cohort_ref": str(person.get("source_cohort_ref", "") or ""), "source_mode": "materialized_emergent_officer"}
        force.setdefault("materialized_assignments", {})[person_ref] = {
            "formation_ref": formation_ref,
            "role": selected_role,
            "personnel": 1,
        }
        person["equipment_custody"] = {
            "mode": "formation_issue_slot",
            "formation_ref": formation_ref,
            "role": selected_role,
            "principle": "field elevation reclassifies one existing formation body and creates no manpower or equipment",
        }
        if state_ref:
            loyalty = self._personal_loyalty(person, state_ref)
            try:
                self._command_person(alignment_ref, active=False)
            except (KeyError, ValueError, FileNotFoundError):
                alignment_is_person = False
            else:
                alignment_is_person = True
            if alignment_is_person:
                loyalty.setdefault("commander_bonds", {})[alignment_ref] = 720
            loyalty["formation_bond_milli"] = max(600, int(loyalty.get("formation_bond_milli", 400)))
        person_path = f"state/char/{person_ref.removeprefix('char_').replace('_', '-')}.json"
        validate_cohort_ledger(force)
        self.put(force_path, force)
        self.put(formation_path, formation)
        self.put(person_path, person)
        self._register_owner(person_ref, person_path)
        self._ensure_person_life_host(person_ref, review)
        history = copy.deepcopy(self.read("state/history/events/index.json"))
        history.setdefault("events", []).append({
            "event_id": f"military_officer_emergence_{token}",
            "kind": "military_officer_materialization",
            "at": at,
            "person_ref": person_ref,
            "formation_ref": formation_ref,
            "source_cohort_ref": person.get("source_cohort_ref"),
            "evidence_ref": evidence_ref,
            "personnel_delta": 0,
            "basis": "existing conserved formation member became command-relevant",
        })
        write_history_index(self, history)
        return person_ref

    # ------------------------------------------------------------------
    # Hierarchical allegiance-crisis resolution
    # ------------------------------------------------------------------

    def _named_officer_support_score(self, person: Mapping[str, Any], state_ref: str | None, proposed_ref: str) -> int:
        if _person_ref(person) == proposed_ref:
            return 1000
        loyalty = person.get("military_loyalty_state") if isinstance(person.get("military_loyalty_state"), Mapping) else {}
        state = int(loyalty.get("state_allegiance_milli", 720))
        institution = int(loyalty.get("institutional_professional_milli", 700))
        formation = int(loyalty.get("formation_bond_milli", 400))
        legitimacy = int(loyalty.get("legitimacy_belief_milli", 700))
        bonds = loyalty.get("commander_bonds") if isinstance(loyalty.get("commander_bonds"), Mapping) else {}
        resentment = loyalty.get("resentment_by_person") if isinstance(loyalty.get("resentment_by_person"), Mapping) else {}
        commander = int(bonds.get(proposed_ref, 250))
        resent = int(resentment.get(proposed_ref, 0))
        raw = 500 + (commander - 500) * 55 // 100 + (formation - 500) * 15 // 100
        raw -= (state - 500) * 25 // 100
        raw -= (institution - 500) * 20 // 100
        raw -= (legitimacy - 500) * 10 // 100
        raw -= resent * 25 // 100
        return _clamp(raw)

    def _formation_named_officer_refs(self, formation: Mapping[str, Any]) -> list[str]:
        refs: list[str] = []
        value = formation.get("commander_ref")
        if isinstance(value, str) and value:
            refs.append(value)
        for key in ("embedded_person_refs", "staff_refs", "notable_person_refs", "specialist_refs"):
            values = formation.get(key)
            if isinstance(values, list):
                refs.extend(str(value) for value in values if isinstance(value, str) and value)
        force_ref = formation.get("owner_force_ref")
        if isinstance(force_ref, str):
            try:
                force = self.read(self.owner_path(force_ref))
            except (KeyError, ValueError, FileNotFoundError):
                force = None
            if isinstance(force, Mapping):
                assignments = formation_materialized_assignments(force, str(formation.get("formation_ref", "")))
                refs.extend(assignments)
        return list(dict.fromkeys(refs))

    def _immediate_officer_support(self, formation_ref: str, proposed_ref: str) -> tuple[int, dict[str, dict[str, Any]]]:
        _path, formation = self._load_formation(formation_ref)
        loyalty = formation.get("military_loyalty_state") if isinstance(formation.get("military_loyalty_state"), Mapping) else {}
        bonds = loyalty.get("commander_bonds") if isinstance(loyalty.get("commander_bonds"), Mapping) else {}
        familiarity = loyalty.get("command_familiarity") if isinstance(loyalty.get("command_familiarity"), Mapping) else {}
        aggregate = 430 + int(bonds.get(proposed_ref, 250)) * 3 // 10 + int(familiarity.get(proposed_ref, 250)) // 8
        if formation.get("commander_ref") == proposed_ref:
            aggregate += 180
        aggregate = _clamp(aggregate)
        state_ref = _formation_state_ref(formation)
        named: dict[str, dict[str, Any]] = {}
        weighted = 0
        weight_total = 0
        world_seed = str(self.read("state/meta.json").get("world_seed", "sword"))
        for person_ref in self._formation_named_officer_refs(formation):
            if person_ref == proposed_ref:
                continue
            try:
                _pp, person = self._exact_person(person_ref, active=False)
            except ValueError:
                continue
            score = self._named_officer_support_score(person, state_ref, proposed_ref)
            role_weight = 4 if formation.get("commander_ref") == person_ref else 1
            weighted += score * role_weight
            weight_total += role_weight
            named[person_ref] = {"support_milli": score, "role_weight": role_weight, "seed": world_seed}
        named_mean = weighted // weight_total if weight_total else aggregate
        return _clamp(aggregate * 6 // 10 + named_mean * 4 // 10), named

    def _named_crisis_decisions(
        self,
        formation_ref: str,
        proposed_ref: str,
        crisis_ref: str,
    ) -> dict[str, dict[str, Any]]:
        _path, formation = self._load_formation(formation_ref)
        state_ref = _formation_state_ref(formation)
        world_seed = str(self.read("state/meta.json").get("world_seed", "sword"))
        decisions: dict[str, dict[str, Any]] = {}
        for person_ref in self._formation_named_officer_refs(formation):
            if person_ref == proposed_ref:
                decisions[person_ref] = {"decision": "follow", "basis": "declared_proposed_commander"}
                continue
            if person_ref == _PLAYER_REF:
                decisions[person_ref] = {"decision": "player_decision_required", "basis": "protected_player_agency"}
                continue
            try:
                _pp, person = self._exact_person(person_ref, active=False)
            except ValueError:
                continue
            support = self._named_officer_support_score(person, state_ref, proposed_ref)
            roll = int(hashlib.sha256(f"{world_seed}|{crisis_ref}|{formation_ref}|{person_ref}".encode("utf-8")).hexdigest()[:8], 16) % 1000
            decisions[person_ref] = {
                "decision": "follow" if roll < support else "remain_legal",
                "basis": "saved personal loyalty, state/professional obligation, commander bond, and deterministic crisis pressure",
            }
        return decisions

    def _crisis_state_legitimacy(self, formation: Mapping[str, Any], action: str, claimant_ref: str | None) -> int:
        loyalty = formation.get("military_loyalty_state") if isinstance(formation.get("military_loyalty_state"), Mapping) else {}
        axes = loyalty.get("axes") if isinstance(loyalty.get("axes"), Mapping) else self._military_rules()["formation_loyalty"]["default_axes"]
        base = int(axes.get("legitimacy_confidence", 700))
        legal = str(formation.get("administrative_owner", ""))
        if claimant_ref and claimant_ref == legal:
            base += 120
        if action == "defect":
            base += 80
        elif action == "defy_state_order":
            base -= 80
        elif action == "mutiny":
            base -= 30
        return _clamp(base)

    def _choose_crisis_outcome(self, estimate: Mapping[str, int], crisis_ref: str, formation_ref: str) -> str:
        follow = int(estimate["follow_proposed_commander_milli"])
        state = int(estimate["state_obedience_milli"])
        fragmentation = int(estimate["fragmentation_risk_milli"])
        follow_weight = max(1, follow * max(250, 1000 - fragmentation // 3))
        state_weight = max(1, state * max(250, 1000 - fragmentation // 3))
        fragment_weight = max(1, fragmentation * (650 + min(follow, state) // 3))
        total = follow_weight + state_weight + fragment_weight
        seed = str(self.read("state/meta.json").get("world_seed", "sword"))
        roll = int(hashlib.sha256(f"{seed}|{crisis_ref}|{formation_ref}|outcome".encode("utf-8")).hexdigest()[:12], 16) % total
        if roll < follow_weight:
            return "follow_proposed_commander"
        if roll < follow_weight + state_weight:
            return "remain_with_legal_authority"
        return "fragment"

    def _mark_person_alignment(self, person_ref: str, *, crisis_ref: str, effective_ref: str, legal_ref: str, decision: str, at: str) -> None:
        try:
            path, person0 = self._exact_person(person_ref, active=False)
        except ValueError:
            return
        person = copy.deepcopy(dict(person0))
        person["military_alignment_state"] = {
            "status": decision,
            "crisis_ref": crisis_ref,
            "effective_authority_ref": effective_ref,
            "legal_authority_ref": legal_ref,
            "at": at,
            "administrative_ownership_changed": False,
        }
        self.put(path, person)

    def _ensure_acting_commander(self, formation_ref: str, *, crisis_ref: str, alignment_ref: str, state_ref: str | None, at: str) -> str | None:
        path, formation0 = self._load_formation(formation_ref)
        formation = copy.deepcopy(dict(formation0))
        current = formation.get("commander_ref")
        if isinstance(current, str) and current:
            return current
        for person_ref in self._formation_named_officer_refs(formation):
            if person_ref == _PLAYER_REF and alignment_ref != _PLAYER_REF:
                continue
            try:
                _pp, person = self._exact_person(person_ref, active=False)
            except ValueError:
                continue
            alignment = person.get("military_alignment_state") if isinstance(person.get("military_alignment_state"), Mapping) else {}
            effective = alignment.get("effective_authority_ref")
            if effective not in {None, alignment_ref}:
                continue
            formation["commander_ref"] = person_ref
            formation["status"] = "formed" if formation.get("status") == "commander_vacant" else formation.get("status")
            self.put(path, formation)
            self._assign_commander_index(person_ref, formation_ref)
            return person_ref
        person_ref = self._materialize_emergent_officer(
            formation_ref,
            at=at,
            evidence_ref=crisis_ref,
            alignment_ref=alignment_ref,
            state_ref=state_ref,
        )
        if person_ref:
            path, formation0 = self._load_formation(formation_ref)
            formation = copy.deepcopy(dict(formation0))
            formation["commander_ref"] = person_ref
            formation["status"] = "formed" if formation.get("status") == "commander_vacant" else formation.get("status")
            formation["command_last_changed_at"] = at
            formation["command_origin"] = "field_elevation_from_conserved_internal_establishment"
            self.put(path, formation)
            self._assign_commander_index(person_ref, formation_ref)
        return person_ref

    def _apply_whole_follow(
        self,
        formation_ref: str,
        *,
        proposed_ref: str,
        crisis_ref: str,
        action: str,
        decisions: Mapping[str, Mapping[str, Any]],
        at: str,
    ) -> dict[str, Any]:
        _path, formation = self._load_formation(formation_ref)
        legal_ref = str(formation.get("administrative_owner", ""))
        for person_ref, decision in decisions.items():
            if decision.get("decision") != "remain_legal":
                continue
            self._detach_person_from_formation(person_ref, formation_ref, at, reason="officer refused formation allegiance shift")
            self._mark_person_alignment(person_ref, crisis_ref=crisis_ref, effective_ref=legal_ref, legal_ref=legal_ref, decision="remained_legal", at=at)
        path, current0 = self._load_formation(formation_ref)
        current = copy.deepcopy(dict(current0))
        current["command_authority"] = proposed_ref
        current["military_allegiance_state"] = {
            "status": action,
            "crisis_ref": crisis_ref,
            "effective_authority_ref": proposed_ref,
            "legal_administrative_owner_ref": legal_ref,
            "resolved_at": at,
            "administrative_ownership_changed": False,
        }
        self.put(path, current)
        commander = self._ensure_acting_commander(formation_ref, crisis_ref=crisis_ref, alignment_ref=proposed_ref, state_ref=_formation_state_ref(current), at=at)
        return {"formation_ref": formation_ref, "outcome": "follow_proposed_commander", "personnel": int(self._load_formation(formation_ref)[1].get("personnel", 0)), "commander_ref": commander}

    def _apply_whole_state(
        self,
        formation_ref: str,
        *,
        proposed_ref: str,
        crisis_ref: str,
        action: str,
        decisions: Mapping[str, Mapping[str, Any]],
        at: str,
    ) -> dict[str, Any]:
        _path, formation = self._load_formation(formation_ref)
        legal_ref = str(formation.get("administrative_owner", ""))
        for person_ref, decision in decisions.items():
            if decision.get("decision") != "follow":
                continue
            self._detach_person_from_formation(person_ref, formation_ref, at, reason="officer personally followed failed allegiance challenge")
            self._mark_person_alignment(person_ref, crisis_ref=crisis_ref, effective_ref=proposed_ref, legal_ref=legal_ref, decision="personal_following_without_unit", at=at)
        path, current0 = self._load_formation(formation_ref)
        current = copy.deepcopy(dict(current0))
        if current.get("commander_ref") == proposed_ref:
            current["commander_ref"] = None
            self._release_commander_index(proposed_ref, formation_ref)
        current["command_authority"] = legal_ref
        current["military_allegiance_state"] = {
            "status": "remained_with_legal_authority",
            "challenged_action": action,
            "crisis_ref": crisis_ref,
            "effective_authority_ref": legal_ref,
            "legal_administrative_owner_ref": legal_ref,
            "resolved_at": at,
            "administrative_ownership_changed": False,
        }
        if int(current.get("personnel", 0)) > 0 and not current.get("commander_ref"):
            current["status"] = "commander_vacant"
        self.put(path, current)
        commander = self._ensure_acting_commander(formation_ref, crisis_ref=crisis_ref, alignment_ref=legal_ref, state_ref=_formation_state_ref(current), at=at)
        return {"formation_ref": formation_ref, "outcome": "remain_with_legal_authority", "personnel": int(self._load_formation(formation_ref)[1].get("personnel", 0)), "commander_ref": commander}

    def _fragment_formation(
        self,
        formation_ref: str,
        *,
        proposed_ref: str,
        crisis_ref: str,
        action: str,
        estimate: Mapping[str, int],
        decisions: Mapping[str, Mapping[str, Any]],
        at: str,
    ) -> dict[str, Any]:
        parent_path, original0 = self._load_formation(formation_ref)
        original = copy.deepcopy(dict(original0))
        total = int(original.get("personnel", 0))
        if total <= 1:
            return self._apply_whole_state(formation_ref, proposed_ref=proposed_ref, crisis_ref=crisis_ref, action=action, decisions=decisions, at=at)
        force_ref = str(original.get("owner_force_ref", ""))
        force_path = self.owner_path(force_ref)
        force = copy.deepcopy(self.read(force_path))
        ensure_formation_composition(force, original, at=at)
        assignments = formation_materialized_assignments(force, formation_ref)
        follower_exact = [ref for ref in assignments if decisions.get(ref, {}).get("decision") == "follow"]
        legal_exact = [ref for ref in assignments if decisions.get(ref, {}).get("decision") != "follow"]
        exact_count = formation_materialized_count(force, formation_ref)
        anonymous_total = max(0, total - exact_count)
        desired = int(round(total * int(estimate["follow_proposed_commander_milli"]) / 1000.0))
        minimum = len(follower_exact)
        maximum = total - len(legal_exact)
        desired = max(minimum, min(maximum, desired))
        desired = max(1, min(total - 1, desired))
        anonymous_follow = max(0, min(anonymous_total, desired - len(follower_exact)))
        desired = anonymous_follow + len(follower_exact)
        if desired <= 0:
            return self._apply_whole_state(formation_ref, proposed_ref=proposed_ref, crisis_ref=crisis_ref, action=action, decisions=decisions, at=at)
        if desired >= total:
            return self._apply_whole_follow(formation_ref, proposed_ref=proposed_ref, crisis_ref=crisis_ref, action=action, decisions=decisions, at=at)
        child_ref = f"formation_{_slug(formation_ref.removeprefix('formation_'))}_alignment_{_digest([crisis_ref, formation_ref])[:12]}"
        parent = copy.deepcopy(original)
        parent["personnel"] = total - anonymous_follow
        parent_comp, child_comp = self._partition_counts(original.get("composition", {}), anonymous_follow, total)
        parent["composition"] = parent_comp
        child = copy.deepcopy(original)
        child["formation_ref"] = child_ref
        child["name"] = f"{original.get('name', formation_ref)} Following Detachment"
        child["personnel"] = anonymous_follow
        child["composition"] = child_comp
        child["commander_ref"] = None
        child["embedded_person_refs"] = []
        child["staff_refs"] = []
        child["status"] = "fragmented_alignment"
        parent["logistics"], child["logistics"] = self._partition_material(original.get("logistics", {}), desired, total)
        parent["mounts"], child["mounts"] = self._partition_material(original.get("mounts", {}), desired, total)
        parent_eq, child_eq = self._partition_material(self._equipment_units(original), desired, total)
        parent_shields, child_shields = self._partition_material(self._shield_units(original), desired, total)
        parent_armor, child_armor = self._partition_material(self._armor_units(original), desired, total)
        self._set_equipment_units(parent, parent_eq)
        self._set_equipment_units(child, child_eq)
        self._set_shield_units(parent, parent_shields)
        self._set_shield_units(child, child_shields)
        self._set_armor_units(parent, parent_armor)
        self._set_armor_units(child, child_armor)
        force.setdefault("allocated_to_formations", {})[formation_ref] = {"personnel": parent["personnel"], "composition": copy.deepcopy(parent_comp)}
        force.setdefault("allocated_to_formations", {})[child_ref] = {"personnel": child["personnel"], "composition": copy.deepcopy(child_comp)}
        parent["cohort_composition"] = copy.deepcopy(original.get("cohort_composition", []))
        child["cohort_composition"] = []
        partition_formation_slices(force, parent, child, anonymous_follow)
        for person_ref in follower_exact:
            assignment = force.setdefault("materialized_assignments", {}).get(person_ref)
            if not isinstance(assignment, MutableMapping):
                continue
            role = str(assignment.get("role", next(iter(original.get("composition", {})), "line_infantry")))
            assignment["formation_ref"] = child_ref
            parent["personnel"] = int(parent.get("personnel", 0)) - 1
            child["personnel"] = int(child.get("personnel", 0)) + 1
            parent.setdefault("composition", {})[role] = max(0, int(parent.get("composition", {}).get(role, 0)) - 1)
            child.setdefault("composition", {})[role] = int(child.get("composition", {}).get(role, 0)) + 1
            self._set_force_allocation(force, formation_ref, -1, role)
            self._set_force_allocation(force, child_ref, 1, role)
            self._remove_person_from_formation_lists(parent, person_ref)
            refs = child.setdefault("embedded_person_refs", [])
            if person_ref not in refs:
                refs.append(person_ref)
            try:
                person_path, person0 = self._exact_person(person_ref, active=False)
                person = copy.deepcopy(dict(person0))
                person["current_formation_id"] = child_ref
                person["military_alignment_state"] = {
                    "status": "followed_fragment",
                    "crisis_ref": crisis_ref,
                    "effective_authority_ref": proposed_ref,
                    "legal_authority_ref": str(original.get("administrative_owner", "")),
                    "at": at,
                    "administrative_ownership_changed": False,
                }
                self.put(person_path, person)
            except ValueError:
                pass
        legal_ref = str(original.get("administrative_owner", ""))
        original_commander = original.get("commander_ref")
        if isinstance(original_commander, str) and (
            original_commander == proposed_ref or decisions.get(original_commander, {}).get("decision") == "follow"
        ):
            parent["commander_ref"] = None
            child["commander_ref"] = original_commander
            self._release_commander_index(original_commander, formation_ref)
        else:
            parent["commander_ref"] = original_commander
        parent["command_authority"] = legal_ref
        child["command_authority"] = proposed_ref
        parent["cohesion"] = max(0, int(parent.get("cohesion", 50)) - 18)
        child["cohesion"] = max(0, int(child.get("cohesion", 50)) - 18)
        parent["military_allegiance_state"] = {
            "status": "fragmented_legal_remnant",
            "crisis_ref": crisis_ref,
            "effective_authority_ref": legal_ref,
            "legal_administrative_owner_ref": legal_ref,
            "resolved_at": at,
            "administrative_ownership_changed": False,
        }
        child["military_allegiance_state"] = {
            "status": f"fragmented_{action}",
            "crisis_ref": crisis_ref,
            "effective_authority_ref": proposed_ref,
            "legal_administrative_owner_ref": legal_ref,
            "resolved_at": at,
            "administrative_ownership_changed": False,
            "source_formation_ref": formation_ref,
        }
        child_path = f"state/formations/{child_ref.removeprefix('formation_').replace('_', '-')}.json"
        validate_cohort_ledger(force)
        self.put(force_path, force)
        self.put(parent_path, parent)
        self.put(child_path, child)
        self._register_owner(child_ref, child_path)
        self._index_formation_location(child_ref, None, str(child.get("location_ref", "")))
        if child.get("commander_ref"):
            self._assign_commander_index(str(child["commander_ref"]), child_ref, replace=True)
        child_commander = self._ensure_acting_commander(child_ref, crisis_ref=crisis_ref, alignment_ref=proposed_ref, state_ref=_formation_state_ref(child), at=at)
        parent_commander = self._ensure_acting_commander(formation_ref, crisis_ref=crisis_ref, alignment_ref=legal_ref, state_ref=_formation_state_ref(parent), at=at)
        return {
            "formation_ref": formation_ref,
            "outcome": "fragment",
            "legal_remnant_personnel": int(self._load_formation(formation_ref)[1].get("personnel", 0)),
            "following_formation_ref": child_ref,
            "following_personnel": int(self._load_formation(child_ref)[1].get("personnel", 0)),
            "legal_commander_ref": parent_commander,
            "following_commander_ref": child_commander,
        }

    def _resolve_military_allegiance_action(self, command: CommandEnvelope, payload: Mapping[str, Any]) -> dict[str, Any]:
        at = str(self.read(_RUNTIME_PATH)["world_time"])
        action = str(payload["action"])
        proposed_ref = str(payload.get("proposed_commander_ref") or command.actor_id)
        claimant_ref = str(payload.get("claimant_ref")) if payload.get("claimant_ref") else None
        formation_refs = [str(ref) for ref in payload.get("formation_refs", [])]
        crisis_ref = f"military_allegiance_crisis_{_digest([command.semantic_digest, action, proposed_ref, formation_refs, at])}"
        results: list[dict[str, Any]] = []
        internal_truth: list[dict[str, Any]] = []
        for formation_ref in formation_refs:
            self._update_formation_loyalty(formation_ref, at)
            _path, formation = self._load_formation(formation_ref)
            support, _support_detail = self._immediate_officer_support(formation_ref, proposed_ref)
            legitimacy = self._crisis_state_legitimacy(formation, action, claimant_ref)
            estimate = self.evaluate_formation_allegiance(
                formation_ref,
                proposed_commander_ref=proposed_ref,
                order_legitimacy_milli=legitimacy,
                immediate_officer_support_milli=support,
            )
            decisions = self._named_crisis_decisions(formation_ref, proposed_ref, crisis_ref)
            outcome = self._choose_crisis_outcome(estimate, crisis_ref, formation_ref)
            if outcome == "follow_proposed_commander":
                result = self._apply_whole_follow(formation_ref, proposed_ref=proposed_ref, crisis_ref=crisis_ref, action=action, decisions=decisions, at=at)
            elif outcome == "remain_with_legal_authority":
                result = self._apply_whole_state(formation_ref, proposed_ref=proposed_ref, crisis_ref=crisis_ref, action=action, decisions=decisions, at=at)
            else:
                result = self._fragment_formation(formation_ref, proposed_ref=proposed_ref, crisis_ref=crisis_ref, action=action, estimate=estimate, decisions=decisions, at=at)
            visible_named = {ref: row.get("decision") for ref, row in decisions.items() if row.get("decision") in {"follow", "remain_legal", "player_decision_required"}}
            result["named_officer_outcomes"] = visible_named
            results.append(result)
            internal_truth.append({"formation_ref": formation_ref, "estimate": dict(estimate), "immediate_officer_support_milli": support, "named_decisions": copy.deepcopy(decisions), "outcome": outcome})
        history = copy.deepcopy(self.read("state/history/events/index.json"))
        history.setdefault("events", []).append({
            "event_id": crisis_ref,
            "kind": "military_allegiance_crisis",
            "at": at,
            "action": action,
            "proposed_commander_ref": proposed_ref,
            "claimant_ref": claimant_ref,
            "formation_refs": formation_refs,
            "results": internal_truth,
            "rule": "resolved through exact formation hierarchy and loyalty; administrative ownership changes only through separate legal authority",
        })
        write_history_index(self, history)
        event_ref = f"event_{crisis_ref}"
        summary = (
            f"A military allegiance crisis has resolved across {len(formation_refs)} formation(s). Units and officers responded separately through "
            "their saved state, institutional, formation, commander, and legitimacy ties; no army-wide player conversion rule was used."
        )
        _event_owner_write(self, event_ref, {
            "event_ref": event_ref,
            "kind": "military_allegiance_crisis",
            "status": "triggered",
            "due_at": at,
            "triggered_at": at,
            "actor_ref": proposed_ref,
            "target_ref": command.actor_id,
            "process_kind": "military_allegiance",
            "process_stage": "resolved",
            "summary": summary,
            "delivery": _player_delivery(self, "immediate command reports"),
        }, at, source_owner_ref=proposed_ref)
        world_time, metrics = self._advance_seconds(3600)
        return {
            "crisis_ref": crisis_ref,
            "action": action,
            "proposed_commander_ref": proposed_ref,
            "formation_results": results,
            "administrative_ownership_changed": False,
            "world_time": world_time,
            **metrics,
        }

    # ------------------------------------------------------------------
    # Production hook integration
    # ------------------------------------------------------------------

    def _settle_petitions(self, state_ref: str, at: str) -> None:
        before = self._petition_index()
        refs = list(before.get("pending_by_state", {}).get(state_ref, []))
        super()._settle_petitions(state_ref, at)
        for petition_ref in refs:
            if isinstance(petition_ref, str):
                self._execute_authorized_petition(petition_ref, at)
        self._settle_temporary_attachments(state_ref, at)
        network = self._career_network()
        commander_refs: set[str] = set()
        for commander_ref in network.get("career_interest", {}).get(state_ref, {}):
            if isinstance(commander_ref, str):
                commander_refs.add(commander_ref)
        for commander_ref in network.get("public_commander_refs", []):
            if not isinstance(commander_ref, str):
                continue
            dossier = self._career_dossier(commander_ref)
            if isinstance(dossier, Mapping) and dossier.get("state_ref") == state_ref:
                commander_refs.add(commander_ref)
        for commander_ref in sorted(commander_refs):
            self._career_concentration_event(
                state_ref=state_ref,
                commander_ref=commander_ref,
                concentration_milli=self._political_concentration(state_ref, commander_ref),
                at=at,
            )

    # Due-host settlement is centrally dispatched by time_integration.py.

    def _validate_command_semantics(self, command: CommandEnvelope, payload: Mapping[str, Any]) -> None:
        super()._validate_command_semantics(command, payload)
        if command.command_type != "military_allegiance_action":
            return
        action = str(payload.get("action", ""))
        if action not in _CRISIS_ACTIONS:
            raise ValueError("unsupported military allegiance action")
        refs = payload.get("formation_refs")
        if not isinstance(refs, list) or not refs or len(refs) > 64 or len(set(map(str, refs))) != len(refs):
            raise ValueError("military allegiance action requires 1-64 distinct formation_refs")
        proposed = str(payload.get("proposed_commander_ref") or command.actor_id)
        self._exact_person(proposed, active=False)
        for ref in refs:
            _path, formation = self._load_formation(str(ref))
            if int(formation.get("personnel", 0)) <= 0:
                raise ValueError("military allegiance action requires living formations")
        claimant = payload.get("claimant_ref")
        if claimant is not None and (not isinstance(claimant, str) or not claimant):
            raise ValueError("claimant_ref must be a non-empty saved reference when supplied")

    def _authorize_command(self, command: CommandEnvelope, payload: Mapping[str, Any]) -> None:
        super()._authorize_command(command, payload)
        if command.command_type != "military_allegiance_action" or command.actor_id == self.INTERNAL_ACTOR:
            return
        proposed = str(payload.get("proposed_commander_ref") or command.actor_id)
        if proposed != command.actor_id:
            raise PermissionError("player may initiate a military allegiance crisis only for their own declared command position")
        for ref in payload.get("formation_refs", []):
            if not self._has_formation_authority(command.actor_id, str(ref)):
                raise PermissionError("military allegiance crisis may be initiated only within formations the player currently commands")
        # A player-authored allegiance break is an immediate, contested command
        # act, not an abstract ownership toggle.  The runtime currently has no
        # delayed remote-allegiance command message owner, so fail closed unless
        # Tang Wei is physically present with every affected formation.  Without
        # this boundary a remote formation could mutiny/defect at the same instant
        # the player spoke elsewhere and the command result would leak the exact
        # remote outcome back to Wei immediately.
        player_location = player_command_location(self)
        if not player_location:
            raise PermissionError("military allegiance crisis requires Tang Wei's exact current location")
        for ref in payload.get("formation_refs", []):
            _path, formation = self._load_formation(str(ref))
            if str(formation.get("location_ref") or "") != player_location:
                raise PermissionError(
                    "remote military allegiance action requires a physical command-message route; "
                    "Tang Wei must be co-located with the affected formation for the immediate crisis command"
                )

    def _command_layer_military_career_loyalty_politics(self, command: CommandEnvelope, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
        if command.command_type == "military_allegiance_action":
            result = self._resolve_military_allegiance_action(command, payload)
            self._write_meta(command, str(result["world_time"]))
            return self._result(**result)
        return next_dispatch()


__all__ = ["MilitaryCareerLoyaltyPoliticsMixin"]
