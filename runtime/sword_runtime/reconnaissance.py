"""Typed military reconnaissance with causal observation and report delivery.

Reconnaissance is a hard military-information consequence.  Player intent may
choose the exact controlled scout, parent operation, bounded observation region,
and observation duration, but it may never supply contact, clues, enemy strength,
or the report result.  The hosted scheduler owns observation time and delivery;
exact formation owners remain world-truth authority and the resulting information
record is only the scout commander's/player's epistemic state.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.geography import location_chain, route_is_usable
from sword_runtime.operation_routing import exact_operation_record
from sword_runtime.scheduler_frontier import ensure_scheduler_state
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.stat_access import merged_skill_map

RECON_SURFACE_COMMAND = "military_reconnaissance_action"
RECON_TRANSPORT_PREFIX = "sword-military-reconnaissance.v1 "
RECON_SCHEMA = "sword-military-reconnaissance"
RECON_INDEX_PATH = "state/index/military-reconnaissance.json"
RECON_OWNER_DIR = "state/reconnaissance"
RECON_HOST_KIND = "military_reconnaissance"
RECON_REPORT_KIND = "military_reconnaissance_report"
_RECON_TRANSPORT_KEYS = frozenset({
    "schema", "surface_digest", "formation_ref", "operation_ref", "region_ref",
    "target_state_ref", "scout_commander_ref", "report_to_ref", "observation_hours",
})


def reconnaissance_transport(record: Mapping[str, Any]) -> str:
    row = dict(record)
    if set(row) != _RECON_TRANSPORT_KEYS or row.get("schema") != "sword-military-reconnaissance.v1":
        raise ValueError("military reconnaissance transport is invalid")
    return RECON_TRANSPORT_PREFIX + json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_reconnaissance_transport(summary: object) -> dict[str, Any] | None:
    if not isinstance(summary, str) or not summary.startswith(RECON_TRANSPORT_PREFIX):
        return None
    try:
        row = json.loads(summary[len(RECON_TRANSPORT_PREFIX):])
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict) or set(row) != _RECON_TRANSPORT_KEYS:
        return None
    if row.get("schema") != "sword-military-reconnaissance.v1":
        return None
    for key in ("surface_digest", "formation_ref", "operation_ref", "region_ref", "target_state_ref", "scout_commander_ref", "report_to_ref"):
        if not isinstance(row.get(key), str) or not row.get(key):
            return None
    hours = row.get("observation_hours")
    if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 24:
        return None
    return row


def reconnaissance_ref_from_digest(surface_digest: str) -> str:
    token = str(surface_digest)[:24]
    if not token:
        raise ValueError("military reconnaissance transport lacks semantic identity")
    return f"reconnaissance_{token}"


def _short_state_tokens(state_ref: str) -> set[str]:
    short = state_ref.removeprefix("state_")
    return {state_ref, short, f"state_{short}", f"force_{short}", f"force_{state_ref}"}


def _formation_belongs_to_state(formation: Mapping[str, Any], state_ref: str) -> bool:
    tokens = _short_state_tokens(state_ref)
    for key in ("administrative_owner", "state", "state_ref", "owner_state_ref", "allegiance", "owner_force_ref"):
        value = formation.get(key)
        if isinstance(value, str) and value in tokens:
            return True
    return False


def _numeric(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


class MilitaryReconnaissanceMixin:
    """Hosted domain owner for exact military reconnaissance processes."""

    def _recon_index(self) -> dict[str, Any]:
        row = copy.deepcopy(self.read_optional(RECON_INDEX_PATH))
        if row is None:
            return {
                "schema": "sword-military-reconnaissance-index",
                "authority": False,
                "reconnaissance": {},
                "active_by_actor": {},
            }
        if not isinstance(row, dict) or row.get("authority") is not False:
            raise ValueError("military reconnaissance routing index is invalid")
        if not isinstance(row.setdefault("reconnaissance", {}), dict):
            raise ValueError("military reconnaissance route map is invalid")
        if not isinstance(row.setdefault("active_by_actor", {}), dict):
            raise ValueError("military reconnaissance actor routing is invalid")
        return row

    @staticmethod
    def _recon_path(ref: str) -> str:
        return f"{RECON_OWNER_DIR}/{ref}.json"

    def _write_recon_index(self, index: Mapping[str, Any]) -> None:
        self.put(RECON_INDEX_PATH, copy.deepcopy(dict(index)))

    def _index_recon(self, ref: str, path: str, actor_ref: str, *, active: bool) -> None:
        index = self._recon_index()
        index["reconnaissance"][ref] = path
        active_refs = [str(x) for x in index["active_by_actor"].get(actor_ref, []) if isinstance(x, str)]
        if active and ref not in active_refs:
            active_refs.append(ref)
        if not active:
            active_refs = [x for x in active_refs if x != ref]
        index["active_by_actor"][actor_ref] = sorted(set(active_refs))
        self._write_recon_index(index)

    def _exact_recon(self, ref: str) -> tuple[str, dict[str, Any]]:
        index = self._recon_index()
        path = index.get("reconnaissance", {}).get(ref)
        if not isinstance(path, str):
            path = self._recon_path(ref)
        row = copy.deepcopy(self.read(path))
        if row.get("schema") != RECON_SCHEMA or row.get("reconnaissance_ref") != ref:
            raise ValueError("military reconnaissance owner identity mismatch")
        return path, row

    def _schedule_recon_host(self, ref: str, due: CampaignTime) -> None:
        runtime = copy.deepcopy(self.read("state/runtime.json"))
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        digest = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:20]
        host_id = f"host_military_reconnaissance_{digest}"
        event_id = f"event_military_reconnaissance_{digest}"
        if host_id in hosts or any(isinstance(row, Mapping) and row.get("event_id") == event_id for row in events):
            raise ValueError("military reconnaissance scheduler route already exists")
        now = CampaignTime.parse(str(runtime["world_time"]))
        hosts[host_id] = {
            "host_id": host_id,
            "kind": RECON_HOST_KIND,
            "owner_ref": ref,
            "reconnaissance_ref": ref,
            "event_id": event_id,
            "next_due": str(due),
            "recurrence_seconds": 0,
            "retire_after_settlement": False,
            "resolved_through": str(now),
            "safe_through": str(due.add_seconds(-1)),
        }
        events.append({
            "event_id": event_id,
            "kind": "military_reconnaissance_due",
            "priority": 52,
            "target_host": host_id,
            "due_at": str(due),
        })
        ensure_scheduler_state(runtime)
        self.put("state/runtime.json", runtime)

    def _start_military_reconnaissance(self, command: Any, record: Mapping[str, Any]) -> dict[str, Any]:
        if command.actor_id != self.PLAYER_ACTOR:
            raise PermissionError("military reconnaissance is player-command authority only")
        ref = reconnaissance_ref_from_digest(str(record["surface_digest"]))
        path = self._recon_path(ref)
        if self.read_optional(path) is not None:
            raise ValueError("military reconnaissance semantic identity already exists")

        formation_ref = str(record["formation_ref"])
        _formation_path, formation = self._load_formation(formation_ref)
        if formation.get("command_authority") != command.actor_id:
            raise PermissionError("military reconnaissance requires exact formation command authority")
        if int(formation.get("personnel", 0) or 0) <= 0:
            raise ValueError("military reconnaissance scout has no personnel")
        if formation.get("mobilized") is False:
            raise ValueError("military reconnaissance scout must be mobilized")
        commander_ref = str(record["scout_commander_ref"])
        if formation.get("commander_ref") != commander_ref:
            raise ValueError("military reconnaissance scout commander changed before dispatch")
        _commander_path, commander = self._exact_person(commander_ref)
        formation_location = str(formation.get("location_ref") or "")
        region_ref = str(record["region_ref"])
        if not formation_location or region_ref not in location_chain(self.read, formation_location):
            raise ValueError("military reconnaissance scout is outside the assigned region")

        operation_ref = str(record["operation_ref"])
        resolved = exact_operation_record(self, operation_ref)
        if resolved is None:
            raise ValueError("military reconnaissance parent operation is missing")
        _operation_path, operation = resolved
        formation_refs = {str(x) for x in operation.get("formation_refs", []) if isinstance(x, str)}
        if formation_ref not in formation_refs:
            raise ValueError("military reconnaissance scout is not part of the parent operation")
        if str(operation.get("status", "")) not in {"planned", "mobilizing", "active", "engaged", "occupied"}:
            raise ValueError("military reconnaissance parent operation is not active")

        now = self._world_time()
        hours = int(record["observation_hours"])
        due = now.add_seconds(hours * 3600)
        process = {
            "schema": RECON_SCHEMA,
            "owner_id": ref,
            "reconnaissance_ref": ref,
            "issuer_ref": command.actor_id,
            "formation_ref": formation_ref,
            "scout_commander_ref": commander_ref,
            "operation_ref": operation_ref,
            "region_ref": region_ref,
            "target_state_ref": str(record["target_state_ref"]),
            "report_to_ref": str(record["report_to_ref"]),
            "observation_hours": hours,
            "status": "active",
            "phase": "observing",
            "started_at": str(now),
            "observation_due_at": str(due),
            "report_information_ref": None,
            "report_event_ref": None,
            "report_dispatched_at": None,
            "report_delivered_at": None,
            "report_target_location_ref": None,
            "courier_origin_ref": formation_location,
            "scout_start_location_ref": formation_location,
            "scout_start_personnel": int(formation.get("personnel", 0) or 0),
            "scout_commander_name": commander.get("name"),
        }
        self.put(path, process)
        self._register_owner(ref, path)
        self._index_recon(ref, path, command.actor_id, active=True)
        self._schedule_recon_host(ref, due)
        # This domain layer intercepts the hidden semantic transport before the
        # base reducer. It therefore owns the ordinary one-command revision write
        # explicitly even though reconnaissance dispatch consumes no world time.
        self._write_meta(command)
        return self._result(
            reconnaissance_ref=ref,
            status="active",
            phase="observing",
            formation_ref=formation_ref,
            operation_ref=operation_ref,
            region_ref=region_ref,
            observation_due_at=str(due),
            world_time=str(now),
        )

    def _command_layer_military_reconnaissance(self, command: Any, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
        if command.command_type != "scene_consequence":
            return next_dispatch()
        record = parse_reconnaissance_transport(payload.get("summary"))
        if record is None:
            return next_dispatch()
        return self._start_military_reconnaissance(command, record)

    def _region_location_name(self, region_ref: str) -> str:
        try:
            locations = self.read("game/data/world/locations.json").get("locations", [])
        except (FileNotFoundError, KeyError, ValueError):
            return region_ref
        for row in locations if isinstance(locations, list) else []:
            if isinstance(row, Mapping) and row.get("ref") == region_ref:
                name = row.get("name")
                return str(name) if isinstance(name, str) and name else region_ref
        return region_ref

    def _usable_region_approach_count(self, region_ref: str) -> int:
        try:
            routes_doc = self.read("game/data/world/routes.json")
        except (FileNotFoundError, KeyError, ValueError):
            return 0
        rows = list(routes_doc.get("routes", [])) + list(routes_doc.get("local_routes", [])) if isinstance(routes_doc, Mapping) else []
        count = 0
        for route in rows:
            if not isinstance(route, Mapping):
                continue
            a, b = route.get("a"), route.get("b")
            if not isinstance(a, str) or not isinstance(b, str):
                continue
            try:
                touches = region_ref in location_chain(self.read, a) or region_ref in location_chain(self.read, b)
            except ValueError:
                touches = False
            if touches and route_is_usable(self.read, route):
                count += 1
        return count

    def _scout_capability_milli(self, commander: Mapping[str, Any], hours: int) -> int:
        skills = merged_skill_map(commander)
        attributes = commander.get("attributes") if isinstance(commander.get("attributes"), Mapping) else {}
        scouting = max(_numeric(skills.get("Scouting")), _numeric(skills.get("Intelligence Operations")))
        awareness = _numeric(attributes.get("Awareness"))
        composure = _numeric(attributes.get("Composure"))
        score = int(round(scouting * 4.0 + awareness * 1.3 + composure * 0.7 + min(24, hours) * 10.0))
        return max(150, min(980, score))

    def _enemy_observation(self, process: Mapping[str, Any], at: str) -> dict[str, Any]:
        formation_ref = str(process["formation_ref"])
        _formation_path, scout = self._load_formation(formation_ref)
        scout_location = str(scout.get("location_ref") or "")
        region_ref = str(process["region_ref"])
        commander_ref = str(process["scout_commander_ref"])
        _commander_path, commander = self._exact_person(commander_ref)
        if scout.get("commander_ref") != commander_ref:
            raise ValueError("military reconnaissance scout commander changed during observation")
        if not scout_location or region_ref not in location_chain(self.read, scout_location):
            return {
                "valid_observation": False,
                "confirmed_count": 0,
                "confirmed_strength": 0,
                "confidence_milli": 400,
                "route_approach_count": self._usable_region_approach_count(region_ref),
                "scout_location_ref": scout_location,
                "summary_reason": "scout_left_assigned_region",
                "evidence_commitment": hashlib.sha256(f"{process['reconnaissance_ref']}:{at}:outside".encode()).hexdigest(),
            }

        capability = self._scout_capability_milli(commander, int(process.get("observation_hours", 1) or 1))
        location_index = self.read("state/index/location-formation-index.json")
        routed_locations = location_index.get("locations", {}) if isinstance(location_index, Mapping) else {}
        owner_index = self.read("state/index/owner-index.json")
        owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
        candidate_refs: set[str] = set()
        for location_ref, refs in routed_locations.items() if isinstance(routed_locations, Mapping) else []:
            if not isinstance(location_ref, str) or not isinstance(refs, Sequence) or isinstance(refs, (str, bytes, bytearray)):
                continue
            try:
                if region_ref not in location_chain(self.read, location_ref):
                    continue
            except ValueError:
                continue
            candidate_refs.update(str(x) for x in refs if isinstance(x, str))

        target_state_ref = str(process["target_state_ref"])
        detected: list[tuple[str, int]] = []
        evidence_rows: list[str] = []
        for target_ref in sorted(candidate_refs):
            if target_ref == formation_ref:
                continue
            path = owners.get(target_ref) if isinstance(owners, Mapping) else None
            if not isinstance(path, str):
                continue
            try:
                target = self.read(path)
            except (FileNotFoundError, KeyError, ValueError):
                continue
            if not isinstance(target, Mapping) or str(target.get("formation_ref") or target.get("owner_id") or "") != target_ref:
                continue
            location_ref = str(target.get("location_ref") or target.get("current_location") or "")
            if not location_ref:
                continue
            try:
                if region_ref not in location_chain(self.read, location_ref):
                    continue
            except ValueError:
                continue
            if not _formation_belongs_to_state(target, target_state_ref):
                continue
            personnel = max(0, int(target.get("personnel", 0) or 0))
            if personnel <= 0:
                continue
            size_bonus = min(240, int(round(math.log2(max(1.0, personnel / 100.0)) * 48.0)))
            threshold = max(260, 690 - size_bonus)
            jitter = int(hashlib.sha256(f"{process['reconnaissance_ref']}:{target_ref}:{at}".encode()).hexdigest()[:8], 16) % 181 - 90
            if capability + jitter >= threshold:
                detected.append((target_ref, personnel))
                evidence_rows.append(f"{target_ref}:{personnel}:{location_ref}")

        evidence_commitment = hashlib.sha256("|".join(evidence_rows).encode("utf-8")).hexdigest()
        return {
            "valid_observation": True,
            "confirmed_count": len(detected),
            "confirmed_strength": sum(personnel for _ref, personnel in detected),
            "confidence_milli": max(400, min(950, capability)),
            "route_approach_count": self._usable_region_approach_count(region_ref),
            "scout_location_ref": scout_location,
            "summary_reason": "confirmed_contact" if detected else "no_confirmed_contact",
            "evidence_commitment": evidence_commitment,
        }

    def _write_recon_information(self, process: Mapping[str, Any], observation: Mapping[str, Any], at: str) -> tuple[str, str]:
        ref = str(process["reconnaissance_ref"])
        digest = hashlib.sha256(f"{ref}:{at}:report".encode()).hexdigest()[:20]
        information_ref = f"information.military_reconnaissance.{digest}"
        info_path = f"state/information/{information_ref}.json"
        if self.read_optional(info_path) is not None:
            existing = self.read(info_path)
            return information_ref, str(existing.get("claim", ""))

        region_ref = str(process["region_ref"])
        region_name = self._region_location_name(region_ref)
        confirmed_count = int(observation.get("confirmed_count", 0) or 0)
        confirmed_strength = int(observation.get("confirmed_strength", 0) or 0)
        routes = int(observation.get("route_approach_count", 0) or 0)
        reason = str(observation.get("summary_reason", ""))
        if reason == "scout_left_assigned_region":
            claim = (
                f"Forward reconnaissance assigned to {region_name} could not complete a valid regional observation because the scout element left the assigned area before the observation interval closed. "
                "No enemy contact is confirmed by this report."
            )
        elif confirmed_count:
            claim = (
                f"Forward reconnaissance in {region_name} confirms {confirmed_count} enemy formation{'s' if confirmed_count != 1 else ''}, approximately {confirmed_strength:,} troops in observed strength. "
                f"The patrol identifies {routes} usable mapped approach route{'s' if routes != 1 else ''} touching the assigned area. "
                "This confirms observed presence only; it does not establish enemy intent, future movement, or initiate battle."
            )
        else:
            claim = (
                f"Forward reconnaissance in {region_name} completed its assigned observation interval without confirming an enemy formation. "
                f"The patrol identifies {routes} usable mapped approach route{'s' if routes != 1 else ''} touching the assigned area. "
                "This is a negative observation, not proof that the region is empty."
            )

        commander_ref = str(process["scout_commander_ref"])
        confidence = max(0, min(1000, int(observation.get("confidence_milli", 500) or 500)))
        doc = {
            "schema": "sword-information",
            "owner_id": information_ref,
            "information_ref": information_ref,
            "subject_ref": f"military_reconnaissance:{region_ref}",
            "fact": claim,
            "claim": claim,
            "epistemic_kind": "official_military_field_report",
            "confidence_milli": confidence,
            "confidence": f"{confidence / 1000:.3f}",
            "provenance": "military_reconnaissance",
            "evidence_refs": [ref, str(process["formation_ref"])],
            "classification": "command_intelligence",
            "location_ref": region_ref,
            "discoverability_milli": 1000,
            "investigation_discoverable": False,
            "origin_authority": "runtime_established",
            "world_truth_authority": False,
            "claim_status": "runtime_established",
            "knowers": [commander_ref],
            "holder_states": {
                commander_ref: {
                    "epistemic_kind": "observation",
                    "confidence_milli": confidence,
                    "source_ref": ref,
                    "channel": "field_reconnaissance",
                    "learned_at": at,
                }
            },
            "deliveries": [],
            "created_at": at,
        }
        self.put(info_path, doc)
        info_index = copy.deepcopy(self.read("state/information/index.json"))
        info_index.setdefault("claims", {})[information_ref] = info_path
        holder_refs = info_index.setdefault("by_holder", {}).setdefault(commander_ref, [])
        if information_ref not in holder_refs:
            holder_refs.append(information_ref)
            holder_refs.sort()
        self.put("state/information/index.json", info_index)
        subject_index = copy.deepcopy(self.read_optional("state/information/subject-index.json") or {"schema": "sword-information-subject-index", "authority": False, "subjects": {}})
        subject_refs = subject_index.setdefault("subjects", {}).setdefault(str(doc["subject_ref"]), [])
        if information_ref not in subject_refs:
            subject_refs.append(information_ref)
            subject_refs.sort()
        self.put("state/information/subject-index.json", subject_index)
        self._register_owner(information_ref, info_path)
        return information_ref, claim

    def _deliver_recon_report(self, process_path: str, process: dict[str, Any], at: str, *, source_location_ref: str, target_location_ref: str) -> None:
        information_ref = str(process["report_information_ref"])
        info_index = self.read("state/information/index.json")
        info_path = info_index.get("claims", {}).get(information_ref) if isinstance(info_index, Mapping) else None
        if not isinstance(info_path, str):
            raise ValueError("military reconnaissance report lost its information owner")
        info = copy.deepcopy(self.read(info_path))
        target_ref = str(process["report_to_ref"])
        knowers = info.setdefault("knowers", [])
        if target_ref not in knowers:
            knowers.append(target_ref)
            knowers.sort()
        confidence = int(info.get("confidence_milli", 500) or 500)
        departed_at = str(process.get("report_dispatched_at") or at)
        # The process owns the courier's actual departure/reroute point. The
        # scheduler's target-location comparison must never relabel the report
        # destination as its source on normal arrival.
        source_location_ref = str(process.get("courier_origin_ref") or source_location_ref)
        travel_hours = max(
            0,
            int(round(CampaignTime.parse(departed_at).seconds_until(CampaignTime.parse(at)) / 3600.0)),
        )
        info.setdefault("holder_states", {})[target_ref] = {
            "epistemic_kind": "report",
            "confidence_milli": confidence,
            "source_ref": str(process["scout_commander_ref"]),
            "channel": "military_command_courier",
            "learned_at": at,
        }
        info.setdefault("deliveries", []).append({
            "source_ref": str(process["scout_commander_ref"]),
            "target_ref": target_ref,
            "departed_at": departed_at,
            "arrived_at": at,
            "source_location_ref": source_location_ref,
            "target_location_ref": target_location_ref,
            "channel": "military_command_courier",
            "travel_hours": travel_hours,
            "confidence_milli": confidence,
        })
        info["deliveries"] = info["deliveries"][-64:]
        self.put(info_path, info)
        latest_index = copy.deepcopy(self.read("state/information/index.json"))
        refs = latest_index.setdefault("by_holder", {}).setdefault(target_ref, [])
        if information_ref not in refs:
            refs.append(information_ref)
            refs.sort()
        self.put("state/information/index.json", latest_index)

        event_digest = hashlib.sha256(f"{process['reconnaissance_ref']}:{at}:delivery".encode()).hexdigest()[:20]
        event_ref = f"event_military_reconnaissance_report_{event_digest}"
        _event_path, owner = read_causal_event_owner(self)
        causal = owner.setdefault("causal_events", {})
        if event_ref not in causal:
            causal[event_ref] = {
                "event_ref": event_ref,
                "kind": RECON_REPORT_KIND,
                "status": "triggered",
                "triggered_at": at,
                "summary": str(info.get("claim", "")),
                "source_ref": str(process["scout_commander_ref"]),
                "target_ref": target_ref,
                "operation_ref": str(process["operation_ref"]),
                "formation_ref": str(process["formation_ref"]),
                "reconnaissance_ref": str(process["reconnaissance_ref"]),
                "information_ref": information_ref,
                "location_ref": target_location_ref,
                "classification": "command_intelligence",
                "topic": "forward reconnaissance enemy contact routes approach conditions",
                "provenance": {
                    "kind": "causal_runtime_settlement",
                    "source_owner_ref": str(process["reconnaissance_ref"]),
                    "work_ref": event_ref,
                    "late_catch_up": False,
                },
            }
            write_causal_event_owner(self, owner)

        process["phase"] = "completed"
        process["status"] = "completed"
        process["report_event_ref"] = event_ref
        process["report_delivered_at"] = at
        process["completed_at"] = at
        self.put(process_path, process)
        self._index_recon(str(process["reconnaissance_ref"]), process_path, str(process["issuer_ref"]), active=False)

    def _settle_military_reconnaissance_host(self, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
        ref = str(host.get("reconnaissance_ref") or host.get("owner_ref") or "")
        if not ref:
            raise ValueError("military reconnaissance host lacks reconnaissance_ref")
        process_path, process = self._exact_recon(ref)
        if process.get("status") == "completed":
            return None
        runtime = copy.deepcopy(self.read("state/runtime.json"))
        active_host_id = getattr(self, "_active_host_id", None)
        active_host = runtime.get("hosts", {}).get(active_host_id) if isinstance(runtime.get("hosts"), Mapping) else None
        if not isinstance(active_host, dict):
            raise ValueError("military reconnaissance settlement lost its active scheduler host")

        phase = str(process.get("phase", "observing"))
        if phase == "observing":
            observation = self._enemy_observation(process, at)
            information_ref, _claim = self._write_recon_information(process, observation, at)
            process["report_information_ref"] = information_ref
            process["observation_completed_at"] = at
            process["observation_summary"] = {
                "valid_observation": bool(observation.get("valid_observation")),
                "confirmed_enemy_formation_count": int(observation.get("confirmed_count", 0) or 0),
                "confirmed_enemy_strength": int(observation.get("confirmed_strength", 0) or 0),
                "confidence_milli": int(observation.get("confidence_milli", 0) or 0),
                "route_approach_count": int(observation.get("route_approach_count", 0) or 0),
                "evidence_commitment": str(observation.get("evidence_commitment", "")),
            }
            _player_path, player = self._exact_person(str(process["report_to_ref"]))
            target_location = self._person_location(player)
            scout_location = str(observation.get("scout_location_ref") or process.get("courier_origin_ref") or "")
            if not isinstance(target_location, str) or not target_location or not scout_location:
                raise ValueError("military reconnaissance report lacks exact delivery endpoints")
            travel_hours = self._route_travel_hours(scout_location, target_location)
            process["phase"] = "report_in_transit"
            process["report_dispatched_at"] = at
            process["courier_origin_ref"] = scout_location
            process["report_target_location_ref"] = target_location
            self.put(process_path, process)
            if travel_hours <= 0:
                self._deliver_recon_report(process_path, process, at, source_location_ref=scout_location, target_location_ref=target_location)
                active_host["recurrence_seconds"] = 0
                active_host["retire_after_settlement"] = True
            else:
                active_host["recurrence_seconds"] = max(3600, int(travel_hours) * 3600)
                active_host["retire_after_settlement"] = False
            self.put("state/runtime.json", runtime)
            return {"reconnaissance_ref": ref, "phase": process.get("phase"), "information_ref": information_ref}

        if phase != "report_in_transit":
            raise ValueError("military reconnaissance process has unsupported phase")
        _player_path, player = self._exact_person(str(process["report_to_ref"]))
        player_location = self._person_location(player)
        target_location = process.get("report_target_location_ref")
        courier_origin = str(target_location or process.get("courier_origin_ref") or "")
        if not isinstance(player_location, str) or not player_location or not isinstance(target_location, str) or not target_location:
            raise ValueError("military reconnaissance report delivery lost exact location")
        if player_location != target_location:
            travel_hours = self._route_travel_hours(courier_origin, player_location)
            process["courier_origin_ref"] = courier_origin
            process["report_target_location_ref"] = player_location
            process["report_dispatched_at"] = at
            self.put(process_path, process)
            active_host["recurrence_seconds"] = max(3600, int(travel_hours) * 3600) if travel_hours > 0 else 3600
            active_host["retire_after_settlement"] = False
            self.put("state/runtime.json", runtime)
            return {"reconnaissance_ref": ref, "phase": "report_in_transit", "rerouted": True}

        self._deliver_recon_report(process_path, process, at, source_location_ref=courier_origin, target_location_ref=player_location)
        active_host["recurrence_seconds"] = 0
        active_host["retire_after_settlement"] = True
        self.put("state/runtime.json", runtime)
        return {"reconnaissance_ref": ref, "phase": "completed", "information_ref": process.get("report_information_ref")}


__all__ = [
    "MilitaryReconnaissanceMixin",
    "RECON_HOST_KIND",
    "RECON_INDEX_PATH",
    "RECON_REPORT_KIND",
    "RECON_SCHEMA",
    "RECON_SURFACE_COMMAND",
    "RECON_TRANSPORT_PREFIX",
    "parse_reconnaissance_transport",
    "reconnaissance_ref_from_digest",
    "reconnaissance_transport",
]
