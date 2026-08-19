"""Routed military career autonomy and formation loyalty for production play.

This layer owns career preferences, petitions, lawful commander-attraction
projections, and aggregate formation loyalty. It never owns offices, formation
custody, manpower, equipment, territorial authority, or state allegiance changes.
Those remain in their existing authoritative owners and reducers.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import parse_interaction_attempt_summary
from sword_runtime.history_store import recent_history_events
from sword_runtime.player_story_flow import _event_owner_write, _player_delivery
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_RULES_PATH = "game/data/mechanics/military-career-loyalty.json"
_NETWORK_PATH = "state/military/career-network/index.json"
_PETITION_INDEX_PATH = "state/military/career-petitions/index.json"
_INFO_INDEX_PATH = "state/information/index.json"
_INFO_SUBJECT_INDEX_PATH = "state/information/subject-index.json"
_PLAYER_REF = "char_tang_wei"
_ROUTE_PREFIX = "host_military_career"
_EVENT_PREFIX = "event_military_career"
_MILITARY_TOKENS = (
    "general", "commander", "captain", "lieutenant", "centurion", "officer",
    "military", "guard", "cavalry", "infantry", "strategist", "warrior",
)


def _slug(value: object) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
    return "_".join(part for part in text.split("_") if part)[:72] or "unknown"


def _clamp(value: int, low: int = 0, high: int = 1000) -> int:
    return max(low, min(high, int(value)))


def _digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _state_ref(person: Mapping[str, Any]) -> str | None:
    raw = person.get("state")
    if not isinstance(raw, str) or not raw.strip():
        affiliation = person.get("affiliation")
        if isinstance(affiliation, str) and affiliation.lower().startswith("state_"):
            return affiliation.lower()
        return None
    clean = _slug(raw)
    return clean if clean.startswith("state_") else f"state_{clean}"


def _text_blob(person: Mapping[str, Any]) -> str:
    pieces: list[str] = []
    for key in ("role", "role_archetype", "authority", "affiliation"):
        value = person.get(key)
        if isinstance(value, str):
            pieces.append(value)
    for owner in (person.get("behavior"), person.get("goal_state"), person.get("career_state")):
        if isinstance(owner, Mapping):
            pieces.append(json.dumps(owner, ensure_ascii=False, sort_keys=True))
    return " ".join(pieces).lower()


def _military_score(person: Mapping[str, Any]) -> int:
    skills = person.get("skills") if isinstance(person.get("skills"), Mapping) else {}
    values = []
    for name in ("Formation Command", "Leadership", "Tactics", "Strategy", "Mass Combat", "Logistics", "Riding"):
        value = skills.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    skill_signal = int(round(sum(values) / max(1, len(values)))) if values else 0
    text = _text_blob(person)
    token_signal = 55 if any(token in text for token in _MILITARY_TOKENS) else 0
    return max(skill_signal, token_signal)


def _is_alive_adult(person: Mapping[str, Any]) -> bool:
    if str(person.get("life_status", person.get("status", "active"))).lower() in {"dead", "deceased"}:
        return False
    stage = str(person.get("age_stage", "adult")).lower()
    return stage not in {"infant", "child", "minor"}


def _is_commander_candidate(person: Mapping[str, Any]) -> bool:
    text = _text_blob(person)
    return (
        any(token in text for token in ("general", "commander", "great_general", "wing commander"))
        or isinstance(person.get("current_formation_id"), str)
        or _military_score(person) >= 105
    )


def _event_mentions(event: Mapping[str, Any], refs: set[str]) -> bool:
    if not refs:
        return False
    rendered = json.dumps(event, ensure_ascii=False, sort_keys=True)
    return any(ref in rendered for ref in refs)


def _event_kind(event: Mapping[str, Any]) -> str:
    return str(event.get("kind", "")).lower()


class MilitaryCareerLoyaltyMixin:
    """General, player-symmetric military career networks and loyalty memory."""

    def _military_rules(self) -> Mapping[str, Any]:
        rules = self.read(_RULES_PATH)
        if not isinstance(rules, Mapping):
            raise ValueError("military career loyalty rules are invalid")
        return rules

    def _career_network(self) -> dict[str, Any]:
        raw = self.read_optional(_NETWORK_PATH)
        if raw is None:
            return {
                "schema": "sword-military-career-network",
                "authority": False,
                "people": {},
                "commanders": {},
                "public_commander_refs": [],
                "state_pressure": {},
            }
        if not isinstance(raw, Mapping) or raw.get("schema") != "sword-military-career-network":
            raise ValueError("military career network routing is invalid")
        return copy.deepcopy(dict(raw))

    def _petition_index(self) -> dict[str, Any]:
        raw = self.read_optional(_PETITION_INDEX_PATH)
        if raw is None:
            return {
                "schema": "sword-military-career-petition-index",
                "authority": False,
                "pending_by_state": {},
                "resolved_count": 0,
            }
        if not isinstance(raw, Mapping) or raw.get("schema") != "sword-military-career-petition-index":
            raise ValueError("military career petition index is invalid")
        return copy.deepcopy(dict(raw))

    @staticmethod
    def _route_ids(state_ref: str, shard_index: int) -> tuple[str, str]:
        suffix = _slug(state_ref.removeprefix("state_"))
        if shard_index:
            suffix = f"{suffix}_{shard_index + 1:04d}"
        return f"{_ROUTE_PREFIX}_{suffix}", f"{_EVENT_PREFIX}_{suffix}_review"

    def _ensure_route_shard(
        self,
        runtime: dict[str, Any],
        *,
        state_ref: str,
        shard_index: int,
        now: CampaignTime,
    ) -> dict[str, Any]:
        rules = self._military_rules()["career_review"]
        cadence = int(rules["cadence_seconds"])
        host_id, event_id = self._route_ids(state_ref, shard_index)
        hosts = runtime["hosts"]
        events = runtime["events"]
        host = hosts.get(host_id)
        if host is None:
            first_due = now.add_seconds(cadence)
            host = {
                "kind": "military_career",
                "owner_ref": f"military_career_network:{state_ref}",
                "state_ref": state_ref,
                "route_shard": shard_index,
                "routed_person_refs": [],
                "next_due": str(first_due),
                "recurrence_seconds": cadence,
                "resolved_through": str(now),
                "safe_through": str(first_due.add_seconds(-1)),
            }
            hosts[host_id] = host
            events.append({
                "due_at": str(first_due),
                "event_id": event_id,
                "kind": "military_career_review",
                "priority": 94,
                "target_host": host_id,
            })
        if not isinstance(host, dict) or host.get("kind") != "military_career":
            raise ValueError("military career route host is invalid")
        return host

    def _ensure_military_career_routes(self) -> None:
        """Route only scheduler-known exact people; never scan character directories."""
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        now = CampaignTime.parse(str(runtime["world_time"]))
        rules = self._military_rules()["career_review"]
        shard_size = int(rules["route_shard_size"])
        network = self._career_network()
        routes_by_state: dict[str, list[dict[str, Any]]] = {}
        for _host_id, host in sorted(hosts.items()):
            if not isinstance(host, dict) or host.get("kind") != "military_career":
                continue
            state = str(host.get("state_ref", ""))
            if state:
                routes_by_state.setdefault(state, []).append(host)
        for rows in routes_by_state.values():
            rows.sort(key=lambda row: int(row.get("route_shard", 0)))

        changed = False
        for host_id, host in sorted(hosts.items()):
            if not isinstance(host_id, str) or not isinstance(host, dict) or host.get("kind") != "person":
                continue
            route_state = host.get("military_career_route")
            if isinstance(route_state, Mapping) and isinstance(route_state.get("classified_at"), str):
                continue
            person_ref = host.get("owner_ref")
            if not isinstance(person_ref, str):
                raise ValueError("person host lost exact owner_ref")
            status = "ineligible"
            try:
                person_path, person = self._exact_person(person_ref, active=False)
            except ValueError:
                person = None
                person_path = ""
            if isinstance(person, Mapping) and _is_alive_adult(person):
                state = _state_ref(person)
                if state and _military_score(person) >= int(rules["minimum_military_signal"]):
                    rows = routes_by_state.setdefault(state, [])
                    target = next((row for row in rows if len(row.get("routed_person_refs", [])) < shard_size), None)
                    if target is None:
                        target = self._ensure_route_shard(runtime, state_ref=state, shard_index=len(rows), now=now)
                        rows.append(target)
                    refs = target.setdefault("routed_person_refs", [])
                    if person_ref not in refs:
                        refs.append(person_ref)
                        refs.sort()
                    network.setdefault("people", {})[person_ref] = {
                        "state_ref": state,
                        "person_path": person_path,
                    }
                    if _is_commander_candidate(person):
                        public = network.setdefault("public_commander_refs", [])
                        if person_ref not in public:
                            public.append(person_ref)
                            public.sort()
                    status = "routed"
            host["military_career_route"] = {
                "status": status,
                "classified_at": str(now),
            }
            changed = True
        if changed:
            network["last_route_sync_at"] = str(now)
            network["routed_person_count"] = len(network.get("people", {}))
            self.put(_NETWORK_PATH, network)
            self.put(_RUNTIME_PATH, runtime)

    def _person_current_formation(self, person: Mapping[str, Any]) -> tuple[str | None, Mapping[str, Any] | None]:
        formation_ref = person.get("current_formation_id")
        if not isinstance(formation_ref, str) or not formation_ref:
            return None, None
        try:
            _path, formation = self._load_formation(formation_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return formation_ref, None
        return formation_ref, formation

    def _career_preferences(self, person: Mapping[str, Any]) -> dict[str, int]:
        text = _text_blob(person)
        skills = person.get("skills") if isinstance(person.get("skills"), Mapping) else {}
        command = int(float(skills.get("Formation Command", 0) or 0))
        leadership = int(float(skills.get("Leadership", 0) or 0))
        riding = int(float(skills.get("Riding", 0) or 0))
        ambition = 520 + (100 if any(word in text for word in ("ambition", "advance", "great general", "independent")) else 0)
        independence = 360 + min(260, max(command, leadership))
        risk = 500 + (110 if any(word in text for word in ("aggressive", "battle-loving", "bold", "risk")) else 0)
        prestige = 500 + (90 if any(word in text for word in ("prestige", "worthy", "renown", "recognition")) else 0)
        security = 500 + (120 if any(word in text for word in ("family", "security", "wealth", "safe")) else 0)
        cavalry = 300 + min(500, riding * 3)
        return {
            "ambition": _clamp(ambition),
            "independence": _clamp(independence),
            "risk_appetite": _clamp(risk),
            "prestige_sensitivity": _clamp(prestige),
            "security_concern": _clamp(security),
            "cavalry_affinity": _clamp(cavalry),
        }

    def _personal_loyalty(self, person: dict[str, Any], state_ref: str) -> dict[str, Any]:
        raw = person.get("military_loyalty_state")
        if not isinstance(raw, dict) or raw.get("schema") != "sword-named-military-loyalty":
            raw = {
                "schema": "sword-named-military-loyalty",
                "state_ref": state_ref,
                "state_allegiance_milli": 720,
                "institutional_professional_milli": 700,
                "formation_bond_milli": 400,
                "legitimacy_belief_milli": 700,
                "commander_bonds": {},
                "house_patron_bonds": {},
                "resentment_by_person": {},
                "recent_memory": [],
            }
            person["military_loyalty_state"] = raw
        return raw

    def _formation_loyalty(self, formation: dict[str, Any], at: str) -> dict[str, Any]:
        rules = self._military_rules()["formation_loyalty"]
        raw = formation.get("military_loyalty_state")
        if not isinstance(raw, dict) or raw.get("schema") != "sword-formation-loyalty":
            raw = {
                "schema": "sword-formation-loyalty",
                "axes": copy.deepcopy(dict(rules["default_axes"])),
                "commander_bonds": {},
                "immediate_officer_bonds": {},
                "house_patron_bonds": {},
                "shared_service": {},
                "doctrine_familiarity": {},
                "command_familiarity": {},
                "recent_memory": [],
                "last_review_at": at,
            }
            formation["military_loyalty_state"] = raw
        return raw

    def _update_formation_loyalty(self, formation_ref: str, at: str) -> None:
        try:
            path, original = self._load_formation(formation_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return
        if not isinstance(original, Mapping):
            return
        formation = copy.deepcopy(dict(original))
        loyalty = self._formation_loyalty(formation, at)
        rules = self._military_rules()["formation_loyalty"]
        last_text = loyalty.get("last_review_at")
        months = 1
        if isinstance(last_text, str):
            try:
                elapsed = CampaignTime.parse(at).seconds_since(CampaignTime.parse(last_text))
                months = max(1, int(elapsed // (30 * 86400)))
            except (TypeError, ValueError):
                months = 1
        axes = loyalty["axes"]
        commander_ref = formation.get("commander_ref")
        if isinstance(commander_ref, str) and commander_ref:
            bonds = loyalty.setdefault("commander_bonds", {})
            current = int(bonds.get(commander_ref, rules["default_commander_bond_milli"]))
            current += months * int(rules["service_month_gain_milli"])
            morale = int(formation.get("morale", 50) or 50)
            if morale >= 70:
                current += int(rules["high_morale_gain_milli"])
            elif morale <= 35:
                current -= int(rules["low_morale_loss_milli"])
            bonds[commander_ref] = _clamp(current)
            service = loyalty.setdefault("shared_service", {}).setdefault(commander_ref, {})
            service["months"] = int(service.get("months", 0)) + months
            service["last_served_at"] = at
            familiarity = loyalty.setdefault("command_familiarity", {})
            familiarity[commander_ref] = _clamp(int(familiarity.get(commander_ref, 250)) + months * 6)
        if int(formation.get("cohesion", 50) or 50) >= 70:
            axes["formation_identity"] = _clamp(int(axes.get("formation_identity", 500)) + int(rules["high_cohesion_identity_gain_milli"]))
        fatigue = int(formation.get("fatigue", 0) or 0)
        if fatigue >= 70:
            axes["disaffection"] = _clamp(int(axes.get("disaffection", 180)) + int(rules["fatigue_disaffection_gain_milli"]))
        logistics = formation.get("logistics") if isinstance(formation.get("logistics"), Mapping) else {}
        personnel = max(1, int(formation.get("personnel", 1) or 1))
        food_kg = max(0, int(logistics.get("food_kg", 0) or 0))
        if food_kg < personnel * 2:
            axes["disaffection"] = _clamp(int(axes.get("disaffection", 180)) + int(rules["supply_shortage_disaffection_gain_milli"]))
        doctrine = formation.get("doctrine_ref")
        if isinstance(doctrine, str) and doctrine:
            familiar = loyalty.setdefault("doctrine_familiarity", {})
            familiar[doctrine] = _clamp(int(familiar.get(doctrine, 250)) + months * 5)
        loyalty["last_review_at"] = at
        formation["military_loyalty_state"] = loyalty
        self.put(path, formation)

    def _commander_dossier(self, commander_ref: str, person: Mapping[str, Any], at: str) -> dict[str, Any]:
        formation_ref, formation = self._person_current_formation(person)
        refs = {commander_ref}
        if formation_ref:
            refs.add(formation_ref)
        wins = 0
        losses = 0
        severe_losses = 0
        relevant_refs: list[str] = []
        for event in recent_history_events(self, 128):
            if not _event_mentions(event, refs):
                continue
            kind = _event_kind(event)
            summary = str(event.get("summary", "")).lower()
            event_ref = event.get("event_id")
            if isinstance(event_ref, str):
                relevant_refs.append(event_ref)
            if any(token in kind + " " + summary for token in ("victory", "won", "success", "successful withdrawal")):
                wins += 1
            if any(token in kind + " " + summary for token in ("defeat", "lost", "failure", "rout")):
                losses += 1
            if any(token in kind + " " + summary for token in ("catastrophic", "mass casualty", "destroyed formation")):
                severe_losses += 1
        text = _text_blob(person)
        prestige = 430
        if "great_general" in text or "great general" in text:
            prestige += 250
        elif "general" in text:
            prestige += 160
        elif "commander" in text:
            prestige += 90
        prestige += min(180, wins * 35) - min(180, losses * 30) - min(180, severe_losses * 60)
        command_scale = int(formation.get("personnel", 0)) if isinstance(formation, Mapping) else 0
        morale = int(formation.get("morale", 50)) if isinstance(formation, Mapping) else 50
        cohesion = int(formation.get("cohesion", 50)) if isinstance(formation, Mapping) else 50
        logistics = formation.get("logistics") if isinstance(formation, Mapping) and isinstance(formation.get("logistics"), Mapping) else {}
        food_signal = 500
        if command_scale > 0:
            food_signal = _clamp(int(max(0, int(logistics.get("food_kg", 0) or 0)) * 1000 / max(1, command_scale * 8)))
        institutional = _clamp(prestige + (morale - 50) * 2 + (cohesion - 50) * 2)
        public = _clamp(prestige + wins * 20 - losses * 15)
        return {
            "schema": "sword-commander-career-dossier",
            "authority": False,
            "commander_ref": commander_ref,
            "state_ref": _state_ref(person),
            "formation_ref": formation_ref,
            "command_scale": command_scale,
            "public_reputation_milli": public,
            "institutional_reputation_milli": institutional,
            "casualty_stewardship_milli": _clamp(650 - severe_losses * 120 - losses * 30),
            "logistics_reliability_milli": food_signal,
            "promotion_opportunity_milli": _clamp(430 + command_scale // 25),
            "political_risk_milli": _clamp(250 + max(0, public - 760)),
            "evidence_refs": relevant_refs[-16:],
            "published_at": at,
            "public_summary": f"{person.get('name', commander_ref)} carries a military reputation shaped by saved service, command scale, and publicly reportable campaign results.",
        }

    def _publish_commander_dossier(self, person_ref: str, person: Mapping[str, Any], at: str) -> None:
        if not _is_commander_candidate(person):
            return
        network = self._career_network()
        dossier = self._commander_dossier(person_ref, person, at)
        path = f"state/military/career-network/commanders/{_slug(person_ref)}.json"
        self.put(path, dossier)
        network.setdefault("commanders", {})[person_ref] = path
        public = network.setdefault("public_commander_refs", [])
        if person_ref not in public:
            public.append(person_ref)
            public.sort()
        self.put(_NETWORK_PATH, network)

    def _record_officer_dossier_knowledge(
        self,
        officer_ref: str,
        dossier: Mapping[str, Any],
        at: str,
        *,
        institutional: bool,
    ) -> str:
        commander_ref = str(dossier["commander_ref"])
        channel = "military_bureau_dossier" if institutional else "public_military_reputation"
        ref = f"information.military_career.{_digest([officer_ref, commander_ref, channel, dossier.get('published_at')])}"
        path = f"state/information/{ref}.json"
        index = copy.deepcopy(self.read(_INFO_INDEX_PATH))
        claims = index.setdefault("claims", {})
        if ref in claims:
            return ref
        confidence = int(self._military_rules()["knowledge"]["institutional_dossier_confidence_milli" if institutional else "public_reputation_confidence_milli"])
        claim = {
            "schema": "sword-information",
            "owner_id": ref,
            "information_ref": ref,
            "subject_ref": f"military_reputation:{commander_ref}",
            "fact": str(dossier.get("public_summary", commander_ref)),
            "claim": str(dossier.get("public_summary", commander_ref)),
            "epistemic_kind": "institutional_record" if institutional else "report",
            "confidence_milli": confidence,
            "confidence": f"{confidence / 1000:.3f}",
            "provenance": f"{channel}:{commander_ref}",
            "evidence_refs": list(dossier.get("evidence_refs", [])),
            "classification": "ordinary",
            "location_ref": None,
            "discoverability_milli": 0,
            "investigation_discoverable": True,
            "origin_authority": "runtime_established",
            "world_truth_authority": False,
            "claim_status": "runtime_established",
            "knowers": [officer_ref],
            "holder_states": {
                officer_ref: {
                    "epistemic_kind": "institutional_record" if institutional else "report",
                    "confidence_milli": confidence,
                    "source_ref": str(dossier.get("formation_ref") or commander_ref),
                    "channel": channel,
                    "learned_at": at,
                }
            },
            "created_at": at,
        }
        self.put(path, claim)
        claims[ref] = path
        holders = index.setdefault("by_holder", {}).setdefault(officer_ref, [])
        holders.append(ref)
        holders.sort()
        self.put(_INFO_INDEX_PATH, index)
        if hasattr(self, "_register_owner"):
            self._register_owner(ref, path)
        subject_index = copy.deepcopy(self.read_optional(_INFO_SUBJECT_INDEX_PATH) or {"schema": "sword-information-subject-index", "authority": False, "subjects": {}})
        subjects = subject_index.setdefault("subjects", {})
        subject = f"military_reputation:{commander_ref}"
        refs = subjects.setdefault(subject, [])
        if ref not in refs:
            refs.append(ref)
            refs.sort()
        self.put(_INFO_SUBJECT_INDEX_PATH, subject_index)
        return ref

    def _candidate_slice(self, person: dict[str, Any], state_ref: str, at: str) -> list[tuple[Mapping[str, Any], str]]:
        network = self._career_network()
        refs = [ref for ref in network.get("public_commander_refs", []) if isinstance(ref, str)]
        career = person.setdefault("military_career_state", {})
        cursor = max(0, int(career.get("commander_discovery_cursor", 0)))
        width = max(1, int(self._military_rules()["career_review"]["candidate_slice_per_review"]))
        if not refs:
            return []
        selected = [refs[(cursor + offset) % len(refs)] for offset in range(min(width, len(refs)))]
        career["commander_discovery_cursor"] = (cursor + len(selected)) % len(refs)
        result: list[tuple[Mapping[str, Any], str]] = []
        for commander_ref in selected:
            if commander_ref == person.get("owner_id"):
                continue
            path = network.get("commanders", {}).get(commander_ref)
            dossier = self.read_optional(path) if isinstance(path, str) else None
            if not isinstance(dossier, Mapping):
                continue
            same_state = dossier.get("state_ref") == state_ref
            info_ref = self._record_officer_dossier_knowledge(str(person.get("owner_id")), dossier, at, institutional=same_state)
            result.append((dossier, info_ref))
        return result

    def _attraction_score(self, person: Mapping[str, Any], dossier: Mapping[str, Any], state_ref: str) -> int:
        preferences = self._career_preferences(person)
        same_state = dossier.get("state_ref") == state_ref
        reputation = int(dossier.get("institutional_reputation_milli" if same_state else "public_reputation_milli", 0))
        promotion = int(dossier.get("promotion_opportunity_milli", 0))
        stewardship = int(dossier.get("casualty_stewardship_milli", 0))
        logistics = int(dossier.get("logistics_reliability_milli", 0))
        political = int(dossier.get("political_risk_milli", 0))
        scale = min(1000, int(dossier.get("command_scale", 0)) // 20)
        state_bonus = 120 if same_state else -180
        return _clamp(int(round(
            reputation * 0.28
            + promotion * 0.20
            + stewardship * 0.17
            + logistics * 0.11
            + scale * 0.08
            + preferences["prestige_sensitivity"] * 0.12
            + state_bonus
            - political * 0.08
        )))

    def _active_petition_refs(self, person: Mapping[str, Any]) -> list[str]:
        career = person.get("military_career_state") if isinstance(person.get("military_career_state"), Mapping) else {}
        refs = career.get("active_petition_refs", []) if isinstance(career, Mapping) else []
        return [str(ref) for ref in refs if isinstance(ref, str) and ref]

    def _petition_path(self, petition_ref: str) -> str:
        return f"state/military/career-petitions/{_slug(petition_ref)}.json"

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
        if self._active_petition_refs(person):
            return None
        formation_ref, formation = self._person_current_formation(person)
        current_commander = formation.get("commander_ref") if isinstance(formation, Mapping) else None
        key = [person.get("owner_id"), state_ref, desired_commander_ref, request_kind, at]
        petition_ref = f"military_career_petition_{_digest(key)}"
        delay_days = int(self._military_rules()["career_review"]["petition_review_delay_days"])
        review_due = str(CampaignTime.parse(at).add_seconds(delay_days * 86400))
        petition = {
            "schema": "sword-military-career-petition",
            "owner_id": petition_ref,
            "petition_ref": petition_ref,
            "officer_ref": str(person.get("owner_id")),
            "state_ref": state_ref,
            "current_formation_ref": formation_ref,
            "current_commander_ref": current_commander,
            "desired_commander_ref": desired_commander_ref,
            "request_kind": request_kind,
            "status": "submitted",
            "submitted_at": at,
            "review_due_at": review_due,
            "attraction_milli": _clamp(attraction_milli),
            "evidence_refs": sorted(set(evidence_refs)),
            "authority_rule": "petition requests institutional action; it does not change office, assignment, formation, manpower, equipment, custody, or allegiance",
        }
        path = self._petition_path(petition_ref)
        self.put(path, petition)
        if hasattr(self, "_register_owner"):
            self._register_owner(petition_ref, path)
        index = self._petition_index()
        pending = index.setdefault("pending_by_state", {}).setdefault(state_ref, [])
        if petition_ref not in pending:
            pending.append(petition_ref)
            pending.sort()
        self.put(_PETITION_INDEX_PATH, index)
        career = person.setdefault("military_career_state", {})
        career.setdefault("active_petition_refs", []).append(petition_ref)
        career["last_career_action"] = {
            "at": at,
            "kind": request_kind,
            "desired_commander_ref": desired_commander_ref,
            "petition_ref": petition_ref,
        }
        return petition_ref

    def _political_concentration(self, state_ref: str, commander_ref: str | None) -> int:
        if not commander_ref:
            return 0
        index = self._petition_index()
        active = 0
        for ref in index.get("pending_by_state", {}).get(state_ref, []):
            petition = self.read_optional(self._petition_path(str(ref)))
            if isinstance(petition, Mapping) and petition.get("desired_commander_ref") == commander_ref:
                active += 1
        network = self._career_network()
        path = network.get("commanders", {}).get(commander_ref)
        dossier = self.read_optional(path) if isinstance(path, str) else None
        reputation = int(dossier.get("public_reputation_milli", 0)) if isinstance(dossier, Mapping) else 0
        return _clamp(active * 90 + reputation // 4)

    def _deliver_player_petition(self, petition: Mapping[str, Any], at: str) -> str:
        event_ref = f"event_{petition['petition_ref']}_delivered"
        officer_ref = str(petition["officer_ref"])
        summary = (
            f"A military personnel petition concerning {officer_ref} reaches Tang Wei through the lawful state personnel channel. "
            f"The state has not transferred the officer. The request is {petition['request_kind']}; Tang Wei may accept or refuse personal service or patronage, but state assignment authority remains separate."
        )
        return _event_owner_write(
            self,
            event_ref,
            {
                "event_ref": event_ref,
                "kind": "military_career_petition_delivery",
                "status": "triggered",
                "due_at": at,
                "triggered_at": at,
                "actor_ref": f"inst_{petition['state_ref'].removeprefix('state_')}_military_bureau",
                "target_ref": _PLAYER_REF,
                "basis_goal": "lawful military personnel petition",
                "process_kind": "military_career_petition",
                "process_stage": "awaiting_prospective_commander_response",
                "summary": summary,
                "delivery": _player_delivery(self, "military bureau courier"),
            },
            at,
            source_owner_ref=f"inst_{petition['state_ref'].removeprefix('state_')}_military_bureau",
        )

    def _player_petition_response(self, petition: Mapping[str, Any]) -> str | None:
        event_ref = f"event_{petition['petition_ref']}_delivered"
        for event in reversed(recent_history_events(self, 128)):
            if _event_kind(event) != "scene_consequence":
                continue
            parsed = parse_interaction_attempt_summary(str(event.get("summary", "")))
            if not isinstance(parsed, Mapping) or parsed.get("target_ref") != event_ref:
                continue
            action = str(parsed.get("action", "")).lower()
            if action in {"proceed", "comply", "accept", "request", "agree"}:
                return "accepted"
            if action in {"refuse", "decline", "reject", "deny"}:
                return "rejected"
        return None

    def _settle_petitions(self, state_ref: str, at: str) -> None:
        index = self._petition_index()
        pending = list(index.get("pending_by_state", {}).get(state_ref, []))
        if not pending:
            return
        now = CampaignTime.parse(at)
        keep: list[str] = []
        rules = self._military_rules()["institutional_response"]
        processed = 0
        for petition_ref in pending:
            if processed >= 64:
                keep.append(petition_ref)
                continue
            path = self._petition_path(str(petition_ref))
            raw = self.read_optional(path)
            if not isinstance(raw, Mapping):
                continue
            petition = copy.deepcopy(dict(raw))
            due = CampaignTime.parse(str(petition.get("review_due_at", at)))
            if due > now:
                keep.append(petition_ref)
                continue
            processed += 1
            if petition.get("status") == "awaiting_commander_response" and petition.get("desired_commander_ref") == _PLAYER_REF:
                response = self._player_petition_response(petition)
                if response is None:
                    keep.append(petition_ref)
                    continue
                petition["prospective_commander_response"] = response
                petition["responded_at"] = at
                petition["status"] = "authorized_handoff" if response == "accepted" else "rejected"
                if response == "accepted":
                    petition["personnel_action_handoff"] = {
                        "required_authority_ref": state_ref,
                        "requested_action": petition["request_kind"],
                        "officer_ref": petition["officer_ref"],
                        "desired_commander_ref": _PLAYER_REF,
                        "rule": "existing appointment/command authority must execute any actual assignment; this handoff is not a transfer",
                    }
                self.put(path, petition)
            elif petition.get("status") == "submitted":
                attraction = int(petition.get("attraction_milli", 0))
                concentration = self._political_concentration(state_ref, petition.get("desired_commander_ref"))
                score = attraction + 90 - concentration // 5
                if petition.get("request_kind") == "independent_command":
                    score += int(rules["independent_command_bias_milli"])
                if score >= int(rules["approve_at_milli"]):
                    if petition.get("desired_commander_ref") == _PLAYER_REF:
                        petition["status"] = "awaiting_commander_response"
                        petition["institutional_decision"] = "approved_subject_to_prospective_commander_response"
                        petition["delivered_event_ref"] = self._deliver_player_petition(petition, at)
                        keep.append(petition_ref)
                    else:
                        petition["status"] = "authorized_handoff"
                        petition["institutional_decision"] = "approved"
                        petition["personnel_action_handoff"] = {
                            "required_authority_ref": state_ref,
                            "requested_action": petition["request_kind"],
                            "officer_ref": petition["officer_ref"],
                            "desired_commander_ref": petition.get("desired_commander_ref"),
                            "rule": "existing appointment/command authority must execute any actual assignment; this handoff is not a transfer",
                        }
                elif score >= int(rules["approve_at_milli"]) - int(rules["delay_band_milli"]):
                    petition["status"] = "delayed"
                    petition["institutional_decision"] = "delayed_for_personnel_balance"
                    petition["review_due_at"] = str(now.add_seconds(30 * 86400))
                    keep.append(petition_ref)
                else:
                    petition["status"] = "rejected"
                    petition["institutional_decision"] = "retained_or_redirected_by_state"
                petition["institutional_score_milli"] = _clamp(score)
                petition["political_concentration_milli"] = concentration
                petition["institution_reviewed_at"] = at
                self.put(path, petition)
            elif petition.get("status") == "delayed":
                petition["status"] = "submitted"
                petition["review_due_at"] = at
                self.put(path, petition)
                keep.append(petition_ref)
            elif petition.get("status") in {"authorized_handoff", "rejected", "cancelled", "completed"}:
                pass
            else:
                keep.append(petition_ref)
        state_rows = index.setdefault("pending_by_state", {})
        resolved = max(0, len(pending) - len(keep))
        state_rows[state_ref] = keep
        index["resolved_count"] = int(index.get("resolved_count", 0)) + resolved
        self.put(_PETITION_INDEX_PATH, index)

    def _settle_person_career(self, person_ref: str, at: str) -> None:
        try:
            path, original = self._exact_person(person_ref, active=False)
        except ValueError:
            return
        if not isinstance(original, Mapping) or not _is_alive_adult(original):
            return
        person = copy.deepcopy(dict(original))
        state_ref = _state_ref(person)
        if not state_ref:
            return
        loyalty = self._personal_loyalty(person, state_ref)
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
        if person_ref != _PLAYER_REF and not self._active_petition_refs(person):
            candidates = self._candidate_slice(person, state_ref, at)
            best: tuple[int, str, str] | None = None
            evidence: list[str] = []
            for dossier, info_ref in candidates:
                score = self._attraction_score(person, dossier, state_ref)
                commander_ref = str(dossier["commander_ref"])
                if best is None or score > best[0] or (score == best[0] and commander_ref < best[1]):
                    best = (score, commander_ref, info_ref)
            prefs = career["derived_preferences"]
            threshold = int(self._military_rules()["career_review"]["petition_threshold_milli"])
            if best and best[0] >= threshold:
                current_commander = formation.get("commander_ref") if isinstance(formation, Mapping) else None
                if best[1] != current_commander:
                    evidence.append(best[2])
                    kind = "permanent_transfer"
                    if prefs["risk_appetite"] < 470:
                        kind = "campaign_attachment"
                    self._create_petition(
                        person,
                        state_ref=state_ref,
                        desired_commander_ref=best[1],
                        request_kind=kind,
                        attraction_milli=best[0],
                        evidence_refs=evidence,
                        at=at,
                    )
            elif prefs["independence"] >= int(self._military_rules()["career_review"]["independence_threshold_milli"]) and _military_score(person) >= 105:
                self._create_petition(
                    person,
                    state_ref=state_ref,
                    desired_commander_ref=None,
                    request_kind="independent_command",
                    attraction_milli=prefs["independence"],
                    evidence_refs=[],
                    at=at,
                )
        self.put(path, person)

    def _settle_military_career_host(self, host: Mapping[str, Any], at: str) -> None:
        refs = host.get("routed_person_refs")
        if not isinstance(refs, list):
            raise ValueError("military career route lost routed_person_refs")
        for person_ref in refs:
            if isinstance(person_ref, str):
                self._settle_person_career(person_ref, at)
        state_ref = str(host.get("state_ref", ""))
        if state_ref:
            self._settle_petitions(state_ref, at)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") == "military_career":
            self._settle_military_career_host(host, due_text)
            self._pending_wake_created = None
            return
        super()._run_due_host(host, due_text)

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        if getattr(self, "_central_scheduler_reconciliation_active", False):
            return super()._advance_runtime(target_text)
        self._ensure_military_career_routes()
        return super()._advance_runtime(target_text)

    def evaluate_formation_allegiance(
        self,
        formation_ref: str,
        *,
        proposed_commander_ref: str | None,
        order_legitimacy_milli: int,
        immediate_officer_support_milli: int,
    ) -> dict[str, int]:
        """Read-only cohort-scale crisis estimate; never changes ownership or allegiance.

        The result is internal simulation truth, not automatically player knowledge.
        Player-facing callers must separately justify any estimate through reports,
        intelligence, observation, or other lawful information.
        """
        _path, formation = self._load_formation(formation_ref)
        loyalty = formation.get("military_loyalty_state") if isinstance(formation.get("military_loyalty_state"), Mapping) else {}
        axes = loyalty.get("axes") if isinstance(loyalty.get("axes"), Mapping) else self._military_rules()["formation_loyalty"]["default_axes"]
        bonds = loyalty.get("commander_bonds") if isinstance(loyalty.get("commander_bonds"), Mapping) else {}
        commander = int(bonds.get(proposed_commander_ref, 250)) if proposed_commander_ref else 0
        rules = self._military_rules()["allegiance_resolution"]
        state_pull = int(axes.get("state_allegiance", 720)) * int(rules["state_weight"])
        institution_pull = int(axes.get("institutional_professional", 690)) * int(rules["institution_weight"])
        formation_pull = int(axes.get("formation_identity", 500)) * int(rules["formation_weight"])
        commander_pull = commander * int(rules["immediate_commander_weight"])
        officer_pull = _clamp(immediate_officer_support_milli) * int(rules["immediate_commander_weight"])
        legitimacy_pull = _clamp(order_legitimacy_milli) * int(rules["legitimacy_weight"])
        disaffection = int(axes.get("disaffection", 180)) * abs(int(rules["disaffection_weight"]))
        obey_state_raw = state_pull + institution_pull + legitimacy_pull + formation_pull // 2
        follow_commander_raw = commander_pull + officer_pull + formation_pull + disaffection
        total = max(1, obey_state_raw + follow_commander_raw)
        follow = _clamp(int(round(follow_commander_raw * 1000 / total)))
        state = _clamp(1000 - follow)
        cohesion = _clamp(int(formation.get("cohesion", 50) or 50) * 10)
        fragmentation = _clamp(1000 - abs(state - follow) - cohesion // 4)
        return {
            "state_obedience_milli": state,
            "follow_proposed_commander_milli": follow,
            "fragmentation_risk_milli": fragmentation,
            "administrative_ownership_changed": 0,
        }


__all__ = ["MilitaryCareerLoyaltyMixin"]
