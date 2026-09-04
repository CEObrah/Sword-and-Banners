"""Durable small-unit, information, investigation, commission and care mechanics.

These systems extend existing authoritative owners rather than creating alternate
military or social truth. Command groups remain command-only nodes with zero
manpower. Information records distinguish a claim from world truth and preserve
per-holder provenance. Investigations discover only pre-existing indexed claims.
Commissions precommit their assignment before player tactics. Medical treatment
changes recovery state through exact practitioners and elapsed time.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.operation_routing import exact_operation_record
from sword_runtime.information_routing import information_claim_refs_for_subject

from sword_runtime.anatomy import anatomy_activity_factor
from sword_runtime.fatigue import RULES_PATH as FATIGUE_RULES_PATH, settle_formation_idle_fatigue, settle_person_idle_fatigue, stamp_formation_activity_fatigue, stamp_person_activity_fatigue
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.command_units import FORMATION, NESTED_ARMY, append_unit, formation_refs, move_unit, nested_army_refs, remove_unit, replace_unit, unit_entries
from sword_runtime.campaign_communications import command_message_route, command_person_location
from sword_runtime.command_authority import command_routing_from_groups, person_order_authority, primary_person_routing_from_groups, staff_routing_from_groups
from sword_runtime.cohort_tx_support import project_person_lite_stats
from sword_runtime.officer_cadre import (
    ensure_officer_cadre, register_materialized_rank, remove_internal_rank_body, reorganize_officer_cadre,
)
from sword_runtime.person_lite_store import promote_person_lite_to_full, put_person_lite
from sword_runtime.officer_personnel import sync_materialized_officer_billets
from sword_runtime.operational_logistics import recursive_army_movement_plan
from sword_runtime.personal_combat import advance_injury_physiology, sync_injury_record
from sword_runtime.training_programs import (
    REGISTRY_PATH as TRAINING_PROGRAM_REGISTRY_PATH,
    resolve_program_ref as resolve_training_program_ref,
    settle_exact_program, settle_person_lite_program,
)
from sword_runtime.training_instructors import exact_person_drill_access, instructor_contexts_for_program
from sword_runtime.training_facilities import training_environment
from sword_runtime.training_promotion import exact_promotion_facts
from sword_runtime.stat_access import merged_skill_map
from sword_runtime.military_doctrine import default_command_group_doctrine_ref
from sword_runtime.military_loadouts import officer_loadout_id
from sword_runtime.unit_establishment import authorized_strength_for, formation_class_for, hierarchy_rows

_CROSS_TYPES = frozenset({
    "command_group_action", "command_group_train", "investigation_action",
    "commission_action", "medical_treatment", "commitment_action",
})
_INFO_KINDS = frozenset({"observation", "report", "inference", "rumor", "testimony", "document", "captured_document", "estimate", "official_report"})
_INFO_CHANNELS = {
    "spoken": 980,
    "written_message": 970,
    "official_report": 990,
    "courier": 960,
    "scout_report": 950,
    "merchant_network": 880,
    "prisoner_testimony": 820,
}
_PLAYER_RETINUE_ROOT = "cmdgrp.tang_wei.personal_force"
_EVIDENCE_STATUS = frozenset({"runtime_established", "verified_evidence", "official_record"})


def _safe_ref(value: Any, prefix: str, label: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) > 180:
        raise ValueError(f"{label} must use {prefix} namespace")
    if any(ch in value for ch in ("/", "\\", "..")):
        raise ValueError(f"{label} contains an unsafe path fragment")
    return value


def _person_skills(person: Mapping[str, Any]) -> Mapping[str, Any]:
    return merged_skill_map(person)


def _person_attrs(person: Mapping[str, Any]) -> Mapping[str, Any]:
    if str(person.get("schema")) == "person-lite" and isinstance(person.get("stats"), Mapping):
        attrs = person.get("stats", {}).get("attributes", {})
    else:
        attrs = person.get("attributes", {})
    return attrs if isinstance(attrs, Mapping) else {}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _group_path(ref: str) -> str:
    _safe_ref(ref, "cmdgrp.", "command_group_ref")
    return f"state/cmd/command-groups/{ref}.json"


def _investigation_path(ref: str) -> str:
    _safe_ref(ref, "investigation.", "investigation_ref")
    return f"state/investigations/{ref}.json"


def _commission_request_path(ref: str) -> str:
    _safe_ref(ref, "commission.request.", "request_ref")
    return f"state/commissions/requests/{ref}.json"


def _commission_path(ref: str) -> str:
    _safe_ref(ref, "commission.", "commission_ref")
    if ref.startswith("commission.request."):
        raise ValueError("commission_ref cannot use request namespace")
    return f"state/commissions/active/{ref}.json"


def _commitment_path(ref: str) -> str:
    _safe_ref(ref, "commitment.", "commitment_ref")
    return f"state/commitments/{ref}.json"


class CampaignDepthMixin:
    """Production mixin for persistent human-scale systems."""

    @staticmethod
    def _index_actor_ref(index: dict[str, Any], actor_ref: str, object_ref: str) -> None:
        by_actor = index.setdefault("by_actor", {})
        refs = by_actor.setdefault(actor_ref, [])
        if object_ref not in refs:
            refs.append(object_ref)
            refs.sort()

    @staticmethod
    def _set_actor_active(index: dict[str, Any], actor_ref: str, object_ref: str, active: bool) -> None:
        active_map = index.setdefault("active_by_actor", {})
        refs = active_map.setdefault(actor_ref, [])
        if active:
            if object_ref not in refs:
                refs.append(object_ref)
                refs.sort()
        elif object_ref in refs:
            refs[:] = [ref for ref in refs if ref != object_ref]
        if not refs:
            active_map.pop(actor_ref, None)

    @staticmethod
    def _index_status_ref(index: dict[str, Any], status: str, object_ref: str) -> None:
        by_status = index.setdefault("by_status", {})
        for refs in by_status.values():
            if isinstance(refs, list) and object_ref in refs:
                refs[:] = [ref for ref in refs if ref != object_ref]
        refs = by_status.setdefault(status, [])
        if object_ref not in refs:
            refs.append(object_ref)
            refs.sort()

    def _evidence_claim(self, actor_ref: str, evidence_ref: str, *, require_authoritative: bool = True) -> tuple[str, dict[str, Any]]:
        """Resolve evidence through the saved information authority.

        Player-authored strings are never evidence merely because they look like
        refs.  A player may cite only an exact information claim they already
        know, and mechanically consequential evidence must have been established
        by the runtime/world rather than authored as the player's assertion.
        """
        idx = self.read("state/information/index.json")
        path = idx.get("claims", {}).get(evidence_ref) if isinstance(idx, Mapping) else None
        if not isinstance(path, str):
            raise ValueError("evidence_ref must resolve to an exact saved information claim")
        claim = copy.deepcopy(self.read(path))
        if actor_ref != self.INTERNAL_ACTOR and actor_ref not in claim.get("knowers", []):
            raise PermissionError("evidence_ref must already be known by the acting exact person")
        origin = str(claim.get("origin_authority", "unspecified"))
        status = str(claim.get("claim_status", "unverified_claim"))
        if require_authoritative and origin != "runtime_established" and status not in _EVIDENCE_STATUS:
            raise ValueError("evidence_ref is a saved claim but not runtime-established evidence")
        return path, claim

    def _evidence_claims(self, actor_ref: str, refs: Sequence[str], *, require_authoritative: bool = True) -> list[dict[str, Any]]:
        if len(refs) != len(set(refs)):
            raise ValueError("evidence refs must be unique")
        return [self._evidence_claim(actor_ref, str(ref), require_authoritative=require_authoritative)[1] for ref in refs]

    def _command_group_index(self) -> dict[str, Any]:
        return copy.deepcopy(self.read("state/cmd/command-groups/index.json"))

    def _write_command_group_index(self, idx: dict[str, Any]) -> None:
        idx.setdefault("refs", [])
        idx["refs"] = sorted(set(str(ref) for ref in idx.get("refs", []) if isinstance(ref, str) and ref.startswith("cmdgrp.")))
        idx["count"] = len(idx["refs"])
        # All routing is a projection from exact command groups. A person may
        # command several groups and may also hold staff duty in another group.
        # Keep the complete command set and one deterministic primary read route.
        idx["command_person_groups"] = command_routing_from_groups(self.read, idx["refs"])
        idx["primary_person_group"] = primary_person_routing_from_groups(self.read, idx["refs"])
        idx["staff_person_groups"] = staff_routing_from_groups(self.read, idx["refs"])
        self.put("state/cmd/command-groups/index.json", idx)

    def _claim_primary_group_slot(self, idx: dict[str, Any], *, person_ref: str | None = None, formation_ref: str | None = None, group_ref: str) -> None:
        if person_ref:
            # Person membership and command are no longer forced into a single
            # slot. Exact groups are authoritative; _write_command_group_index
            # derives complete command/staff routing after the mutation.
            idx.setdefault("primary_person_group", {}).setdefault(person_ref, group_ref)
        if formation_ref:
            mapping = idx.setdefault("primary_formation_group", {})
            try:
                _formation_path, formation = self._load_formation(formation_ref)
            except (FileNotFoundError, KeyError, ValueError):
                formation = None
            exact_current = formation.get("higher_command_ref") if isinstance(formation, Mapping) else None
            if isinstance(exact_current, str) and exact_current and exact_current != group_ref:
                raise ValueError(f"{formation_ref} already has exact higher command {exact_current}")
            mapping[formation_ref] = group_ref

    def _advance_exact_or_reject(self, target: CampaignTime, label: str) -> dict[str, Any]:
        """Advance through the normal causal frontier without credit past an interrupt.

        Long-duration local work is atomic at the semantic-command layer. If an
        autonomous high-salience boundary stops chronology before the requested
        completion instant, rejecting here lets the surrounding transaction roll
        back rather than awarding hours that the campaign never actually reached.

        The causal runtime owns the advancing frontier, while ``state/meta.json``
        receives the command revision only once at final command settlement.  A
        multi-stage semantic action (for example command-staff muster followed by
        an army march) may nevertheless need to query the exact campaign time
        between elapsed stages.  Keep the staged meta *time* synchronized here
        without changing its revision; the command's final ``_write_meta`` still
        performs the single revision increment.  Failed previews discard both
        staged documents transactionally.
        """
        metrics = self._advance_runtime(str(target))
        runtime = self.read("state/runtime.json")
        actual = CampaignTime.parse(str(runtime.get("world_time")))
        if actual != target:
            raise ValueError(f"{label} crossed a player-facing causal boundary before completion")
        meta = copy.deepcopy(self.read("state/meta.json"))
        if str(meta.get("time")) != str(actual):
            meta["time"] = str(actual)
            self.put("state/meta.json", meta)
        return metrics

    def _validate_command_semantics(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._validate_command_semantics(command, payload)
        t = command.command_type
        if t == "command_group_action":
            action = str(payload.get("action", ""))
            if action not in {"create", "add_person", "remove_person", "attach_formation", "detach_formation", "attach_command_group", "detach_command_group", "move_unit", "move_army", "promote_formation_to_army", "set_successors", "set_order", "set_communication", "set_doctrine", "set_establishment", "review_organization"}:
                raise ValueError("unsupported command-group action")
            ref = _safe_ref(payload.get("command_group_ref"), "cmdgrp.", "command_group_ref")
            if action == "create":
                self._exact_person(str(payload.get("commander_ref", "")))
                if payload.get("parent_ref") is not None:
                    _safe_ref(payload.get("parent_ref"), "cmdgrp.", "parent_ref")
            elif action in {"add_person", "remove_person"}:
                self._command_person(str(payload.get("person_ref", "")))
                if action == "add_person":
                    role = str(payload.get("role") or "").strip().casefold()
                    if role:
                        staff_doc = self.read("game/data/mechanics/command-staff.json")
                        staff_roles = staff_doc.get("roles", {}) if isinstance(staff_doc, Mapping) else {}
                        if role not in staff_roles:
                            raise ValueError("unknown registered command-staff role")
            elif action in {"attach_formation", "detach_formation"}:
                self._load_formation(str(payload.get("formation_ref", "")))
            elif action in {"attach_command_group", "detach_command_group"}:
                child_ref = _safe_ref(payload.get("subordinate_group_ref"), "cmdgrp.", "subordinate_group_ref")
                if child_ref == ref:
                    raise ValueError("a command group cannot contain itself")
                self.read(_group_path(child_ref))
            elif action == "move_unit":
                unit_ref = str(payload.get("formation_ref") or payload.get("subordinate_group_ref") or "")
                if not unit_ref:
                    raise ValueError("move_unit requires formation_ref or subordinate_group_ref")
                slot = payload.get("unit_slot")
                if isinstance(slot, bool) or not isinstance(slot, int) or slot < 1:
                    raise ValueError("unit_slot must be a positive integer")
            elif action == "move_army":
                destination_ref = str(payload.get("location_ref", ""))
                if not destination_ref:
                    raise ValueError("move_army requires location_ref destination")
                self._location_record(destination_ref)
            elif action == "promote_formation_to_army":
                self._load_formation(str(payload.get("formation_ref", "")))
                _safe_ref(payload.get("subordinate_group_ref"), "cmdgrp.", "subordinate_group_ref")
                if self.read_optional(_group_path(str(payload.get("subordinate_group_ref")))) is not None:
                    raise ValueError("promoted nested army command already exists")
            elif action == "set_successors":
                refs = payload.get("successor_refs")
                if not isinstance(refs, list) or len(refs) > 16 or len(refs) != len(set(refs)):
                    raise ValueError("successor_refs must be a unique bounded array")
                for person_ref in refs:
                    self._exact_person(str(person_ref))
            elif action == "set_order":
                order = payload.get("order")
                if not isinstance(order, str) or not order.strip() or len(order) > 500:
                    raise ValueError("standing order must be 1..500 characters")
                if payload.get("issuer_ref") is not None:
                    self._command_person(str(payload.get("issuer_ref")))
            elif action == "set_communication":
                value = payload.get("communication_ref")
                if value is not None and (not isinstance(value, str) or not value or len(value) > 160):
                    raise ValueError("communication_ref is invalid")
            elif action == "set_doctrine":
                doctrine_ref = str(payload.get("doctrine_ref") or "")
                if not doctrine_ref:
                    raise ValueError("set_doctrine requires doctrine_ref")
                doctrine_index = self.read("game/data/mil/doctrines.json").get("record_index", {})
                if doctrine_ref not in doctrine_index:
                    raise ValueError("unknown command-group doctrine_ref")
            if action != "create" and self.read_optional(_group_path(ref)) is None:
                raise ValueError("unknown command group")
        elif t == "command_group_train":
            ref = _safe_ref(payload.get("command_group_ref"), "cmdgrp.", "command_group_ref")
            if self.read_optional(_group_path(ref)) is None:
                raise ValueError("unknown command group")
            hours = payload.get("hours", 1)
            if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 12:
                raise ValueError("command-group training must consume 1..12 hours")
            focus = payload.get("focus")
            if focus is not None and (not isinstance(focus, str) or not focus or len(focus) > 120):
                raise ValueError("training focus is invalid")
        elif t == "investigation_action":
            action = str(payload.get("action", ""))
            if action not in {"start", "work", "close"}:
                raise ValueError("unsupported investigation action")
            ref = _safe_ref(payload.get("investigation_ref"), "investigation.", "investigation_ref")
            if action == "start":
                question = payload.get("question")
                if not isinstance(question, str) or not question.strip() or len(question) > 1000:
                    raise ValueError("investigation question is invalid")
                subject = payload.get("subject_ref")
                if not isinstance(subject, str) or not subject or len(subject) > 180:
                    raise ValueError("investigation subject_ref is required")
                if payload.get("location_ref") is not None:
                    self._location_record(str(payload.get("location_ref")))
                if self.read_optional(_investigation_path(ref)) is not None:
                    raise ValueError("investigation_ref already exists")
            else:
                if self.read_optional(_investigation_path(ref)) is None:
                    raise ValueError("unknown investigation")
                if action == "work":
                    hours = payload.get("hours", 1)
                    if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 24:
                        raise ValueError("investigation work must consume 1..24 hours")
            investigator = payload.get("investigator_ref")
            if investigator is not None:
                self._exact_person(str(investigator))
        elif t == "commission_action":
            action = str(payload.get("action", ""))
            if action not in {"request", "accept", "decline", "report"}:
                raise ValueError("unsupported commission action")
            if action == "request":
                _safe_ref(payload.get("request_ref"), "commission.request.", "request_ref")
                category = payload.get("category")
                if category is not None and (not isinstance(category, str) or not category or len(category) > 80):
                    raise ValueError("commission category is invalid")
                issuer = payload.get("issuer_ref")
                if issuer is not None:
                    self._validate_commission_issuer(str(issuer))
            else:
                _safe_ref(payload.get("commission_ref"), "commission.", "commission_ref")
                if action == "report":
                    refs = payload.get("evidence_refs", [])
                    if not isinstance(refs, list) or len(refs) > 32 or any(not isinstance(x, str) or not x for x in refs):
                        raise ValueError("commission evidence_refs must be a bounded exact-ref array")
                    self._evidence_claims(command.actor_id, [str(x) for x in refs], require_authoritative=True)
                    if payload.get("report_ref") is not None:
                        self._evidence_claim(command.actor_id, str(payload.get("report_ref")), require_authoritative=False)
        elif t == "medical_treatment":
            target = str(payload.get("target_ref", self.PLAYER_ACTOR))
            self._exact_person(target)
            practitioner = str(payload.get("practitioner_ref", self.PLAYER_ACTOR))
            self._exact_person(practitioner)
            treatment = str(payload.get("treatment", "treat"))
            if treatment not in {"stabilize", "treat", "surgery", "rehabilitation"}:
                raise ValueError("unsupported medical treatment")
            hours = payload.get("hours", 2)
            if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 24:
                raise ValueError("medical treatment must consume 1..24 hours")
            body_site = payload.get("body_site")
            if body_site is not None and (not isinstance(body_site, str) or not body_site or len(body_site) > 120):
                raise ValueError("body_site is invalid")
            facility_ref = payload.get("facility_ref")
            if facility_ref is not None:
                if not isinstance(facility_ref, str) or not facility_ref or len(facility_ref) > 180:
                    raise ValueError("facility_ref is invalid")
                if facility_ref.startswith("loc_"):
                    self._location_record(facility_ref)
                else:
                    self.owner(facility_ref)
            medical_supply_ref = payload.get("medical_supply_ref")
            if medical_supply_ref is not None:
                if not isinstance(medical_supply_ref, str) or not medical_supply_ref or len(medical_supply_ref) > 180:
                    raise ValueError("medical_supply_ref is invalid")
                _sp, supply = self.owner(medical_supply_ref)
                stocks = supply.get("stocks") if isinstance(supply, Mapping) else None
                if not isinstance(stocks, Mapping) or isinstance(stocks.get("medicine_lots"), bool) or not isinstance(stocks.get("medicine_lots"), int):
                    raise ValueError("medical_supply_ref must route to exact medicine_lots stock")
        elif t == "commitment_action":
            action = str(payload.get("action", ""))
            if action not in {"create", "fulfill", "confirm_fulfillment", "breach", "release"}:
                raise ValueError("unsupported commitment action")
            ref = _safe_ref(payload.get("commitment_ref"), "commitment.", "commitment_ref")
            if action == "create":
                obligor = payload.get("obligor_ref")
                beneficiary = payload.get("beneficiary_ref")
                if not isinstance(obligor, str) or not obligor or not isinstance(beneficiary, str) or not beneficiary:
                    raise ValueError("commitment parties are required")
                description = payload.get("description")
                if not isinstance(description, str) or not description.strip() or len(description) > 1200:
                    raise ValueError("commitment description is invalid")
                if payload.get("due_at") is not None:
                    due = CampaignTime.parse(str(payload.get("due_at")))
                    if due <= self._world_time():
                        raise ValueError("commitment due_at must be in the future")
                if self.read_optional(_commitment_path(ref)) is not None:
                    raise ValueError("commitment_ref already exists")
            elif self.read_optional(_commitment_path(ref)) is None:
                raise ValueError("unknown commitment")
            if action == "fulfill":
                evidence = payload.get("evidence_ref")
                if not isinstance(evidence, str) or not evidence:
                    raise ValueError("fulfillment claim requires exact evidence_ref")
                self._evidence_claim(command.actor_id, evidence, require_authoritative=True)

        if t == "information_create":
            kind = str(payload.get("epistemic_kind", "observation"))
            if kind not in _INFO_KINDS:
                raise ValueError("unsupported epistemic_kind")
            cm = payload.get("confidence_milli", 1000)
            if isinstance(cm, bool) or not isinstance(cm, int) or not 0 <= cm <= 1000:
                raise ValueError("confidence_milli must be 0..1000")
            dm = payload.get("discoverability_milli", 500)
            if isinstance(dm, bool) or not isinstance(dm, int) or not 0 <= dm <= 1000:
                raise ValueError("discoverability_milli must be 0..1000")
            evidence = payload.get("evidence_refs", [])
            if not isinstance(evidence, list) or len(evidence) > 32 or any(not isinstance(x, str) or not x for x in evidence):
                raise ValueError("evidence_refs must be a bounded exact-ref array")
            if payload.get("location_ref") is not None:
                self._location_record(str(payload.get("location_ref")))
            if command.actor_id != self.INTERNAL_ACTOR:
                if payload.get("evidence_refs"):
                    raise PermissionError("player-authored information cannot self-assert authoritative evidence")
                if "discoverability_milli" in payload:
                    raise PermissionError("investigation discoverability is runtime-owned")
        elif t == "information_deliver":
            channel = str(payload.get("channel", "courier"))
            if channel not in _INFO_CHANNELS:
                raise ValueError("unsupported information delivery channel")

    def _authorize_command(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._authorize_command(command, payload)
        if command.actor_id == self.INTERNAL_ACTOR:
            return
        t = command.command_type
        if t in {"command_group_action", "command_group_train"}:
            action = str(payload.get("action", ""))
            if t == "command_group_action" and action == "create":
                commander = str(payload.get("commander_ref"))
                self._require_person_in_player_command(command.actor_id, commander)
                parent = payload.get("parent_ref")
                if parent is not None:
                    self._require_command_group_authority(command.actor_id, str(parent))
            else:
                operational_staff_actions = {"set_order", "move_army", "set_communication"}
                self._require_command_group_authority(
                    command.actor_id,
                    str(payload.get("command_group_ref")),
                    allow_strategist=(t == "command_group_action" and action in operational_staff_actions),
                )
            if t == "command_group_action" and action in {"add_person", "set_successors"}:
                refs: list[str] = []
                if action == "add_person": refs = [str(payload.get("person_ref"))]
                else: refs = [str(x) for x in payload.get("successor_refs", [])]
                for ref in refs: self._require_person_in_player_command(command.actor_id, ref)
            if t == "command_group_action" and action == "set_order" and payload.get("issuer_ref") is not None:
                issuer_ref = str(payload.get("issuer_ref"))
                self._require_person_in_player_command(command.actor_id, issuer_ref)
                delegated = person_order_authority(
                    self.read, person_ref=issuer_ref, target_group_ref=str(payload.get("command_group_ref"))
                )
                if not delegated.get("allowed"):
                    raise PermissionError("delegated order issuer lacks scoped authority over this command-group subtree")
            if t == "command_group_action" and action in {"attach_formation", "detach_formation", "promote_formation_to_army"}:
                self._require_formation_authority(command.actor_id, str(payload.get("formation_ref")))
            if t == "command_group_action" and action in {"attach_command_group", "detach_command_group"}:
                self._require_command_group_authority(command.actor_id, str(payload.get("subordinate_group_ref")))
        elif t == "investigation_action":
            investigator = str(payload.get("investigator_ref", command.actor_id))
            if investigator != command.actor_id:
                self._require_person_in_player_command(command.actor_id, investigator)
        elif t == "commission_action":
            if str(payload.get("action")) == "request":
                self._require_commission_request_access(command.actor_id, str(payload.get("issuer_ref") or "house_tang"))
            if str(payload.get("action")) in {"accept", "decline", "report"}:
                doc = self.read(_commission_path(str(payload.get("commission_ref"))))
                if str(doc.get("assignee_ref")) != command.actor_id:
                    raise PermissionError("player may act only on commissions assigned to them")
        elif t == "medical_treatment":
            target = str(payload.get("target_ref", command.actor_id))
            practitioner = str(payload.get("practitioner_ref", command.actor_id))
            if target != command.actor_id:
                self._require_person_in_player_command(command.actor_id, target)
            if practitioner != command.actor_id:
                self._require_person_in_player_command(command.actor_id, practitioner)
        elif t == "commitment_action":
            action = str(payload.get("action"))
            if action == "create":
                if str(payload.get("obligor_ref")) != command.actor_id:
                    raise PermissionError("player may create only their own voluntary commitment")
            else:
                doc = self.read(_commitment_path(str(payload.get("commitment_ref"))))
                if action in {"fulfill", "breach"} and str(doc.get("obligor_ref")) != command.actor_id:
                    raise PermissionError("only the obligor may claim fulfillment or breach this commitment")
                if action in {"confirm_fulfillment", "release"} and str(doc.get("beneficiary_ref")) != command.actor_id:
                    raise PermissionError("only the beneficiary may confirm fulfillment or release this commitment")

        if t == "information_create" and command.actor_id != self.INTERNAL_ACTOR:
            if payload.get("evidence_refs") or "discoverability_milli" in payload:
                raise PermissionError("player-authored claims cannot define evidence or investigation discoverability")

    def _validate_commission_issuer(self, ref: str) -> None:
        if ref.startswith("state_"):
            self._state_key(ref)
            return
        self.owner(ref)

    def _require_commission_request_access(self, actor_ref: str, issuer_ref: str) -> None:
        if actor_ref == self.INTERNAL_ACTOR or issuer_ref == "house_tang":
            return
        player = self.read("state/player.json")
        location = str(player.get("location", ""))
        routes = self.read_optional("game/data/politics/contact-routes.json") or {}
        for route in routes.get("routes", []) if isinstance(routes, Mapping) else []:
            if not isinstance(route, Mapping):
                continue
            if str(route.get("institution_ref")) == issuer_ref and str(route.get("location_ref")) == location:
                return
        try:
            _path, issuer = self.owner(issuer_ref)
        except (KeyError, ValueError, FileNotFoundError):
            raise PermissionError("commission issuer is not a reachable saved institution")
        if str(issuer.get("house_ref", "")) == "house_tang" or str(issuer.get("administrative_owner", "")) == "house_tang":
            return
        raise PermissionError("commission issuer has no saved contact/authority route from the player's current position")

    def _require_person_in_player_command(self, actor: str, person_ref: str) -> None:
        if person_ref == actor:
            return
        _path, person = self._exact_person(person_ref)
        pforce = self.read_optional("state/pforce/wei.json") or {}
        if person_ref in pforce.get("members", []):
            return
        affiliation = str(person.get("affiliation", ""))
        if affiliation in {"House Tang", "Tang Wei Personal Retinue"}:
            return
        current = str(person.get("current_formation_id", ""))
        if current:
            try:
                _fp, formation = self._load_formation(current)
                if str(formation.get("command_authority")) == actor or str(formation.get("administrative_owner")) == actor:
                    return
            except (ValueError, FileNotFoundError):
                pass
        raise PermissionError("exact person is outside the player's saved command/retinue authority")

    def _require_command_group_authority(self, actor: str, group_ref: str, *, allow_strategist: bool = False) -> None:
        """Require lawful authority over a command node.

        Full commander/owner authority may flow down an army subtree. Registered
        strategist authority is narrower: it permits operational orders within
        the exact command subtree where that strategist is assigned, never up to
        a parent or sideways into a sibling army. Organizational mutation remains
        commander/owner-only.
        """
        authority = person_order_authority(self.read, person_ref=actor, target_group_ref=group_ref)
        if authority.get("allowed") and authority.get("role") == "commander_or_command_authority":
            return
        # Preserve the player's explicit institutional authority over their own
        # personal-force roots even where authority_ref is an institutional ref.
        current = group_ref
        seen: set[str] = set()
        for _ in range(32):
            if current in seen:
                break
            seen.add(current)
            group = self.read(_group_path(current))
            group_authority = str(group.get("authority_ref", ""))
            if group_authority in {"pforce.tang_wei", "force_tang_wei_personal"} and actor == self.PLAYER_ACTOR:
                return
            parent = group.get("parent_command_group_ref")
            if not isinstance(parent, str) or not parent:
                break
            current = parent
        if allow_strategist and authority.get("allowed") and str(authority.get("role") or "").casefold() == "strategist":
            return
        if allow_strategist:
            raise PermissionError("actor lacks commander/strategist operational authority over this command-group subtree")
        raise PermissionError("actor lacks organizational authority over this command group")

    def _dispatch_campaign_depth(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Base-reducer hook reached only after normal production dispatch wrappers.

        Keeping the hook below the causal/wake wrappers preserves pending-wake
        enforcement, command chronology, and response acknowledgement for every
        newly added semantic command.
        """
        t = command.command_type
        if t == "command_group_action":
            return self._dispatch_command_group_action(command, payload)
        if t == "command_group_train":
            return self._dispatch_command_group_train(command, payload)
        if t == "investigation_action":
            return self._dispatch_investigation(command, payload)
        if t == "commission_action":
            return self._dispatch_commission(command, payload)
        if t == "medical_treatment":
            return self._dispatch_medical_treatment(command, payload)
        if t == "commitment_action":
            return self._dispatch_commitment(command, payload)
        if t in {"information_create", "information_deliver"}:
            return self._dispatch_information(command, payload)
        raise ValueError(f"unsupported campaign-depth command: {t}")

    # Due-host settlement is centrally dispatched by time_integration.py.

    def _command_group_organizational_summary(self, group_ref: str, *, seen: set[str] | None = None) -> dict[str, Any]:
        seen = set() if seen is None else set(seen)
        if group_ref in seen:
            raise ValueError("command hierarchy contains a cycle")
        seen.add(group_ref)
        doc = self.read(_group_path(group_ref))
        direct_strength = 0
        recursive_strength = 0
        formation_count = 0
        units: list[dict[str, Any]] = []
        for row in unit_entries(doc):
            ref = str(row["ref"])
            if row["kind"] == FORMATION:
                _fp, formation = self._load_formation(ref)
                strength = max(0, int(formation.get("personnel", 0)))
                direct_strength += strength
                recursive_strength += strength
                formation_count += 1
                units.append({"kind": FORMATION, "ref": ref, "current_strength": strength, "status": str(formation.get("status", "active"))})
            else:
                child = self._command_group_organizational_summary(ref, seen=seen)
                strength = int(child["recursive_strength"])
                recursive_strength += strength
                formation_count += int(child["formation_count"])
                units.append({"kind": NESTED_ARMY, "ref": ref, "current_strength": strength, "status": str(child["reorganization_need"])})
        return {
            "recursive_strength": recursive_strength,
            "direct_strength": direct_strength,
            "formation_count": formation_count,
            "direct_unit_count": len(units),
            "units": units,
            "reorganization_need": "none",
        }

    def _refresh_command_group_organizational_state(self, group_ref: str, at: str, *, initialize: bool = False) -> dict[str, Any]:
        path = _group_path(group_ref)
        doc = copy.deepcopy(self.read(path))
        summary = self._command_group_organizational_summary(group_ref)
        org = doc.get("organizational_state") if isinstance(doc.get("organizational_state"), dict) else {}
        if initialize or "authorized_strength" not in org:
            org.setdefault("authorized_strength", int(summary["recursive_strength"]))
        if initialize or "authorized_direct_unit_slots" not in org:
            org.setdefault("authorized_direct_unit_slots", max(1, int(summary["direct_unit_count"])))
        baselines = org.setdefault("baseline_unit_strengths", {})
        for row in summary["units"]:
            baselines.setdefault(str(row["ref"]), int(row["current_strength"]))
        org["current_recursive_strength"] = int(summary["recursive_strength"])
        org["current_direct_formation_strength"] = int(summary["direct_strength"])
        org["recursive_formation_count"] = int(summary["formation_count"])
        org["direct_unit_count"] = int(summary["direct_unit_count"])
        org["unit_statuses"] = summary["units"]
        org.setdefault("status", "active")
        org.setdefault("mission", doc.get("context") or "standing command")
        authorized = max(0, int(org.get("authorized_strength", 0)))
        ratio = int(summary["recursive_strength"]) * 1000 // authorized if authorized else 1000
        destroyed = [row["ref"] for row in summary["units"] if int(row["current_strength"]) <= 0]
        shattered = [row["ref"] for row in summary["units"] if int(row["current_strength"]) > 0 and int(row["current_strength"]) * 1000 < max(1, int(baselines.get(str(row["ref"]), row["current_strength"]))) * 350]
        if destroyed:
            need = "destroyed_unit_review"
        elif shattered or ratio < 500:
            need = "major_reconstitution_or_reorganization"
        elif ratio < 750:
            need = "understrength_reconstitution_review"
        elif int(summary["direct_unit_count"]) > max(1, int(org.get("authorized_direct_unit_slots", 1))):
            need = "direct_command_span_review"
        else:
            need = "none"
        prior = str(org.get("reorganization_need", "none"))
        org["reorganization_need"] = need
        doc["organizational_state"] = org
        self.put(path, doc)
        return org

    def _refresh_command_group_organizational_chain(self, group_ref: str, at: str) -> None:
        cursor: str | None = group_ref
        seen: set[str] = set()
        while isinstance(cursor, str) and cursor not in seen:
            seen.add(cursor)
            org_doc = self.read(_group_path(cursor))
            parent = org_doc.get("parent_command_group_ref")
            self._refresh_command_group_organizational_state(cursor, at)
            cursor = str(parent) if isinstance(parent, str) else None

    def _dispatch_command_group_action(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        action = str(payload["action"]); ref = str(payload["command_group_ref"]); path = _group_path(ref); now = str(self._world_time())
        if action == "create":
            if self.read_optional(path) is not None: raise ValueError("command group already exists")
            commander_ref = str(payload["commander_ref"]); _pp, commander = self._exact_person(commander_ref)
            parent = payload.get("parent_ref")
            if command.actor_id != self.INTERNAL_ACTOR and not parent and ref != _PLAYER_RETINUE_ROOT:
                parent = _PLAYER_RETINUE_ROOT
                if self.read_optional(_group_path(parent)) is None:
                    raise ValueError("player retinue root is missing")
            doc = {
                "schema":"command-group", "id":ref, "commander_ref":commander_ref,
                "units":[], "parent_command_group_ref":parent,
                "context":"retinue", "standing_order_refs":[], "standing_orders":[],
                "location": self._person_location(commander), "direct_person_refs":[],
                "display_name": str(payload.get("display_name") or ref), "successor_refs":[],
                "authority_ref": command.actor_id, "active_context_ref":None, "communication_ref":None,
                "standing_doctrine_ref":None,
                "role_assignments":{}, "familiarity_milli":0, "verified_group_training_hours":0,
                "created_at":now, "updated_at":now,
                "organizational_state": {
                    "status":"active", "authorized_strength":0, "authorized_direct_unit_slots":1,
                    "current_recursive_strength":0, "current_direct_formation_strength":0, "recursive_formation_count":0,
                    "direct_unit_count":0, "reorganization_need":"none",
                    "mission":str(payload.get("mission") or "retinue"),
                },
            }
            doc["standing_doctrine_ref"] = default_command_group_doctrine_ref(doc)
            self.put(path, doc)
            if isinstance(parent, str):
                pp = _group_path(parent); parent_doc = copy.deepcopy(self.read(pp)); append_unit(parent_doc, kind=NESTED_ARMY, ref=ref); parent_doc["updated_at"]=now; self.put(pp,parent_doc)
            idx=self._command_group_index(); refs=idx.setdefault("refs",[])
            if ref not in refs: refs.append(ref)
            self._claim_primary_group_slot(idx, person_ref=commander_ref, group_ref=ref)
            self._write_command_group_index(idx); self._register_owner(ref,path)
        else:
            doc = copy.deepcopy(self.read(path))
            if action == "add_person":
                person_ref=str(payload["person_ref"]); idx=self._command_group_index(); role=str(payload.get("role") or "").strip()
                # Explicit staff/specialist duty is additive, not the person's
                # primary troop-command billet. A nested-army commander may also
                # be strategist on a parent army without losing either role.
                if not role:
                    self._claim_primary_group_slot(idx, person_ref=person_ref, group_ref=ref)
                refs=doc.setdefault("direct_person_refs",[])
                if person_ref not in refs: refs.append(person_ref); refs.sort()
                if role: doc.setdefault("role_assignments",{})[person_ref]=role
                self.put(path, doc)
                self._write_command_group_index(idx)
            elif action == "remove_person":
                person_ref=str(payload["person_ref"]); doc["direct_person_refs"]=[x for x in doc.get("direct_person_refs",[]) if x!=person_ref]; doc.setdefault("role_assignments",{}).pop(person_ref,None)
                doc["successor_refs"]=[x for x in doc.get("successor_refs",[]) if x!=person_ref]
                idx=self._command_group_index(); mapping=idx.setdefault("primary_person_group",{})
                if mapping.get(person_ref)==ref: mapping.pop(person_ref,None)
                self._write_command_group_index(idx)
            elif action == "attach_formation":
                formation_ref=str(payload["formation_ref"]); idx=self._command_group_index(); self._claim_primary_group_slot(idx, formation_ref=formation_ref, group_ref=ref); append_unit(doc, kind=FORMATION, ref=formation_ref)
                formation_path, formation_doc = self._load_formation(formation_ref); formation_doc=copy.deepcopy(formation_doc)
                current_higher=formation_doc.get("higher_command_ref")
                if current_higher not in {None, ref}: raise ValueError(f"{formation_ref} already reports to {current_higher}")
                formation_doc["higher_command_ref"]=ref; self.put(formation_path,formation_doc)
                doc["active_context_ref"] = formation_ref if doc.get("active_context_ref") is None else doc.get("active_context_ref")
                self._write_command_group_index(idx)
            elif action == "detach_formation":
                formation_ref=str(payload["formation_ref"]); remove_unit(doc, formation_ref)
                if doc.get("active_context_ref")==formation_ref: doc["active_context_ref"]=None
                formation_path, formation_doc = self._load_formation(formation_ref); formation_doc=copy.deepcopy(formation_doc)
                if formation_doc.get("higher_command_ref")==ref: formation_doc["higher_command_ref"]=None; self.put(formation_path,formation_doc)
                idx=self._command_group_index(); mapping=idx.setdefault("primary_formation_group",{})
                if mapping.get(formation_ref)==ref: mapping.pop(formation_ref,None)
                self._write_command_group_index(idx)
            elif action == "attach_command_group":
                child_ref=str(payload["subordinate_group_ref"]); child_path=_group_path(child_ref); child=copy.deepcopy(self.read(child_path))
                parent=child.get("parent_command_group_ref")
                if parent not in {None, ref}: raise ValueError(f"{child_ref} already reports to {parent}")
                cursor=ref; seen=set()
                while isinstance(cursor,str):
                    if cursor==child_ref: raise ValueError("command-group attachment would create a cycle")
                    if cursor in seen: raise ValueError("existing command-group hierarchy contains a cycle")
                    seen.add(cursor); current=self.read(_group_path(cursor)); nxt=current.get("parent_command_group_ref"); cursor=nxt if isinstance(nxt,str) else None
                append_unit(doc, kind=NESTED_ARMY, ref=child_ref)
                child["parent_command_group_ref"]=ref; child["updated_at"]=now; self.put(child_path,child)
            elif action == "detach_command_group":
                child_ref=str(payload["subordinate_group_ref"]); child_path=_group_path(child_ref); child=copy.deepcopy(self.read(child_path))
                remove_unit(doc, child_ref)
                if child.get("parent_command_group_ref")==ref: child["parent_command_group_ref"]=None; child["updated_at"]=now; self.put(child_path,child)
            elif action == "move_unit":
                unit_ref = str(payload.get("formation_ref") or payload.get("subordinate_group_ref"))
                move_unit(doc, unit_ref, int(payload["unit_slot"]))
            elif action == "move_army":
                return self._move_recursive_army(command, payload, root_doc=doc, root_path=path, now=now)
            elif action == "promote_formation_to_army":
                return self._promote_formation_to_nested_army(command, payload, parent_doc=doc, parent_path=path, now=now)
            elif action == "set_establishment":
                org = doc.setdefault("organizational_state", {})
                if "authorized_strength" in payload:
                    value = int(payload["authorized_strength"])
                    if value < 0: raise ValueError("authorized_strength cannot be negative")
                    org["authorized_strength"] = value
                if "authorized_direct_unit_slots" in payload:
                    value = int(payload["authorized_direct_unit_slots"])
                    if value <= 0: raise ValueError("authorized_direct_unit_slots must be positive")
                    org["authorized_direct_unit_slots"] = value
                if payload.get("mission") is not None: org["mission"] = str(payload["mission"])
            elif action == "review_organization":
                pass
            elif action == "set_successors": doc["successor_refs"] = [str(x) for x in payload.get("successor_refs",[])]
            elif action == "set_order":
                issuer_ref = str(payload.get("issuer_ref") or command.actor_id)
                issuer_authority = person_order_authority(self.read, person_ref=issuer_ref, target_group_ref=ref)
                if command.actor_id == self.INTERNAL_ACTOR and not issuer_authority.get("allowed"):
                    raise PermissionError("internal named order issuer lacks scoped command authority")
                order_ref="order."+hashlib.sha256(f"{ref}\x00{now}\x00{issuer_ref}\x00{payload['order']}".encode()).hexdigest()[:16]
                doc.setdefault("standing_order_refs",[]).append(order_ref); doc["standing_order_refs"]=doc["standing_order_refs"][-32:]
                row={"order_ref":order_ref,"text":str(payload["order"]),"issued_at":now,"issued_by":issuer_ref}
                if issuer_ref != command.actor_id and command.actor_id != self.INTERNAL_ACTOR:
                    row["delegated_by"] = command.actor_id
                if issuer_authority.get("role") == "strategist":
                    row["staff_role"] = "strategist"
                    row["scope_root_ref"] = issuer_authority.get("scope_root_ref")
                doc.setdefault("standing_orders",[]).append(row); doc["standing_orders"]=doc["standing_orders"][-32:]
            elif action == "set_communication": doc["communication_ref"] = payload.get("communication_ref")
            elif action == "set_doctrine": doc["standing_doctrine_ref"] = str(payload["doctrine_ref"])
            doc["updated_at"] = now; self.put(path,doc)
        self._refresh_command_group_organizational_chain(ref, now)
        self._write_meta(command, now)
        current_org = self.read(path).get("organizational_state", {})
        return self._result(command_group_ref=ref, action=action, organizational_state=current_org, world_time=now)

    def _move_recursive_army(
        self,
        command: Any,
        payload: Mapping[str, Any],
        *,
        root_doc: dict[str, Any],
        root_path: str,
        now: str,
    ) -> dict[str, Any]:
        """Move one recursive army while preserving its complete command tree.

        The parent command remains a zero-body command owner.  Descendant
        formations move in saved Unit order through the same physical route.
        Road throughput delays later Units instead of capping army size.  The
        command completes when the final formation tail reaches the destination;
        individual formations may still be deploying and therefore remain
        unavailable for deliberate battle until their saved ready timestamp.
        """
        group_ref = str(payload["command_group_ref"])
        destination = str(payload["location_ref"])
        operation_ref = str(payload.get("operation_ref") or "")
        operation_path: str | None = None
        operation_doc: dict[str, Any] | None = None
        operation_required_refs: set[str] | None = None
        if operation_ref:
            resolved_operation = exact_operation_record(self, operation_ref)
            op_path = resolved_operation[0] if resolved_operation is not None else None
            operation = resolved_operation[1] if resolved_operation is not None else None
            if not isinstance(operation, Mapping):
                raise ValueError("army movement requires an exact active operation")
            if str(operation.get("status", "")) not in {"planned", "mobilizing", "active", "advancing", "engaged", "occupied"}:
                raise ValueError("army movement requires an active operation")
            op_group = str(operation.get("command_group_ref") or "")
            if op_group and op_group != group_ref:
                raise ValueError("operation is assigned to a different command group")
            if command.actor_id != self.INTERNAL_ACTOR:
                assignment = str(operation.get("assignment_authority_ref") or operation.get("administrative_authority") or "")
                if assignment not in {command.actor_id, ""}:
                    raise PermissionError("army movement requires current operational assignment authority")

            # An institutional order governs only the formations that institution
            # may lawfully order.  It does not forbid the commander from bringing
            # separately owned household, House, retinue, allied, or mercenary
            # formations already under the same field command.  The operation owns
            # participation, never manpower ownership.  Extra descendants become
            # explicit auxiliaries only when the commander actually marches them.
            orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
            latest = next((row for row in reversed(orders) if isinstance(row, Mapping)), None)
            ordered_refs = latest.get("applies_to_formation_refs") if isinstance(latest, Mapping) else None
            if isinstance(ordered_refs, list) and ordered_refs:
                operation_required_refs = {str(ref) for ref in ordered_refs if isinstance(ref, str) and ref}
            else:
                existing_aux = {str(ref) for ref in operation.get("auxiliary_formation_refs", []) if isinstance(ref, str) and ref}
                operation_required_refs = {str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str) and ref} - existing_aux
            if not operation_required_refs:
                raise ValueError("operation has no assigned formations to move")
            operation_path = str(op_path)
            operation_doc = copy.deepcopy(dict(operation))

        def read_group(ref: str) -> Mapping[str, Any]:
            return self.read(_group_path(ref))

        # Load the recursive hierarchy once and prove that all subordinate
        # formation bodies are physically assembled before issuing one army
        # march.  A scattered theater force is not a single road column.
        hierarchy: list[tuple[str, str, dict[str, Any]]] = []
        seen: set[str] = set()
        group_parent: dict[str, str | None] = {}
        formation_parent: dict[str, str] = {}

        def collect(ref: str) -> None:
            if ref in seen:
                raise ValueError("command hierarchy contains a cycle")
            seen.add(ref)
            gp = _group_path(ref)
            gd = copy.deepcopy(self.read(gp))
            hierarchy.append((ref, gp, gd))
            parent = gd.get("parent_command_group_ref")
            group_parent[ref] = str(parent) if isinstance(parent, str) and parent else None
            for row in unit_entries(gd):
                if row["kind"] == NESTED_ARMY:
                    collect(str(row["ref"]))
                elif row["kind"] == FORMATION:
                    formation_parent[str(row["ref"])] = ref

        collect(group_ref)

        formation_refs: list[str] = []
        formation_rows: dict[str, tuple[str, dict[str, Any]]] = {}
        origins: set[str] = set()
        for _gref, _gpath, gdoc in hierarchy:
            for row in unit_entries(gdoc):
                if row["kind"] != FORMATION:
                    continue
                fref = str(row["ref"])
                if fref in formation_rows:
                    raise ValueError("formation appears more than once in recursive army hierarchy")
                fp, f0 = self._load_formation(fref)
                f = copy.deepcopy(f0)
                if int(f.get("personnel", 0)) <= 0:
                    raise ValueError(f"army movement rejected: {fref} has no personnel")
                if not bool(f.get("mobilized", False)):
                    raise ValueError(f"army movement rejected: {fref} is not mobilized")
                origin = str(f.get("location_ref", ""))
                if not origin:
                    raise ValueError(f"army movement rejected: {fref} has no exact location")
                origins.add(origin)
                formation_refs.append(fref)
                formation_rows[fref] = (fp, f)
        if not formation_refs:
            raise ValueError("army command has no descendant formations to move")
        if operation_required_refs is not None and not operation_required_refs.issubset(set(formation_refs)):
            missing = sorted(operation_required_refs - set(formation_refs))
            raise ValueError(f"operation requires formations outside the command hierarchy: {missing}")

        auxiliary_refs: list[str] = []
        if operation_doc is not None and operation_path is not None:
            existing_participants = [str(ref) for ref in operation_doc.get("formation_refs", []) if isinstance(ref, str) and ref]
            existing_aux = [str(ref) for ref in operation_doc.get("auxiliary_formation_refs", []) if isinstance(ref, str) and ref]
            auxiliary_refs = [ref for ref in formation_refs if ref not in operation_required_refs]
            merged_participants = list(dict.fromkeys(existing_participants + formation_refs))
            merged_aux = list(dict.fromkeys(existing_aux + auxiliary_refs))
            operation_doc["formation_refs"] = merged_participants
            if merged_aux:
                operation_doc["auxiliary_formation_refs"] = merged_aux
                operation_doc["auxiliary_participation_rule"] = (
                    "These formations accompany the operation under their existing lawful commander. "
                    "Their institutional ownership, manpower provenance, treasury, and equipment ownership do not transfer to the campaign sponsor."
                )
            operation_doc["updated_at"] = now
            self.put(operation_path, operation_doc)

        relevant_groups: set[str] = {group_ref}
        for fref in formation_refs:
            cursor = formation_parent.get(fref)
            while isinstance(cursor, str) and cursor:
                relevant_groups.add(cursor)
                cursor = group_parent.get(cursor)

        # Existing Units receive deterministic march duties before departure.
        # This is assignment only: it creates no scout/baggage formations and no
        # extra bodies. The duty state travels with the same Units.
        move_duties = self._apply_unit_duties(
            formation_refs, "march", context_ref=f"command_group_move:{command.semantic_digest[:24]}", at=now
        )
        if move_duties:
            # Duty assignment writes the authoritative formation owners, so
            # refresh the movement snapshots before route/fatigue settlement.
            for fref in list(formation_refs):
                fp, fresh = self._load_formation(fref)
                formation_rows[fref] = (fp, copy.deepcopy(fresh))

        participating_formation_refs = list(formation_refs)
        prepositioned_refs = [ref for ref in formation_refs if str(formation_rows[ref][1].get("location_ref", "")) == destination]
        movement_refs = [ref for ref in formation_refs if ref not in prepositioned_refs]
        if not movement_refs:
            raise ValueError("all descendant formations are already at the requested destination")
        moving_origins = {str(formation_rows[ref][1].get("location_ref", "")) for ref in movement_refs}
        if len(moving_origins) != 1:
            raise ValueError("army concentration requires the formations still in motion to share one exact origin")
        origin = next(iter(moving_origins))
        if len(origins) > 1 and not operation_ref:
            raise ValueError("army movement requires all descendant formations to be assembled at one exact origin")
        if len(origins) > 1 and not prepositioned_refs:
            raise ValueError("army concentration requires at least one command element already at the requested rendezvous")

        # An operation move may therefore finish a real concentration: formations
        # already at the lawful rendezvous hold there while the remaining Units
        # and command staff close on them. This avoids a redundant player command
        # without teleporting any body or moving unrelated formations.

        # The player's declared army movement includes the obvious prerequisite of
        # physically joining the already-assembled command. Exact command staff
        # therefore muster to the column origin first, with real elapsed time. This
        # is not teleportation and does not move unrelated formations. Formation
        # unit commanders/deputies are reconciled by the surrounding staff layer.
        staff_paths: dict[str, str] = {}
        staff_muster: dict[str, tuple[str, str]] = {}
        muster_hours = 0
        for gref, _gp, gdoc in hierarchy:
            if gref not in relevant_groups:
                continue
            for pref in [gdoc.get("commander_ref"), *gdoc.get("direct_person_refs", [])]:
                if not isinstance(pref, str) or not pref or pref in staff_paths:
                    continue
                try:
                    pp = self.owner_path(pref)
                    person = self.read(pp)
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                current_location = self._person_location(person)
                if not isinstance(current_location, str) or not current_location:
                    raise ValueError(f"army movement rejected: command staff {pref} has no exact location")
                staff_paths[pref] = pp
                if current_location != origin:
                    hours = int(self._route_travel_hours(current_location, origin, modes=("foot", "horse")))
                    if hours <= 0:
                        raise ValueError(f"army movement rejected: command staff {pref} cannot physically muster to {origin}")
                    muster_hours = max(muster_hours, hours)
                    staff_muster[pref] = (pp, current_location)

        if muster_hours > 0:
            muster_target = self._world_time().add_seconds(muster_hours * 3600)
            self._advance_exact_or_reject(muster_target, "army command staff muster")
            for pref, (pp, start_location) in staff_muster.items():
                person = copy.deepcopy(self.read(pp))
                current_location = self._person_location(person)
                if current_location == origin:
                    continue
                if current_location != start_location:
                    raise ValueError(f"army movement rejected: command staff {pref} location changed during muster")
                self._set_person_location(person, origin)
                self.put(pp, person)
            # _advance_exact_or_reject proves the staged runtime reached this
            # exact muster boundary. The semantic command intentionally leaves
            # meta.time at the pre-command instant until its final _write_meta,
            # so calling the strict _world_time() view here would manufacture a
            # chronology disagreement inside one still-atomic transaction.
            now = str(muster_target)

        for pref, pp in staff_paths.items():
            person = self.read(pp)
            if self._person_location(person) != origin:
                raise ValueError(f"army movement rejected: command staff {pref} is not assembled at {origin}")

        route = self._find_route(origin, destination, mode="formation")
        for fref in movement_refs:
            _fp, f = formation_rows[fref]
            if hasattr(self, "_validate_formation_transit"):
                self._validate_formation_transit(f, destination, now)

        plan = recursive_army_movement_plan(
            self.read,
            read_group,
            lambda ref: formation_rows[str(ref)][1],
            group_ref,
            route,
            formation_refs=movement_refs,
        )
        plan_by_ref = {str(row["formation_ref"]): row for row in plan["ordered_units"]}

        # Baggage and support move with the army as an aggregate physical burden.
        # The movement plan already accounts for required wagon-equivalents and
        # route throughput.  There is no independent persistent army-train owner
        # and no carried ration/feed inventory to validate or consume here.

        started = CampaignTime.parse(now)
        duration_hours = max(1, int(plan["whole_army_tail_arrival_hours"]))
        target = started.add_seconds(duration_hours * 3600)
        time_metrics = self._advance_exact_or_reject(target, "recursive army movement")
        completed_at = str(target)

        # Commit descendant formation movement without changing their owners or
        # flattening the hierarchy.  Each formation keeps its own physical
        # timeline and may remain in arrived_forming status after the army tail
        # reaches the destination.
        for fref in movement_refs:
            fp, f = formation_rows[fref]
            row = plan_by_ref[fref]
            departed = started.add_seconds(int(math.ceil(float(row["departure_offset_hours"]) * 3600)))
            tail = started.add_seconds(int(math.ceil(float(row["tail_arrival_hours"]) * 3600)))
            ready = started.add_seconds(int(math.ceil(float(row["battle_ready_hours"]) * 3600)))
            settle_formation_idle_fatigue(f, current=departed, rules=self.read(FATIGUE_RULES_PATH))
            f["location_ref"] = destination
            self._index_formation_location(fref, origin, destination)
            stamp_formation_activity_fatigue(
                f, completed_at=tail, fatigue_gain=max(1, int(math.ceil(float(row["tail_arrival_hours"]) / 12.0))), activity_kind="march"
            )
            f["last_moved_at"] = str(tail)
            f["last_route_refs"] = list(route.get("route_refs", []))
            f["last_route_path"] = list(route.get("path", []))
            f["operational_movement"] = {
                **row,
                "command_group_ref": group_ref,
                "origin_ref": origin,
                "destination_ref": destination,
                "departed_at": str(departed),
                "tail_arrived_at": str(tail),
                "deployment_ready_at": str(ready),
                "road_column_order": movement_refs.index(fref) + 1,
                "supply_condition": str(row.get("supply_condition", "adequate")),
                "supply_score_milli": int(row.get("supply_score_milli", 1000)),
            }
            f["status"] = "ready" if ready <= target else "arrived_forming"
            self.put(fp, f)

        # Move the zero-body command establishment and direct staff.  Their
        # existence does not add soldiers to any descendant formation.
        for gref, gp, gdoc in hierarchy:
            if gref not in relevant_groups:
                continue
            gdoc["location"] = destination
            gdoc["updated_at"] = completed_at
            if gref == group_ref:
                gdoc["last_operational_movement"] = {
                    "origin_ref": origin,
                    "destination_ref": destination,
                    "departed_at": now,
                    "army_tail_arrived_at": completed_at,
                    "army_battle_ready_at": str(started.add_seconds(int(plan["whole_army_battle_ready_hours"]) * 3600)),
                    "total_personnel": int(plan["total_personnel"]),
                    "formation_count": int(plan["formation_count"]),
                    "route_refs": list(route.get("route_refs", [])),
                    "ordered_formation_refs": participating_formation_refs,
                    **({"operation_ref": operation_ref} if operation_ref else {}),
                }
            self.put(gp, gdoc)
        for pref, pp in staff_paths.items():
            person = copy.deepcopy(self.read(pp))
            self._set_person_location(person, destination)
            self.put(pp, person)

        army_battle_ready_at = str(started.add_seconds(int(plan["whole_army_battle_ready_hours"]) * 3600))
        root_after = copy.deepcopy(self.read(root_path))
        root_after.setdefault("last_operational_movement", {})["required_wagon_equivalents"] = int(plan.get("required_wagon_equivalents", 0))
        self.put(root_path, root_after)

        self._write_meta(command, completed_at)
        result = self._result(
            command_group_ref=group_ref,
            action="move_army",
            origin_ref=origin,
            destination_ref=destination,
            duration_hours=duration_hours,
            world_time=completed_at,
            total_personnel=int(plan["total_personnel"]),
            formation_count=int(plan["formation_count"]),
            assembled_total_personnel=sum(max(0, int(formation_rows[ref][1].get("personnel", 0))) for ref in participating_formation_refs),
            assembled_formation_count=len(participating_formation_refs),
            operation_ref=operation_ref or None,
            participating_formation_refs=list(participating_formation_refs),
            moved_formation_refs=list(movement_refs),
            prepositioned_formation_refs=list(prepositioned_refs),
            operation_assigned_formation_refs=sorted(operation_required_refs or []),
            auxiliary_formation_refs=list(auxiliary_refs),
            command_staff_muster_hours=int(muster_hours),
            command_staff_mustered=sorted(staff_muster),
            whole_army_battle_ready_at=army_battle_ready_at,
            required_wagon_equivalents=int(plan.get("required_wagon_equivalents", 0)),
        )
        result["operational_plan"] = plan
        result["unit_duties"] = move_duties
        result.update(time_metrics)
        return result

    def _promote_formation_to_nested_army(self, command: Any, payload: Mapping[str, Any], *, parent_doc: dict[str, Any], parent_path: str, now: str, write_command_meta: bool = True) -> dict[str, Any]:
        """Promote one direct formation into one recursive nested-army Unit.

        The formation's current top commander rises to the new zero-body army
        command. The child formation still needs exactly one top commander, so
        one already-conserved internal officer is promoted out of fighting strength.
        The successor scale is the highest lawful internal echelon in that Unit's
        establishment. No generic second-command body is required or created.
        """
        formation_ref = str(payload["formation_ref"])
        army_ref = str(payload["subordinate_group_ref"])
        if self.read_optional(_group_path(army_ref)) is not None:
            raise ValueError("promoted nested army command already exists")
        if not any(row["kind"] == FORMATION and row["ref"] == formation_ref for row in unit_entries(parent_doc)):
            raise ValueError("formation must be a direct Unit of the parent command before promotion")

        formation_path, formation0 = self._load_formation(formation_ref)
        formation = copy.deepcopy(formation0)
        old_commander = formation.get("commander_ref")
        if not isinstance(old_commander, str) or not old_commander:
            raise ValueError("formation promotion requires an exact commander")
        self._exact_person(old_commander)

        force_path, force0 = self.owner(str(formation.get("owner_force_ref")))
        force = copy.deepcopy(force0)
        from sword_runtime.cohort_personnel import ensure_cohort_ledger, validate_cohort_ledger
        ensure_cohort_ledger(force)
        cadre = ensure_officer_cadre(formation)
        location_ref = str(formation.get("location_ref"))
        allocation = force.setdefault("allocated_to_formations", {}).get(formation_ref)
        if not isinstance(allocation, Mapping):
            raise ValueError("formation promotion requires an exact force allocation")
        allocation = dict(allocation)
        force["allocated_to_formations"][formation_ref] = allocation

        internal_refs = [str(x) for x in formation.get("embedded_person_refs", []) if isinstance(x, str)]
        candidate_rows: list[tuple[int, str, str, dict[str, Any]]] = []
        for ref in internal_refs:
            try:
                pp, person0 = self.owner(ref)
            except (ValueError, KeyError, FileNotFoundError):
                continue
            person = copy.deepcopy(person0)
            assignment = person.get("command_assignment") if isinstance(person.get("command_assignment"), Mapping) else {}
            scale = int(assignment.get("scale", 0) or 0)
            if scale <= 0:
                rank_text = str((person.get("military_rank") or {}).get("grade") if isinstance(person.get("military_rank"), Mapping) else person.get("rank", ""))
                if "1000" in rank_text:
                    scale = 1000
                elif "500" in rank_text:
                    scale = 500
                elif "100" in rank_text:
                    scale = 100
            if scale > 0:
                candidate_rows.append((scale, ref, pp, person))
        candidate_rows.sort(key=lambda row: (-row[0], row[1]))

        materialized_successors: list[str] = []

        def choose_or_materialize(scale: int, label: str) -> tuple[int, str, str, dict[str, Any]]:
            row = next((r for r in candidate_rows if r[0] == scale), None)
            if row is None:
                row = next((r for r in candidate_rows if r[0] > scale), None)
            if row is not None:
                return row
            rank_key = f"{scale}_commander"
            if int(cadre.get("rank_inventory", {}).get(rank_key, 0)) <= 0:
                raise ValueError(f"formation has no surviving {rank_key} cadre for succession")
            digest = hashlib.sha256(f"{formation_ref}:{army_ref}:{scale}:{label}".encode()).hexdigest()[:12]
            person_ref = f"officer.{formation_ref.replace('formation_','').replace('_','.')}.{scale}.{digest}"
            composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
            role = max(((int(v), str(k)) for k, v in composition.items() if int(v) > 0), default=(0, "line_infantry"))[1]
            person = {
                "schema":"person-lite", "id":person_ref, "owner":str(formation.get("owner_force_ref")),
                "name":f"{scale}-Commander {digest[:4].upper()}",
                "military_rank":{"grade":rank_key,"durable":True},
                "role":f"internal_{scale}_commander", "current_location":location_ref,
                "health":{"status":"healthy","fatigue":0}, "relationships":[],
                "command_assignment":{"external_to_fighting_strength":False,"formation_ref":formation_ref,"scale":scale,"billet":f"internal_{scale}_command"},
            }
            self._ct_materialize_from_formation(force, formation, role=role, person_ref=person_ref, person=person)
            cid = str(person.get("source_cohort_ref") or "")
            cohort = force.get("cohort_ledger", {}).get("cohorts", {}).get(cid, {}) if cid else {}
            if isinstance(cohort, Mapping):
                personal_loadout = officer_loadout_id(self.read, person, formation, command_role=rank_key)
                person["personal_loadout_ref"] = personal_loadout
                projected = project_person_lite_stats(cohort, person_ref, command_rank=rank_key, loadout_id=personal_loadout)
                person["stats"] = {"attributes": projected.get("attributes", {}), "skills": projected.get("skills", {})}
                if projected.get("professional_skills"):
                    person["professional_skills"] = dict(projected["professional_skills"])
                person["aptitude"] = projected.get("aptitude", {})
            else:
                person["stats"] = {"attributes": dict(person.pop("attributes", {})), "skills": dict(person.pop("skills", {}))}
            seed_int = int(digest[:8], 16)
            person["birth_date"] = f"{260 + (seed_int % 25)}-BCE-{1 + ((seed_int >> 4) % 12):02d}-{1 + ((seed_int >> 9) % 28):02d}"
            person["appearance"] = 40 + (seed_int % 31)
            person["body"] = {
                "adult_height_cm": round(165.0 + ((seed_int >> 5) % 170) / 10.0, 1), "growth_end_age":18,
                "current_weight_kg": round(58.0 + ((seed_int >> 11) % 220) / 10.0, 1),
                "frame":["lean","athletic","broad"][seed_int % 3],
            }
            force.setdefault("materialized_people", {})[person_ref] = {"personnel": 1, "role": role, "source_cohort_ref": cid, "source_mode": "materialized_internal_commander"}
            force.setdefault("materialized_assignments", {})[person_ref] = {"formation_ref":formation_ref,"personnel":1,"role":role}
            put_person_lite(self, person=person, scope_ref=formation_ref)
            internal_refs.append(person_ref)
            register_materialized_rank(formation, person_ref, rank_key)
            materialized_successors.append(person_ref)
            return (scale, person_ref, self.owner_path(person_ref), person)

        formation_class = formation_class_for(formation, personnel=int(formation.get("personnel", 0)), explicit=formation.get("formation_class"))
        authorized = authorized_strength_for(formation, personnel=int(formation.get("personnel", 0)), formation_class=formation_class)
        successor_scales = [
            int(row.get("scale", 0)) for row in hierarchy_rows(
                authorized_strength=authorized,
                current_personnel=int(formation.get("personnel", 0)),
                formation_class=formation_class,
            ) if isinstance(row, Mapping) and int(row.get("count", 0) or 0) > 0
        ]
        if not successor_scales:
            raise ValueError("formation promotion requires a lawful internal command echelon for succession")
        successor_scale = max(successor_scales)
        new_commander_row = choose_or_materialize(successor_scale, "formation_commander_successor")
        representation_policy = self.read("game/data/mechanics/officer-representation.json")
        full_policy = representation_policy.get("automatic_full_character", {}) if isinstance(representation_policy, Mapping) else {}
        full_threshold = max(1, int(full_policy.get("minimum_persistent_commanded_personnel", 500) or 500))
        if authorized >= full_threshold and str(new_commander_row[3].get("schema", "")) == "person-lite":
            full_path, full_person = promote_person_lite_to_full(self, new_commander_row[1])
            new_commander_row = (new_commander_row[0], new_commander_row[1], full_path, full_person)
        new_commander_ref = new_commander_row[1]
        unfilled_roles: list[str] = []

        assignments = force.setdefault("materialized_assignments", {})
        assignment = assignments.get(new_commander_ref)
        if not isinstance(assignment, Mapping) or str(assignment.get("formation_ref")) != formation_ref:
            raise ValueError("promoted embedded officer is not a conserved member of the formation")
        role = str(assignment.get("role") or "")
        if not role:
            role = max(((int(v), str(k)) for k, v in formation.get("composition", {}).items() if int(v) > 0), default=(0, "line_infantry"))[1]
        unfilled_roles.append(role)
        durable = new_commander_row[3].get("military_rank") if isinstance(new_commander_row[3].get("military_rank"), Mapping) else {}
        rank_key = str(durable.get("grade") or f"{new_commander_row[0]}_commander")
        assignments.pop(new_commander_ref, None)
        remove_internal_rank_body(formation, rank_key, person_ref=new_commander_ref)
        formation["personnel"] = max(0, int(formation.get("personnel", 0)) - 1)
        comp = dict(formation.get("composition", {})) if isinstance(formation.get("composition"), Mapping) else {}
        if int(comp.get(role, 0)) > 0:
            comp[role] = int(comp.get(role, 0)) - 1
            if comp[role] <= 0:
                comp.pop(role, None)
            formation["composition"] = comp
        allocation["personnel"] = max(0, int(allocation.get("personnel", 0)) - 1)
        alloc_comp = dict(allocation.get("composition", {})) if isinstance(allocation.get("composition"), Mapping) else {}
        if int(alloc_comp.get(role, 0)) > 0:
            alloc_comp[role] = int(alloc_comp.get(role, 0)) - 1
            if alloc_comp[role] <= 0:
                alloc_comp.pop(role, None)
            allocation["composition"] = alloc_comp
        formation["embedded_person_refs"] = [ref for ref in internal_refs if ref != new_commander_ref]

        # The child formation has exactly one top commander.
        ref, pp, person = new_commander_row[1], new_commander_row[2], copy.deepcopy(new_commander_row[3])
        durable_rank = str((person.get("military_rank") or {}).get("grade") if isinstance(person.get("military_rank"), Mapping) else person.get("rank", ""))
        if not durable_rank:
            durable_rank = f"{new_commander_row[0]}_commander"
        person["rank"] = durable_rank
        person["military_rank"] = {"grade":durable_rank,"durable":True}
        person["role"] = "formation_commander"
        person["command_assignment"] = {"external_to_fighting_strength":True,"formation_ref":formation_ref,"billet":"formation_commander","scope":army_ref,"current_command_span":int(formation.get("personnel",0))}
        person.setdefault("career_state", {})["current_billet"] = "formation_commander"
        self.put(pp, person)

        formation["commander_ref"] = new_commander_ref
        formation.pop("command_structure", None)
        formation["higher_command_ref"] = army_ref
        formation["command_last_changed_at"] = now
        reorganize_officer_cadre(formation, at=now, reason="formation_promoted_to_nested_army")
        sync_materialized_officer_billets(self, formation)

        # Existing top commander moves upward; the child commander remains below.
        pp, person0 = self.owner(old_commander)
        person = copy.deepcopy(person0)
        person.setdefault("career_state", {})["office_or_command"] = str(payload.get("display_name") or army_ref) + " Commander"
        person.setdefault("career_state", {})["current_billet"] = "nested_army_commander"
        person["military_command"] = {
            "level":"nested_army", "command_group_ref":army_ref,
            "external_to_descendant_troop_strength":True,
        }
        self.put(pp, person)

        nested_doc = {
            "schema":"command-group","id":army_ref,"authority_ref":parent_doc.get("authority_ref"),
            "commander_ref":old_commander,"direct_person_refs":[],
            "units":[{"kind":FORMATION,"ref":formation_ref}],"parent_command_group_ref":str(parent_doc.get("id")),
            "display_name":str(payload.get("display_name") or f"{old_commander} Army"),"location":formation.get("location_ref"),
            "context":"nested_army","communication_ref":None,"standing_doctrine_ref":None,"standing_order_refs":[],"standing_orders":[],
            "successor_refs":[new_commander_ref],"role_assignments":{},"familiarity_milli":0,"verified_group_training_hours":0,
            "created_at":now,"updated_at":now,
            "organizational_state": {
                "status":"active",
                "authorized_strength":int(formation.get("personnel",0)),
                "authorized_direct_unit_slots":3,
                "current_recursive_strength":int(formation.get("personnel",0)),
                "current_direct_formation_strength":int(formation.get("personnel",0)),
                "recursive_formation_count":1,
                "direct_unit_count":1,
                "reorganization_need":"none",
                "reviewed_at":now,
                "mission":"authorized independent command; establishment may grow only through explicit lawful staffing",
                "baseline_unit_strengths":{formation_ref:int(formation.get("personnel",0))}
            },
        }
        nested_doc["standing_doctrine_ref"] = default_command_group_doctrine_ref(nested_doc)
        replace_unit(parent_doc, formation_ref, kind=NESTED_ARMY, ref=army_ref)
        parent_doc["updated_at"] = now
        self.put(parent_path,parent_doc)
        self.put(_group_path(army_ref),nested_doc)
        self.put(formation_path,formation)
        self.put(force_path,force)
        validate_cohort_ledger(force)
        idx=self._command_group_index()
        refs=idx.setdefault("refs",[])
        if army_ref not in refs:
            refs.append(army_ref)
        idx.setdefault("primary_formation_group",{})[formation_ref]=army_ref
        idx.setdefault("primary_person_group",{})[old_commander]=army_ref
        idx.setdefault("primary_person_group",{})[new_commander_ref]=army_ref
        self._write_command_group_index(idx)
        self._register_owner(army_ref,_group_path(army_ref))
        self._refresh_command_group_organizational_chain(army_ref, now)
        if write_command_meta:
            self._write_meta(command,now)
        cadre_after = ensure_officer_cadre(formation)
        return self._result(
            command_group_ref=str(parent_doc.get("id")), promoted_army_ref=army_ref, original_formation_ref=formation_ref,
            army_commander_ref=old_commander,
            new_formation_commander_ref=new_commander_ref,
            materialized_successor_refs=materialized_successors, replacement_embedded_officer_refs=[],
            unfilled_promoted_command_vacancy_roles=unfilled_roles, resulting_formation_personnel=int(formation.get("personnel",0)),
            officer_cadre={"rank_inventory":dict(cadre_after.get("rank_inventory",{})),"active_billets":dict(cadre_after.get("active_billets",{})),"cadre_reserve":dict(cadre_after.get("cadre_reserve",{})),"vacant_billets":dict(cadre_after.get("vacant_billets",{}))},
            world_time=now,
        )
    def _dispatch_command_group_train(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        ref = str(payload["command_group_ref"])
        path = _group_path(ref)
        start_doc = self.read(path)
        hours = int(payload.get("hours", 1))
        requested_theme = payload.get("focus")

        participant_refs: list[str] = []
        for value in [start_doc.get("commander_ref"), *start_doc.get("direct_person_refs", [])]:
            if isinstance(value, str) and value and value not in participant_refs:
                _pp, person = self._exact_person(value)
                if self._person_health(person) in {"healthy", "fit", "stable"}:
                    participant_refs.append(value)
        if len(participant_refs) < 2:
            raise ValueError("retinue training requires at least two fit exact participants")

        start_locations = {self._person_location(self._exact_person(person_ref)[1]) for person_ref in participant_refs}
        start_locations.discard(None)
        if len(start_locations) != 1:
            raise ValueError("retinue training requires exact co-location of participating named members")

        start = self._world_time()
        target = start.add_seconds(hours * 3600)
        metrics = self._advance_exact_or_reject(target, "retinue training")

        # Rehydrate after causal settlement so training cannot overwrite a routine
        # world update that happened during the elapsed interval. Caller-owned focus
        # is a scene/training theme only; registered programs own gain-bearing drills.
        doc = copy.deepcopy(self.read(path))
        people: list[tuple[str, str, dict[str, Any]]] = []
        end_locations: set[str] = set()
        for person_ref in participant_refs:
            pp, p0 = self._exact_person(person_ref)
            person = copy.deepcopy(p0)
            location = self._person_location(person)
            if isinstance(location, str) and location:
                end_locations.add(location)
            if self._person_health(person) not in {"healthy", "fit", "stable"}:
                raise ValueError("retinue training participant became unavailable before completion")
            people.append((person_ref, pp, person))
        if len(end_locations) != 1:
            raise ValueError("retinue training participants did not remain co-located through completion")

        rules = self.read("game/data/mechanics/training.json")
        session_rules = self.read("game/data/mechanics/training-session.json")
        registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
        profiles = self.read("game/data/mil/recruitment-cohort-profiles.json")
        regimens = profiles.get("training_regimens", {}) if isinstance(profiles, Mapping) else {}
        fatigue_rules = self.read(FATIGUE_RULES_PATH)
        development: dict[str, Any] = {}
        for person_ref, pp, person in people:
            contract = person.get("activity_contract") if isinstance(person.get("activity_contract"), Mapping) else {}
            explicit_program = str(contract.get("training_program_ref", "") or "")
            program_ref = resolve_training_program_ref(registry, person=person, explicit_program_ref=explicit_program or None)
            regimen = regimens.get(str(contract.get("training_regimen_ref", "regular_army")), {}) if isinstance(regimens, Mapping) else {}
            if not isinstance(regimen, Mapping):
                regimen = {}
            person_location = str(self._person_location(person) or "")
            environment = training_environment(self, location_ref=person_location, simultaneous_trainees=1) if person_location else {"facility_grade": "none", "capacity_factor": 0.0}
            if str(person.get("schema", "")) == "person-lite" and isinstance(person.get("stats"), Mapping):
                trainee_skills = person.get("stats", {}).get("skills", {})
            else:
                trainee_skills = person.get("skills", {})
            if not isinstance(trainee_skills, Mapping):
                trainee_skills = {}
            evidence = f"command_group_train:{command.semantic_digest[:24]}:{ref}:{person_ref}"
            instructor_contexts = instructor_contexts_for_program(
                self, registry=registry, training_rules=rules, program_ref=program_ref,
                trainee_skills=trainee_skills, student_count=1, location_ref=person_location, trainee_ref=person_ref,
                scheduled_hours=float(hours), window_start=str(start), window_end=str(target),
                evidence_ref=evidence, reserve_duty=True,
            )
            drill_access = exact_person_drill_access(self, registry=registry, program_ref=program_ref, person=person)
            settle_person_idle_fatigue(person, current=start, rules=fatigue_rules, state="ordinary")
            promotion_facts = exact_promotion_facts(self, person)
            if str(person.get("schema", "")) == "person-lite":
                result = settle_person_lite_program(
                    person, registry=registry, program_ref=program_ref, deliberate_hours=float(hours), role_exposure_hours=0.0,
                    training_rules=rules, facility_grade=str(environment.get("facility_grade", "none")),
                    equipment_grade=str(regimen.get("equipment_grade", "adequate")), recovery_grade=str(regimen.get("recovery_grade", "adequate")),
                    evidence_ref=evidence, promotion_facts=promotion_facts, instructor_context_by_drill=instructor_contexts,
                    drill_access=drill_access, time_window_start=str(start), time_window_end=str(target),
                )
                verified = max(0.0, float(result.get("deliberate_hours", 0.0) or 0.0))
            else:
                result = settle_exact_program(
                    person, registry=registry, program_ref=program_ref, hours=hours, at=target,
                    training_rules=rules, session_rules=session_rules, facility_grade=str(environment.get("facility_grade", "none")),
                    equipment_grade=str(regimen.get("equipment_grade", "adequate")), recovery_grade=str(regimen.get("recovery_grade", "adequate")),
                    feedback_grade=str(regimen.get("feedback_grade", "ordinary")), cursor_key="command_group_training_cursor",
                    promotion_facts=promotion_facts, instructor_context_by_drill=instructor_contexts, drill_access=drill_access,
                    time_window_start=str(start), time_window_end=str(target), time_evidence_ref=evidence,
                )
                verified = max(0.0, float(result.get("verified_hours", 0.0) or 0.0))
            if verified > 0.0:
                stamp_person_activity_fatigue(person, completed_at=target, fatigue_gain=max(1, int(round(verified / 2.0))), activity_kind="command_group_training")
            self.put(pp, person)
            development[person_ref] = {
                "program_ref": program_ref, "requested_theme": requested_theme, "gain_authority": "registered_deterministic_program",
                "verified_hours": round(verified, 6), "development": result,
            }

        doc["verified_group_training_hours"] = int(doc.get("verified_group_training_hours", 0)) + hours
        doc["familiarity_milli"] = min(1000, int(doc.get("familiarity_milli", 0)) + max(4, hours * 8))
        doc["last_training"] = {
            "started_at": str(start),
            "completed_at": str(target),
            "hours": hours,
            "focus": requested_theme,
            "participant_refs": [row[0] for row in people],
        }
        doc["updated_at"] = str(target)
        self.put(path, doc)
        self._write_meta(command, str(target))
        return self._result(
            command_group_ref=ref,
            hours=hours,
            focus=requested_theme,
            familiarity_milli=doc["familiarity_milli"],
            person_development=development,
            world_time=str(target),
            **metrics,
        )

    def _information_subject_index(self) -> dict[str, Any]:
        return copy.deepcopy(self.read_optional("state/information/subject-index.json") or {"schema":"sword-information-subject-index","authority":False,"subjects":{}})

    def _dispatch_information(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        idxp = "state/information/index.json"
        idx = copy.deepcopy(self.read(idxp))
        now = self._world_time()
        if command.command_type == "information_create":
            ref = str(payload["information_ref"])
            path = f"state/information/{ref}.json"
            if self.read_optional(path) is not None:
                raise ValueError("information_ref already exists")
            claim = str(payload.get("claim", payload.get("fact", "")))
            knowers = [str(x) for x in payload.get("knowers", [])]
            subject = str(payload.get("subject_ref") or ref)
            player_authored = command.actor_id != self.INTERNAL_ACTOR
            kind = str(payload.get("epistemic_kind", "observation"))
            confidence = int(payload.get("confidence_milli", round(_number(payload.get("confidence", 1.0), 1.0) * 1000)))
            confidence = max(0, min(1000, confidence))
            classification = str(payload.get("classification", "ordinary"))
            evidence = [] if player_authored else [str(x) for x in payload.get("evidence_refs", [])]
            location = payload.get("location_ref")
            discoverability = 1000 if player_authored else int(payload.get("discoverability_milli", 500))
            origin_authority = "player_assertion" if player_authored else "runtime_established"
            claim_status = "unverified_claim" if player_authored else "runtime_established"
            investigation_discoverable = not player_authored
            holder_states = {
                knower: {
                    "epistemic_kind": kind,
                    "confidence_milli": confidence,
                    "source_ref": "player_assertion" if player_authored else str(payload.get("provenance", "runtime")),
                    "learned_at": str(now),
                }
                for knower in knowers
            }
            doc = {
                "schema": "sword-information",
                "owner_id": ref,
                "information_ref": ref,
                "subject_ref": subject,
                "fact": claim,
                "claim": claim,
                "epistemic_kind": kind,
                "confidence_milli": confidence,
                "confidence": f"{confidence / 1000:.3f}",
                "provenance": "player_assertion" if player_authored else str(payload.get("provenance", "runtime")),
                "evidence_refs": evidence,
                "classification": classification,
                "location_ref": location,
                "discoverability_milli": discoverability,
                "investigation_discoverable": investigation_discoverable,
                "origin_authority": origin_authority,
                "world_truth_authority": False,
                "claim_status": claim_status,
                "knowers": knowers,
                "holder_states": holder_states,
                "deliveries": [],
                "created_at": str(now),
            }
            self.put(path, doc)
            idx.setdefault("claims", {})[ref] = path
            by_holder = idx.setdefault("by_holder", {})
            for knower in knowers:
                holder_refs = by_holder.setdefault(knower, [])
                if ref not in holder_refs:
                    holder_refs.append(ref)
                    holder_refs.sort()
            self.put(idxp, idx)
            self._register_owner(ref, path)
            sidx = self._information_subject_index()
            refs = sidx.setdefault("subjects", {}).setdefault(subject, [])
            if ref not in refs:
                refs.append(ref)
                refs.sort()
            self.put("state/information/subject-index.json", sidx)
            target_time = now.add_seconds(300)
            metrics = self._advance_exact_or_reject(target_time, "information recording")
            self._write_meta(command, str(target_time))
            return self._result(
                information_ref=ref,
                subject_ref=subject,
                epistemic_kind=kind,
                confidence_milli=confidence,
                world_time=str(target_time),
                **metrics,
            )

        ref = str(payload["information_ref"])
        path = idx.get("claims", {}).get(ref)
        if not path:
            raise ValueError("unknown information claim")
        pre_doc = self.read(path)
        target = str(payload.get("target_ref", self.PLAYER_ACTOR))
        _, target_person = self._exact_person(target)
        sender_ref = command.actor_id if command.actor_id != self.INTERNAL_ACTOR else str(
            payload.get("source_ref", pre_doc.get("knowers", [self.PLAYER_ACTOR])[0] if pre_doc.get("knowers") else self.PLAYER_ACTOR)
        )
        _, sender = self._exact_person(sender_ref)
        sender_loc = self._person_location(sender)
        target_loc = self._person_location(target_person)
        if sender_ref not in pre_doc.get("knowers", []):
            raise PermissionError("information may travel only from an exact saved knower")
        if not sender_loc or not target_loc:
            raise ValueError("information delivery requires exact sender and recipient locations")

        channel = str(payload.get("channel", "courier"))
        hours = self._route_travel_hours(sender_loc, target_loc)
        seconds = 300 if hours == 0 else hours * 3600
        departed = str(now)
        target_time = now.add_seconds(seconds)
        metrics = self._advance_exact_or_reject(target_time, "information delivery")

        # Rehydrate the claim/recipient after the elapsed route so concurrent
        # information or person updates are not overwritten by a stale snapshot.
        doc = copy.deepcopy(self.read(path))
        _, target_after = self._exact_person(target)
        if self._person_location(target_after) != target_loc:
            raise ValueError("information recipient left the routed delivery destination before arrival")
        if sender_ref not in doc.get("knowers", []):
            raise PermissionError("information source ceased to be a lawful saved knower")
        knowers = doc.setdefault("knowers", [])
        if target not in knowers:
            knowers.append(target)
            knowers.sort()
        source_states = doc.get("holder_states") if isinstance(doc.get("holder_states"), Mapping) else {}
        source_state = source_states.get(sender_ref, {}) if isinstance(source_states, Mapping) else {}
        source_conf = int(source_state.get("confidence_milli", doc.get("confidence_milli", 1000)))
        delivered_conf = max(0, min(1000, source_conf * _INFO_CHANNELS[channel] // 1000))
        holder_states = doc.setdefault("holder_states", {})
        holder_states[target] = {
            "epistemic_kind": "report",
            "confidence_milli": delivered_conf,
            "source_ref": sender_ref,
            "channel": channel,
            "learned_at": str(target_time),
        }
        delivery = {
            "source_ref": sender_ref,
            "target_ref": target,
            "departed_at": departed,
            "arrived_at": str(target_time),
            "source_location_ref": sender_loc,
            "target_location_ref": target_loc,
            "channel": channel,
            "travel_hours": hours,
            "confidence_milli": delivered_conf,
        }
        deliveries = doc.setdefault("deliveries", [])
        deliveries.append(delivery)
        doc["deliveries"] = deliveries[-64:]
        self.put(path, doc)
        latest_idx = copy.deepcopy(self.read(idxp))
        holder_refs = latest_idx.setdefault("by_holder", {}).setdefault(target, [])
        if ref not in holder_refs:
            holder_refs.append(ref)
            holder_refs.sort()
        self.put(idxp, latest_idx)
        self._write_meta(command, str(target_time))
        return self._result(
            information_ref=ref,
            delivered_to=target,
            channel=channel,
            confidence_milli=delivered_conf,
            world_time=str(target_time),
            travel_hours=hours,
            **metrics,
        )

    def _investigation_score(self, person: Mapping[str, Any], hours: int, ref: str) -> int:
        skills=_person_skills(person); attrs=_person_attrs(person); skill=max(_number(skills.get("Intelligence Operations")),_number(skills.get("Scouting")),_number(skills.get("Intelligence Operations")),_number(skills.get("Law"))); cognition=(_number(attrs.get("Intelligence"))+_number(attrs.get("Awareness"))+_number(attrs.get("Composure")))/3.0; base=int(round(skill*6+cognition*2+min(240,hours*10))); jitter=int(hashlib.sha256(ref.encode()).hexdigest()[:4],16)%61-30; return max(0,min(1000,base+jitter))

    def _dispatch_investigation(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        action = str(payload["action"])
        ref = str(payload["investigation_ref"])
        path = _investigation_path(ref)
        idxp = "state/investigations/index.json"
        idx = copy.deepcopy(self.read(idxp))
        now = self._world_time()
        investigator_ref = str(payload.get("investigator_ref", command.actor_id))
        if action == "start":
            _pp, person = self._exact_person(investigator_ref)
            loc = payload.get("location_ref") or self._person_location(person)
            doc = {
                "schema": "sword-investigation",
                "investigation_ref": ref,
                "question": str(payload["question"]),
                "subject_ref": str(payload["subject_ref"]),
                "location_ref": loc,
                "investigator_ref": investigator_ref,
                "status": "active",
                "started_at": str(now),
                "worked_hours": 0,
                "discovered_claim_refs": [],
            }
            self.put(path, doc)
            idx.setdefault("investigations", {})[ref] = path
            self._index_actor_ref(idx, investigator_ref, ref)
            self._set_actor_active(idx, investigator_ref, ref, True)
            self._index_status_ref(idx, "active", ref)
            self.put(idxp, idx)
            self._register_owner(ref, path)
            self._write_meta(command, str(now))
            return self._result(investigation_ref=ref, status="active", world_time=str(now))

        doc = copy.deepcopy(self.read(path))
        if action == "close":
            doc["status"] = "closed"
            doc["closed_at"] = str(now)
            self.put(path, doc)
            self._index_status_ref(idx, "closed", ref)
            self._set_actor_active(idx, str(doc.get("investigator_ref")), ref, False)
            self.put(idxp, idx)
            self._write_meta(command, str(now))
            return self._result(
                investigation_ref=ref,
                status="closed",
                discovered_claim_refs=doc.get("discovered_claim_refs", []),
                world_time=str(now),
            )
        if doc.get("status") != "active":
            raise ValueError("investigation is not active")

        hours = int(payload.get("hours", 1))
        investigator_ref = str(payload.get("investigator_ref", doc.get("investigator_ref")))
        _pp, person_before = self._exact_person(investigator_ref)
        if doc.get("location_ref") and self._person_location(person_before) != doc.get("location_ref"):
            raise ValueError("investigation work requires investigator at the exact investigation location")
        target = now.add_seconds(hours * 3600)
        metrics = self._advance_exact_or_reject(target, "investigation work")

        # Re-read both process and actor after causal settlement.
        doc = copy.deepcopy(self.read(path))
        if doc.get("status") != "active":
            raise ValueError("investigation changed state before the work interval completed")
        _pp, person_after = self._exact_person(investigator_ref)
        if doc.get("location_ref") and self._person_location(person_after) != doc.get("location_ref"):
            raise ValueError("investigator did not remain at the exact investigation location")
        score = self._investigation_score(person_after, hours, f"{ref}:{target}:{doc.get('worked_hours', 0)}")
        sidx = self._information_subject_index()
        discovered: list[str] = []
        information_index = self.read("state/information/index.json")
        candidates = information_claim_refs_for_subject(
            self.read_optional, information_index, sidx, str(doc.get("subject_ref") or ""),
        )
        info_idx = information_index.get("claims", {}) if isinstance(information_index, Mapping) else {}
        for claim_ref in candidates:
            if claim_ref in doc.get("discovered_claim_refs", []):
                continue
            cpath = info_idx.get(claim_ref)
            if not isinstance(cpath, str):
                continue
            claim = copy.deepcopy(self.read(cpath))
            if claim.get("origin_authority") == "player_assertion" or claim.get("investigation_discoverable") is False:
                continue
            if "investigation_discoverable" not in claim and not claim.get("evidence_refs"):
                # A claim without discoverability authority or evidence is not a
                # discoverable world trace. Keep it as hearsay/knowledge only.
                continue
            required = int(claim.get("discoverability_milli", 500))
            claim_loc = claim.get("location_ref")
            if claim_loc is not None and doc.get("location_ref") is not None and claim_loc != doc.get("location_ref"):
                continue
            if score < required:
                continue
            knowers = claim.setdefault("knowers", [])
            if investigator_ref not in knowers:
                knowers.append(investigator_ref)
                knowers.sort()
            claim.setdefault("holder_states", {})[investigator_ref] = {
                "epistemic_kind": "observation" if claim.get("origin_authority") == "runtime_established" and claim.get("evidence_refs") else "report",
                "confidence_milli": min(int(claim.get("confidence_milli", 700)), max(400, score)),
                "source_ref": ref,
                "channel": "investigation",
                "learned_at": str(target),
            }
            self.put(cpath, claim)
            latest_idx = copy.deepcopy(self.read("state/information/index.json"))
            holder_refs = latest_idx.setdefault("by_holder", {}).setdefault(investigator_ref, [])
            if claim_ref not in holder_refs:
                holder_refs.append(claim_ref)
                holder_refs.sort()
            self.put("state/information/index.json", latest_idx)
            discovered.append(claim_ref)

        doc["worked_hours"] = int(doc.get("worked_hours", 0)) + hours
        known = doc.setdefault("discovered_claim_refs", [])
        known.extend(x for x in discovered if x not in known)
        known.sort()
        self.put(path, doc)
        self._write_meta(command, str(target))
        return self._result(
            investigation_ref=ref,
            hours=hours,
            search_score_milli=score,
            new_claim_refs=discovered,
            known_claim_refs=known,
            world_time=str(target),
            **metrics,
        )

    def _commission_issuer_location(self, issuer_ref: str) -> str:
        """Resolve the exact physical endpoint for a commission issuer.

        Institutions do not receive messages in the abstract. Houses route to
        their exact leader, polities route to their registered royal court, and
        exact-person/institution owners must expose a physical location directly
        or through an exact leader/sovereign.
        """
        issuer_ref = str(issuer_ref or "")
        if not issuer_ref:
            raise ValueError("commission issuer requires an exact ref")
        if issuer_ref.startswith("state_"):
            attendance = self.read_optional("state/index/court-attendance-index.json") or {}
            courts = attendance.get("courts", {}) if isinstance(attendance, Mapping) else {}
            row = courts.get(issuer_ref) if isinstance(courts, Mapping) else None
            capital = row.get("capital_ref") if isinstance(row, Mapping) else None
            if isinstance(capital, str) and capital:
                return capital
        try:
            _path, owner = self.owner(issuer_ref)
        except (FileNotFoundError, KeyError, ValueError):
            owner = None
        if isinstance(owner, Mapping):
            for key in ("current_location", "location_ref", "location", "seat_ref", "capital_ref"):
                value = owner.get(key)
                if isinstance(value, str) and value:
                    return value
            for key in ("leader_ref", "sovereign_ref", "commander_ref"):
                person_ref = owner.get(key)
                location = command_person_location(self, person_ref)
                if location:
                    return location
        location = command_person_location(self, issuer_ref)
        if location:
            return location
        raise ValueError("commission issuer has no exact physical message endpoint")

    def _commission_communication(self, issuer_ref: str, *, round_trip: bool) -> dict[str, Any]:
        player = self.read("state/player.json")
        source = str(player.get("current_location") or player.get("location") or "")
        if not source:
            raise ValueError("commission communication requires the player's exact current location")
        destination = self._commission_issuer_location(issuer_ref)
        return command_message_route(self.read, source, destination, round_trip=round_trip)

    def _schedule_commission(self, request_ref: str, due: CampaignTime) -> None:
        rt=copy.deepcopy(self.read("state/runtime.json")); digest=hashlib.sha256(request_ref.encode()).hexdigest()[:20]; host_id=f"host_commission_{digest}"; event_id=f"event_commission_{digest}"; rt.setdefault("hosts",{})[host_id]={"host_id":host_id,"kind":"commission","owner_ref":request_ref,"request_ref":request_ref,"event_id":event_id,"next_due":str(due),"recurrence_seconds":0,"resolved_through":str(self._world_time()),"safe_through":str(due.add_seconds(-1))}; rt.setdefault("events",[]).append({"event_id":event_id,"kind":"commission_response","priority":55,"target_host":host_id,"due_at":str(due)}); self.put("state/runtime.json",rt)

    def _schedule_commitment_due(self, commitment_ref: str, due: CampaignTime) -> None:
        rt = copy.deepcopy(self.read("state/runtime.json")); digest = hashlib.sha256(commitment_ref.encode()).hexdigest()[:20]
        host_id=f"host_commitment_{digest}"; event_id=f"event_commitment_{digest}"
        rt.setdefault("hosts",{})[host_id]={"host_id":host_id,"kind":"commitment_due","owner_ref":commitment_ref,"commitment_ref":commitment_ref,"event_id":event_id,"next_due":str(due),"recurrence_seconds":0,"resolved_through":str(self._world_time()),"safe_through":str(due.add_seconds(-1))}
        rt.setdefault("events",[]).append({"event_id":event_id,"kind":"commitment_due","priority":60,"target_host":host_id,"due_at":str(due)})
        self.put("state/runtime.json",rt)

    def _schedule_commission_settlement(self, commission_ref: str, due: CampaignTime) -> None:
        rt = copy.deepcopy(self.read("state/runtime.json")); digest = hashlib.sha256((commission_ref+":settlement").encode()).hexdigest()[:20]
        host_id=f"host_commission_settlement_{digest}"; event_id=f"event_commission_settlement_{digest}"
        rt.setdefault("hosts",{})[host_id]={"host_id":host_id,"kind":"commission_settlement","owner_ref":commission_ref,"commission_ref":commission_ref,"event_id":event_id,"next_due":str(due),"recurrence_seconds":0,"resolved_through":str(self._world_time()),"safe_through":str(due.add_seconds(-1))}
        rt.setdefault("events",[]).append({"event_id":event_id,"kind":"commission_settlement","priority":58,"target_host":host_id,"due_at":str(due)})
        self.put("state/runtime.json",rt)

    def _autonomy_commitment_due(self, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
        ref = str(host.get("commitment_ref") or host.get("owner_ref") or "")
        if not ref:
            return None
        path = _commitment_path(ref); doc = copy.deepcopy(self.read(path))
        if doc.get("status") != "active":
            return None
        due = doc.get("due_at")
        if not isinstance(due, str) or CampaignTime.parse(due) > CampaignTime.parse(at):
            return None
        doc["status"]="overdue"; doc["overdue_at"]=at; self.put(path,doc)
        idxp="state/commitments/index.json"; idx=copy.deepcopy(self.read(idxp)); self._index_status_ref(idx,"overdue",ref); self.put(idxp,idx)
        histp="state/history/events/index.json"; hist=copy.deepcopy(self.read(histp)); hist.setdefault("events",[]).append({"event_id":"commitment_overdue_"+hashlib.sha256(f"{ref}:{at}".encode()).hexdigest()[:16],"kind":"commitment_overdue","at":at,"commitment_ref":ref,"obligor_ref":doc.get("obligor_ref"),"beneficiary_ref":doc.get("beneficiary_ref")}); self.put(histp,hist)
        return {"commitment_ref":ref,"status":"overdue"}

    def _autonomy_commission_settlement(self, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
        ref=str(host.get("commission_ref") or host.get("owner_ref") or "")
        if not ref: return None
        path=_commission_path(ref); doc=copy.deepcopy(self.read(path))
        if doc.get("status") not in {"report_in_transit", "reported"} or not doc.get("settlement_pending"): return None
        response_due = doc.get("report_response_due_at")
        if isinstance(response_due, str) and CampaignTime.parse(at) < CampaignTime.parse(response_due):
            return None
        claims=[]
        for evidence_ref in doc.get("evidence_refs",[]):
            try: claims.append(self._evidence_claim(self.INTERNAL_ACTOR,str(evidence_ref),require_authoritative=True)[1])
            except (ValueError,PermissionError,FileNotFoundError): continue
        accepted_at = CampaignTime.parse(str(doc.get("accepted_at"))) if isinstance(doc.get("accepted_at"), str) else None
        location_ref = str(doc.get("location_ref", ""))
        direct_subjects = {str(doc.get("commission_ref", "")), str(doc.get("archetype_ref", ""))}
        category = str(doc.get("category", ""))
        location_evidence_categories = {"reconnaissance", "inspection", "investigation", "intelligence"}
        supporting=[]
        for claim in claims:
            subject_ref = str(claim.get("subject_ref", ""))
            claim_location = str(claim.get("location_ref", ""))
            created_raw = claim.get("created_at")
            if accepted_at is not None and isinstance(created_raw, str):
                try:
                    if CampaignTime.parse(created_raw) < accepted_at:
                        continue
                except ValueError:
                    continue
            kind = str(claim.get("epistemic_kind", ""))
            if kind not in {"observation", "document", "captured_document", "official_report", "testimony", "report"}:
                continue
            direct_support = subject_ref in direct_subjects
            location_support = (
                category in location_evidence_categories
                and bool(location_ref)
                and claim_location == location_ref
                and kind in {"observation", "document", "captured_document", "official_report", "testimony"}
            )
            if direct_support or location_support:
                supporting.append(claim)
        doc["settlement_pending"]=False; doc["reviewed_at"]=at
        if doc.get("status") == "report_in_transit":
            doc["report_delivered_at"] = doc.get("report_delivery_due_at") or at
        if supporting:
            doc["status"]="completed"; doc["completed_at"]=at; doc["settlement_result"]="supported_by_runtime_established_evidence"
        else:
            doc["settlement_result"]="insufficient_relevant_evidence"; doc["status"]="reported"
        self.put(path,doc)
        idxp="state/commissions/index.json"; idx=copy.deepcopy(self.read(idxp)); self._index_status_ref(idx,str(doc["status"]),ref); self._set_actor_active(idx,str(doc.get("assignee_ref")),ref,doc.get("status") in {"report_in_transit", "reported"}); self.put(idxp,idx)
        histp="state/history/events/index.json"; hist=copy.deepcopy(self.read(histp)); hist.setdefault("events",[]).append({"event_id":"commission_review_"+hashlib.sha256(f"{ref}:{at}".encode()).hexdigest()[:16],"kind":"commission_review","at":at,"commission_ref":ref,"status":doc["status"],"settlement_result":doc.get("settlement_result")}); self.put(histp,hist)
        return {"commission_ref":ref,"status":doc["status"],"settlement_result":doc.get("settlement_result")}

    def _commission_location(self, seed_text: str) -> str:
        player=self.read("state/player.json"); origin=str(player.get("location","loc_kanyou")); routes=self.read("game/data/world/routes.json").get("routes",[]); dests=[]
        for row in routes if isinstance(routes,list) else []:
            if not isinstance(row,Mapping): continue
            a,b=row.get("a",row.get("from")),row.get("b",row.get("to"))
            if a==origin and isinstance(b,str): dests.append(b)
            elif b==origin and isinstance(a,str): dests.append(a)
        if not dests: return origin
        dests=sorted(set(dests)); return dests[int(hashlib.sha256(seed_text.encode()).hexdigest()[:8],16)%len(dests)]

    def _autonomy_commission(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        request_ref=str(host.get("request_ref",host.get("owner_ref",""))); path=_commission_request_path(request_ref); req0=self.read_optional(path)
        if not isinstance(req0,Mapping) or req0.get("status")!="pending": return
        responds_at = req0.get("responds_at")
        if isinstance(responds_at, str) and CampaignTime.parse(at) < CampaignTime.parse(responds_at):
            return None
        req=copy.deepcopy(dict(req0)); catalog=self.read("game/data/content/mission-archetypes.json"); rows=[x for x in catalog.get("archetypes",[]) if isinstance(x,Mapping)]; category=req.get("category")
        if isinstance(category,str) and category: rows=[x for x in rows if str(x.get("category"))==category]
        if not rows and isinstance(category,str) and category:
            req["status"]="rejected"; req["responded_at"]=at; req["rejection_reason"]="issuer has no registered commission archetype in the requested category"; self.put(path,req)
            idxp="state/commissions/index.json"; idx=copy.deepcopy(self.read(idxp)); self._index_status_ref(idx,"rejected",request_ref); self._set_actor_active(idx,str(req.get("requester_ref")),request_ref,False); self.put(idxp,idx)
            events_path="state/history/events/index.json"; hist=copy.deepcopy(self.read(events_path)); event_id="commission_rejection_"+hashlib.sha256(f"{request_ref}:{at}".encode()).hexdigest()[:16]; hist.setdefault("events",[]).append({"event_id":event_id,"kind":"commission_request_rejected","at":at,"request_ref":request_ref,"issuer_ref":req.get("issuer_ref"),"category":category,"reason":req["rejection_reason"]}); self.put(events_path,hist)
            return {"commission_ref": request_ref, "event_id": event_id}
        if not rows: raise ValueError("commission archetype catalog is empty")
        rows=sorted(rows,key=lambda x:str(x.get("id"))); seed=f"{request_ref}:{self.read('state/meta.json').get('world_seed','sword')}"; chosen=rows[int(hashlib.sha256(seed.encode()).hexdigest()[:8],16)%len(rows)]; digest=hashlib.sha256((seed+":offer").encode()).hexdigest()[:16]; commission_ref=f"commission.{digest}"; cpath=_commission_path(commission_ref); loc=self._commission_location(seed)
        risk=250+(int(hashlib.sha256((seed+":risk").encode()).hexdigest()[:8],16)%601); risk_band=("low" if risk<400 else "moderate" if risk<650 else "high")
        doc={"schema":"sword-commission","commission_ref":commission_ref,"request_ref":request_ref,"issuer_ref":req.get("issuer_ref"),"assignee_ref":req.get("requester_ref"),"archetype_ref":chosen.get("id"),"category":chosen.get("category"),"objective":chosen.get("description"),"location_ref":loc,"status":"offered","offered_at":at,"accepted_at":None,"reported_at":None,"evidence_refs":[],"hidden_assignment_profile":{"risk_milli":risk,"issuer_risk_band":risk_band,"profile_authority":"issuer_risk_assessment_not_world_truth","seed_commitment":hashlib.sha256(seed.encode()).hexdigest()},"assignment_rule":catalog.get("assignment_rule")}; self.put(cpath,doc); self._register_owner(commission_ref,cpath); idxp="state/commissions/index.json"; idx=copy.deepcopy(self.read(idxp)); idx.setdefault("commissions",{})[commission_ref]=cpath; self._index_actor_ref(idx, str(req.get("requester_ref")), commission_ref); self._set_actor_active(idx,str(req.get("requester_ref")),request_ref,False); self._set_actor_active(idx,str(req.get("requester_ref")),commission_ref,True); self._index_status_ref(idx,"offered",commission_ref); self._index_status_ref(idx,"offered",request_ref); self.put(idxp,idx); req["status"]="offered"; req["commission_ref"]=commission_ref; req["responded_at"]=at; self.put(path,req)
        # The player-facing event advertises the precommitted offer without exposing the hidden profile.
        events_path="state/history/events/index.json"; hist=copy.deepcopy(self.read(events_path)); event_id="commission_offer_"+digest; hist.setdefault("events",[]).append({"event_id":event_id,"kind":"commission_offer","at":at,"commission_ref":commission_ref,"issuer_ref":req.get("issuer_ref"),"assignee_ref":req.get("requester_ref"),"category":chosen.get("category"),"location_ref":loc,"objective":chosen.get("description")}); self.put(events_path,hist)
        return {"commission_ref": commission_ref, "event_id": event_id}

    def _dispatch_commission(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        action=str(payload["action"]); now=self._world_time(); idxp="state/commissions/index.json"; idx=copy.deepcopy(self.read(idxp))
        if action=="request":
            request_ref=str(payload["request_ref"]); path=_commission_request_path(request_ref)
            if self.read_optional(path) is not None: raise ValueError("commission request already exists")
            issuer=str(payload.get("issuer_ref") or "house_tang"); category=payload.get("category")
            route=self._commission_communication(issuer, round_trip=True)
            travel_seconds=max(0,int(route.get("travel_seconds",0) or 0))
            processing_seconds=6*3600
            due=now.add_seconds(travel_seconds+processing_seconds)
            one_way=max(0,int(route.get("one_way_seconds",0) or 0))
            doc={
                "schema":"sword-commission-request","request_ref":request_ref,"requester_ref":command.actor_id,
                "issuer_ref":issuer,"category":category,"status":"pending","requested_at":str(now),
                "request_delivery_due_at":str(now.add_seconds(one_way)),"responds_at":str(due),
                "source_location_ref":route.get("origin_ref"),"issuer_location_ref":route.get("destination_ref"),
                "communication_travel_seconds":travel_seconds,"issuer_processing_seconds":processing_seconds,
                "communication_route":dict(route),
                "communication_rule":"requested_at is dispatch, not receipt; issuer response becomes player-usable only after physical round-trip delivery plus processing",
            }
            self.put(path,doc); idx.setdefault("requests",{})[request_ref]=path; self._index_actor_ref(idx, command.actor_id, request_ref); self._set_actor_active(idx,command.actor_id,request_ref,True); self._index_status_ref(idx,"pending",request_ref); self.put(idxp,idx); self._register_owner(request_ref,path); self._schedule_commission(request_ref,due); self._write_meta(command,str(now)); return self._result(request_ref=request_ref,status="pending",responds_at=str(due),communication_travel_seconds=travel_seconds,world_time=str(now))
        ref=str(payload["commission_ref"]); path=_commission_path(ref); doc=copy.deepcopy(self.read(path)); status=str(doc.get("status"))
        if action=="accept":
            if status!="offered": raise ValueError("commission is not awaiting acceptance")
            doc["status"]="active"; doc["accepted_at"]=str(now)
        elif action=="decline":
            if status!="offered": raise ValueError("commission is not awaiting a decision")
            doc["status"]="declined"; doc["declined_at"]=str(now)
        else:
            if status not in {"active","reported"}: raise ValueError("only an active or evidence-insufficient reported commission may be reported")
            if status=="reported" and doc.get("settlement_result")!="insufficient_relevant_evidence": raise ValueError("commission report is already under or past settlement")
            refs=[str(x) for x in payload.get("evidence_refs",[])]
            route=self._commission_communication(str(doc.get("issuer_ref") or ""), round_trip=True)
            travel_seconds=max(0,int(route.get("travel_seconds",0) or 0)); one_way=max(0,int(route.get("one_way_seconds",0) or 0)); review_seconds=3600
            response_due=now.add_seconds(travel_seconds+review_seconds)
            doc["status"]="report_in_transit"; doc["reported_at"]=str(now); doc["report_dispatched_at"]=str(now); doc["report_ref"]=payload.get("report_ref"); doc["evidence_refs"]=refs; doc["settlement_pending"]=True; doc.pop("settlement_result",None)
            doc["report_source_location_ref"]=route.get("origin_ref"); doc["report_issuer_location_ref"]=route.get("destination_ref"); doc["report_delivery_due_at"]=str(now.add_seconds(one_way)); doc["report_response_due_at"]=str(response_due); doc["communication_travel_seconds"]=travel_seconds; doc["issuer_review_seconds"]=review_seconds; doc["communication_route"]=dict(route); doc["communication_rule"]="reported_at is dispatch, not issuer receipt; evidence cannot settle until physical delivery, issuer review, and returned response"
            self._schedule_commission_settlement(ref,response_due)
        self._index_status_ref(idx,str(doc["status"]),ref)
        self._set_actor_active(idx,str(doc.get("assignee_ref")),ref,doc.get("status") in {"offered","active","report_in_transit","reported"})
        self.put(idxp,idx); self.put(path,doc); self._write_meta(command,str(now)); return self._result(commission_ref=ref,status=doc["status"],world_time=str(now),settlement_pending=doc.get("settlement_pending",False))

    def _medical_treatment_supply_reservation(
        self,
        *,
        command: Any,
        payload: Mapping[str, Any],
        target_location_ref: str,
        treatment: str,
        injury_mechanics: Mapping[str, Any],
    ) -> dict[str, Any]:
        rules = injury_mechanics.get("medical_treatment_resources")
        if not isinstance(rules, Mapping):
            raise ValueError("medical treatment resource mechanics are missing")
        costs = rules.get("lots_by_treatment")
        if not isinstance(costs, Mapping) or treatment not in costs:
            raise ValueError("medical treatment resource cost is not registered")
        raw_cost = costs.get(treatment)
        if isinstance(raw_cost, bool) or not isinstance(raw_cost, int) or raw_cost < 0:
            raise ValueError("medical treatment resource cost is invalid")
        cost = int(raw_cost)
        if cost == 0:
            return {
                "medical_supply_ref": None,
                "medicine_lots_before": None,
                "medicine_lots_consumed": 0,
                "medicine_lots_after": None,
            }

        supply_ref = payload.get("medical_supply_ref")
        facility_ref = payload.get("facility_ref")
        if supply_ref is None and isinstance(facility_ref, str) and facility_ref and not facility_ref.startswith("loc_"):
            _fp, facility = self.owner(facility_ref)
            fstocks = facility.get("stocks") if isinstance(facility, Mapping) else None
            if isinstance(fstocks, Mapping) and isinstance(fstocks.get("medicine_lots"), int) and not isinstance(fstocks.get("medicine_lots"), bool):
                supply_ref = facility_ref

        if supply_ref is None:
            fort_index = self.read("state/fortifications/index.json")
            static = fort_index.get("static_profiles") if isinstance(fort_index, Mapping) else None
            row = static.get(target_location_ref) if isinstance(static, Mapping) else None
            if isinstance(row, Mapping):
                live_ref = row.get("live_logistics_depot_ref")
                if live_ref is not None:
                    if not isinstance(live_ref, str) or not live_ref:
                        raise ValueError("fortified-site live medical depot route is invalid")
                    # A non-null live route is a promise of an exact hot owner.
                    # If it is stale or broken, fail closed rather than treating
                    # the site as though its medical stock did not matter.
                    self.owner(live_ref)
                    supply_ref = live_ref

        if supply_ref is None:
            raise ValueError(
                "stabilize/treat/surgery requires exact co-located medical stock; "
                "provide medical_supply_ref or use a materialized fortified medical depot"
            )

        supply_path, supply0 = self.owner(str(supply_ref))
        if not isinstance(supply0, Mapping):
            raise ValueError("medical supply owner is invalid")
        exact_locations = {
            str(supply0.get(key))
            for key in ("location_ref", "current_location", "location", "site_ref")
            if isinstance(supply0.get(key), str) and supply0.get(key)
        }
        if target_location_ref not in exact_locations:
            raise ValueError("medical supply owner is not at the exact treatment location")
        stocks0 = supply0.get("stocks")
        if not isinstance(stocks0, Mapping):
            raise ValueError("medical supply owner has no exact stock ledger")
        before_raw = stocks0.get("medicine_lots")
        if isinstance(before_raw, bool) or not isinstance(before_raw, int) or before_raw < 0:
            raise ValueError("medical supply owner medicine_lots stock is invalid")
        before = int(before_raw)
        if before < cost:
            raise ValueError(f"medical treatment requires {cost} medicine_lots but only {before} are available")

        supply = copy.deepcopy(supply0)
        stocks = supply.setdefault("stocks", {})
        stocks["medicine_lots"] = before - cost
        history = supply.setdefault("consumption_history", [])
        if not isinstance(history, list):
            raise ValueError("medical supply consumption_history is invalid")
        history.append({
            "at": str(self._world_time()),
            "kind": "medical_treatment",
            "target_ref": str(payload.get("target_ref", command.actor_id)),
            "practitioner_ref": str(payload.get("practitioner_ref", command.actor_id)),
            "treatment": treatment,
            "medicine_lots": cost,
            "semantic_digest": str(command.semantic_digest),
        })
        supply["consumption_history"] = history[-128:]
        self.put(supply_path, supply)
        return {
            "medical_supply_ref": str(supply_ref),
            "medicine_lots_before": before,
            "medicine_lots_consumed": cost,
            "medicine_lots_after": before - cost,
        }

    def _dispatch_medical_treatment(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        target_ref = str(payload.get("target_ref", command.actor_id))
        practitioner_ref = str(payload.get("practitioner_ref", command.actor_id))
        _tp, target_before = self._exact_person(target_ref)
        _pp, practitioner_before = self._exact_person(practitioner_ref)
        target_loc = self._person_location(target_before)
        practitioner_loc = self._person_location(practitioner_before)
        if not target_loc or target_loc != practitioner_loc:
            raise ValueError("medical treatment requires exact co-location")
        injury_before = target_before.get("injury_state")
        if not isinstance(injury_before, dict) or not injury_before.get("active"):
            raise ValueError("target has no active injury requiring treatment")

        treatment = str(payload.get("treatment", "treat"))
        hours = int(payload.get("hours", 2))
        facility_ref = payload.get("facility_ref")
        body_site = payload.get("body_site")
        injury_mechanics = self.read("game/data/mechanics/injury.json")
        supply_accounting = self._medical_treatment_supply_reservation(
            command=command, payload=payload, target_location_ref=target_loc,
            treatment=treatment, injury_mechanics=injury_mechanics,
        )
        target_time = self._world_time().add_seconds(hours * 3600)
        metrics = self._advance_exact_or_reject(target_time, "medical treatment")

        # Rehydrate after elapsed causal settlement. This prevents medical care
        # from restoring a stale pre-treatment person snapshot over other lawful
        # changes that happened during the same hours.
        tp, target0 = self._exact_person(target_ref)
        _pp, practitioner0 = self._exact_person(practitioner_ref)
        target = copy.deepcopy(target0)
        practitioner = copy.deepcopy(practitioner0)
        if self._person_location(target) != target_loc or self._person_location(practitioner) != target_loc:
            raise ValueError("medical participants did not remain at the treatment location")
        injury = target.get("injury_state")
        if not isinstance(injury, dict) or not injury.get("active"):
            raise ValueError("target injury changed before treatment completion")

        learned_skill = _number(_person_skills(practitioner).get("Medicine"))
        body_function = anatomy_activity_factor(practitioner, "medicine")
        skill = learned_skill * body_function
        minimum_skill = {"stabilize": 20, "treat": 35, "surgery": 80, "rehabilitation": 25}[treatment]
        if skill < minimum_skill:
            if learned_skill >= minimum_skill and body_function < 0.999:
                raise PermissionError(
                    f"{treatment} requires effective Medicine {minimum_skill} or higher; permanent bodily function currently limits effective practice"
                )
            raise PermissionError(f"{treatment} requires Medicine {minimum_skill} or higher")
        if treatment == "surgery" and facility_ref is None:
            raise ValueError("surgery requires an exact medical facility/location_ref")
        facility_quality = 0
        if facility_ref is not None:
            if str(facility_ref).startswith("loc_"):
                facility = self._location_record(str(facility_ref))
                if str(facility_ref) != target_loc:
                    raise ValueError("medical facility must be the exact treatment location")
                functions = facility.get("functions", []) if isinstance(facility, Mapping) else []
                has_medical_function = isinstance(functions, list) and "medical" in functions
                if treatment == "surgery" and not has_medical_function:
                    raise ValueError("surgery requires a location with registered medical function")
                facility_quality = 20 if has_medical_function else 5
            else:
                _fp, facility = self.owner(str(facility_ref))
                if not isinstance(facility, Mapping):
                    raise ValueError("medical facility owner is invalid")
                facility_location = next((
                    str(facility.get(key)) for key in ("location_ref", "current_location", "location", "site_ref")
                    if isinstance(facility.get(key), str) and facility.get(key)
                ), None)
                if facility_location is None:
                    raise ValueError("medical facility owner does not prove an exact treatment location")
                if facility_location != target_loc:
                    raise ValueError("medical facility owner is not at the exact treatment location")
                facility_quality_milli = int(_number(facility.get("medical_quality_milli",0)))
                if treatment == "surgery" and facility_quality_milli <= 0:
                    raise ValueError("surgery requires a registered medical-capable facility owner")
                facility_quality = max(0, min(30, facility_quality_milli // 50))
        difficulty = {"minor": 20, "moderate": 35, "serious": 55, "severe": 55, "critical": 75}.get(str(injury.get("severity", "moderate")), 40)
        seed = int(hashlib.sha256(f"{command.semantic_digest}:{target_ref}:{treatment}".encode()).hexdigest()[:8], 16) % 21 - 10
        quality = max(0, min(100, int(round(skill + facility_quality + seed))))
        outcome = "completed"

        # Treatment begins immediately even though the command owns the entire
        # elapsed care interval.  Model the short interval needed to obtain
        # first hemorrhage control, then settle the remainder under the treated
        # wound state.  External compression/tourniquet can arrest accessible
        # bleeding; internal bleeding generally requires successful surgery.
        total_seconds = max(0.0, float(hours) * 3600.0)
        bleed = injury.get("bleeding") if isinstance(injury.get("bleeding"), dict) else {}
        total_rate = max(0.0, _number(bleed.get("rate_units_per_minute", injury.get("bleeding_units_per_minute", 0.0))))
        internal_rate = max(0.0, min(total_rate, _number(bleed.get("internal_rate_units_per_minute", injury.get("internal_bleeding_units_per_minute", 0.0)))))
        external_rate = max(0.0, total_rate - internal_rate)
        if total_rate > 0.0 and not bool(bleed.get("controlled", False)) and treatment in {"stabilize", "treat", "surgery"}:
            first_control_seconds = {
                "stabilize": max(4.0, 20.0 - 0.14 * quality),
                "treat": max(4.0, 18.0 - 0.12 * quality),
                "surgery": max(12.0, 55.0 - 0.35 * quality),
            }[treatment]
            first_control_seconds = min(total_seconds, first_control_seconds)
            sync_injury_record(target, injury)
            precontrol = advance_injury_physiology(target, injury_mechanics, elapsed_seconds=first_control_seconds)
            if precontrol.get("state") == "dead":
                target["died_at"] = str(target_time)
                target["death_reason"] = "physiological_collapse_before_hemorrhage_control"
                injury.setdefault("treatment_history", []).append({
                    "at": str(target_time), "treatment": treatment, "practitioner_ref": practitioner_ref,
                    "facility_ref": facility_ref, "body_site": body_site, "hours": hours,
                    "quality": quality, "outcome": "died_before_control",
                })
                sync_injury_record(target, injury)
                self._settle_person_death(target_ref,tp,target,str(target_time),"physiological_collapse_before_hemorrhage_control",settle_force_body=True)
                self._write_meta(command, str(target_time))
                return self._result(
                    target_ref=target_ref, practitioner_ref=practitioner_ref, treatment=treatment,
                    quality=quality, treatment_outcome="died_before_control", facility_ref=facility_ref,
                    body_site=body_site, world_time=str(target_time), physiology_state="dead",
                    **supply_accounting, **metrics,
                )
        else:
            first_control_seconds = 0.0
        if treatment == "stabilize":
            injury["stabilized_at"] = str(target_time)
            injury["stabilized_by_ref"] = practitioner_ref
            injury["stabilization_quality"] = quality
            external_rate *= 0.01 if quality >= difficulty else 0.10
            internal_rate *= 0.92
            if _number(injury.get("respiratory_compromise", 0.0)) > 0.0:
                injury["respiratory_compromise"] = round(_number(injury.get("respiratory_compromise")) * (0.28 if quality >= difficulty else 0.62), 3)
        elif treatment == "treat":
            reduction = max(0, min(24, int(round(hours * (0.5 + quality / 100.0)))))
            original = int(injury.get("minimum_recovery_hours", 24))
            injury["minimum_recovery_hours"] = max(max(4, original // 2), original - reduction)
            injury["treated_at"] = str(target_time)
            injury["treated_by_ref"] = practitioner_ref
            injury["treatment_quality"] = quality
            external_rate *= 0.005 if quality >= difficulty else 0.08
            internal_rate *= 0.75
            if _number(injury.get("respiratory_compromise", 0.0)) > 0.0:
                injury["respiratory_compromise"] = round(_number(injury.get("respiratory_compromise")) * (0.18 if quality >= difficulty else 0.48), 3)
        elif treatment == "surgery":
            if str(injury.get("severity")) not in {"serious", "severe", "critical"}:
                raise ValueError("surgery is reserved for severe or critical injuries")
            success = quality >= difficulty
            injury["surgery_at"] = str(target_time)
            injury["surgeon_ref"] = practitioner_ref
            injury["surgery_quality"] = quality
            injury["surgery_successful"] = success
            original = int(injury.get("minimum_recovery_hours", 72))
            injury["minimum_recovery_hours"] = max(24, int(round(original * (0.72 if success else 1.20))))
            outcome = "successful" if success else "complication"
            external_rate *= 0.0 if success else 0.05
            internal_rate *= 0.03 if success else 0.75
            if _number(injury.get("respiratory_compromise", 0.0)) > 0.0:
                injury["respiratory_compromise"] = round(_number(injury.get("respiratory_compromise")) * (0.06 if success else 0.58), 3)
        else:
            injury["rehabilitation_hours"] = int(injury.get("rehabilitation_hours", 0)) + hours
            injury["rehabilitation_quality"] = quality

        if treatment in {"stabilize", "treat", "surgery"}:
            remaining_rate = max(0.0, external_rate + internal_rate)
            injury["bleeding_units_per_minute"] = round(remaining_rate, 4)
            injury["internal_bleeding_units_per_minute"] = round(max(0.0, internal_rate), 4)
            bleeding_state = injury.setdefault("bleeding", {})
            bleeding_state["rate_units_per_minute"] = round(remaining_rate, 4)
            bleeding_state["internal_rate_units_per_minute"] = round(max(0.0, internal_rate), 4)
            bleeding_state["controlled"] = remaining_rate < 0.25
            bleeding_state["last_control_attempt_at"] = str(target_time)
            bleeding_state["last_control_quality"] = quality
            sync_injury_record(target, injury)
            remaining_seconds = max(0.0, total_seconds - first_control_seconds)
            physiology = advance_injury_physiology(target, injury_mechanics, elapsed_seconds=remaining_seconds)
            if physiology.get("state") == "dead":
                target["died_at"] = str(target_time)
                target["death_reason"] = "physiological_collapse_during_treatment"
                self._settle_person_death(target_ref,tp,target,str(target_time),"physiological_collapse_during_treatment",settle_force_body=True)
                outcome = "died_during_treatment"
            elif physiology.get("state") == "incapacitated":
                self._set_person_health(target, "injured")

        history = injury.setdefault("treatment_history", [])
        history.append({
            "at": str(target_time),
            "treatment": treatment,
            "practitioner_ref": practitioner_ref,
            "facility_ref": facility_ref,
            "body_site": body_site,
            "hours": hours,
            "quality": quality,
            "learned_medicine_skill": round(learned_skill, 3),
            "bodily_function_factor": round(body_function, 5),
            "effective_medicine_skill": round(skill, 3),
            "medical_supply_ref": supply_accounting.get("medical_supply_ref"),
            "medicine_lots_consumed": supply_accounting.get("medicine_lots_consumed", 0),
            "outcome": outcome,
        })
        injury["treatment_history"] = history[-32:]
        sync_injury_record(target, injury)
        self.put(tp, target)
        self._write_meta(command, str(target_time))
        return self._result(
            target_ref=target_ref,
            practitioner_ref=practitioner_ref,
            treatment=treatment,
            quality=quality,
            treatment_outcome=outcome,
            facility_ref=facility_ref,
            body_site=body_site,
            minimum_recovery_hours=injury.get("minimum_recovery_hours"),
            bleeding_units_per_minute=injury.get("bleeding_units_per_minute", 0.0),
            bleeding_controlled=bool(injury.get("bleeding", {}).get("controlled", False)) if isinstance(injury.get("bleeding"), Mapping) else False,
            physiology_state=(target.get("physiology_state", {}).get("consciousness") if isinstance(target.get("physiology_state"), Mapping) else None),
            world_time=str(target_time),
            **supply_accounting,
            **metrics,
        )

    def _dispatch_commitment(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        action=str(payload["action"]); ref=str(payload["commitment_ref"]); path=_commitment_path(ref); idxp="state/commitments/index.json"; idx=copy.deepcopy(self.read(idxp)); now=str(self._world_time())
        if action=="create":
            doc={"schema":"sword-commitment","commitment_ref":ref,"obligor_ref":str(payload["obligor_ref"]),"beneficiary_ref":str(payload["beneficiary_ref"]),"kind":str(payload.get("kind","promise")),"description":str(payload["description"]),"due_at":payload.get("due_at"),"status":"active","created_at":now,"evidence_refs":[]}; self.put(path,doc); idx.setdefault("commitments",{})[ref]=path; self._index_actor_ref(idx, doc["obligor_ref"], ref); self._index_actor_ref(idx, doc["beneficiary_ref"], ref); self._set_actor_active(idx,doc["obligor_ref"],ref,True); self._set_actor_active(idx,doc["beneficiary_ref"],ref,True); self._index_status_ref(idx,"active",ref); self.put(idxp,idx); self._register_owner(ref,path)
            if isinstance(doc.get("due_at"),str): self._schedule_commitment_due(ref,CampaignTime.parse(str(doc["due_at"])))
        else:
            doc=copy.deepcopy(self.read(path))
            if doc.get("status") not in {"active","overdue","fulfillment_claimed"}: raise ValueError("commitment is already terminal")
            evidence=payload.get("evidence_ref")
            if action=="fulfill":
                if doc.get("status")=="fulfillment_claimed": raise ValueError("fulfillment is already awaiting beneficiary confirmation")
                if not isinstance(evidence,str) or not evidence: raise ValueError("fulfillment claim requires exact evidence_ref")
                self._evidence_claim(command.actor_id,evidence,require_authoritative=True)
                if command.actor_id == self.INTERNAL_ACTOR:
                    doc["status"]="fulfilled"; doc["fulfilled_at"]=now
                else:
                    doc["status"]="fulfillment_claimed"; doc["fulfillment_claimed_at"]=now
                refs=doc.setdefault("evidence_refs",[])
                if evidence not in refs: refs.append(evidence)
            elif action=="confirm_fulfillment":
                if doc.get("status")!="fulfillment_claimed": raise ValueError("commitment has no pending fulfillment claim")
                doc["status"]="fulfilled"; doc["fulfilled_at"]=now; doc["confirmed_by_ref"]=command.actor_id
            elif action=="breach":
                doc["status"]="breached"; doc["breached_at"]=now
            else:
                doc["status"]="released"; doc["released_at"]=now
            self.put(path,doc)
            self._index_status_ref(idx,str(doc["status"]),ref)
            still_active=doc.get("status") in {"active","overdue","fulfillment_claimed"}
            self._set_actor_active(idx,str(doc.get("obligor_ref")),ref,still_active); self._set_actor_active(idx,str(doc.get("beneficiary_ref")),ref,still_active); self.put(idxp,idx)
        self._write_meta(command,now); return self._result(commitment_ref=ref,status=doc["status"],world_time=now)



__all__ = ["CampaignDepthMixin"]
