"""Compact campaign aftermath and post-war institutional closure.

This domain deliberately owns no battle, manpower, treasury, diplomacy, office,
reward, or travel authority.  It joins exact evidence that already exists in
operations, formations, semantic history, treaties, and people into two sparse
lifecycle products:

* an after-action review for a terminal operation/battle phase; and
* a post-war court ceremony plan/receipt once the wider conflict is actually
  settled.

A battle review never implies that the war ended.  A ceremony never grants a
promotion, land, silver, office, or nobility by itself.  Those remain separate
lawful decisions in their existing owners.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.campaign_briefing import _persist_information, campaign_arc_ref
from sword_runtime.court_presence import court_session_projection
from sword_runtime.history_store import HISTORY_INDEX_PATH, iter_history_events, write_history_index
from sword_runtime.sim.calendar import CampaignTime

_LOCATIONS_PATH = "game/data/world/locations.json"
_PLAYER_REF = "char_tang_wei"
_TERMINAL_OPERATION_STATUS = {"completed", "cancelled"}


def _event_exists(planner: Any, event_id: str) -> Mapping[str, Any] | None:
    for event in iter_history_events(planner):
        if str(event.get("event_id", "")) == event_id:
            return event
    return None


def _person(planner: Any, person_ref: str) -> Mapping[str, Any] | None:
    try:
        row = planner.read(planner.owner_path(person_ref))
    except (FileNotFoundError, KeyError, ValueError):
        return None
    return row if isinstance(row, Mapping) else None


def _formation(planner: Any, formation_ref: str) -> Mapping[str, Any] | None:
    try:
        row = planner.read(planner.owner_path(formation_ref))
    except (FileNotFoundError, KeyError, ValueError):
        return None
    return row if isinstance(row, Mapping) else None


def _operation(planner: Any, operation_ref: str) -> tuple[str, dict[str, Any]]:
    path = planner.owner_path(operation_ref)
    row = planner.read(path)
    if not isinstance(row, Mapping) or str(row.get("schema", "")) != "sword-operation":
        raise ValueError("campaign closure requires an exact operation")
    return path, copy.deepcopy(dict(row))


def _location_rows(planner: Any) -> list[Mapping[str, Any]]:
    doc = planner.read(_LOCATIONS_PATH)
    rows = doc.get("locations") if isinstance(doc, Mapping) else None
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _capital_ref(planner: Any, state_ref: str) -> str | None:
    key = str(state_ref).removeprefix("state_")
    candidates = [
        str(row.get("ref"))
        for row in _location_rows(planner)
        if str(row.get("kind", "")) == "capital"
        and str(row.get("state", "")) == key
        and isinstance(row.get("ref"), str)
    ]
    return sorted(set(candidates))[0] if candidates else None


def _person_state_ref(person: Mapping[str, Any]) -> str | None:
    value = person.get("state")
    if not isinstance(value, str) or not value:
        return None
    return value if value.startswith("state_") else f"state_{value}"


def _formation_state_ref(planner: Any, formation: Mapping[str, Any]) -> str | None:
    owner = formation.get("administrative_owner")
    if isinstance(owner, str) and owner.startswith("state_"):
        return owner
    if isinstance(owner, str) and owner.startswith("house_"):
        try:
            house = planner.read(planner.owner_path(owner))
        except (FileNotFoundError, KeyError, ValueError):
            house = None
        if isinstance(house, Mapping):
            state = house.get("state")
            if isinstance(state, str) and state:
                return state if state.startswith("state_") else f"state_{state}"
    force_ref = formation.get("owner_force_ref")
    if isinstance(force_ref, str) and force_ref.startswith("force_state_"):
        return f"state_{force_ref.removeprefix('force_state_')}"
    return None


def _exact_command_people(planner: Any, formation_ref: str, formation: Mapping[str, Any]) -> set[str]:
    refs: set[str] = set()
    for key in ("commander_ref", "command_authority"):
        value = formation.get(key)
        if isinstance(value, str) and value.startswith("char_") and _person(planner, value) is not None:
            refs.add(value)
    # Command groups can carry the exact commander and staff even when the formation
    # record intentionally keeps only institutional command authority.
    try:
        index = planner.read("state/cmd/command-groups/index.json")
    except (FileNotFoundError, KeyError, ValueError):
        index = None
    mapping = index.get("primary_formation_group") if isinstance(index, Mapping) else None
    group_ref = mapping.get(formation_ref) if isinstance(mapping, Mapping) else None
    if isinstance(group_ref, str) and group_ref:
        path_template = index.get("path_template") if isinstance(index, Mapping) else None
        path = path_template.replace("{ref}", group_ref) if isinstance(path_template, str) and "{ref}" in path_template else f"state/cmd/command-groups/{group_ref}.json"
        try:
            group = planner.read(path)
        except (FileNotFoundError, KeyError, ValueError):
            group = None
        if isinstance(group, Mapping):
            for value in [group.get("commander_ref"), *group.get("direct_person_refs", [])]:
                if isinstance(value, str) and value.startswith("char_") and _person(planner, value) is not None:
                    refs.add(value)
    return refs


def _battle_events_for_operation(planner: Any, operation_ref: str, formation_refs: set[str], created_at: str | None) -> list[Mapping[str, Any]]:
    exact: list[Mapping[str, Any]] = []
    fallback: list[Mapping[str, Any]] = []
    for event in iter_history_events(planner):
        kind = str(event.get("kind", ""))
        if kind not in {"battle", "interstate_battle"}:
            continue
        if str(event.get("operation_ref", "")) == operation_ref:
            exact.append(event)
            continue
        # Compatibility for older battle receipts that predate operation_ref on
        # the event.  Formation overlap plus chronology is evidence; no global
        # story inference is made from labels.
        event_refs: set[str] = set()
        for key in ("attackers", "defenders", "attacker_formation_refs", "defender_formation_refs"):
            raw = event.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
                event_refs.update(str(ref) for ref in raw if isinstance(ref, str))
        if not event_refs.intersection(formation_refs):
            continue
        if created_at and str(event.get("at", "")) and str(event.get("at")) < created_at:
            continue
        fallback.append(event)
    return exact if exact else fallback


def _casualty_total(event: Mapping[str, Any]) -> int:
    killed = event.get("killed")
    if isinstance(killed, Mapping):
        return sum(max(0, int(value or 0)) for value in killed.values() if not isinstance(value, bool))
    if isinstance(killed, (int, float)) and not isinstance(killed, bool):
        return max(0, int(killed))
    losses = event.get("losses")
    if isinstance(losses, Mapping):
        total = 0
        for value in losses.values():
            if isinstance(value, Mapping):
                total += max(0, int(value.get("personnel_killed", value.get("killed", value.get("losses", 0))) or 0))
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                total += max(0, int(value))
        return total
    return 0


def _named_participants(planner: Any, formation_refs: set[str], battle_events: Sequence[Mapping[str, Any]]) -> list[str]:
    refs: set[str] = set()
    for event in battle_events:
        raw = event.get("participant_refs")
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            refs.update(str(ref) for ref in raw if isinstance(ref, str) and ref.startswith("char_") and _person(planner, str(ref)) is not None)
    for formation_ref in sorted(formation_refs):
        formation = _formation(planner, formation_ref)
        if isinstance(formation, Mapping):
            refs.update(_exact_command_people(planner, formation_ref, formation))
            owner = formation.get("administrative_owner")
            if isinstance(owner, str) and owner.startswith("house_"):
                try:
                    house = planner.read(planner.owner_path(owner))
                except (FileNotFoundError, KeyError, ValueError):
                    house = None
                leader = house.get("leader_ref") if isinstance(house, Mapping) else None
                if isinstance(leader, str) and leader.startswith("char_") and _person(planner, leader) is not None:
                    refs.add(leader)
    return sorted(refs)


def record_operation_after_action(planner: Any, operation_ref: str, *, at: str) -> dict[str, Any]:
    """Record one compact evidence-backed review for a terminal operation.

    This is *not* a war-ending ceremony. It preserves the campaign handoff after
    a battle/operation so command can issue the next order, replace losses, or
    continue the war without losing what actually happened.
    """
    path, operation = _operation(planner, operation_ref)
    status = str(operation.get("status", ""))
    if status not in _TERMINAL_OPERATION_STATUS:
        raise ValueError("after-action review requires a terminal operation")
    existing = operation.get("after_action_review")
    if isinstance(existing, Mapping) and isinstance(existing.get("event_ref"), str):
        return copy.deepcopy(dict(existing))
    formation_refs = {str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)}
    battles = _battle_events_for_operation(planner, operation_ref, formation_refs, str(operation.get("created_at", "")) or None)
    battle_refs = [str(event.get("event_id")) for event in battles if isinstance(event.get("event_id"), str)]
    participant_refs = _named_participants(planner, formation_refs, battles)
    casualties = sum(_casualty_total(event) for event in battles)
    token = hashlib.sha256(f"{operation_ref}|{status}|{'|'.join(battle_refs)}".encode()).hexdigest()[:18]
    event_ref = f"campaign_after_action_{token}"
    review = {
        "event_ref": event_ref,
        "operation_ref": operation_ref,
        "campaign_ref": campaign_arc_ref(operation),
        "status": status,
        "reviewed_at": at,
        "battle_event_refs": battle_refs,
        "participant_formation_refs": sorted(formation_refs),
        "participant_person_refs": participant_refs,
        "battle_count": len(battle_refs),
        "casualty_count": casualties,
        "next_step_rule": "This review closes only the operation. The wider war/campaign continues unless exact diplomacy/campaign authority separately ends it.",
    }
    if _event_exists(planner, event_ref) is None:
        history = copy.deepcopy(planner.read(HISTORY_INDEX_PATH))
        history.setdefault("events", []).append({
            "event_id": event_ref,
            "kind": "campaign_after_action_review",
            "at": at,
            **copy.deepcopy(review),
        })
        write_history_index(planner, history)
    operation["after_action_review"] = copy.deepcopy(review)
    operation["campaign_phase"] = "operation_closed_awaiting_campaign_direction"
    planner.put(path, operation)
    return review


def _campaign_evidence(
    planner: Any,
    *,
    war_scope_ref: str,
    operation_refs: Sequence[str] | None,
) -> tuple[list[str], list[Mapping[str, Any]], set[str]]:
    operations = sorted({str(ref) for ref in (operation_refs or []) if isinstance(ref, str) and ref})
    formation_refs: set[str] = set()
    for ref in operations:
        try:
            _path, operation = _operation(planner, ref)
        except (FileNotFoundError, KeyError, ValueError):
            continue
        formation_refs.update(str(x) for x in operation.get("formation_refs", []) if isinstance(x, str))
    battles: list[Mapping[str, Any]] = []
    for event in iter_history_events(planner):
        if str(event.get("kind", "")) not in {"battle", "interstate_battle"}:
            continue
        if str(event.get("theater_ref", "")) == war_scope_ref or str(event.get("campaign_ref", "")) == war_scope_ref:
            battles.append(event); continue
        if str(event.get("operation_ref", "")) in operations:
            battles.append(event); continue
        refs: set[str] = set()
        for key in ("attackers", "defenders", "attacker_formation_refs", "defender_formation_refs"):
            raw = event.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
                refs.update(str(x) for x in raw if isinstance(x, str))
        if formation_refs and refs.intersection(formation_refs):
            battles.append(event)
    # Preserve first occurrence order while de-duplicating.
    seen: set[str] = set(); unique: list[Mapping[str, Any]] = []
    for event in battles:
        eid = str(event.get("event_id", ""))
        key = eid or repr(sorted(event.items()))
        if key in seen: continue
        seen.add(key); unique.append(event)
        for field in ("attackers", "defenders", "attacker_formation_refs", "defender_formation_refs"):
            raw = event.get(field)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
                formation_refs.update(str(x) for x in raw if isinstance(x, str))
    return operations, unique, formation_refs



def _close_postwar_operation_assignments(
    planner: Any,
    *,
    war_scope_ref: str,
    closure_event_ref: str,
    operation_refs: Sequence[str],
    at: str,
) -> list[dict[str, Any]]:
    """Close obsolete war-operation routing without moving or rewriting troops.

    A peace settlement ends the operation assignment, not the physical existence
    of its formations.  State forces become available for their lawful owner to
    reassign; House/private forces remain their owner's property and may receive a
    later return movement order.  No formation teleports, heals, refills, changes
    ownership, or loses its commander merely because the war ended.
    """
    dispositions: list[dict[str, Any]] = []
    operation_index = copy.deepcopy(planner.read("state/operations/index.json"))
    active_battlefields = operation_index.get("active_battlefield_operation_refs")
    if not isinstance(active_battlefields, list):
        active_battlefields = []
        operation_index["active_battlefield_operation_refs"] = active_battlefields
    index_changed = False

    for operation_ref in sorted(set(str(ref) for ref in operation_refs if isinstance(ref, str) and ref)):
        try:
            path, operation = _operation(planner, operation_ref)
        except (FileNotFoundError, KeyError, ValueError):
            continue

        prior_status = str(operation.get("status", ""))
        if prior_status not in _TERMINAL_OPERATION_STATUS:
            operation["status"] = "completed"
        operation["campaign_phase"] = "war_closed_available_for_owner_reassignment"
        operation["war_closure_event_ref"] = closure_event_ref
        operation["war_scope_ref"] = operation.get("war_scope_ref") or war_scope_ref

        battlefields = operation.get("battlefields")
        if isinstance(battlefields, dict):
            for battlefield_ref, battlefield in battlefields.items():
                if not isinstance(battlefield, dict) or str(battlefield.get("status", "")) != "active":
                    continue
                battlefield["status"] = "ended"
                battlefield["concluded_at"] = at
                battlefield["conclusion"] = {
                    "scope": "field_battle_only",
                    "result": "war_settlement_ended_further_contact",
                    "war_scope_ref": war_scope_ref,
                    "closure_event_ref": closure_event_ref,
                    "rule": "A wider lawful war settlement ends further organized contact without inventing a local battlefield winner.",
                }

        op_dispositions: list[dict[str, Any]] = []
        for formation_ref in sorted({str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)}):
            formation = _formation(planner, formation_ref)
            if not isinstance(formation, Mapping):
                continue
            owner_ref = str(formation.get("administrative_owner") or formation.get("owner_force_ref") or "")
            if owner_ref.startswith("state_"):
                action = "available_for_state_reassignment"
            elif owner_ref.startswith("house_"):
                action = "return_to_house_authority_pending_movement"
            else:
                action = "available_for_owner_reassignment"
            row = {
                "formation_ref": formation_ref,
                "administrative_owner_ref": owner_ref or None,
                "current_location_ref": formation.get("location_ref"),
                "current_command_authority_ref": formation.get("command_authority"),
                "current_commander_ref": formation.get("commander_ref"),
                "action": action,
                "status": "pending_owner_order",
                "ordered_at": at,
                "war_scope_ref": war_scope_ref,
                "closure_event_ref": closure_event_ref,
                "rule": "Disposition closes campaign assignment only. It does not move, demobilize, heal, refill, transfer ownership, or silently replace command.",
            }
            op_dispositions.append(row)
            dispositions.append(copy.deepcopy(row))
        operation["postwar_dispositions"] = op_dispositions
        planner.put(path, operation)

        if operation_ref in active_battlefields:
            active_battlefields[:] = [ref for ref in active_battlefields if ref != operation_ref]
            index_changed = True

    if index_changed:
        planner.put("state/operations/index.json", operation_index)
    return dispositions

def schedule_war_closure_ceremonies(
    planner: Any,
    *,
    war_scope_ref: str,
    party_refs: Sequence[str],
    at: str,
    result: str,
    treaty_ref: str | None = None,
    operation_refs: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Create one post-war institutional closure and state-specific court summons.

    The wider conflict must already be settled by diplomacy/theater authority.
    This function never decides peace and never grants rewards.
    """
    parties = sorted({str(ref) for ref in party_refs if isinstance(ref, str) and ref})
    if len(parties) < 2:
        raise ValueError("war closure requires at least two exact parties")
    operations, battles, formation_refs = _campaign_evidence(planner, war_scope_ref=war_scope_ref, operation_refs=operation_refs)
    battle_refs = [str(event.get("event_id")) for event in battles if isinstance(event.get("event_id"), str)]
    participant_refs = _named_participants(planner, formation_refs, battles)
    casualties = sum(_casualty_total(event) for event in battles)
    closure_token = hashlib.sha256(f"{war_scope_ref}|{treaty_ref or ''}|{result}|{'|'.join(battle_refs)}".encode()).hexdigest()[:18]
    closure_event_ref = f"war_closure_{closure_token}"
    existing = _event_exists(planner, closure_event_ref)
    if isinstance(existing, Mapping):
        return copy.deepcopy(dict(existing))

    postwar_dispositions = _close_postwar_operation_assignments(
        planner,
        war_scope_ref=war_scope_ref,
        closure_event_ref=closure_event_ref,
        operation_refs=operations,
        at=at,
    )

    by_state: dict[str, list[str]] = {party: [] for party in parties if party.startswith("state_")}
    for person_ref in participant_refs:
        person = _person(planner, person_ref)
        state_ref = _person_state_ref(person) if isinstance(person, Mapping) else None
        if state_ref in by_state:
            by_state[state_ref].append(person_ref)
    # A House commander may have a different personal-state field than the army
    # side it served.  Formation evidence therefore supplements, never overrides,
    # exact person identity.
    for formation_ref in sorted(formation_refs):
        formation = _formation(planner, formation_ref)
        if not isinstance(formation, Mapping):
            continue
        state_ref = _formation_state_ref(planner, formation)
        if state_ref not in by_state:
            continue
        for person_ref in _exact_command_people(planner, formation_ref, formation):
            if person_ref not in by_state[state_ref]:
                by_state[state_ref].append(person_ref)
        owner = formation.get("administrative_owner")
        if isinstance(owner, str) and owner.startswith("house_"):
            try: house = planner.read(planner.owner_path(owner))
            except (FileNotFoundError, KeyError, ValueError): house = None
            leader = house.get("leader_ref") if isinstance(house, Mapping) else None
            if isinstance(leader, str) and leader.startswith("char_") and _person(planner, leader) is not None and leader not in by_state[state_ref]:
                by_state[state_ref].append(leader)

    ceremony_rows: list[dict[str, Any]] = []
    for state_ref in sorted(by_state):
        summoned = sorted(set(by_state[state_ref]))
        if not summoned:
            continue
        venue_ref = _capital_ref(planner, state_ref)
        # Court ceremony is scheduled after a short institutional return/review
        # window. This does not teleport anyone. Actual attendance is checked
        # against exact person locations when the ceremony is settled.
        scheduled_at = str(CampaignTime.parse(at).add_seconds(7 * 86400))
        ceremony_ref = f"war_ceremony_{hashlib.sha256(f'{closure_event_ref}|{state_ref}'.encode()).hexdigest()[:18]}"
        row = {
            "ceremony_ref": ceremony_ref,
            "state_ref": state_ref,
            "venue_ref": venue_ref,
            "scheduled_at": scheduled_at,
            "status": "summoned",
            "summoned_person_refs": summoned,
            "attendance_rule": "Summons establish obligation/invitation only. No person is teleported; ceremony attendance requires the exact person to be at the venue when it is held.",
            "reward_rule": "The ceremony may recognize verified service and open lawful reward review, but cannot itself mint promotion, office, nobility, land, troops or silver.",
        }
        ceremony_rows.append(row)
        if _PLAYER_REF in summoned:
            info_ref = f"information.war_ceremony_summons.{hashlib.sha256(ceremony_ref.encode()).hexdigest()[:18]}"
            summary = (
                f"Post-war court summons: {state_ref} has called the materially involved campaign commanders and notable participants to a formal war-closing review at "
                f"{venue_ref or 'the state court'} on {scheduled_at}. The conflict settlement is {result}. Attendance is physical; this summons does not move Tang Wei automatically, "
                "and any promotion, office, land, silver, nobility or command change remains a separate lawful decision."
            )
            _persist_information(
                planner,
                info_ref=info_ref,
                subject_ref=war_scope_ref,
                fact=summary,
                epistemic_kind="official_military_summons",
                confidence_milli=1000,
                provenance=f"{state_ref} post-war military/court authority",
                evidence_refs=[ref for ref in [treaty_ref, closure_event_ref, *battle_refs] if isinstance(ref, str) and ref],
                classification="official_command_notice",
                location_ref=venue_ref,
                at=at,
                campaign_context={
                    "war_scope_ref": war_scope_ref,
                    "closure_event_ref": closure_event_ref,
                    "ceremony_ref": ceremony_ref,
                    "ceremony_state_ref": state_ref,
                    "venue_ref": venue_ref,
                    "scheduled_at": scheduled_at,
                    "result": result,
                    "battle_event_refs": battle_refs,
                    "participant_person_refs": participant_refs,
                },
            )
            row["player_summons_information_ref"] = info_ref

    event = {
        "event_id": closure_event_ref,
        "kind": "war_campaign_closure",
        "at": at,
        "war_scope_ref": war_scope_ref,
        "party_refs": parties,
        "result": result,
        "treaty_ref": treaty_ref,
        "operation_refs": operations,
        "battle_event_refs": battle_refs,
        "participant_formation_refs": sorted(formation_refs),
        "participant_person_refs": participant_refs,
        "postwar_dispositions": postwar_dispositions,
        "battle_count": len(battle_refs),
        "casualty_count": casualties,
        "ceremonies": ceremony_rows,
        "status": "postwar_review_scheduled" if ceremony_rows else "closed_without_materialized_ceremony",
        "closure_rule": "Battle aftermath and war closure are distinct. This record exists only because exact war/diplomatic authority already ended the wider conflict.",
    }
    history = copy.deepcopy(planner.read(HISTORY_INDEX_PATH))
    history.setdefault("events", []).append(copy.deepcopy(event))
    write_history_index(planner, history)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    for ceremony in ceremony_rows:
        _ensure_ceremony_route(planner, runtime, closure_event_ref=closure_event_ref, ceremony=ceremony)
    planner.put("state/runtime.json", runtime)

    if treaty_ref:
        try:
            treaties = copy.deepcopy(planner.read("state/politics/treaties.json"))
            record = (treaties.get("records") or {}).get(treaty_ref) if isinstance(treaties, Mapping) else None
            if isinstance(record, dict):
                record["war_closure_event_ref"] = closure_event_ref
                record["postwar_ceremony_refs"] = [row["ceremony_ref"] for row in ceremony_rows]
                planner.put("state/politics/treaties.json", treaties)
        except (FileNotFoundError, KeyError, ValueError):
            pass
    return event


