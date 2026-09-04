"""Integrity overlay for military career autonomy and loyalty.

Keeps the base career network focused on ownership/routing while hardening
long-campaign petition reuse, foreign-service authority, bounded loyalty memory,
officer knowledge boundaries, and service-versus-allegiance separation.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.history_store import recent_history_events
from sword_runtime.military_career_loyalty import (
    MilitaryCareerLoyaltyMixin,
    _PLAYER_REF,
    _RUNTIME_PATH,
    _clamp,
    _event_kind,
    _event_mentions,
    _is_alive_adult,
    _is_commander_candidate,
    _military_score,
    _state_ref,
)
from sword_runtime.sim.calendar import CampaignTime

_ACTIVE_PETITION_STATES = {"submitted", "delayed", "awaiting_commander_response"}


def _service_state_ref(person: Mapping[str, Any]) -> str | None:
    """Return current military service state without asserting personal allegiance."""
    state_ref = _state_ref(person)
    if state_ref:
        return state_ref
    career = person.get("career_state")
    appointments = career.get("appointments", []) if isinstance(career, Mapping) else []
    if isinstance(appointments, list):
        for row in reversed(appointments):
            if not isinstance(row, Mapping):
                continue
            if str(row.get("status", "")) not in {"active", "awaiting_assumption", "campaign_attachment"}:
                continue
            value = row.get("state_ref")
            if isinstance(value, str) and value.startswith("state_"):
                return value
    return None


class MilitaryCareerLoyaltyIntegrityMixin(MilitaryCareerLoyaltyMixin):
    """Fail-closed hardening for career/petition/formation loyalty state."""

    def _ensure_military_career_routes(self) -> None:
        """Also route state-appointed officers whose personal allegiance is not state-owned."""
        super()._ensure_military_career_routes()
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        hosts = runtime.get("hosts")
        if not isinstance(hosts, dict):
            raise ValueError("runtime causal hosts are invalid")
        now = CampaignTime.parse(str(runtime["world_time"]))
        rules = self._military_rules()["career_review"]
        shard_size = int(rules["route_shard_size"])
        network = self._career_network()
        changed = False
        for _host_id, host in sorted(hosts.items()):
            if not isinstance(host, dict) or host.get("kind") != "person":
                continue
            route = host.get("military_career_route")
            if isinstance(route, Mapping) and route.get("status") == "routed":
                continue
            person_ref = host.get("owner_ref")
            if not isinstance(person_ref, str):
                continue
            try:
                person_path, person = self._exact_person(person_ref, active=False)
            except ValueError:
                continue
            if not isinstance(person, Mapping) or not _is_alive_adult(person):
                continue
            state_ref = _service_state_ref(person)
            if not state_ref or _military_score(person) < int(rules["minimum_military_signal"]):
                continue
            rows = [
                row for row in hosts.values()
                if isinstance(row, dict) and row.get("kind") == "military_career" and row.get("state_ref") == state_ref
            ]
            rows.sort(key=lambda row: int(row.get("route_shard", 0)))
            target = next((row for row in rows if len(row.get("routed_person_refs", [])) < shard_size), None)
            if target is None:
                target = self._ensure_route_shard(runtime, state_ref=state_ref, shard_index=len(rows), now=now)
            refs = target.setdefault("routed_person_refs", [])
            if person_ref not in refs:
                refs.append(person_ref)
                refs.sort()
            network.setdefault("people", {})[person_ref] = {
                "state_ref": state_ref,
                "person_path": person_path,
                "basis": "current_military_service",
            }
            if _is_commander_candidate(person):
                public = network.setdefault("public_commander_refs", [])
                if person_ref not in public:
                    public.append(person_ref)
                    public.sort()
            host["military_career_route"] = {
                "version": 1,
                "status": "routed",
                "classified_at": str(now),
                "basis": "current_military_service",
            }
            changed = True
        if changed:
            network["last_route_sync_at"] = str(now)
            network["routed_person_count"] = len(network.get("people", {}))
            self.put("state/military/career-network/index.json", network)
            self.put(_RUNTIME_PATH, runtime)

    def _commander_dossier(self, commander_ref: str, person: Mapping[str, Any], at: str) -> dict[str, Any]:
        dossier = super()._commander_dossier(commander_ref, person, at)
        if dossier.get("state_ref") is None:
            dossier["state_ref"] = _service_state_ref(person)
            dossier["state_context_kind"] = "current_military_service"
        else:
            dossier["state_context_kind"] = "personal_or_institutional_state"
        return dossier

    def _settle_person_career(self, person_ref: str, at: str) -> None:
        """Preserve player agency and support service-state officers without inventing allegiance."""
        try:
            path, original = self._exact_person(person_ref, active=False)
        except ValueError:
            return
        if not isinstance(original, Mapping) or not _is_alive_adult(original):
            return
        service_state = _service_state_ref(original)
        if not service_state:
            return
        if person_ref == _PLAYER_REF:
            self._publish_commander_dossier(person_ref, original, at)
            return
        if _state_ref(original):
            super()._settle_person_career(person_ref, at)
            return

        person = copy.deepcopy(dict(original))
        loyalty = self._personal_loyalty(person, service_state)
        loyalty["state_context_kind"] = "current_military_service"
        formation_ref, formation = self._person_current_formation(person)
        if formation_ref:
            self._update_formation_loyalty(formation_ref, at)
            if isinstance(formation, Mapping):
                commander = formation.get("commander_ref")
                if isinstance(commander, str) and commander:
                    bonds = loyalty.setdefault("commander_bonds", {})
                    bonds[commander] = _clamp(int(bonds.get(commander, 300)) + 4)
                    loyalty["formation_bond_milli"] = _clamp(int(loyalty.get("formation_bond_milli", 400)) + 3)
        career = person.setdefault("military_career_state", {})
        if not isinstance(career, dict):
            raise ValueError("exact person military career state is invalid")
        career.setdefault("schema", "sword-military-career-state")
        career["derived_preferences"] = self._career_preferences(person)
        career["last_review_at"] = at
        career["review_count"] = int(career.get("review_count", 0)) + 1
        self._publish_commander_dossier(person_ref, person, at)
        if not self._active_petition_refs(person):
            candidates = self._candidate_slice(person, service_state, at)
            best: tuple[int, str, str] | None = None
            for dossier, info_ref in candidates:
                score = self._attraction_score(person, dossier, service_state)
                commander_ref = str(dossier["commander_ref"])
                if best is None or score > best[0] or (score == best[0] and commander_ref < best[1]):
                    best = (score, commander_ref, info_ref)
            prefs = career["derived_preferences"]
            threshold = int(self._military_rules()["career_review"]["petition_threshold_milli"])
            if best and best[0] >= threshold:
                current_commander = formation.get("commander_ref") if isinstance(formation, Mapping) else None
                if best[1] != current_commander:
                    request_kind = "campaign_attachment" if prefs["risk_appetite"] < 470 else "permanent_transfer"
                    self._create_petition(
                        person,
                        state_ref=service_state,
                        desired_commander_ref=best[1],
                        request_kind=request_kind,
                        attraction_milli=best[0],
                        evidence_refs=[best[2]],
                        at=at,
                    )
            elif prefs["independence"] >= int(self._military_rules()["career_review"]["independence_threshold_milli"]) and _military_score(person) >= 105:
                self._create_petition(
                    person,
                    state_ref=service_state,
                    desired_commander_ref=None,
                    request_kind="independent_command",
                    attraction_milli=prefs["independence"],
                    evidence_refs=[],
                    at=at,
                )
        self.put(path, person)

    def _active_petition_refs(self, person: Mapping[str, Any]) -> list[str]:
        refs = super()._active_petition_refs(person)
        active: list[str] = []
        for petition_ref in refs:
            petition = self.read_optional(self._petition_path(petition_ref))
            if isinstance(petition, Mapping) and str(petition.get("status", "")) in _ACTIVE_PETITION_STATES:
                active.append(petition_ref)
        return active

    def _update_formation_loyalty(self, formation_ref: str, at: str) -> None:
        """Extend base service memory with bounded exact causal-history effects."""
        super()._update_formation_loyalty(formation_ref, at)
        try:
            path, original = self._load_formation(formation_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return
        if not isinstance(original, Mapping):
            return
        before_personnel = int(original.get("personnel", 0) or 0)
        before_admin = original.get("administrative_owner")
        before_force = original.get("owner_force_ref")
        formation = copy.deepcopy(dict(original))
        loyalty = formation.get("military_loyalty_state")
        if not isinstance(loyalty, dict):
            raise ValueError("formation loyalty state disappeared after base settlement")
        axes = loyalty.get("axes")
        if not isinstance(axes, dict):
            raise ValueError("formation loyalty axes are invalid")
        commander_ref = formation.get("commander_ref")
        rules = self._military_rules()["formation_loyalty"]
        recent = loyalty.setdefault("recent_memory", [])
        if not isinstance(recent, list):
            raise ValueError("formation loyalty recent memory is invalid")
        seen = {
            row.get("event_ref")
            for row in recent
            if isinstance(row, Mapping) and isinstance(row.get("event_ref"), str)
        }
        for event in recent_history_events(self, 128):
            event_ref = event.get("event_id")
            if not isinstance(event_ref, str) or event_ref in seen:
                continue
            if not _event_mentions(event, {formation_ref}):
                continue
            text = (_event_kind(event) + " " + str(event.get("summary", ""))).lower()
            commander_delta = 0
            disaffection_delta = 0
            state_delta = 0
            institution_delta = 0
            formation_delta = 0
            if any(token in text for token in ("victory", "successful withdrawal", "won", "held the field")):
                commander_delta += 18
                formation_delta += 8
            if any(token in text for token in ("defeat", "rout", "abandoned", "failed withdrawal")):
                commander_delta -= 14
                disaffection_delta += 10
            if any(token in text for token in ("catastrophic", "mass casualty", "destroyed formation", "sacrificed")):
                commander_delta -= 35
                disaffection_delta += 30
                formation_delta += 10
            if any(token in text for token in ("wounded recovered", "wounded were recovered", "evacuation succeeded")):
                commander_delta += 12
                institution_delta += 5
            if any(token in text for token in ("missed pay", "withheld pay", "unpaid")):
                disaffection_delta += 35
                institution_delta -= 24
            if any(token in text for token in ("starvation", "no food", "supply collapse")):
                disaffection_delta += 35
                commander_delta -= 16
                institution_delta -= 12
            if any(token in text for token in ("fair discipline", "merit promotion", "rewarded merit")):
                commander_delta += 10
                institution_delta += 8
            if any(token in text for token in ("arbitrary punishment", "unfair discipline", "public humiliation")):
                commander_delta -= 18
                disaffection_delta += 18
            if any(token in text for token in ("lawful succession", "recognized claimant", "legitimate authority")):
                state_delta += 8
            if isinstance(commander_ref, str) and commander_ref:
                bonds = loyalty.setdefault("commander_bonds", {})
                bonds[commander_ref] = _clamp(int(bonds.get(commander_ref, rules["default_commander_bond_milli"])) + commander_delta)
            axes["disaffection"] = _clamp(int(axes.get("disaffection", 180)) + disaffection_delta)
            axes["state_allegiance"] = _clamp(int(axes.get("state_allegiance", 720)) + state_delta)
            axes["institutional_professional"] = _clamp(int(axes.get("institutional_professional", 690)) + institution_delta)
            axes["formation_identity"] = _clamp(int(axes.get("formation_identity", 500)) + formation_delta)
            recent.append({
                "at": event.get("at"),
                "event_ref": event_ref,
                "commander_delta_milli": commander_delta,
                "disaffection_delta_milli": disaffection_delta,
                "state_delta_milli": state_delta,
                "institution_delta_milli": institution_delta,
                "formation_delta_milli": formation_delta,
            })
            seen.add(event_ref)
        limit = max(1, int(rules["recent_memory_limit"]))
        loyalty["recent_memory"] = recent[-limit:]

        commander_bond = 0
        if isinstance(commander_ref, str):
            commander_bond = int(loyalty.get("commander_bonds", {}).get(commander_ref, 250))
        state_axis = int(axes.get("state_allegiance", 720))
        disaffection = int(axes.get("disaffection", 180))
        divided = _clamp(220 + disaffection // 5 - abs(state_axis - commander_bond) // 5)
        commander_lean = _clamp(commander_bond * 3 // 10)
        disaffected_bucket = _clamp(disaffection * 2 // 5)
        state_lean = max(0, 1000 - divided - commander_lean - disaffected_bucket)
        loyalty["allegiance_distribution"] = {
            "state_leaning_milli": state_lean,
            "commander_leaning_milli": commander_lean,
            "divided_milli": divided,
            "disaffected_milli": disaffected_bucket,
        }
        formation["military_loyalty_state"] = loyalty
        if int(formation.get("personnel", 0) or 0) != before_personnel:
            raise ValueError("loyalty settlement attempted to change formation manpower")
        if formation.get("administrative_owner") != before_admin or formation.get("owner_force_ref") != before_force:
            raise ValueError("loyalty settlement attempted to change formation ownership")
        self.put(path, formation)

    def _candidate_slice(self, person: dict[str, Any], state_ref: str, at: str) -> list[tuple[Mapping[str, Any], str]]:
        """Return only commander signals that have lawfully reached this officer."""
        network = self._career_network()
        refs = [ref for ref in network.get("public_commander_refs", []) if isinstance(ref, str)]
        career = person.setdefault("military_career_state", {})
        cursor = max(0, int(career.get("commander_discovery_cursor", 0)))
        width = max(1, int(self._military_rules()["career_review"]["candidate_slice_per_review"]))
        if not refs:
            return []
        selected = [refs[(cursor + offset) % len(refs)] for offset in range(min(width, len(refs)))]
        career["commander_discovery_cursor"] = (cursor + len(selected)) % len(refs)
        public_threshold = int(self._military_rules()["knowledge"]["public_discovery_threshold_milli"])
        officer_ref = str(person.get("owner_id"))
        result: list[tuple[Mapping[str, Any], str]] = []
        for commander_ref in selected:
            if commander_ref == officer_ref:
                continue
            dossier = self._career_dossier(commander_ref)
            if not isinstance(dossier, Mapping):
                continue
            same_state = dossier.get("state_ref") == state_ref
            public_reputation = int(dossier.get("public_reputation_milli", 0))
            if not same_state and public_reputation < public_threshold:
                continue
            info_ref = self._record_officer_dossier_knowledge(officer_ref, dossier, at, institutional=same_state)
            if same_state:
                known = copy.deepcopy(dict(dossier))
                known["knowledge_scope"] = "institutional_dossier"
            else:
                command_scale = max(0, int(dossier.get("command_scale", 0)))
                approximate_scale = int(round(command_scale / 1000.0)) * 1000 if command_scale else 0
                known = {
                    "schema": "sword-commander-career-dossier",
                    "authority": False,
                    "commander_ref": commander_ref,
                    "state_ref": dossier.get("state_ref"),
                    "formation_ref": None,
                    "command_scale": approximate_scale,
                    "public_reputation_milli": public_reputation,
                    "institutional_reputation_milli": public_reputation,
                    "casualty_stewardship_milli": 500,
                    "logistics_reliability_milli": 500,
                    "promotion_opportunity_milli": 500,
                    "political_risk_milli": 350,
                    "evidence_refs": list(dossier.get("evidence_refs", []))[-4:],
                    "published_at": dossier.get("published_at"),
                    "public_summary": dossier.get("public_summary"),
                    "knowledge_scope": "public_reputation_only",
                }
            known["knowledge_ref"] = info_ref
            result.append((known, info_ref))
        return result

    def _attraction_score(self, person: Mapping[str, Any], dossier: Mapping[str, Any], state_ref: str) -> int:
        score = super()._attraction_score(person, dossier, state_ref)
        if dossier.get("knowledge_scope") != "institutional_dossier":
            return score
        _current_ref, current = self._person_current_formation(person)
        target = None
        target_ref = dossier.get("formation_ref")
        if isinstance(target_ref, str):
            try:
                _path, target = self._load_formation(target_ref)
            except (KeyError, ValueError, FileNotFoundError):
                target = None
        current_doctrine = current.get("doctrine_ref") if isinstance(current, Mapping) else None
        target_doctrine = target.get("doctrine_ref") if isinstance(target, Mapping) else None
        if current_doctrine and target_doctrine:
            score += 45 if current_doctrine == target_doctrine else -25
        return _clamp(score)

    def _settle_petitions(self, state_ref: str, at: str) -> None:
        """Make cross-state service requests explicitly harder than intra-state transfers."""
        index = self._petition_index()
        for petition_ref in list(index.get("pending_by_state", {}).get(state_ref, [])):
            path = self._petition_path(str(petition_ref))
            petition = self.read_optional(path)
            if not isinstance(petition, Mapping) or petition.get("status") != "submitted":
                continue
            desired = petition.get("desired_commander_ref")
            if not isinstance(desired, str) or not desired:
                continue
            dossier = self._career_dossier(desired)
            desired_state = dossier.get("state_ref") if isinstance(dossier, Mapping) else None
            if not isinstance(desired_state, str) or desired_state == state_ref:
                continue
            adjusted = copy.deepcopy(dict(petition))
            officer_ref = adjusted.get("officer_ref")
            state_loyalty = 720
            institution_loyalty = 700
            if isinstance(officer_ref, str):
                try:
                    _person_path, person = self._exact_person(officer_ref, active=False)
                except ValueError:
                    person = None
                if isinstance(person, Mapping):
                    loyalty = person.get("military_loyalty_state")
                    if isinstance(loyalty, Mapping):
                        state_loyalty = int(loyalty.get("state_allegiance_milli", state_loyalty))
                        institution_loyalty = int(loyalty.get("institutional_professional_milli", institution_loyalty))
            adjusted["desired_state_ref"] = desired_state
            adjusted["request_kind"] = "foreign_service_request"
            if state_loyalty >= 500 or institution_loyalty >= 540:
                adjusted["attraction_milli"] = _clamp(int(adjusted.get("attraction_milli", 0)) - 360)
            adjusted["foreign_service_authority_note"] = (
                "cross-state service is not an intra-state transfer; origin-state allegiance and institutional duty materially oppose approval"
            )
            self.put(path, adjusted)
        super()._settle_petitions(state_ref, at)


__all__ = ["MilitaryCareerLoyaltyIntegrityMixin"]
