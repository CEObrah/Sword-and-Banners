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
from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.development import settle_skill_training
from sword_runtime.sim.calendar import CampaignTime

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
    if str(person.get("schema")) == "person-lite" and isinstance(person.get("stats"), Mapping):
        skills = person.get("stats", {}).get("skills", {})
    else:
        skills = person.get("skills", {})
    return skills if isinstance(skills, Mapping) else {}


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
        origin = str(claim.get("origin_authority", "legacy_unknown"))
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
        self.put("state/cmd/command-groups/index.json", idx)

    def _claim_primary_group_slot(self, idx: dict[str, Any], *, person_ref: str | None = None, formation_ref: str | None = None, group_ref: str) -> None:
        if person_ref:
            mapping = idx.setdefault("primary_person_group", {})
            current = mapping.get(person_ref)
            if current not in {None, group_ref}:
                raise ValueError(f"{person_ref} already has primary command assignment {current}")
            mapping[person_ref] = group_ref
        if formation_ref:
            mapping = idx.setdefault("primary_formation_group", {})
            current = mapping.get(formation_ref)
            if current not in {None, group_ref}:
                raise ValueError(f"{formation_ref} already has primary command assignment {current}")
            mapping[formation_ref] = group_ref

    def _advance_exact_or_reject(self, target: CampaignTime, label: str) -> dict[str, Any]:
        """Advance through the normal causal frontier without credit past an interrupt.

        Long-duration local work is atomic at the semantic-command layer. If an
        autonomous high-salience boundary stops chronology before the requested
        completion instant, rejecting here lets the surrounding transaction roll
        back rather than awarding hours that the campaign never actually reached.
        """
        metrics = self._advance_runtime(str(target))
        runtime = self.read("state/runtime.json")
        actual = CampaignTime.parse(str(runtime.get("world_time")))
        if actual != target:
            raise ValueError(f"{label} crossed a player-facing causal boundary before completion")
        return metrics

    def _validate_command_semantics(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._validate_command_semantics(command, payload)
        t = command.command_type
        if t == "command_group_action":
            action = str(payload.get("action", ""))
            if action not in {"create", "add_person", "remove_person", "attach_formation", "detach_formation", "set_deputy", "set_successors", "set_order", "set_communication"}:
                raise ValueError("unsupported command-group action")
            ref = _safe_ref(payload.get("command_group_ref"), "cmdgrp.", "command_group_ref")
            if action == "create":
                self._exact_person(str(payload.get("commander_ref", "")))
                if payload.get("parent_ref") is not None:
                    _safe_ref(payload.get("parent_ref"), "cmdgrp.", "parent_ref")
            elif action in {"add_person", "remove_person"}:
                self._exact_person(str(payload.get("person_ref", "")))
            elif action in {"attach_formation", "detach_formation"}:
                self._load_formation(str(payload.get("formation_ref", "")))
            elif action == "set_deputy" and payload.get("deputy_ref") is not None:
                self._exact_person(str(payload.get("deputy_ref")))
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
            elif action == "set_communication":
                value = payload.get("communication_ref")
                if value is not None and (not isinstance(value, str) or not value or len(value) > 160):
                    raise ValueError("communication_ref is invalid")
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
                self._require_command_group_authority(command.actor_id, str(payload.get("command_group_ref")))
            if t == "command_group_action" and action in {"add_person", "set_deputy", "set_successors"}:
                refs: list[str] = []
                if action == "add_person": refs = [str(payload.get("person_ref"))]
                elif action == "set_deputy" and payload.get("deputy_ref"): refs = [str(payload.get("deputy_ref"))]
                else: refs = [str(x) for x in payload.get("successor_refs", [])]
                for ref in refs: self._require_person_in_player_command(command.actor_id, ref)
            if t == "command_group_action" and action in {"attach_formation", "detach_formation"}:
                self._require_formation_authority(command.actor_id, str(payload.get("formation_ref")))
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

    def _require_command_group_authority(self, actor: str, group_ref: str) -> None:
        group = self.read(_group_path(group_ref))
        if actor in {str(group.get("commander_ref")), str(group.get("authority_ref"))}:
            return
        authority = str(group.get("authority_ref", ""))
        if authority in {"pforce.tang_wei", "force_tang_wei_personal"} and actor == self.PLAYER_ACTOR:
            return
        parent = group.get("parent_command_group_ref")
        if isinstance(parent, str) and parent:
            parent_doc = self.read(_group_path(parent))
            if actor in {str(parent_doc.get("commander_ref")), str(parent_doc.get("authority_ref"))}:
                return
            if str(parent_doc.get("authority_ref")) in {"pforce.tang_wei", "force_tang_wei_personal"} and actor == self.PLAYER_ACTOR:
                return
        raise PermissionError("actor lacks authority over this command group")

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

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") == "commitment_due":
            result = self._autonomy_commitment_due(host, due_text)
            if isinstance(result, Mapping) and result.get("commitment_ref"):
                digest = hashlib.sha256(f"{result['commitment_ref']}:{due_text}".encode()).hexdigest()[:16]
                self._pending_wake_created = {
                    "wake_ref": f"wake.campaign_event.commitment.{digest}",
                    "kind": "campaign_event",
                    "at": due_text,
                    "campaign_event_ref": str(result["commitment_ref"]),
                    "reason": "A durable commitment has reached its due time without recorded fulfillment.",
                    "target_host": getattr(self, "_active_host_id", None),
                    "event_id": getattr(self, "_active_event_id", None),
                }
            return
        if host.get("kind") == "commission_settlement":
            result = self._autonomy_commission_settlement(host, due_text)
            if isinstance(result, Mapping) and result.get("commission_ref"):
                digest = hashlib.sha256(f"{result['commission_ref']}:{due_text}:settlement".encode()).hexdigest()[:16]
                self._pending_wake_created = {
                    "wake_ref": f"wake.campaign_event.commission_settlement.{digest}",
                    "kind": "campaign_event",
                    "at": due_text,
                    "campaign_event_ref": str(result["commission_ref"]),
                    "reason": "The commission issuer has reviewed the submitted evidence.",
                    "target_host": getattr(self, "_active_host_id", None),
                    "event_id": getattr(self, "_active_event_id", None),
                }
            return
        if host.get("kind") != "commission":
            super()._run_due_host(host, due_text)
            return
        result = self._autonomy_commission(host, 1, due_text)
        if not isinstance(result, Mapping):
            self._pending_wake_created = None
            return
        commission_ref = str(result.get("commission_ref", ""))
        digest = hashlib.sha256(f"{commission_ref}:{due_text}".encode()).hexdigest()[:16]
        self._pending_wake_created = {
            "wake_ref": f"wake.campaign_event.commission.{digest}",
            "kind": "campaign_event",
            "at": due_text,
            "campaign_event_ref": commission_ref,
            "reason": "A requested commission has received a durable response.",
            "target_host": getattr(self, "_active_host_id", None),
            "event_id": getattr(self, "_active_event_id", None),
        }

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
                "schema":"command-group.v1", "id":ref, "commander_ref":commander_ref,
                "direct_unit_refs":[], "subordinate_command_group_refs":[], "parent_command_group_ref":parent,
                "context":"retinue", "standing_order_refs":[], "standing_orders":[],
                "location": self._person_location(commander), "direct_person_refs":[],
                "display_name": str(payload.get("display_name") or ref), "deputy_ref":None, "successor_refs":[],
                "authority_ref": command.actor_id, "active_context_ref":None, "communication_ref":None,
                "role_assignments":{}, "familiarity_milli":0, "verified_group_training_hours":0,
                "training_history":[], "created_at":now, "updated_at":now,
            }
            self.put(path, doc)
            if isinstance(parent, str):
                pp = _group_path(parent); parent_doc = copy.deepcopy(self.read(pp)); refs=parent_doc.setdefault("subordinate_command_group_refs",[])
                if ref not in refs: refs.append(ref); refs.sort(); parent_doc["updated_at"]=now; self.put(pp,parent_doc)
            idx=self._command_group_index(); refs=idx.setdefault("refs",[])
            if ref not in refs: refs.append(ref)
            self._claim_primary_group_slot(idx, person_ref=commander_ref, group_ref=ref)
            self._write_command_group_index(idx); self._register_owner(ref,path)
        else:
            doc = copy.deepcopy(self.read(path))
            if action == "add_person":
                person_ref=str(payload["person_ref"]); idx=self._command_group_index(); self._claim_primary_group_slot(idx, person_ref=person_ref, group_ref=ref); refs=doc.setdefault("direct_person_refs",[])
                if person_ref not in refs: refs.append(person_ref); refs.sort()
                if payload.get("role"): doc.setdefault("role_assignments",{})[person_ref]=str(payload["role"])
                self._write_command_group_index(idx)
            elif action == "remove_person":
                person_ref=str(payload["person_ref"]); doc["direct_person_refs"]=[x for x in doc.get("direct_person_refs",[]) if x!=person_ref]; doc.setdefault("role_assignments",{}).pop(person_ref,None)
                if doc.get("deputy_ref")==person_ref: doc["deputy_ref"]=None
                doc["successor_refs"]=[x for x in doc.get("successor_refs",[]) if x!=person_ref]
                idx=self._command_group_index(); mapping=idx.setdefault("primary_person_group",{})
                if mapping.get(person_ref)==ref: mapping.pop(person_ref,None)
                self._write_command_group_index(idx)
            elif action == "attach_formation":
                formation_ref=str(payload["formation_ref"]); idx=self._command_group_index(); self._claim_primary_group_slot(idx, formation_ref=formation_ref, group_ref=ref); refs=doc.setdefault("direct_unit_refs",[])
                if formation_ref not in refs: refs.append(formation_ref); refs.sort()
                doc["active_context_ref"] = formation_ref if doc.get("active_context_ref") is None else doc.get("active_context_ref")
                self._write_command_group_index(idx)
            elif action == "detach_formation":
                formation_ref=str(payload["formation_ref"]); doc["direct_unit_refs"]=[x for x in doc.get("direct_unit_refs",[]) if x!=formation_ref]
                if doc.get("active_context_ref")==formation_ref: doc["active_context_ref"]=None
                idx=self._command_group_index(); mapping=idx.setdefault("primary_formation_group",{})
                if mapping.get(formation_ref)==ref: mapping.pop(formation_ref,None)
                self._write_command_group_index(idx)
            elif action == "set_deputy":
                deputy = payload.get("deputy_ref")
                if deputy is not None and deputy not in doc.get("direct_person_refs", []) and deputy != doc.get("commander_ref"):
                    raise ValueError("active deputy must be the commander or a direct member of this command group")
                doc["deputy_ref"] = deputy
            elif action == "set_successors": doc["successor_refs"] = [str(x) for x in payload.get("successor_refs",[])]
            elif action == "set_order":
                order_ref="order."+hashlib.sha256(f"{ref}\x00{now}\x00{payload['order']}".encode()).hexdigest()[:16]
                doc.setdefault("standing_order_refs",[]).append(order_ref); doc["standing_order_refs"]=doc["standing_order_refs"][-32:]
                doc.setdefault("standing_orders",[]).append({"order_ref":order_ref,"text":str(payload["order"]),"issued_at":now,"issued_by":command.actor_id}); doc["standing_orders"]=doc["standing_orders"][-32:]
            elif action == "set_communication": doc["communication_ref"] = payload.get("communication_ref")
            doc["updated_at"] = now; self.put(path,doc)
        self._write_meta(command, now)
        return self._result(command_group_ref=ref, action=action, world_time=now)

    def _dispatch_command_group_train(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        ref = str(payload["command_group_ref"])
        path = _group_path(ref)
        start_doc = self.read(path)
        hours = int(payload.get("hours", 1))
        focus = payload.get("focus")

        participant_refs: list[str] = []
        for value in [start_doc.get("commander_ref"), start_doc.get("deputy_ref"), *start_doc.get("direct_person_refs", [])]:
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
        # world update that happened during the elapsed interval.
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

        development: dict[str, Any] = {}
        if isinstance(focus, str):
            rules = self.read("game/data/mechanics/training.json")
            for person_ref, pp, person in people:
                if focus not in _person_skills(person):
                    continue
                if str(person.get("schema")) == "person-lite":
                    temp = {
                        "skills": dict(_person_skills(person)),
                        "attributes": dict(_person_attrs(person)),
                        "aptitude": dict(person.get("aptitude", {})),
                        "birth_date": person.get("birth_date", "270-BCE-01-01"),
                        "health_status": self._person_health(person),
                        "development_state": copy.deepcopy(person.get("development_state", {})),
                    }
                    result = settle_skill_training(temp, focus, hours, target, rules)
                    person.setdefault("stats", {})["skills"] = temp["skills"]
                    person["development_state"] = temp.get("development_state", {})
                else:
                    result = settle_skill_training(person, focus, hours, target, rules)
                self.put(pp, person)
                development[person_ref] = result

        doc["verified_group_training_hours"] = int(doc.get("verified_group_training_hours", 0)) + hours
        doc["familiarity_milli"] = min(1000, int(doc.get("familiarity_milli", 0)) + max(4, hours * 8))
        history = doc.setdefault("training_history", [])
        history.append({
            "started_at": str(start),
            "completed_at": str(target),
            "hours": hours,
            "focus": focus,
            "participant_refs": [row[0] for row in people],
        })
        doc["training_history"] = history[-32:]
        doc["updated_at"] = str(target)
        self.put(path, doc)
        self._write_meta(command, str(target))
        return self._result(
            command_group_ref=ref,
            hours=hours,
            focus=focus,
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
        skills=_person_skills(person); attrs=_person_attrs(person); skill=max(_number(skills.get("Intelligence Operations")),_number(skills.get("Scouting")),_number(skills.get("Intrigue")),_number(skills.get("Law"))); cognition=(_number(attrs.get("Intelligence"))+_number(attrs.get("Awareness"))+_number(attrs.get("Composure")))/3.0; base=int(round(skill*6+cognition*2+min(240,hours*10))); jitter=int(hashlib.sha256(ref.encode()).hexdigest()[:4],16)%61-30; return max(0,min(1000,base+jitter))

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
                "work_history": [],
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
        candidates = [str(x) for x in sidx.get("subjects", {}).get(str(doc.get("subject_ref")), [])]
        discovered: list[str] = []
        info_idx = self.read("state/information/index.json").get("claims", {})
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
                # Legacy claims without evidence were never established as a
                # discoverable world trace. Keep them as hearsay/knowledge only.
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
        history = doc.setdefault("work_history", [])
        history.append({
            "at": str(target),
            "hours": hours,
            "investigator_ref": investigator_ref,
            "search_score_milli": score,
            "discovered_claim_refs": discovered,
        })
        doc["work_history"] = history[-64:]
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
        if doc.get("status")!="reported" or not doc.get("settlement_pending"): return None
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
        if supporting:
            doc["status"]="completed"; doc["completed_at"]=at; doc["settlement_result"]="supported_by_runtime_established_evidence"
        else:
            doc["settlement_result"]="insufficient_relevant_evidence"; doc["status"]="reported"
        self.put(path,doc)
        idxp="state/commissions/index.json"; idx=copy.deepcopy(self.read(idxp)); self._index_status_ref(idx,str(doc["status"]),ref); self._set_actor_active(idx,str(doc.get("assignee_ref")),ref,doc.get("status")=="reported"); self.put(idxp,idx)
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
            issuer=str(payload.get("issuer_ref") or "house_tang"); category=payload.get("category"); due=now.add_seconds(6*3600); doc={"schema":"sword-commission-request","request_ref":request_ref,"requester_ref":command.actor_id,"issuer_ref":issuer,"category":category,"status":"pending","requested_at":str(now),"responds_at":str(due)}; self.put(path,doc); idx.setdefault("requests",{})[request_ref]=path; self._index_actor_ref(idx, command.actor_id, request_ref); self._set_actor_active(idx,command.actor_id,request_ref,True); self._index_status_ref(idx,"pending",request_ref); self.put(idxp,idx); self._register_owner(request_ref,path); self._schedule_commission(request_ref,due); self._write_meta(command,str(now)); return self._result(request_ref=request_ref,status="pending",responds_at=str(due),world_time=str(now))
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
            refs=[str(x) for x in payload.get("evidence_refs",[])]; doc["status"]="reported"; doc["reported_at"]=str(now); doc["report_ref"]=payload.get("report_ref"); doc["evidence_refs"]=refs; doc["settlement_pending"]=True; doc.pop("settlement_result",None)
            self._schedule_commission_settlement(ref,now.add_seconds(3600))
        self._index_status_ref(idx,str(doc["status"]),ref)
        self._set_actor_active(idx,str(doc.get("assignee_ref")),ref,doc.get("status") in {"offered","active","reported"})
        self.put(idxp,idx); self.put(path,doc); self._write_meta(command,str(now)); return self._result(commission_ref=ref,status=doc["status"],world_time=str(now),settlement_pending=doc.get("settlement_pending",False))

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

        skill = _number(_person_skills(practitioner).get("Medicine"))
        minimum_skill = {"stabilize": 20, "treat": 35, "surgery": 80, "rehabilitation": 25}[treatment]
        if skill < minimum_skill:
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
        difficulty = {"minor": 20, "moderate": 35, "severe": 55, "critical": 75}.get(str(injury.get("severity", "moderate")), 40)
        seed = int(hashlib.sha256(f"{command.request_id}:{target_ref}:{treatment}".encode()).hexdigest()[:8], 16) % 21 - 10
        quality = max(0, min(100, int(round(skill + facility_quality + seed))))
        outcome = "completed"
        if treatment == "stabilize":
            injury["stabilized_at"] = str(target_time)
            injury["stabilized_by_ref"] = practitioner_ref
            injury["stabilization_quality"] = quality
        elif treatment == "treat":
            reduction = max(0, min(24, int(round(hours * (0.5 + quality / 100.0)))))
            original = int(injury.get("minimum_recovery_hours", 24))
            injury["minimum_recovery_hours"] = max(max(4, original // 2), original - reduction)
            injury["treated_at"] = str(target_time)
            injury["treated_by_ref"] = practitioner_ref
            injury["treatment_quality"] = quality
        elif treatment == "surgery":
            if str(injury.get("severity")) not in {"severe", "critical"}:
                raise ValueError("surgery is reserved for severe or critical injuries")
            success = quality >= difficulty
            injury["surgery_at"] = str(target_time)
            injury["surgeon_ref"] = practitioner_ref
            injury["surgery_quality"] = quality
            injury["surgery_successful"] = success
            original = int(injury.get("minimum_recovery_hours", 72))
            injury["minimum_recovery_hours"] = max(24, int(round(original * (0.72 if success else 1.20))))
            outcome = "successful" if success else "complication"
            if not success:
                injury.setdefault("complications", []).append({
                    "at": str(target_time),
                    "kind": "surgical_complication",
                    "quality": quality,
                })
        else:
            injury["rehabilitation_hours"] = int(injury.get("rehabilitation_hours", 0)) + hours
            injury["rehabilitation_quality"] = quality

        history = injury.setdefault("treatment_history", [])
        history.append({
            "at": str(target_time),
            "treatment": treatment,
            "practitioner_ref": practitioner_ref,
            "facility_ref": facility_ref,
            "body_site": body_site,
            "hours": hours,
            "quality": quality,
            "outcome": outcome,
        })
        injury["treatment_history"] = history[-32:]
        target["injury_state"] = injury
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
            world_time=str(target_time),
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