def _ceremony_route_ids(ceremony_ref: str) -> tuple[str, str]:
    token = hashlib.sha256(ceremony_ref.encode()).hexdigest()[:18]
    return f"host_war_ceremony_{token}", f"event_war_ceremony_{token}"


def _ensure_ceremony_route(planner: Any, runtime: dict[str, Any], *, closure_event_ref: str, ceremony: Mapping[str, Any]) -> bool:
    """Register one sparse one-shot chronology route from durable ceremony evidence."""
    ceremony_ref = str(ceremony.get("ceremony_ref", ""))
    due_text = str(ceremony.get("scheduled_at", ""))
    if not ceremony_ref or not due_text:
        return False
    if _event_exists(planner, f"{ceremony_ref}.held") is not None:
        return False
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    host_id, event_id = _ceremony_route_ids(ceremony_ref)
    if host_id in hosts:
        return False
    due = CampaignTime.parse(due_text)
    current = CampaignTime.parse(str(runtime.get("world_time")))
    # A recovered overdue ceremony settles at the current frontier rather than
    # pretending chronology can move backward. The durable scheduled_at remains
    # the institutional appointment time.
    route_due = current if due < current else due
    hosts[host_id] = {
        "host_id": host_id,
        "kind": "war_closure_ceremony",
        "owner_ref": str(ceremony.get("state_ref", "")),
        "closure_event_ref": closure_event_ref,
        "ceremony_ref": ceremony_ref,
        "recurrence_seconds": 0,
        "next_due": str(route_due),
        "resolved_through": str(current),
        "safe_through": str(route_due.add_seconds(-1)) if route_due > current else str(current),
        "retire_after_settlement": True,
    }
    events.append({
        "event_id": event_id,
        "kind": "war_closure_ceremony",
        "priority": 34,
        "target_host": host_id,
        "due_at": str(route_due),
    })
    return True


