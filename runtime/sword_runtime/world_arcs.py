"""Causal world-arc pressure and report propagation.

The existing arc registry remains campaign-scale pressure authority. Active arcs
receive autonomous causal reviews without creating a second plot database or
forcing future historical outcomes. Reviews may establish only abstract arc
initiatives from exact saved actors and their saved goals. Domain consequences
such as formation movement, treasury spending, office changes, injuries, and
territory remain owned by their existing subsystems.
"""
from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.stat_access import merged_skill_map

ARC_REGISTRY_PATH = "state/arc/kingdom-arcs.json"
RUNTIME_PATH = "state/runtime.json"
EVENT_OWNER_REF = "events_messages_and_movement"
WORLD_ARC_REVIEW_SECONDS = 7 * 86400
WORLD_ARC_REPORT_RETRY_SECONDS = 12 * 3600
WORLD_ARC_REPORT_RETRY_SCHEDULE_SECONDS = (12 * 3600, 24 * 3600, 2 * 86400, 4 * 86400, 7 * 86400, 14 * 86400)
WORLD_ARC_REPORT_MAX_ATTEMPTS = len(WORLD_ARC_REPORT_RETRY_SCHEDULE_SECONDS)
_RECENT_INITIATIVE_REFS = 16
_ALLOWED_DRIVER_PREFIXES = ("char_", "state_", "polity_", "house_", "faction_", "inst_", "process_")
_SAFE_TEXT = re.compile(r"[^a-z0-9]+")
_EXPLICIT_REF = re.compile(r"\b(?:char|state|polity|house|faction|inst|process)_[a-z0-9_]+\b")
_PLAYER_REPORTABLE_RESULTS = frozenset({"material_action_settled"})


def _slug(value: object) -> str:
    return _SAFE_TEXT.sub(" ", str(value).lower()).strip()


def _active_status(value: object) -> bool:
    return str(value or "").strip().lower().startswith("active")