def sync_war_ceremony_routes(planner: Any, runtime: dict[str, Any]) -> int:
    """Recover only still-pending ceremony routes from the bounded hot history head.

    Ceremony creation writes the route immediately. This reconciler exists for
    interrupted upgrades/recovery and deliberately scans only the hot semantic
    history window rather than the world.
    """
    history = planner.read(HISTORY_INDEX_PATH)
    events = history.get("events", []) if isinstance(history, Mapping) else []
    added = 0
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, Mapping) or str(event.get("kind", "")) != "war_campaign_closure":
            continue
        closure_ref = str(event.get("event_id", ""))
        for ceremony in event.get("ceremonies", []) if isinstance(event.get("ceremonies"), list) else []:
            if isinstance(ceremony, Mapping) and _ensure_ceremony_route(planner, runtime, closure_event_ref=closure_ref, ceremony=ceremony):
                added += 1
    return added


def settle_war_ceremony(planner: Any, ceremony_ref: str, *, at: str) -> dict[str, Any]:
    """Hold one scheduled ceremony using exact attendance at the venue.

    This function is intentionally presentation/recognition state only. It does
    not grant material rewards or move absent people into the room.
    """
    plan: Mapping[str, Any] | None = None
    closure_ref: str | None = None
    for event in iter_history_events(planner):
        if str(event.get("kind", "")) != "war_campaign_closure":
            continue
        for row in event.get("ceremonies", []) if isinstance(event.get("ceremonies"), list) else []:
            if isinstance(row, Mapping) and str(row.get("ceremony_ref", "")) == ceremony_ref:
                plan = row; closure_ref = str(event.get("event_id", "")); break
        if plan is not None:
            break
    if plan is None:
        raise ValueError("unknown war ceremony")
    scheduled = str(plan.get("scheduled_at", ""))
    if scheduled and CampaignTime.parse(at) < CampaignTime.parse(scheduled):
        raise ValueError("war ceremony cannot be held before its scheduled time")
    held_ref = f"{ceremony_ref}.held"
    existing = _event_exists(planner, held_ref)
    if isinstance(existing, Mapping):
        return copy.deepcopy(dict(existing))
    venue_ref = str(plan.get("venue_ref", "")) or None
    present: list[str] = []
    absent: list[str] = []
    dead: list[str] = []
    unavailable: list[str] = []
    summoned = [str(ref) for ref in plan.get("summoned_person_refs", []) if isinstance(ref, str)]
    for person_ref in summoned:
        person = _person(planner, person_ref)
        if not isinstance(person, Mapping):
            unavailable.append(person_ref); continue
        if str(person.get("life_status", person.get("status", "active"))).lower() in {"dead", "deceased"}:
            dead.append(person_ref); continue
        location = str(person.get("location", person.get("current_location", "")))
        if venue_ref and location == venue_ref:
            present.append(person_ref)
        else:
            absent.append(person_ref)

    court_session = None
    state_ref_for_court = plan.get("state_ref")
    if venue_ref and isinstance(state_ref_for_court, str) and state_ref_for_court:
        court_session = court_session_projection(
            planner, state_ref=state_ref_for_court, venue_ref=venue_ref,
            additional_candidate_refs=summoned,
        )
        present = list(dict.fromkeys(present + [
            str(ref) for ref in court_session.get("present_person_refs", []) if isinstance(ref, str)
        ]))
        absent = list(dict.fromkeys(absent + [
            str(ref) for ref in court_session.get("absent_person_refs", []) if isinstance(ref, str)
        ]))
        absent = [ref for ref in absent if ref not in set(present)]

    # Ceremony opens evidence-backed formal review only. The reward authority
    # remains in court_rewards and no promotion, office, land or silver is granted
    # here. Attendance is not required for service to remain reviewable.
    reward_review_refs: list[str] = []
    state_ref = str(plan.get("state_ref", ""))
    state_key = state_ref.removeprefix("state_")
    if closure_ref and state_key:
        from sword_runtime.court_rewards import open_reward_review
        for person_ref in summoned:
            try:
                review = open_reward_review(
                    planner, state=state_key, subject_ref=person_ref,
                    evidence_ref=closure_ref, at=at,
                )
            except (FileNotFoundError, KeyError, ValueError):
                continue
            review_ref = review.get("review_ref") if isinstance(review, Mapping) else None
            if isinstance(review_ref, str):
                reward_review_refs.append(review_ref)

    event = {
        "event_id": held_ref,
        "kind": "war_closure_ceremony",
        "at": at,
        "ceremony_ref": ceremony_ref,
        "closure_event_ref": closure_ref,
        "state_ref": plan.get("state_ref"),
        "venue_ref": venue_ref,
        "summoned_person_refs": list(plan.get("summoned_person_refs", [])),
        "present_person_refs": sorted(present),
        "absent_person_refs": sorted(absent),
        "court_session": copy.deepcopy(dict(court_session)) if isinstance(court_session, Mapping) else None,
        "dead_person_refs": sorted(dead),
        "unavailable_person_refs": sorted(unavailable),
        "memorial_review_person_refs": sorted(dead),
        "reward_review_refs": sorted(set(reward_review_refs)),
        "formal_reward_status": "reviews_opened" if reward_review_refs else "separate_review_required",
        "rule": "Presence is derived from exact saved locations. The ceremony may open evidence-backed reward review, but only court reward authority may later grant material or career rewards.",
    }
    history = copy.deepcopy(planner.read(HISTORY_INDEX_PATH))
    history.setdefault("events", []).append(copy.deepcopy(event))
    write_history_index(planner, history)
    return event


__all__ = [
    "record_operation_after_action",
    "schedule_war_closure_ceremonies",
    "settle_war_ceremony",
    "sync_war_ceremony_routes",
]