def _route_ids(arc_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(arc_ref.encode("utf-8")).hexdigest()[:20]
    return f"host_world_arc_{digest}", f"event_world_arc_review_{digest}"


def _report_route_ids(arc_ref: str, source_event_ref: str) -> tuple[str, str]:
    """Give every arc initiative its own report route.

    An older undeliverable report must never monopolize the arc's only scheduler
    host and starve newer information.
    """
    digest = hashlib.sha256(("report|" + arc_ref + "|" + source_event_ref).encode("utf-8")).hexdigest()[:20]
    return f"host_world_arc_report_{digest}", f"event_world_arc_report_{digest}"


def _arc_document(planner: Any) -> dict[str, Any]:
    document = copy.deepcopy(planner.read(ARC_REGISTRY_PATH))
    if not isinstance(document, dict) or document.get("schema") != "arc-registry":
        raise ValueError("world arc registry is invalid")
    if not isinstance(document.get("records"), list):
        raise ValueError("world arc registry records are invalid")
    return document


def _record_index(document: Mapping[str, Any], arc_ref: str) -> tuple[int, dict[str, Any]]:
    records = document.get("records")
    if not isinstance(records, list):
        raise ValueError("world arc registry records are invalid")
    for index, raw in enumerate(records):
        if isinstance(raw, dict) and raw.get("record_id") == arc_ref:
            return index, raw
    raise ValueError("world arc host lost its exact arc record")


def _active_arc_refs(document: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for raw in document.get("records", []):
        if not isinstance(raw, Mapping):
            continue
        record_id = raw.get("record_id")
        facts = raw.get("facts")
        if (
            isinstance(record_id, str)
            and record_id.startswith("arc_")
            and isinstance(facts, Mapping)
            and _active_status(facts.get("status"))
        ):
            refs.append(record_id)
    return sorted(set(refs))




def _protected_pressure(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    facts = record.get("facts") if isinstance(record.get("facts"), Mapping) else {}
    pressure = facts.get("protected_pressure") if isinstance(facts, Mapping) else None
    return pressure if isinstance(pressure, Mapping) else None


def _protected_directive(record: Mapping[str, Any], actor_ref: str) -> Mapping[str, Any] | None:
    pressure = _protected_pressure(record)
    if pressure is None:
        return None
    directives = pressure.get("actor_directives")
    if not isinstance(directives, Mapping):
        return None
    directive = directives.get(actor_ref)
    return directive if isinstance(directive, Mapping) else None


def _relation_status(owner: Mapping[str, Any], target_ref: str) -> str:
    diplomacy = owner.get("diplomacy") if isinstance(owner.get("diplomacy"), Mapping) else {}
    row = diplomacy.get(target_ref)
    if row is None and target_ref.startswith("state_"):
        row = diplomacy.get(target_ref.removeprefix("state_"))
    return str(row.get("status", "")).lower() if isinstance(row, Mapping) else ""


def _seed_protected_pressure_context(
    planner: Any, *, arc_ref: str, pressure: Mapping[str, Any], actor_refs: list[str], at: str
) -> None:
    """Persist strategic awareness only, never a treaty, mobilization, or battle result.

    Protected historical pressure is allowed to make an era-defining problem enter
    sovereign decision space.  The normal diplomacy/war/operation systems still own
    whether anyone coordinates, mobilizes, fights, wins, defects, or makes peace.
    """
    target_ref = str(pressure.get("pressure_target_ref", ""))
    if not target_ref:
        return
    severity = max(1, min(100, int(pressure.get("threat_severity", 65))))
    coordination = sorted(ref for ref in actor_refs if ref != target_ref)
    for actor_ref in coordination:
        if not actor_ref.startswith("state_"):
            continue
        owner = _owner_record(planner, actor_ref)
        if owner is None:
            continue
        path = planner.owner_path(actor_ref)
        doc = copy.deepcopy(planner.read(path))
        threats = doc.setdefault("known_threats", {})
        if not isinstance(threats, dict):
            raise ValueError("sovereign known-threat registry is invalid")
        key = f"protected_arc:{arc_ref}"
        prior = threats.get(key) if isinstance(threats.get(key), Mapping) else {}
        threats[key] = {
            **dict(prior),
            "kind": "protected_world_arc_pressure",
            "source_ref": target_ref,
            "severity": max(severity, int(prior.get("severity", 0)) if isinstance(prior, Mapping) else 0),
            "observed_at": at,
            "arc_ref": arc_ref,
            "coordination_candidate_refs": [ref for ref in coordination if ref != actor_ref],
            "basis": "era-defining strategic pressure entered sovereign decision space; this establishes concern only, not coalition membership, hostility outcome, mobilization, or battle result",
        }
        planner.put(path, doc)


def _activate_due_pressure_anchors(planner: Any, document: dict[str, Any], current: CampaignTime) -> bool:
    """Activate protected era pressure when its BCE year is reached.

    The source timeline usually establishes a year, not an exact day.  Therefore the
    runtime activates the pressure when play first reaches that BCE year rather than
    inventing a historical month/day.  An anchor can fail closed only for material
    causal impossibility such as the target sovereign no longer existing or too few
    eligible actors remaining.
    """
    changed = False
    owners = _owner_index(planner)
    for record in document.get("records", []):
        if not isinstance(record, dict):
            continue
        facts = record.get("facts")
        pressure = _protected_pressure(record)
        if not isinstance(facts, dict) or pressure is None:
            continue
        status = str(facts.get("status", "")).lower()
        if not status.startswith("dormant"):
            continue
        activation_year = pressure.get("activation_bce_year")
        if isinstance(activation_year, bool) or not isinstance(activation_year, int) or activation_year <= 0:
            raise ValueError("protected world-arc pressure requires activation_bce_year")
        if current.bce_year > activation_year:
            continue
        arc_ref = str(record.get("record_id", ""))
        target_ref = str(pressure.get("pressure_target_ref", ""))
        target = _owner_record(planner, target_ref) if target_ref else None
        if target_ref and (target is None or not _owner_active(target)):
            facts["status"] = "resolved transformed"
            record.setdefault("runtime", {})["anchor_resolution"] = {
                "at": str(current),
                "kind": "causal_impossibility",
                "reason": "protected pressure target no longer exists as an active exact owner",
                "target_ref": target_ref,
            }
            changed = True
            continue

        raw_actor_refs = pressure.get("potential_actor_refs", [])
        if not isinstance(raw_actor_refs, Sequence) or isinstance(raw_actor_refs, (str, bytes, bytearray)):
            raise ValueError("protected world-arc pressure potential_actor_refs must be a list")
        eligible: list[str] = []
        for ref in [str(x) for x in raw_actor_refs if isinstance(x, str)]:
            if ref not in owners:
                continue
            owner = _owner_record(planner, ref)
            if owner is None or not _owner_active(owner):
                continue
            # A sovereign that has causally become an ally/client of the pressure
            # target is not compelled to act as a hostile coalition member.
            if target_ref and _relation_status(owner, target_ref) in {"allied", "alliance", "client_relation", "client_state"}:
                continue
            eligible.append(ref)
        minimum = max(1, int(pressure.get("minimum_active_actors", 1)))
        if len(eligible) < minimum:
            facts["status"] = "resolved transformed"
            record.setdefault("runtime", {})["anchor_resolution"] = {
                "at": str(current),
                "kind": "causal_impossibility",
                "reason": "too few eligible exact actors remain for the protected pressure to take its registered form",
                "eligible_actor_refs": eligible,
                "minimum_active_actors": minimum,
            }
            changed = True
            continue

        facts["status"] = str(pressure.get("active_status", "active distant"))
        facts["stage"] = str(pressure.get("initial_stage", facts.get("stage", "organizing")))
        runtime_state = record.setdefault("runtime", {})
        if not isinstance(runtime_state, dict):
            raise ValueError("world arc runtime state is invalid")
        runtime_state.update({
            "anchor_activated_at": str(current),
            "anchor_activation_bce_year": activation_year,
            "eligible_actor_refs": sorted(eligible),
            "protected_pressure": True,
            "outcome_authority": "domain subsystems; protected pressure guarantees entry into decision space, never its outcome",
        })
        _seed_protected_pressure_context(planner, arc_ref=arc_ref, pressure=pressure, actor_refs=eligible, at=str(current))
        changed = True
    return changed


def sync_world_arc_routes(planner: Any, runtime: dict[str, Any]) -> None:
    """Register all active arcs on the temporal frontier.

    Active records that existed before this scheduler are caught up at the
    current instant rather than backdated. Dormant/resolved records have their
    prior route suspended. No fixed arc-count ceiling is imposed.
    """
    document = _arc_document(planner)
    current = CampaignTime.parse(str(runtime["world_time"]))
    if _activate_due_pressure_anchors(planner, document, current):
        planner.put(ARC_REGISTRY_PATH, document)
    active = set(_active_arc_refs(document))
    record_by_ref = {str(row.get("record_id")): row for row in document.get("records", []) if isinstance(row, Mapping) and isinstance(row.get("record_id"), str)}
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    event_by_id = {
        str(event.get("event_id")): event
        for event in events
        if isinstance(event, dict) and isinstance(event.get("event_id"), str)
    }

    # The causal-event store is the durable report authority. Prune terminal
    # one-shot delivery routes that predate the current eager-GC behavior, while
    # preserving a route that is still referenced by an unresolved player wake.
    protected_host_ids: set[str] = set()
    for wake_key in ("pending_wake", "acknowledged_wake"):
        wake = runtime.get(wake_key)
        if isinstance(wake, Mapping) and isinstance(wake.get("target_host"), str):
            protected_host_ids.add(str(wake.get("target_host")))
    terminal_report_hosts = {
        str(host_id)
        for host_id, host in list(hosts.items())
        if isinstance(host_id, str)
        and isinstance(host, Mapping)
        and host.get("kind") == "world_arc_report"
        and host.get("next_due") is None
        and host_id not in protected_host_ids
    }
    if terminal_report_hosts:
        for host_id in terminal_report_hosts:
            hosts.pop(host_id, None)
        events[:] = [
            event for event in events
            if not (isinstance(event, Mapping) and str(event.get("target_host", "")) in terminal_report_hosts)
        ]
        event_by_id = {
            str(event.get("event_id")): event
            for event in events
            if isinstance(event, dict) and isinstance(event.get("event_id"), str)
        }

    for host in list(hosts.values()):
        if not isinstance(host, dict) or host.get("kind") != "world_arc":
            continue
        arc_ref = host.get("arc_ref")
        if not isinstance(arc_ref, str) or arc_ref in active:
            continue
        host["next_due"] = None
        host["safe_through"] = str(current)
        event = event_by_id.get(str(host.get("event_id")))
        if isinstance(event, dict):
            event["suspended"] = True

    for arc_ref in sorted(active):
        recurrence = _arc_review_seconds(record_by_ref.get(arc_ref, {}))
        host_id, event_id = _route_ids(arc_ref)
        host = hosts.get(host_id)
        if not isinstance(host, dict):
            host = {
                "host_id": host_id,
                "kind": "world_arc",
                "owner_ref": "kingdom_arcs",
                "arc_ref": arc_ref,
                "event_id": event_id,
                "recurrence_seconds": recurrence,
                "next_due": str(current),
                "resolved_through": str(current.add_seconds(-1)),
                "safe_through": str(current.add_seconds(-1)),
            }
            hosts[host_id] = host
        elif host.get("next_due") is None:
            host["recurrence_seconds"] = recurrence
            host["next_due"] = str(current)
            host["safe_through"] = str(current.add_seconds(-1))
        else:
            host["recurrence_seconds"] = recurrence
        event = event_by_id.get(event_id)
        if not isinstance(event, dict):
            event = {
                "event_id": event_id,
                "kind": "world_arc_review",
                "priority": 70,
                "target_host": host_id,
                "due_at": str(host["next_due"]),
            }
            events.append(event)
            event_by_id[event_id] = event
        else:
            event.update({
                "kind": "world_arc_review",
                "priority": int(event.get("priority", 70)),
                "target_host": host_id,
                "due_at": str(host["next_due"]),
            })
            event.pop("suspended", None)


def _owner_index(planner: Any) -> Mapping[str, str]:
    index = planner.read("state/index/owner-index.json")
    owners = index.get("owners") if isinstance(index, Mapping) else None
    if not isinstance(owners, Mapping):
        raise ValueError("owner index is invalid")
    return {
        str(key): str(value)
        for key, value in owners.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _record_text(record: Mapping[str, Any]) -> str:
    pieces = [str(record.get("record_id", "")), str(record.get("label", ""))]
    facts = record.get("facts")
    if isinstance(facts, Mapping):
        for key in (
            "actors", "owner", "owners", "current_basis", "information_path",
            "visibility_to_tang_wei", "possible_results", "stage", "status",
        ):
            value = facts.get(key)
            if isinstance(value, str):
                pieces.append(value)
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                pieces.extend(str(item) for item in value)
    return " ".join(pieces)


def _resolve_driver_refs(planner: Any, record: Mapping[str, Any]) -> list[str]:
    owners = _owner_index(planner)
    pressure = _protected_pressure(record)
    if pressure is not None:
        runtime_state = record.get("runtime") if isinstance(record.get("runtime"), Mapping) else {}
        raw = runtime_state.get("eligible_actor_refs", pressure.get("potential_actor_refs", []))
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            explicit = sorted({str(ref) for ref in raw if isinstance(ref, str) and ref in owners})
            if explicit:
                return explicit
    text = _record_text(record)
    normalized = " " + _slug(text) + " "
    resolved: set[str] = set()
    for explicit in _EXPLICIT_REF.findall(text.lower()):
        if explicit in owners:
            resolved.add(explicit)

    candidates = [ref for ref in owners if ref.startswith(_ALLOWED_DRIVER_PREFIXES)]
    candidates.sort(key=lambda ref: (-len(ref), ref))
    for ref in candidates:
        label = ref
        for prefix in _ALLOWED_DRIVER_PREFIXES:
            if label.startswith(prefix):
                label = label[len(prefix):]
                break
        words = _slug(label.replace("_", " "))
        if len(words) >= 3 and f" {words} " in normalized:
            resolved.add(ref)
    return sorted(resolved)


def _owner_record(planner: Any, owner_ref: str) -> Mapping[str, Any] | None:
    try:
        record = planner.read(planner.owner_path(owner_ref))
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return None
    return record if isinstance(record, Mapping) else None


def _owner_active(record: Mapping[str, Any]) -> bool:
    life = str(record.get("life_status", record.get("status", "active"))).lower()
    health = str(record.get("health", record.get("health_status", "healthy"))).lower()
    return life not in {"dead", "deceased", "destroyed", "dissolved"} and health != "dead"


def _goal_strings(record: Mapping[str, Any]) -> list[str]:
    goals: list[str] = []
    goal_state = record.get("goal_state")
    if isinstance(goal_state, Mapping):
        for key in ("current_goals", "long_term_goals", "institutional_duties"):
            raw = goal_state.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
                goals.extend(str(item).strip() for item in raw if isinstance(item, str) and item.strip())
    for key in ("strategic_goals", "goals", "objectives", "priorities", "agenda"):
        raw = record.get(key)
        if isinstance(raw, str) and raw.strip():
            goals.append(raw.strip())
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            goals.extend(str(item).strip() for item in raw if isinstance(item, str) and item.strip())
        elif isinstance(raw, Mapping):
            goals.extend(
                value.strip()
                for value in raw.values()
                if isinstance(value, str) and value.strip()
            )
    return list(dict.fromkeys(goals))


def _capability_score(record: Mapping[str, Any]) -> int:
    skills = merged_skill_map(record)
    if skills:
        relevant = [
            skills.get(name)
            for name in (
                "Strategy", "Intelligence Operations", "Diplomacy", "Governance",
                "Intelligence Operations", "Leadership", "Logistics",
                "Formation Command", "Formation Fighting", "Trade",
            )
        ]
        values = [
            int(value) for value in relevant
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if values:
            return max(10, min(100, int(round(max(values) / 2))))
    admin = record.get("administrative_capacity")
    if isinstance(admin, (int, float)) and not isinstance(admin, bool):
        return max(10, min(100, int(admin)))
    influence = record.get("influence")
    if isinstance(influence, (int, float)) and not isinstance(influence, bool):
        return max(10, min(100, int(influence)))
    return 50


def _actor_state(owner_ref: str, record: Mapping[str, Any]) -> str | None:
    if owner_ref.startswith("state_"):
        return owner_ref.replace("state_", "", 1)
    # Dynamic polities keep their sovereign identity distinct from geography.
    # A communication-origin state is only a courier-distance hint for reports.
    raw = record.get("communication_origin_state", record.get("state"))
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower().replace("state_", "")
    return None


def _initial_momentum(record: Mapping[str, Any]) -> int:
    facts = record.get("facts") if isinstance(record.get("facts"), Mapping) else {}
    stage = str(facts.get("stage", "")).lower()
    if any(token in stage for token in ("active_operation", "crisis", "battle", "mobilizing")):
        return 3
    if any(token in stage for token in ("organizing", "advocacy", "intrigue", "developing")):
        return 2
    return 1


def _pressure_stage(momentum: int) -> str:
    if momentum <= 0:
        return "contained"
    if momentum <= 2:
        return "developing"
    if momentum <= 4:
        return "material"
    return "acute"


def _initiative_kind(record: Mapping[str, Any]) -> str:
    text = _slug(_record_text(record))
    if any(token in text for token in ("campaign", "army", "military", "border", "invasion", "operation", "siege")):
        return "strategic_initiative"
    if any(token in text for token in ("succession", "court", "palace", "royal", "faction", "intrigue")):
        return "political_initiative"
    return "world_initiative"


def _evidence_stage_required(record: Mapping[str, Any]) -> str:
    facts = record.get("facts") if isinstance(record.get("facts"), Mapping) else {}
    explicit = str(facts.get("progress_evidence_stage", ""))
    if explicit in {"commitment", "domain_action", "external_consequence"}:
        return explicit
    kind = _initiative_kind(record)
    if kind == "political_initiative":
        return "external_consequence"
    if kind == "strategic_initiative":
        return "domain_action"
    return "external_consequence"


def _evidence_stage_rank(stage: str) -> int:
    return {"intent": 0, "commitment": 1, "domain_action": 2, "external_consequence": 3}.get(str(stage), 0)


def _arc_review_seconds(record: Mapping[str, Any]) -> int:
    """Choose a bounded evidence-review cadence for an arc.

    Arc owners orchestrate and observe exact domain work; they are not the
    consequence owner themselves.  Re-reviewing an arc every two days after it
    repeatedly records only blocked/intent work wastes scheduler boundaries
    without making the world more alive.  Material work keeps a responsive
    cadence while repeated non-material reviews back off deterministically.
    """
    kind = _initiative_kind(record)
    facts = record.get("facts") if isinstance(record.get("facts"), Mapping) else {}
    runtime_state = record.get("runtime") if isinstance(record.get("runtime"), Mapping) else {}
    stage = str(facts.get("stage", "")).lower()
    last_result = str(runtime_state.get("last_domain_status", ""))
    quiet_streak = max(0, int(runtime_state.get("consecutive_nonmaterial_reviews", 0) or 0))
    if kind == "strategic_initiative":
        active = any(token in stage for token in ("battle", "active_operation", "crisis", "mobilizing"))
        base = 2 * 86400 if active else 4 * 86400
        if last_result == "material_action_settled":
            return base
        if last_result == "work_queued":
            return max(base, 4 * 86400)
        if quiet_streak >= 4:
            return 14 * 86400
        if quiet_streak >= 2:
            return 7 * 86400
        if quiet_streak >= 1:
            return max(base, 4 * 86400)
        return base
    if kind == "political_initiative":
        if last_result == "material_action_settled":
            return 7 * 86400
        return 14 * 86400 if quiet_streak >= 2 else 7 * 86400
    if last_result == "material_action_settled":
        return 14 * 86400
    return 30 * 86400 if quiet_streak >= 2 else 14 * 86400


def _mission_opportunity_template(planner: Any, record: Mapping[str, Any], actor_ref: str, target_ref: str | None, goal: str, at: str) -> dict[str, Any] | None:
    """Select one cold mission archetype as a non-canonical opportunity template.

    The archetype never supplies missing issuer/location/opposition facts. It only
    classifies a future mission that may be materialized by the normal causal
    mission/interaction owners once all required exact fields exist.
    """
    catalog = planner.read('game/data/content/mission-archetypes.json')
    rows = catalog.get('archetypes', []) if isinstance(catalog, Mapping) else []
    if not isinstance(rows, list):
        return None
    kind = _initiative_kind(record)
    preferred = {
        'strategic_initiative': {'military', 'reconnaissance', 'security', 'protection'},
        'political_initiative': {'political', 'diplomatic', 'investigation', 'contract'},
        'world_initiative': {'escort', 'security', 'inspection', 'institutional', 'contract'},
    }.get(kind, set())
    candidates = [row for row in rows if isinstance(row, Mapping) and str(row.get('category')) in preferred]
    if not candidates:
        candidates = [row for row in rows if isinstance(row, Mapping)]
    if not candidates:
        return None
    seed = f'{actor_ref}|{target_ref or "none"}|{goal}|{at}|mission-archetype'
    index = int(hashlib.sha256(seed.encode('utf-8')).hexdigest()[:8], 16) % len(candidates)
    row = candidates[index]
    return {
        'archetype_id': str(row.get('id')),
        'category': str(row.get('category')),
        'description': str(row.get('description', '')),
        'canonical': False,
        'actor_ref': actor_ref,
        'target_ref': target_ref,
        'basis_goal': goal[:500],
        'required_before_canonical': [
            'issuer_ref', 'assignee_ref', 'objective', 'location_or_route_ref',
            'deadline_or_timing', 'authority_or_reward', 'known_information',
            'opposition', 'success_conditions', 'failure_conditions',
        ],
        'authority': 'game/data/content/mission-archetypes.json',
    }


def _visibility(record: Mapping[str, Any]) -> tuple[str, str | None]:
    facts = record.get("facts") if isinstance(record.get("facts"), Mapping) else {}
    status = str(facts.get("status", "")).lower()
    explicit = str(facts.get("visibility_to_tang_wei", "")).lower()
    route = facts.get("information_path")
    route_text = route.strip() if isinstance(route, str) and route.strip() else None
    if "none" in explicit or "hidden" in status:
        return "hidden", route_text
    if any(token in explicit for token in ("direct", "family", "delivered")):
        return "direct", route_text or explicit
    if route_text is not None or any(token in explicit for token in ("public", "rumor", "indirect", "report")):
        return "discoverable", route_text or explicit
    return "hidden", route_text


def _event_owner(planner: Any) -> tuple[str, dict[str, Any]]:
    return read_causal_event_owner(planner)


def _schedule_report_route(
    planner: Any,
    *,
    arc_ref: str,
    source_event_ref: str,
    at: str,
    route: str,
    origin_state: str | None,
    pressure_stage: str,
    visibility: str,
) -> None:
    runtime = copy.deepcopy(planner.read(RUNTIME_PATH))
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    host_id, event_id = _report_route_ids(arc_ref, source_event_ref)
    existing = hosts.get(host_id)
    if isinstance(existing, dict) and existing.get("next_due") is not None:
        return
    due = CampaignTime.parse(at).add_seconds(WORLD_ARC_REPORT_RETRY_SECONDS)
    hosts[host_id] = {
        "host_id": host_id,
        "kind": "world_arc_report",
        "owner_ref": "kingdom_arcs",
        "arc_ref": arc_ref,
        "source_event_ref": source_event_ref,
        "event_id": event_id,
        "independent_report_route": True,
        "route": route,
        "origin_state": origin_state,
        "pressure_stage": pressure_stage,
        "visibility": visibility,
        "attempts": 0,
        "recurrence_seconds": WORLD_ARC_REPORT_RETRY_SECONDS,
        "next_due": str(due),
        "resolved_through": at,
        "safe_through": str(due.add_seconds(-1)),
    }
    found = next(
        (event for event in events if isinstance(event, dict) and event.get("event_id") == event_id),
        None,
    )
    if found is None:
        events.append({
            "event_id": event_id,
            "kind": "world_arc_report",
            "priority": 75,
            "target_host": host_id,
            "due_at": str(due),
        })
    else:
        found.update({
            "kind": "world_arc_report",
            "priority": 75,
            "target_host": host_id,
            "due_at": str(due),
        })
        found.pop("suspended", None)
    planner.put(RUNTIME_PATH, runtime)


def _player_controlled_arc_operation(
    planner: Any,
    arc_ref: str,
    *,
    actor_ref: str | None = None,
    outcome: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    """Return bounded evidence that the blocked work belongs to a player-controlled operation.

    Merely sharing an arc is not enough.  A failed move by an opposing actor must
    never be re-labelled as Tang Wei's own field-army stall.  Exact outcome
    references win when supplied; otherwise the blocked actor must own the
    operation institutionally.
    """
    try:
        meta = planner.read("state/meta.json")
        player_ref = str(meta.get("player_id", "char_tang_wei")) if isinstance(meta, Mapping) else "char_tang_wei"
        index = planner.read("state/operations/index.json")
    except (KeyError, FileNotFoundError, ValueError):
        return None
    operations = index.get("operations", {}) if isinstance(index, Mapping) else {}
    if not isinstance(operations, Mapping):
        return None
    for operation_ref, path in sorted(operations.items()):
        if not isinstance(operation_ref, str) or not isinstance(path, str):
            continue
        try: operation = planner.read(path)
        except (KeyError, FileNotFoundError, ValueError): continue
        if not isinstance(operation, Mapping) or str(operation.get("status", "")) not in {"active", "mobilizing", "planned"}:
            continue
        objective_refs = operation.get("objective_refs", [])
        if not isinstance(objective_refs, Sequence) or isinstance(objective_refs, (str, bytes, bytearray)) or arc_ref not in objective_refs:
            continue
        authority = str(operation.get("assignment_authority_ref") or operation.get("administrative_authority") or "")
        group_ref = str(operation.get("command_group_ref") or "")
        controlled = authority == player_ref
        if not controlled and group_ref.startswith("cmdgrp."):
            try: group = planner.read(f"state/cmd/command-groups/{group_ref}.json")
            except (KeyError, FileNotFoundError, ValueError): group = {}
            controlled = isinstance(group, Mapping) and (group.get("commander_ref") == player_ref or group.get("authority_ref") == player_ref)
        if not controlled:
            continue

        exact_outcome_refs: set[str] = set()
        if isinstance(outcome, Mapping):
            for key in ("operation_ref", "action_ref", "domain_action_ref"):
                value = outcome.get(key)
                if isinstance(value, str) and value:
                    exact_outcome_refs.add(value)
            evidence = outcome.get("material_evidence")
            if isinstance(evidence, Mapping):
                for key in ("operation_ref", "action_ref"):
                    value = evidence.get(key)
                    if isinstance(value, str) and value:
                        exact_outcome_refs.add(value)

        institutional_owner_ref = str(operation.get("institutional_owner_ref") or "")
        source_force_ref = str(operation.get("source_force_ref") or "")
        actor_matches = bool(actor_ref) and (
            institutional_owner_ref == actor_ref
            or source_force_ref == f"force_{str(actor_ref).removeprefix('state_')}"
        )
        exact_match = operation_ref in exact_outcome_refs
        # An exact operation ref disambiguates work owned by the same actor; it
        # never lets an opposing actor's failed action masquerade as the player's
        # operation. Actor/owner agreement is therefore mandatory whenever the
        # world-arc review supplies an actor.
        if actor_ref and not actor_matches:
            continue
        if exact_outcome_refs and not exact_match:
            continue

        return {
            "kind": "controlled_operation_stall",
            "operation_ref": operation_ref,
            "command_group_ref": group_ref or None,
            "formation_refs": [str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)],
            "institutional_owner_ref": institutional_owner_ref or None,
            "location_ref": str(operation.get("location_ref") or "") or None,
            "evidence_stage": "domain_action",
        }
    return None


def _controlled_stall_report_due(runtime_state: Mapping[str, Any], *, at: str, reason: str) -> bool:
    prior = runtime_state.get("last_controlled_stall_report") if isinstance(runtime_state, Mapping) else None
    if not isinstance(prior, Mapping):
        return True
    if str(prior.get("reason", "")) != str(reason or ""):
        return True
    prior_at = prior.get("at")
    if not isinstance(prior_at, str):
        return True
    try:
        return CampaignTime.parse(prior_at).seconds_until(CampaignTime.parse(at)) >= 7 * 86400
    except (TypeError, ValueError):
        return True


def _source_reportable(source: Mapping[str, Any]) -> bool:
    if str(source.get("result", "")) in _PLAYER_REPORTABLE_RESULTS:
        return True
    provenance = source.get("provenance") if isinstance(source.get("provenance"), Mapping) else {}
    controlled = provenance.get("controlled_operation_evidence") if isinstance(provenance, Mapping) else None
    return str(source.get("result", "")) == "work_blocked" and isinstance(controlled, Mapping) and controlled.get("kind") == "controlled_operation_stall"


def settle_world_arc_review(planner: Any, host: Mapping[str, Any], at: str) -> None:
    """Settle one arc review as orchestration over exact domain work.

    Arc pressure may select an actor and a saved goal, but it does not roll a
    strategic outcome. If the selected actor has a registered domain-action
    bridge, that subsystem performs the actual resource/knowledge/relationship
    work. Otherwise the arc records intent only.
    """
    arc_ref = host.get("arc_ref")
    if not isinstance(arc_ref, str):
        raise ValueError("world arc host is invalid")
    document = _arc_document(planner)
    index, record = _record_index(document, arc_ref)
    facts = record.get("facts")
    if not isinstance(facts, dict) or not _active_status(facts.get("status")):
        return

    runtime_state = record.setdefault("runtime", {})
    if not isinstance(runtime_state, dict):
        raise ValueError("world arc runtime state is invalid")
    review_count = int(runtime_state.get("review_count", 0)) + 1
    initiative_count = int(runtime_state.get("initiative_count", 0))
    momentum = int(runtime_state.get("pressure_momentum", _initial_momentum(record)))

    driver_refs = _resolve_driver_refs(planner, record)
    drivers: list[tuple[str, Mapping[str, Any], list[str], int]] = []
    for ref in driver_refs:
        owner = _owner_record(planner, ref)
        if owner is None or not _owner_active(owner):
            continue
        directive = _protected_directive(record, ref)
        protected_goal = str(directive.get("goal", "")).strip() if isinstance(directive, Mapping) else ""
        goals = [protected_goal] if protected_goal else _goal_strings(owner)
        if goals:
            drivers.append((ref, owner, goals, _capability_score(owner)))

    event_ref: str | None = None
    if drivers:
        drivers.sort(key=lambda row: row[0])
        # First observe material work that an actor-owned causal host settled since
        # the previous arc review. This makes the arc a watcher of domain evidence,
        # not a scheduler that must randomly select the same actor twice before a
        # completed action can matter.
        completed = None
        if hasattr(planner, "_world_arc_completed_priority"):
            for candidate_ref, candidate_owner, _candidate_goals, _candidate_score in drivers:
                observed = planner._world_arc_completed_priority(candidate_ref, arc_ref)
                if isinstance(observed, Mapping):
                    effect = observed.get("effect") if isinstance(observed.get("effect"), Mapping) else {}
                    completed = (
                        candidate_ref,
                        candidate_owner,
                        str(effect.get("goal", "saved autonomous objective")),
                        str(effect.get("target_ref")) if effect.get("target_ref") is not None else None,
                        observed,
                    )
                    break
        if completed is not None:
            actor_ref, actor_owner, goal, target_ref, outcome = completed
        else:
            pressure = _protected_pressure(record)
            selector_seed = f"{arc_ref}|{at}|{review_count}|actor"
            if pressure is not None:
                # Protected pressure must not disappear because deterministic random
                # selection repeatedly overlooks one sovereign.  Round-robin gives
                # every still-eligible actor a chance to respond; the domain action
                # may still be blocked, refused, defeated, or transformed.
                actor_index = (review_count - 1) % len(drivers)
            else:
                actor_index = int(hashlib.sha256(selector_seed.encode("utf-8")).hexdigest()[:8], 16) % len(drivers)
            actor_ref, actor_owner, actor_goals, _actor_score = drivers[actor_index]
            directive = _protected_directive(record, actor_ref)
            if isinstance(directive, Mapping) and str(directive.get("goal", "")).strip():
                goal = str(directive.get("goal")).strip()
                target_ref = str(directive.get("target_ref")) if directive.get("target_ref") else str(pressure.get("pressure_target_ref")) if pressure is not None and pressure.get("pressure_target_ref") else None
            else:
                goal_seed = f"{arc_ref}|{at}|{review_count}|{actor_ref}|goal"
                goal_index = int(hashlib.sha256(goal_seed.encode("utf-8")).hexdigest()[:8], 16) % len(actor_goals)
                goal = actor_goals[goal_index]
                opposition = [row for row in drivers if row[0] != actor_ref]
                target_ref = None
                if opposition:
                    target_index = int(hashlib.sha256((selector_seed + "|target").encode("utf-8")).hexdigest()[:8], 16) % len(opposition)
                    target_ref = opposition[target_index][0]

            if hasattr(planner, "_world_arc_domain_action"):
                outcome = planner._world_arc_domain_action(actor_ref, target_ref, goal, at, arc_ref)
            else:
                outcome = {"status": "intent_recorded", "reason": "no domain-action bridge is installed"}
        if not isinstance(outcome, Mapping):
            raise ValueError("world arc domain action returned an invalid result")
        result = str(outcome.get("status", "intent_recorded"))
        if result not in {"material_action_settled", "work_queued", "work_blocked", "intent_recorded"}:
            raise ValueError("world arc domain action returned an unsupported status")
        material_evidence = outcome.get("material_evidence") if isinstance(outcome.get("material_evidence"), Mapping) else None
        evidence_stage = str(outcome.get("evidence_stage", material_evidence.get("evidence_stage", "domain_action") if isinstance(material_evidence, Mapping) else "intent"))
        required_stage = _evidence_stage_required(record)
        if result == "material_action_settled" and not material_evidence:
            # Fail closed: a domain bridge may queue work freely, but it cannot make
            # an arc stronger merely by claiming execution. Concrete momentum
            # requires verifiable exact/resource evidence supplied by the owning
            # subsystem. This prevents saved priorities/attempt rows from becoming
            # a second narrative outcome authority.
            result = "work_queued"
            outcome = dict(outcome)
            outcome["status"] = result
            outcome["reason"] = "domain bridge supplied no verifiable material evidence"
            evidence_stage = "intent"
        if result == "material_action_settled" and _evidence_stage_rank(evidence_stage) < _evidence_stage_rank(required_stage):
            result = "work_queued"
            outcome = dict(outcome)
            outcome["status"] = result
            outcome["reason"] = f"{evidence_stage} evidence is durable but this arc requires {required_stage} before momentum may increase"
        delta = 1 if result == "material_action_settled" else (-1 if result == "work_blocked" else 0)
        momentum = max(0, min(6, momentum + delta))
        initiative_count += 1
        pressure_stage = _pressure_stage(momentum)
        digest = hashlib.sha256(f"{arc_ref}|{review_count}|{at}|{actor_ref}|{target_ref}|{goal}".encode("utf-8")).hexdigest()[:20]
        event_ref = f"event_world_arc_{digest}"
        visibility, route = _visibility(record)
        origin_state = _actor_state(actor_ref, actor_owner)
        action_name = str(outcome.get("action", ""))
        reason = str(outcome.get("reason", ""))
        controlled_operation_evidence = _player_controlled_arc_operation(planner, arc_ref, actor_ref=actor_ref, outcome=outcome) if result == "work_blocked" else None
        if result == "material_action_settled":
            summary = f"{arc_ref}: {actor_ref} converts a saved objective into material domain work{(' (' + action_name + ')') if action_name else ''}; strategic evidence comes from conserved or exact state change rather than an arc success roll."
        elif result == "work_queued":
            summary = f"{arc_ref}: {actor_ref} queues actor-owned work{(' (' + action_name + ')') if action_name else ''}, but no material consequence has settled yet. Arc momentum does not increase from the queue record."
        elif result == "work_blocked":
            summary = f"{arc_ref}: {actor_ref} attempts to advance a saved objective, but exact domain requirements block the work{(': ' + reason) if reason else ''}. No strategic success is created."
        else:
            summary = f"{arc_ref}: {actor_ref} retains a saved objective, but no exact domain-action route settles it during this review. The arc records intent only and creates no strategic outcome."

        _owner_path, event_owner = _event_owner(planner)
        causal = event_owner["causal_events"]
        if get_causal_event(planner, event_ref) is None:
            causal[event_ref] = {
                "event_ref": event_ref,
                "kind": "world_arc_activity",
                "status": "triggered",
                "due_at": at,
                "triggered_at": at,
                "arc_ref": arc_ref,
                "actor_ref": actor_ref,
                "target_ref": target_ref,
                "initiative_kind": _initiative_kind(record),
                "basis_goal": goal[:500],
                "result": result,
                "evidence_stage": evidence_stage,
                "required_evidence_stage": required_stage,
                "pressure_stage": pressure_stage,
                "visibility_class": visibility,
                "summary": summary[:4000],
                "provenance": {
                    "kind": "world_arc_orchestration",
                    "arc_owner_ref": "kingdom_arcs",
                    "review_count": review_count,
                    "domain_status": result,
                    "evidence_stage": evidence_stage,
                    "required_evidence_stage": required_stage,
                    "domain_action_ref": str(outcome.get("action_ref", outcome.get("faction_ref", actor_ref))),
                    **({"material_evidence": copy.deepcopy(material_evidence)} if result == "material_action_settled" and material_evidence else {}),
                    **({"controlled_operation_evidence": copy.deepcopy(controlled_operation_evidence)} if isinstance(controlled_operation_evidence, Mapping) else {}),
                },
                "opportunity_template": _mission_opportunity_template(planner, record, actor_ref, target_ref, goal, at),
            }
            event_owner.setdefault("runtime", {})["last_settled_at"] = at
            write_causal_event_owner(planner, event_owner)

        recent = runtime_state.setdefault("recent_initiative_refs", [])
        if not isinstance(recent, list):
            recent = []
            runtime_state["recent_initiative_refs"] = recent
        if event_ref in recent:
            recent.remove(event_ref)
        recent.append(event_ref)
        del recent[:-_RECENT_INITIATIVE_REFS]

        # Generic arc propagation is reserved for materially settled work. Domain
        # prerequisite failures remain valid causal history, but without an
        # observable consequence from the owning subsystem they are not player-
        # facing news and must not interrupt standing activity.
        report_controlled_stall = (
            result == "work_blocked"
            and isinstance(controlled_operation_evidence, Mapping)
            and _controlled_stall_report_due(runtime_state, at=at, reason=reason)
        )
        if (result in _PLAYER_REPORTABLE_RESULTS or report_controlled_stall) and (visibility in {"discoverable", "direct"} or report_controlled_stall):
            report_route = "Field Army military dispatches" if report_controlled_stall else route
            report_visibility = "direct" if report_controlled_stall else visibility
            if report_route:
                _schedule_report_route(planner, arc_ref=arc_ref, source_event_ref=event_ref, at=at, route=report_route, origin_state=origin_state, pressure_stage=pressure_stage, visibility=report_visibility)
                if report_controlled_stall:
                    runtime_state["last_controlled_stall_report"] = {"at": at, "reason": reason, "operation_ref": controlled_operation_evidence.get("operation_ref")}
    else:
        momentum = max(0, momentum - 1)

    nonmaterial = result != "material_action_settled" if drivers else True
    quiet_streak = max(0, int(runtime_state.get("consecutive_nonmaterial_reviews", 0) or 0))
    quiet_streak = quiet_streak + 1 if nonmaterial else 0
    runtime_state.update({
        "review_count": review_count,
        "initiative_count": initiative_count,
        "pressure_momentum": momentum,
        "pressure_stage": _pressure_stage(momentum),
        "last_reviewed_at": at,
        "last_initiative_ref": event_ref,
        "last_domain_status": result if drivers else "no_eligible_driver",
        "consecutive_nonmaterial_reviews": quiet_streak,
        "driver_refs": driver_refs,
        "outcome_authority": "domain subsystems; arc orchestration records intent and evidence only",
    })
    runtime_state["review_seconds"] = _arc_review_seconds(record)
    document["records"][index] = record
    document.setdefault("runtime", {})["last_settled_at"] = at
    planner.put(ARC_REGISTRY_PATH, document)

    # The scheduler consumes recurrence after the callback returns. Update the
    # live route now so the next occurrence uses the evidence-sensitive cadence
    # calculated above instead of waiting for a later reconciliation pass.
    runtime = planner.read("state/runtime.json")
    hosts = runtime.get("hosts") if isinstance(runtime, Mapping) else None
    host_id, _event_id = _route_ids(arc_ref)
    live_host = hosts.get(host_id) if isinstance(hosts, dict) else None
    if isinstance(live_host, dict):
        live_host["recurrence_seconds"] = int(runtime_state["review_seconds"])
        planner.put("state/runtime.json", runtime)


def _location_record(planner: Any, location_ref: str) -> Mapping[str, Any] | None:
    if location_ref.startswith("loc_tang_manor_"):
        return {
            "ref": location_ref,
            "state": "qin",
            "kind": "estate",
            "functions": ["politics", "information", "house"],
        }
    world = planner.read("game/data/world/locations.json")
    for raw in world.get("locations", []) if isinstance(world, Mapping) else []:
        if isinstance(raw, Mapping) and raw.get("ref") == location_ref:
            return raw
    return None


def _route_functions(route: str) -> set[str]:
    text = route.lower()
    required: set[str] = set()
    if any(token in text for token in ("merchant", "price", "market", "trade")):
        required.add("market")
    if any(token in text for token in ("court", "politic", "palace", "official")):
        required.add("politics")
    if any(token in text for token in ("military", "dispatch", "troop", "scout")):
        required.update({"military", "information"})
    if any(token in text for token in ("report", "rumor", "intelligence", "message", "family", "house", "direct")):
        required.add("information")
    return required or {"information"}


def _public_report_summary(record: Mapping[str, Any], source_event: Mapping[str, Any], route: str) -> str:
    facts = record.get("facts") if isinstance(record.get("facts"), Mapping) else {}
    basis = str(facts.get("current_basis", record.get("label", record.get("record_id", "world development"))))
    result = str(source_event.get("result", "inconclusive"))
    if result == "material_action_settled":
        direction = "The latest report describes material domain work that actually settled."
    elif result == "work_queued":
        direction = "The actor has queued work, but no material consequence has settled yet."
    elif result == "work_blocked":
        direction = "The attempted move was blocked by material, informational, or institutional constraints."
    elif result == "intent_recorded":
        direction = "The objective remains active, but no concrete domain action was established by this report."
    elif result == "gains_ground":
        direction = "The underlying pressure appears to be strengthening."
    elif result == "checked":
        direction = "The latest move appears to have met resistance."
    else:
        direction = "The latest reports do not yet show a decisive shift."
    return f"Reports reaching Tang Wei through {route} concern {basis}. {direction}"


def settle_world_arc_report(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    """Attempt one lawful player-facing propagation of an arc initiative."""
    arc_ref = host.get("arc_ref")
    source_event_ref = host.get("source_event_ref")
    route = host.get("route")
    if not isinstance(arc_ref, str) or not isinstance(source_event_ref, str) or not isinstance(route, str):
        raise ValueError("world arc report host is invalid")

    document = _arc_document(planner)
    _index, record = _record_index(document, arc_ref)
    _owner_path, event_owner = _event_owner(planner)
    source = get_causal_event(planner, source_event_ref)
    if not isinstance(source, Mapping) or source.get("status") != "triggered":
        raise ValueError("world arc report lost its source event")

    runtime = copy.deepcopy(planner.read(RUNTIME_PATH))
    runtime_host = runtime.get("hosts", {}).get(host.get("host_id"))
    if not isinstance(runtime_host, dict):
        raise ValueError("world arc report lost its scheduler host")

    # Only materially settled or explicitly blocked work is reportable. Other
    # arc records terminate without emitting a player-facing report or
    # interrupting standing activity.
    if not _source_reportable(source):
        runtime_host["recurrence_seconds"] = 0
        planner.put(RUNTIME_PATH, runtime)
        return None

    attempts = int(runtime_host.get("attempts", 0)) + 1
    runtime_host["attempts"] = attempts

    player = planner.read("state/player.json")
    location_ref = str(player.get("location", player.get("current_location", "")))
    location = _location_record(planner, location_ref)
    location_state = str(location.get("state", "")).lower() if isinstance(location, Mapping) else ""
    functions = {
        str(value)
        for value in (location.get("functions", []) if isinstance(location, Mapping) else [])
        if isinstance(value, str)
    }
    origin_state = str(host.get("origin_state") or "").lower()
    visibility = str(host.get("visibility") or "discoverable")
    channel_fit = visibility == "direct" or bool(functions & _route_functions(route))
    state_fit = (
        not origin_state
        or origin_state == location_state
        or "merchant" in route.lower()
        or "rumor" in route.lower()
    )

    seed = f"{source_event_ref}|{attempts}|{location_ref}|{route}"
    roll = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 100
    exposure_chance = 100 if visibility == "direct" else 70
    delivered = channel_fit and state_fit and roll < exposure_chance

    if delivered:
        report_ref = f"{source_event_ref}.report"
        if report_ref not in event_owner["causal_events"]:
            summary = _public_report_summary(record, source, route)
            event_owner["causal_events"][report_ref] = {
                "event_ref": report_ref,
                "kind": "world_arc_report",
                "status": "triggered",
                "due_at": at,
                "triggered_at": at,
                "arc_ref": arc_ref,
                "source_event_ref": source_event_ref,
                "summary": summary,
                "delivery": {
                    "target_ref": "char_tang_wei",
                    "location_ref": location_ref,
                    "route": route,
                },
                "provenance": {
                    "kind": "world_arc_information_propagation",
                    "exposure_roll": roll,
                    "exposure_chance": exposure_chance,
                },
            }
            event_owner.setdefault("runtime", {})["last_settled_at"] = at
            write_causal_event_owner(planner, event_owner)
        runtime_host["recurrence_seconds"] = 0
        planner.put(RUNTIME_PATH, runtime)
        if str(host.get("pressure_stage")) == "acute" and visibility == "direct":
            summary = event_owner["causal_events"][report_ref]["summary"]
            return {
                "wake_ref": f"wake.world_arc.{hashlib.sha256(report_ref.encode('utf-8')).hexdigest()[:20]}",
                "kind": "campaign_event",
                "at": at,
                "campaign_event_ref": report_ref,
                "reason": summary,
            }
        return None

    # Failed delivery remains causal, but it must not create an indefinitely hot
    # 12-hour clock. Back off deterministically; after the bounded schedule is
    # exhausted, retire this delivery route while preserving the source event.
    if attempts >= WORLD_ARC_REPORT_MAX_ATTEMPTS:
        runtime_host["recurrence_seconds"] = 0
        runtime_host["delivery_exhausted_at"] = at
    else:
        runtime_host["recurrence_seconds"] = WORLD_ARC_REPORT_RETRY_SCHEDULE_SECONDS[attempts]
    planner.put(RUNTIME_PATH, runtime)
    return None


__all__ = [
    "ARC_REGISTRY_PATH",
    "EVENT_OWNER_REF",
    "WORLD_ARC_REPORT_MAX_ATTEMPTS",
    "WORLD_ARC_REPORT_RETRY_SECONDS",
    "WORLD_ARC_REPORT_RETRY_SCHEDULE_SECONDS",
    "WORLD_ARC_REVIEW_SECONDS",
    "settle_world_arc_report",
    "settle_world_arc_review",
    "sync_world_arc_routes",
]
