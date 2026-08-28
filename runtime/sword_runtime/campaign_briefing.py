"""Derived player-safe campaign briefings and campaign-phase handoffs.

This module is deliberately a projection/lifecycle layer, not another campaign
simulation. Exact operations, formations, command groups, geography and
information claims remain authority. It joins those owners into the minimum
operational picture a field commander needs and records only official reports
that were actually delivered to Tang Wei.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.geography import nearest_reachable_destination, shortest_path
from sword_runtime.campaign_march_planning import build_march_planning_baseline

_OPERATIONS_INDEX = "state/operations/index.json"
_COMMAND_GROUP_INDEX = "state/cmd/command-groups/index.json"
_LOCATIONS = "game/data/world/locations.json"
_INFO_INDEX = "state/information/index.json"
_INFO_SUBJECT_INDEX = "state/information/subject-index.json"
_PLAYER_REF = "char_tang_wei"
_QIN_BUREAU_REF = "inst_qin_military_bureau"
_ACTIVE_OPERATION_STATUSES = {"active", "mobilizing", "advancing", "engaged", "occupied"}
_ACTIVE_FORMATION_STATUSES = {
    "active", "forming", "ready", "garrisoned", "reserve", "mobilized", "marching", "engaged", "deployed",
    "arrived_forming",
}


def _digest(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}|{value}".encode("utf-8")).hexdigest()[:20]


def _operation_path(planner: Any, operation_ref: str) -> str | None:
    index = planner.read(_OPERATIONS_INDEX)
    rows = index.get("operations") if isinstance(index, Mapping) else None
    if not isinstance(rows, Mapping):
        return None
    path = rows.get(operation_ref)
    return str(path) if isinstance(path, str) and path else None


def _load_operation(planner: Any, operation_ref: str) -> tuple[str, dict[str, Any]]:
    path = _operation_path(planner, operation_ref)
    if path is None:
        raise ValueError(f"unknown operation: {operation_ref}")
    raw = planner.read(path)
    if not isinstance(raw, Mapping):
        raise ValueError(f"invalid operation owner: {operation_ref}")
    return path, copy.deepcopy(dict(raw))


def _latest_order(operation: Mapping[str, Any]) -> dict[str, Any]:
    ref = str(operation.get("last_operational_order_ref", ""))
    rows = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    if ref:
        for row in reversed(rows):
            if isinstance(row, Mapping) and str(row.get("order_ref", "")) == ref:
                return copy.deepcopy(dict(row))
    for row in reversed(rows):
        if isinstance(row, Mapping):
            return copy.deepcopy(dict(row))
    current = operation.get("current_operational_order")
    return copy.deepcopy(dict(current)) if isinstance(current, Mapping) else {}


def campaign_arc_ref(operation: Mapping[str, Any]) -> str | None:
    order = _latest_order(operation)
    for candidate in (order.get("arc_ref"), operation.get("arc_ref")):
        if isinstance(candidate, str) and candidate.startswith("arc_"):
            return candidate
    for ref in operation.get("objective_refs", []) if isinstance(operation.get("objective_refs"), list) else []:
        if isinstance(ref, str) and ref.startswith("arc_"):
            return ref
    return None


def _formation(planner: Any, formation_ref: str) -> dict[str, Any] | None:
    try:
        raw = planner.read(planner.owner_path(formation_ref))
    except (KeyError, ValueError, FileNotFoundError):
        return None
    return copy.deepcopy(dict(raw)) if isinstance(raw, Mapping) else None


def _operation_state(planner: Any, operation: Mapping[str, Any]) -> str | None:
    for key in ("institutional_owner_ref", "administrative_authority"):
        value = operation.get(key)
        if isinstance(value, str) and value.startswith("state_"):
            return value
    states: set[str] = set()
    for ref in operation.get("formation_refs", []) if isinstance(operation.get("formation_refs"), list) else []:
        if not isinstance(ref, str):
            continue
        row = _formation(planner, ref)
        if not isinstance(row, Mapping):
            continue
        owner = row.get("administrative_owner")
        if isinstance(owner, str) and owner.startswith("state_"):
            states.add(owner)
    return next(iter(states)) if len(states) == 1 else None


def _target_state(operation: Mapping[str, Any], friendly_state: str | None) -> str | None:
    order = _latest_order(operation)
    candidates = [order.get("strategic_pressure_target_ref"), order.get("target_ref")]
    candidates.extend(operation.get("objective_refs", []) if isinstance(operation.get("objective_refs"), list) else [])
    for value in candidates:
        if isinstance(value, str) and value.startswith("state_") and value != friendly_state:
            return value
    return None


def _person_name(planner: Any, person_ref: str | None) -> str | None:
    if not isinstance(person_ref, str) or not person_ref:
        return None
    try:
        row = planner.read(planner.owner_path(person_ref))
    except (KeyError, ValueError, FileNotFoundError):
        return person_ref
    if isinstance(row, Mapping):
        return str(row.get("name") or row.get("display_name") or person_ref)
    return person_ref


def _location_rows(planner: Any) -> dict[str, Mapping[str, Any]]:
    doc = planner.read(_LOCATIONS)
    return {
        str(row.get("ref")): row
        for row in doc.get("locations", []) if isinstance(row, Mapping) and row.get("ref")
    }


def _location_name(rows: Mapping[str, Mapping[str, Any]], ref: str | None) -> str:
    if not isinstance(ref, str) or not ref:
        return "unestablished location"
    row = rows.get(ref)
    return str(row.get("name") or ref) if isinstance(row, Mapping) else ref


def _command_group_for_formation(planner: Any, formation_ref: str) -> tuple[str | None, Mapping[str, Any] | None]:
    try:
        index = planner.read(_COMMAND_GROUP_INDEX)
    except (FileNotFoundError, KeyError):
        return None, None
    mapping = index.get("primary_formation_group") if isinstance(index, Mapping) else None
    group_ref = mapping.get(formation_ref) if isinstance(mapping, Mapping) else None
    if not isinstance(group_ref, str) or not group_ref:
        return None, None
    path_template = index.get("path_template") if isinstance(index, Mapping) else None
    path = path_template.replace("{ref}", group_ref) if isinstance(path_template, str) and "{ref}" in path_template else f"state/cmd/command-groups/{group_ref}.json"
    try:
        group = planner.read(path)
    except (FileNotFoundError, KeyError):
        return group_ref, None
    return group_ref, group if isinstance(group, Mapping) else None


def _formation_commander(planner: Any, formation_ref: str, formation: Mapping[str, Any]) -> tuple[str | None, str | None]:
    _group_ref, group = _command_group_for_formation(planner, formation_ref)
    commander_ref = group.get("commander_ref") if isinstance(group, Mapping) else None
    if not isinstance(commander_ref, str) or not commander_ref:
        direct = formation.get("commander_ref")
        commander_ref = direct if isinstance(direct, str) and direct else None
    return commander_ref, _person_name(planner, commander_ref)


def _snapshot_operation(planner: Any, operation_ref: str, operation: Mapping[str, Any], locations: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    formations: list[dict[str, Any]] = []
    commanders: dict[str, str] = {}
    total = 0
    auxiliary_strength = 0
    auxiliary_refs = {str(ref) for ref in operation.get("auxiliary_formation_refs", []) if isinstance(ref, str) and ref}
    opposing_refs = {str(ref) for ref in operation.get("opposing_formation_refs", []) if isinstance(ref, str) and ref}
    location_strength: dict[str, int] = {}
    for ref in operation.get("formation_refs", []) if isinstance(operation.get("formation_refs"), list) else []:
        if not isinstance(ref, str) or ref in opposing_refs:
            continue
        row = _formation(planner, ref)
        if not isinstance(row, Mapping):
            continue
        if str(row.get("status", "")) not in _ACTIVE_FORMATION_STATUSES and int(row.get("personnel", 0) or 0) <= 0:
            continue
        personnel = max(0, int(row.get("personnel", 0) or 0))
        total += personnel
        is_auxiliary = ref in auxiliary_refs
        if is_auxiliary:
            auxiliary_strength += personnel
        location_ref = str(row.get("location_ref", ""))
        if location_ref:
            location_strength[location_ref] = location_strength.get(location_ref, 0) + personnel
        commander_ref, commander_name = _formation_commander(planner, ref, row)
        if commander_ref and commander_name:
            commanders[commander_ref] = commander_name
        formations.append({
            "formation_ref": ref,
            "name": str(row.get("name") or ref),
            "personnel": personnel,
            "location_ref": location_ref or None,
            "location_name": _location_name(locations, location_ref),
            "commander_ref": commander_ref,
            "commander_name": commander_name,
            "status": str(row.get("status", "")),
            "participation_kind": "commander_auxiliary" if is_auxiliary else "institutionally_assigned",
        })
    actual_locations = sorted(location_strength)
    return {
        "operation_ref": operation_ref,
        "owner_state_ref": _operation_state(planner, operation),
        "objective": str(operation.get("objective", "")),
        "status": str(operation.get("status", "")),
        "strength": total,
        "assigned_strength": total - auxiliary_strength,
        "auxiliary_strength": auxiliary_strength,
        "auxiliary_formation_refs": sorted(auxiliary_refs),
        "formation_count": len(formations),
        "formations": formations,
        "location_ref": actual_locations[0] if len(actual_locations) == 1 else None,
        "location_refs": actual_locations,
        "location_strength": location_strength,
        "commanders": [{"person_ref": ref, "name": name} for ref, name in sorted(commanders.items())],
    }


def _same_arc_operations(planner: Any, arc_ref: str, locations: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    index = planner.read(_OPERATIONS_INDEX)
    rows = index.get("operations") if isinstance(index, Mapping) else None
    if not isinstance(rows, Mapping):
        return []
    result: list[dict[str, Any]] = []
    for operation_ref, path in sorted(rows.items()):
        if not isinstance(operation_ref, str) or not isinstance(path, str):
            continue
        raw = planner.read(path)
        if not isinstance(raw, Mapping) or str(raw.get("status", "")) not in _ACTIVE_OPERATION_STATUSES:
            continue
        if campaign_arc_ref(raw) != arc_ref:
            continue
        result.append(_snapshot_operation(planner, operation_ref, raw, locations))
    return result


def _campaign_operation_snapshots(
    planner: Any,
    *,
    operation_ref: str,
    operation: Mapping[str, Any],
    arc_ref: str | None,
    locations: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return active same-campaign operations without silently losing a saved roster.

    ``campaign_participant_operation_refs`` is a durable roster guard on the
    player's campaign operation. It does not freeze participation forever: an
    exact referenced operation may lawfully become terminal and then drops from
    the active dossier. But a referenced owner disappearing from routing, being
    reassigned to a different arc, or becoming unreadable is structural damage
    and must fail closed rather than turning a large campaign into a solo one.

    Active same-arc operations not yet present in the saved roster are unioned in
    so lawful reinforcements can still join dynamically.
    """
    active = _same_arc_operations(planner, arc_ref, locations) if arc_ref else []
    by_ref = {str(row.get("operation_ref")): row for row in active if row.get("operation_ref")}
    explicit = operation.get("campaign_participant_operation_refs")
    if not isinstance(explicit, list):
        return active
    for peer_ref in explicit:
        if not isinstance(peer_ref, str) or not peer_ref or peer_ref == operation_ref:
            continue
        path = _operation_path(planner, peer_ref)
        if path is None:
            raise ValueError(f"campaign participant roster lost exact operation owner: {peer_ref}")
        raw = planner.read(path)
        if not isinstance(raw, Mapping):
            raise ValueError(f"campaign participant operation is invalid: {peer_ref}")
        if arc_ref and campaign_arc_ref(raw) != arc_ref:
            raise ValueError(f"campaign participant operation left its saved campaign without roster update: {peer_ref}")
        status = str(raw.get("status", ""))
        if status in _ACTIVE_OPERATION_STATUSES:
            by_ref[peer_ref] = _snapshot_operation(planner, peer_ref, raw, locations)
        elif status not in {"completed", "cancelled"}:
            raise ValueError(f"campaign participant operation has unsupported roster status: {peer_ref}:{status}")
    return [by_ref[key] for key in sorted(by_ref)]


def _origin_location(own: Mapping[str, Any], operation: Mapping[str, Any]) -> str | None:
    refs = [str(x) for x in own.get("location_refs", []) if isinstance(x, str)]
    if len(refs) == 1:
        return refs[0]
    op_loc = operation.get("location_ref")
    return str(op_loc) if isinstance(op_loc, str) and op_loc else (refs[0] if refs else None)


def _hostile_entry_authorized(planner: Any, friendly_state: str | None, target_state: str | None) -> bool:
    if not friendly_state or not target_state or friendly_state == target_state:
        return True
    key = friendly_state.removeprefix("state_")
    try:
        state = planner.read(f"state/states/{key}.json")
    except (KeyError, FileNotFoundError, ValueError):
        return False
    diplomacy = state.get("diplomacy", {}) if isinstance(state, Mapping) else {}
    relation = diplomacy.get(target_state, {}) if isinstance(diplomacy, Mapping) else {}
    if isinstance(relation, Mapping) and str(relation.get("status", "")) == "war":
        return True
    for intent in state.get("war_intents", []) if isinstance(state, Mapping) else []:
        if not isinstance(intent, Mapping):
            continue
        if str(intent.get("target_ref", "")) == target_state and str(intent.get("status", "")) in {"authorized", "ready", "activated"}:
            return True
    return False


def _operational_area(
    planner: Any,
    origin: str | None,
    friendly_state: str | None,
    target_state: str | None,
    locations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not origin or not target_state:
        return None
    target_key = target_state.removeprefix("state_")
    targets = [
        ref for ref, row in locations.items()
        if str(row.get("state", "")) == target_key and bool(row.get("strategic_node")) and not bool(row.get("flavor_only"))
    ]
    if not targets:
        return None
    try:
        target_route = nearest_reachable_destination(planner.read, origin, targets, modes=("formation", "foot", "horse"))
    except ValueError:
        return None
    strategic_target = str(target_route.get("destination", ""))
    if not strategic_target:
        return None
    authorized = _hostile_entry_authorized(planner, friendly_state, target_state)
    destination = strategic_target
    selection_basis = "nearest reachable strategic node in the target state"
    if not authorized and friendly_state:
        friendly_key = friendly_state.removeprefix("state_")
        staging_candidates = [
            ref for ref, row in locations.items()
            if str(row.get("state", "")) == friendly_key and bool(row.get("strategic_node")) and not bool(row.get("flavor_only"))
        ]
        best: tuple[int, str] | None = None
        for candidate in staging_candidates:
            try:
                to_stage = shortest_path(planner.read, origin, candidate, modes=("formation", "foot", "horse"))
                to_target = shortest_path(planner.read, candidate, strategic_target, modes=("formation", "foot", "horse"))
            except ValueError:
                continue
            score = int(to_stage.get("duration_hours", 0) or 0) + int(to_target.get("duration_hours", 0) or 0)
            row = (score, candidate)
            if best is None or row < best:
                best = row
        if best is not None:
            destination = best[1]
            selection_basis = "nearest lawful friendly strategic staging node on the approach to the target theater"
    try:
        immediate_route = shortest_path(planner.read, origin, destination, modes=("formation", "foot", "horse"))
        immediate_hours = int(immediate_route.get("duration_hours", 0) or 0)
    except ValueError:
        immediate_hours = 0
    return {
        "destination_ref": destination or None,
        "destination_name": _location_name(locations, destination),
        "strategic_target_ref": strategic_target,
        "strategic_target_name": _location_name(locations, strategic_target),
        "target_state_ref": target_state,
        "hostile_entry_authorized": authorized,
        "entry_status": "authorized" if authorized else "awaiting_war_or_entry_authority",
        "route_hours_from_current_assembly": immediate_hours,
        "selection_basis": selection_basis,
    }


def _confirmed_hostile_contacts(
    planner: Any,
    *,
    target_state_ref: str | None,
    location_ref: str | None,
    excluded: set[str],
    locations: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return exact co-located hostile formations as player-safe contact rows.

    Exact formation refs are exposed only once physical co-location establishes a
    targetable contact. Personnel are converted to bounded estimates for the
    player-facing report; exact strength remains in the formation owner.
    """
    if not target_state_ref or not location_ref:
        return []
    try:
        owner_index = planner.read("state/index/owner-index.json")
    except (KeyError, FileNotFoundError):
        return []
    owners = owner_index.get("owners") if isinstance(owner_index, Mapping) else None
    if not isinstance(owners, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for ref, path in sorted(owners.items()):
        if not isinstance(ref, str) or not ref.startswith("formation_") or ref in excluded or not isinstance(path, str):
            continue
        raw = planner.read(path)
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("administrative_owner", "")) != target_state_ref:
            continue
        if str(raw.get("location_ref", "")) != location_ref:
            continue
        personnel = max(0, int(raw.get("personnel", 0) or 0))
        if personnel <= 0 or str(raw.get("status", "")) == "destroyed":
            continue
        low, high = _estimate_range(personnel)
        commander_ref, commander_name = _formation_commander(planner, ref, raw)
        rows.append({
            "formation_ref": ref,
            "name": str(raw.get("name") or ref),
            "location_ref": location_ref,
            "location_name": _location_name(locations, location_ref),
            "estimated_strength_low": low,
            "estimated_strength_high": high,
            "commander_ref": commander_ref,
            "commander_name": commander_name,
            "confidence_milli": 900,
            "intelligence_basis": "confirmed_physical_contact",
        })
    return rows


def _theater_enemy_formations(
    planner: Any,
    *,
    target_state_ref: str | None,
    destination_ref: str | None,
    already: set[str],
    locations: Mapping[str, Mapping[str, Any]],
    max_hours: int = 48,
) -> list[dict[str, Any]]:
    if not target_state_ref or not destination_ref:
        return []
    state_key = target_state_ref.removeprefix("state_")
    owner_index = planner.read("state/index/owner-index.json")
    owners = owner_index.get("owners") if isinstance(owner_index, Mapping) else None
    if not isinstance(owners, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for ref, path in sorted(owners.items()):
        if not isinstance(ref, str) or not ref.startswith("formation_") or ref in already or not isinstance(path, str):
            continue
        raw = planner.read(path)
        if not isinstance(raw, Mapping) or str(raw.get("administrative_owner", "")) != target_state_ref:
            continue
        personnel = max(0, int(raw.get("personnel", 0) or 0))
        if personnel <= 0:
            continue
        location_ref = str(raw.get("location_ref", ""))
        if not location_ref:
            continue
        loc = locations.get(location_ref)
        if isinstance(loc, Mapping) and str(loc.get("state", "")) not in {state_key, ""}:
            continue
        try:
            route = shortest_path(planner.read, location_ref, destination_ref, modes=("formation", "foot", "horse"))
        except ValueError:
            continue
        hours = int(route.get("duration_hours", 10**9))
        if hours > max_hours:
            continue
        commander_ref, commander_name = _formation_commander(planner, ref, raw)
        rows.append({
            "formation_ref": ref,
            "name": str(raw.get("name") or ref),
            "personnel": personnel,
            "location_ref": location_ref,
            "location_name": _location_name(locations, location_ref),
            "commander_ref": commander_ref,
            "commander_name": commander_name,
            "hours_to_operational_area": hours,
            "intelligence_basis": "theater_reinforcement_potential",
        })
    return rows


def _estimate_range(exact_strength: int) -> tuple[int, int]:
    if exact_strength <= 0:
        return 0, 0
    step = 1000 if exact_strength >= 5000 else 500
    low = max(step, int(math.floor((exact_strength * 0.78) / step) * step))
    high = int(math.ceil((exact_strength * 1.28) / step) * step)
    return (low, high if high > low else low + step)


def build_campaign_dossier(planner: Any, operation_ref: str) -> dict[str, Any]:
    """Build one current dossier from exact owners without persisting a cache."""
    _path, operation = _load_operation(planner, operation_ref)
    locations = _location_rows(planner)
    arc_ref = campaign_arc_ref(operation)
    friendly_state = _operation_state(planner, operation)
    target_state = _target_state(operation, friendly_state)
    own = _snapshot_operation(planner, operation_ref, operation, locations)
    same_arc = _campaign_operation_snapshots(
        planner, operation_ref=operation_ref, operation=operation, arc_ref=arc_ref, locations=locations
    ) if arc_ref else [own]
    friendly = [row for row in same_arc if row.get("owner_state_ref") == friendly_state]
    opposing = [row for row in same_arc if target_state and row.get("owner_state_ref") == target_state]
    if not any(row.get("operation_ref") == operation_ref for row in friendly):
        friendly.append(own)

    origin = _origin_location(own, operation)
    area = _operational_area(planner, origin, friendly_state, target_state, locations)
    opposing_refs = {str(ref) for ref in operation.get("opposing_formation_refs", []) if isinstance(ref, str) and ref}
    confirmed_location = str(operation.get("contact_location_ref") or operation.get("location_ref") or "")
    confirmed_contacts = _confirmed_hostile_contacts(
        planner, target_state_ref=target_state, location_ref=confirmed_location or None,
        excluded={str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str) and ref} - opposing_refs,
        locations=locations,
    )
    confirmed_refs = {str(row.get("formation_ref")) for row in confirmed_contacts if row.get("formation_ref")}
    enemy_campaign_refs = {
        str(form.get("formation_ref"))
        for row in opposing
        for form in row.get("formations", []) if isinstance(form, Mapping) and form.get("formation_ref")
    }
    nearby = _theater_enemy_formations(
        planner,
        target_state_ref=target_state,
        destination_ref=str(area.get("strategic_target_ref") or area.get("destination_ref")) if isinstance(area, Mapping) else None,
        already=enemy_campaign_refs | confirmed_refs,
        locations=locations,
    )
    enemy_forms = [copy.deepcopy(dict(row)) for row in confirmed_contacts]
    enemy_forms.extend(copy.deepcopy(dict(form)) for row in opposing for form in row.get("formations", []) if isinstance(form, Mapping))
    for form in enemy_forms:
        if str(form.get("intelligence_basis", "")) != "confirmed_physical_contact":
            form["intelligence_basis"] = "campaign_association"
    enemy_forms.extend(nearby)
    exact_enemy_strength = sum(max(0, int(row.get("personnel", 0) or 0)) for row in enemy_forms)
    low, high = _estimate_range(exact_enemy_strength)
    commander_rows: dict[str, dict[str, Any]] = {}
    for row in enemy_forms:
        ref, name = row.get("commander_ref"), row.get("commander_name")
        if not isinstance(ref, str) or not ref or not isinstance(name, str) or not name:
            continue
        basis = str(row.get("intelligence_basis", ""))
        confidence = 760 if basis == "campaign_association" else 620
        prior = commander_rows.get(ref)
        if prior is None or confidence > int(prior.get("confidence_milli", 0)):
            commander_rows[ref] = {"person_ref": ref, "name": name, "confidence_milli": confidence, "basis": basis}

    explicit_commander = None
    explicit_coordinator = None
    for row in same_arc:
        try:
            _p, op = _load_operation(planner, str(row.get("operation_ref")))
        except ValueError:
            continue
        if explicit_commander is None:
            for commander_key in ("campaign_commander_ref", "supreme_commander_ref"):
                commander_ref = op.get(commander_key)
                if isinstance(commander_ref, str) and commander_ref:
                    explicit_commander = str(commander_ref)
                    break
        if explicit_coordinator is None and isinstance(op.get("coordination_authority_ref"), str) and op.get("coordination_authority_ref"):
            explicit_coordinator = str(op["coordination_authority_ref"])
    if explicit_coordinator is None and friendly_state == "state_qin":
        explicit_coordinator = _QIN_BUREAU_REF

    march_planning = build_march_planning_baseline(
        planner, friendly_participants=friendly, operational_area=area
    )
    friendly.sort(key=lambda row: (-int(row.get("strength", 0)), str(row.get("operation_ref", ""))))
    return {
        "operation_ref": operation_ref,
        "arc_ref": arc_ref,
        "friendly_state_ref": friendly_state,
        "target_state_ref": target_state,
        "objective": str(_latest_order(operation).get("objective") or operation.get("objective") or ""),
        "own": own,
        "friendly_participants": friendly,
        "other_friendly_participants": [row for row in friendly if row.get("operation_ref") != operation_ref],
        "friendly_total_strength": sum(int(row.get("strength", 0)) for row in friendly),
        "campaign_commander_ref": explicit_commander,
        "campaign_commander_name": _person_name(planner, explicit_commander),
        "coordination_authority_ref": explicit_coordinator,
        "operational_area": area,
        "march_planning": march_planning,
        "enemy_intelligence": {
            "estimated_strength_low": low,
            "estimated_strength_high": high,
            "reported_formation_count": len(enemy_forms),
            "reported_commanders": sorted(commander_rows.values(), key=lambda row: (-int(row["confidence_milli"]), row["name"])),
            "confidence_milli": 900 if confirmed_contacts else (700 if enemy_forms else 350),
            "basis": "Qin operational intelligence synthesis from campaign activity and forces able to reach the selected theater within roughly two days",
            "contact_status": (
                f"confirmed enemy contact at {_location_name(locations, confirmed_location)}"
                if confirmed_contacts else ("no confirmed battle contact" if enemy_forms else "no confirmed opposing field formation")
            ),
            "confirmed_contact": {
                "location_ref": confirmed_location or None,
                "location_name": _location_name(locations, confirmed_location) if confirmed_location else None,
                "formation_count": len(confirmed_contacts),
                "targetable_formations": [
                    {
                        "formation_ref": row.get("formation_ref"),
                        "name": row.get("name"),
                        "estimated_strength_low": row.get("estimated_strength_low"),
                        "estimated_strength_high": row.get("estimated_strength_high"),
                        "commander_ref": row.get("commander_ref"),
                        "commander_name": row.get("commander_name"),
                        "confidence_milli": row.get("confidence_milli"),
                    }
                    for row in confirmed_contacts
                ],
            } if confirmed_contacts else None,
        },
    }


def safe_campaign_context(dossier: Mapping[str, Any]) -> dict[str, Any]:
    own = dossier.get("own") if isinstance(dossier.get("own"), Mapping) else {}
    friendlies = []
    for row in dossier.get("other_friendly_participants", []) if isinstance(dossier.get("other_friendly_participants"), list) else []:
        if not isinstance(row, Mapping):
            continue
        friendlies.append({
            "operation_ref": row.get("operation_ref"), "objective": row.get("objective"),
            "strength": row.get("strength"), "formation_count": row.get("formation_count"),
            "location_refs": list(row.get("location_refs", [])), "commanders": copy.deepcopy(row.get("commanders", [])),
        })
    enemy = dossier.get("enemy_intelligence") if isinstance(dossier.get("enemy_intelligence"), Mapping) else {}
    area = dossier.get("operational_area") if isinstance(dossier.get("operational_area"), Mapping) else None
    return {
        "arc_ref": dossier.get("arc_ref"), "target_state_ref": dossier.get("target_state_ref"), "objective": dossier.get("objective"),
        "own_strength": own.get("strength"), "own_assigned_strength": own.get("assigned_strength"), "own_auxiliary_strength": own.get("auxiliary_strength"),
        "own_location_refs": list(own.get("location_refs", [])) if isinstance(own, Mapping) else [],
        "friendly_total_strength": dossier.get("friendly_total_strength"), "other_friendly_participants": friendlies,
        "campaign_commander_ref": dossier.get("campaign_commander_ref"), "campaign_commander_name": dossier.get("campaign_commander_name"),
        "coordination_authority_ref": dossier.get("coordination_authority_ref"),
        "operational_area": copy.deepcopy(dict(area)) if isinstance(area, Mapping) else None,
        "march_planning": copy.deepcopy(dict(dossier.get("march_planning"))) if isinstance(dossier.get("march_planning"), Mapping) else None,
        "enemy_intelligence": {
            "estimated_strength_low": enemy.get("estimated_strength_low"), "estimated_strength_high": enemy.get("estimated_strength_high"),
            "reported_formation_count": enemy.get("reported_formation_count"), "reported_commanders": copy.deepcopy(enemy.get("reported_commanders", [])),
            "confidence_milli": enemy.get("confidence_milli"), "basis": enemy.get("basis"), "contact_status": enemy.get("contact_status"),
            "confirmed_contact": copy.deepcopy(enemy.get("confirmed_contact")),
        },
    }


def render_campaign_briefing(planner: Any, dossier: Mapping[str, Any], mission_packet: Mapping[str, Any] | None = None) -> str:
    locations = _location_rows(planner)
    own = dossier.get("own") if isinstance(dossier.get("own"), Mapping) else {}
    own_locs = [_location_name(locations, ref) for ref in own.get("location_refs", []) if isinstance(ref, str)]
    friendly_parts: list[str] = []
    for row in dossier.get("other_friendly_participants", []) if isinstance(dossier.get("other_friendly_participants"), list) else []:
        if not isinstance(row, Mapping):
            continue
        commanders = row.get("commanders") if isinstance(row.get("commanders"), list) else []
        commander_text = ", ".join(str(x.get("name")) for x in commanders if isinstance(x, Mapping) and x.get("name")) or "command not named in the current operation"
        loc_text = ", ".join(_location_name(locations, ref) for ref in row.get("location_refs", []) if isinstance(ref, str)) or "location not established"
        friendly_parts.append(f"{int(row.get('strength', 0)):,} troops in {int(row.get('formation_count', 0))} formation(s), under {commander_text}, at {loc_text}, task: {str(row.get('objective') or 'campaign support')}")
    enemy = dossier.get("enemy_intelligence") if isinstance(dossier.get("enemy_intelligence"), Mapping) else {}
    low, high = int(enemy.get("estimated_strength_low", 0) or 0), int(enemy.get("estimated_strength_high", 0) or 0)
    enemy_strength_text = "no confirmed opposing field strength" if high <= 0 else f"an official estimate of roughly {low:,}-{high:,} troops able to influence the theater"
    enemy_commanders = ", ".join(str(x.get("name")) for x in enemy.get("reported_commanders", []) if isinstance(x, Mapping) and x.get("name")) or "none confidently identified"
    area = dossier.get("operational_area") if isinstance(dossier.get("operational_area"), Mapping) else {}
    area_text = str(area.get("destination_name") or area.get("destination_ref") or "not yet fixed")
    strategic_target_text = str(area.get("strategic_target_name") or area.get("strategic_target_ref") or area_text)
    staging_completed = (
        isinstance(mission_packet, Mapping)
        and str(mission_packet.get("phase_status", "")) == "completed"
        and not bool(mission_packet.get("hostile_entry_authorized"))
    )
    if area and not bool(area.get("hostile_entry_authorized")):
        if staging_completed:
            entry_text = f" The field command has completed its lawful staging at {area_text}; {strategic_target_text} remains the strategic target, but Qin has not yet authorized entry into Wei territory."
        else:
            entry_text = f" Immediate lawful staging is {area_text}; hostile entry is not yet authorized, so {strategic_target_text} remains the strategic target rather than the current march destination."
    else:
        entry_text = f" Qin has authorized movement into the target state; the field command may now advance toward {strategic_target_text}."
    auxiliary_strength = int(own.get("auxiliary_strength", 0) or 0)
    assigned_strength = int(own.get("assigned_strength", int(own.get("strength", 0) or 0) - auxiliary_strength) or 0)
    ownership_text = (
        f" Of these, {assigned_strength:,} are Qin-assigned troops and {auxiliary_strength:,} are House or retinue troops accompanying under Tang Wei's own authority."
        if auxiliary_strength > 0 else ""
    )
    order_text = ""
    if isinstance(mission_packet, Mapping):
        dest = mission_packet.get("destination_name") or mission_packet.get("destination_ref")
        rendezvous = mission_packet.get("rendezvous_name") or mission_packet.get("rendezvous_location_ref")
        entry_authorized = bool(mission_packet.get("hostile_entry_authorized"))
        if str(mission_packet.get("phase_status", "")) == "completed" and not entry_authorized:
            completed_place = dest or rendezvous
            order_text = (
                f" The Bureau's standing orders record concentration at {completed_place} as complete. "
                "Further advance into Wei territory awaits new lawful entry authority."
            )
        elif dest == rendezvous and not entry_authorized:
            order_text = (
                f" The Bureau's written orders require the field command to complete its concentration at {rendezvous} and report readiness there. "
                "These instructions do not authorize crossing into Wei territory."
            )
        elif entry_authorized:
            order_text = (
                f" The Bureau's written orders direct the field command to concentrate and report at {rendezvous}, then march toward {dest} when Tang Wei gives the order."
            )
        else:
            order_text = (
                f" The Bureau's written orders require concentration and reporting at {rendezvous}. {dest} remains beyond the present movement authority."
            )
    return (
        f"Qin Military Bureau briefing. Tang Wei's field command numbers {int(own.get('strength', 0)):,} troops in {int(own.get('formation_count', 0))} formation(s), currently at {', '.join(own_locs) or 'an unestablished location'}.{ownership_text} "
        f"Other Qin forces on the campaign roster: {'; '.join(friendly_parts) if friendly_parts else 'none presently listed'}. "
        f"Combined Qin strength on the current campaign roster is {int(dossier.get('friendly_total_strength', 0) or 0):,}. "
        f"The staff designate {area_text} as the present operational area.{entry_text} Intelligence estimate: {enemy_strength_text}; reported opposing commanders: {enemy_commanders}; {enemy.get('contact_status', 'contact status uncertain')}. "
        f"These are staff estimates rather than confirmed enemy counts.{order_text}"
    )[:4000]


def ensure_actionable_mission_packet(planner: Any, operation_ref: str, dossier: Mapping[str, Any], *, at: str) -> dict[str, Any] | None:
    path, operation = _load_operation(planner, operation_ref)
    order_ref = str(operation.get("last_operational_order_ref", ""))
    orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    order_index = None
    for i in range(len(orders) - 1, -1, -1):
        row = orders[i]
        if not isinstance(row, Mapping):
            continue
        if order_ref and str(row.get("order_ref", "")) != order_ref:
            continue
        order_index = i
        break
    if order_index is None:
        return None

    order = copy.deepcopy(dict(orders[order_index]))
    area = dossier.get("operational_area") if isinstance(dossier.get("operational_area"), Mapping) else None
    destination_ref = area.get("destination_ref") if isinstance(area, Mapping) else None
    if not isinstance(destination_ref, str) or not destination_ref:
        return None

    own = dossier.get("own") if isinstance(dossier.get("own"), Mapping) else {}
    own_locations = [str(x) for x in own.get("location_refs", []) if isinstance(x, str)]
    rendezvous_ref = own_locations[0] if len(own_locations) == 1 else str(operation.get("location_ref") or "")
    if not rendezvous_ref:
        return None

    locations = _location_rows(planner)
    enemy = dossier.get("enemy_intelligence") if isinstance(dossier.get("enemy_intelligence"), Mapping) else {}
    entry_authorized = bool(area.get("hostile_entry_authorized")) if isinstance(area, Mapping) else False
    current_friendlies = [
        str(x.get("operation_ref"))
        for x in dossier.get("other_friendly_participants", [])
        if isinstance(x, Mapping) and x.get("operation_ref")
    ]
    enemy_estimate = {
        "strength_low": int(enemy.get("estimated_strength_low", 0) or 0),
        "strength_high": int(enemy.get("estimated_strength_high", 0) or 0),
        "confidence_milli": int(enemy.get("confidence_milli", 0) or 0),
        "contact_status": enemy.get("contact_status"),
    }
    existing_packet = order.get("mission_packet") if isinstance(order.get("mission_packet"), Mapping) else None

    # Refreshing a briefing must not reopen a staging phase that the formation
    # already completed.  The completed order remains authoritative until Qin
    # supplies a new lawful basis to cross into the hostile state.
    staging_already_completed = (
        not entry_authorized
        and isinstance(existing_packet, Mapping)
        and str(existing_packet.get("phase_status", "")) == "completed"
        and str(order.get("actionability_status", "")) == "completed"
        and str(order.get("status", "")) == "staged_awaiting_entry_authority"
    )
    if staging_already_completed:
        packet = copy.deepcopy(dict(existing_packet))
        packet.update({
            "mission_phase": "campaign_muster_and_staging",
            "phase_status": "completed",
            "destination_ref": destination_ref,
            "destination_name": _location_name(locations, destination_ref),
            "strategic_target_ref": area.get("strategic_target_ref") if isinstance(area, Mapping) else destination_ref,
            "strategic_target_name": area.get("strategic_target_name") if isinstance(area, Mapping) else _location_name(locations, destination_ref),
            "hostile_entry_authorized": False,
            "entry_status": area.get("entry_status") if isinstance(area, Mapping) else None,
            "coordination_authority_ref": dossier.get("coordination_authority_ref") or _QIN_BUREAU_REF,
            "friendly_participant_operation_refs": current_friendlies,
            "enemy_estimate": enemy_estimate,
            "agency_rule": "These Qin instructions establish the lawful staging and coordination requirement but do not move Tang Wei, commandeer privately owned auxiliaries, commit him to battle, or choose his tactics.",
        })
        packet.setdefault("actual_arrival_ref", destination_ref)
        if operation.get("last_phase_completed_at"):
            packet.setdefault("completed_at", operation.get("last_phase_completed_at"))
        order["mission_packet"] = packet
        order["status"] = "staged_awaiting_entry_authority"
        order["actionability_status"] = "completed"
        orders[order_index] = order
        operation["operational_orders"] = orders
        operation["order_status"] = "awaiting_entry_authority"
        operation["campaign_phase"] = "awaiting_entry_authority"
        operation["entry_status"] = area.get("entry_status") if isinstance(area, Mapping) else operation.get("entry_status")
        operation["operational_area_ref"] = destination_ref
        planner.put(path, operation)
        return copy.deepcopy(packet)

    if str(order.get("actionability_status", "")) == "actionable" and isinstance(existing_packet, Mapping):
        current_authorized = entry_authorized
        packet_authorized = bool(existing_packet.get("hostile_entry_authorized"))
        enemy_then = existing_packet.get("enemy_estimate") if isinstance(existing_packet.get("enemy_estimate"), Mapping) else {}
        packet_is_current = (
            current_authorized == packet_authorized
            and destination_ref == existing_packet.get("destination_ref")
            and current_friendlies == [str(x) for x in existing_packet.get("friendly_participant_operation_refs", []) if isinstance(x, str)]
            and enemy_estimate["strength_low"] == int(enemy_then.get("strength_low", 0) or 0)
            and enemy_estimate["strength_high"] == int(enemy_then.get("strength_high", 0) or 0)
            and enemy_estimate["confidence_milli"] == int(enemy_then.get("confidence_milli", 0) or 0)
            and enemy_estimate["contact_status"] == enemy_then.get("contact_status")
        )
        if packet_is_current:
            return copy.deepcopy(dict(existing_packet))

    mission_phase = "campaign_concentration_and_advance" if entry_authorized else "campaign_muster_and_staging"
    packet = {
        "mission_phase": mission_phase,
        "phase_status": "ready_for_commander_execution",
        "issued_at": at,
        "rendezvous_location_ref": rendezvous_ref,
        "rendezvous_name": _location_name(locations, rendezvous_ref),
        "destination_ref": destination_ref,
        "destination_name": _location_name(locations, destination_ref),
        "strategic_target_ref": area.get("strategic_target_ref") if isinstance(area, Mapping) else destination_ref,
        "strategic_target_name": area.get("strategic_target_name") if isinstance(area, Mapping) else _location_name(locations, destination_ref),
        "hostile_entry_authorized": entry_authorized,
        "entry_status": area.get("entry_status") if isinstance(area, Mapping) else None,
        "success_condition": (
            "the current field command physically assembles at the lawful staging area and completes deployment"
            if not entry_authorized else
            "the current field command physically reaches the authorized operational area and completes deployment"
        ),
        "coordination_authority_ref": dossier.get("coordination_authority_ref") or _QIN_BUREAU_REF,
        "friendly_participant_operation_refs": current_friendlies,
        "enemy_estimate": enemy_estimate,
        "next_phase_trigger": (
            "Arrival at staging causes a field-command situation report. Crossing into the target state still requires lawful war/entry authority and does not happen automatically."
            if not entry_authorized else
            "Arrival at the destination causes a field-command situation report; it does not automatically start a battle or choose Tang Wei's next maneuver."
        ),
        "agency_rule": "These Qin instructions establish the immediate lawful destination and coordination requirement but do not move Tang Wei, commandeer privately owned auxiliaries, commit him to battle, or choose his tactics.",
    }
    order["mission_packet"] = packet
    order["status"] = "staff_briefed_awaiting_commander_execution"
    order["actionability_status"] = "actionable"
    order["staff_briefed_at"] = at
    orders[order_index] = order
    operation["operational_orders"] = orders
    operation["order_status"] = "staff_briefed_awaiting_commander_execution"
    operation["campaign_phase"] = "campaign_concentration"
    planner.put(path, operation)
    return copy.deepcopy(packet)

def _persist_information(
    planner: Any,
    *,
    info_ref: str,
    subject_ref: str,
    fact: str,
    epistemic_kind: str,
    confidence_milli: int,
    provenance: str,
    evidence_refs: list[str],
    classification: str,
    location_ref: str | None,
    at: str,
    campaign_context: Mapping[str, Any] | None = None,
) -> str:
    path = f"state/information/{info_ref}.json"
    existing = planner.read_optional(path)
    if isinstance(existing, Mapping):
        return info_ref
    doc: dict[str, Any] = {
        "schema": "sword-information", "owner_id": info_ref, "information_ref": info_ref,
        "subject_ref": subject_ref, "fact": fact, "claim": fact, "epistemic_kind": epistemic_kind,
        "confidence_milli": max(0, min(1000, int(confidence_milli))),
        "confidence": f"{max(0, min(1000, int(confidence_milli))) / 1000:.3f}",
        "provenance": provenance, "evidence_refs": sorted(set(evidence_refs)), "classification": classification,
        "location_ref": location_ref, "discoverability_milli": 1000, "investigation_discoverable": False,
        "origin_authority": "runtime_established", "world_truth_authority": False,
        "claim_status": "runtime_established_estimate", "knowers": [_PLAYER_REF],
        "holder_states": {_PLAYER_REF: {"epistemic_kind": epistemic_kind, "confidence_milli": max(0, min(1000, int(confidence_milli))), "source_ref": subject_ref, "channel": provenance, "learned_at": at}},
        "deliveries": [], "created_at": at,
    }
    if isinstance(campaign_context, Mapping):
        doc["campaign_context"] = copy.deepcopy(dict(campaign_context))
    planner.put(path, doc)
    info_index = copy.deepcopy(planner.read(_INFO_INDEX))
    info_index.setdefault("claims", {})[info_ref] = path
    holder_refs = info_index.setdefault("by_holder", {}).setdefault(_PLAYER_REF, [])
    if info_ref not in holder_refs:
        holder_refs.append(info_ref); holder_refs.sort()
    planner.put(_INFO_INDEX, info_index)
    subject_index = copy.deepcopy(planner.read_optional(_INFO_SUBJECT_INDEX) or {"schema": "sword-information-subject-index", "authority": False, "subjects": {}})
    refs = subject_index.setdefault("subjects", {}).setdefault(subject_ref, [])
    if info_ref not in refs:
        refs.append(info_ref); refs.sort()
    planner.put(_INFO_SUBJECT_INDEX, subject_index)
    try:
        planner._register_owner(info_ref, path)
    except AttributeError:
        pass
    return info_ref


def persist_campaign_briefing(planner: Any, *, dossier: Mapping[str, Any], summary: str, at: str) -> str:
    context = safe_campaign_context(dossier)
    fingerprint = hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    arc_ref = str(dossier.get("arc_ref") or dossier.get("operation_ref"))
    operation_ref = str(dossier.get("operation_ref"))
    info_ref = f"information.qin_campaign_briefing.{_digest(arc_ref, fingerprint)}"
    player = planner.read("state/player.json")
    persisted_ref = _persist_information(
        planner, info_ref=info_ref, subject_ref=arc_ref, fact=summary,
        epistemic_kind="official_military_briefing", confidence_milli=800,
        provenance="Qin Military Bureau operational briefing", evidence_refs=[operation_ref],
        classification="command_intelligence", location_ref=str(player.get("location", "")) or None,
        at=at, campaign_context=context,
    )
    # The operation owns which briefing is current for its actionable packet.
    # Information claims remain immutable historical knowledge, so timestamp/order
    # inference is insufficient when two materially different briefings are issued
    # at the same campaign instant during a deterministic reconciliation.
    try:
        operation_path, operation = _load_operation(planner, operation_ref)
    except (FileNotFoundError, KeyError, ValueError):
        return persisted_ref
    operation = copy.deepcopy(operation)
    operation["briefing_information_ref"] = persisted_ref
    planner.put(operation_path, operation)
    return persisted_ref


def persist_campaign_phase_report(
    planner: Any,
    *,
    operation_ref: str,
    arc_ref: str | None,
    phase: str,
    summary: str,
    campaign_context: Mapping[str, Any],
    at: str,
) -> str:
    fingerprint = hashlib.sha256(json.dumps({"phase": phase, "context": campaign_context}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    info_ref = f"information.campaign_phase.{_digest(operation_ref + '|' + phase, fingerprint)}"
    own_locs = campaign_context.get("own_location_refs") if isinstance(campaign_context.get("own_location_refs"), list) else []
    confidence = int((campaign_context.get("enemy_intelligence") or {}).get("confidence_milli", 700)) if isinstance(campaign_context, Mapping) else 700
    return _persist_information(
        planner, info_ref=info_ref, subject_ref=arc_ref or operation_ref, fact=summary,
        epistemic_kind="official_military_field_report", confidence_milli=confidence,
        provenance="field-command staff report", evidence_refs=[operation_ref], classification="command_intelligence",
        location_ref=str(own_locs[0]) if own_locs else None, at=at, campaign_context=campaign_context,
    )


def reconcile_campaign_arrival(
    planner: Any,
    operation_ref: str,
    *,
    destination_ref: str,
    at: str,
    unit_duties: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Complete an actionable concentration/advance phase after real army movement."""
    path, operation = _load_operation(planner, operation_ref)
    order_ref = str(operation.get("last_operational_order_ref", ""))
    orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    order_index = None
    for i in range(len(orders) - 1, -1, -1):
        row = orders[i]
        if not isinstance(row, Mapping):
            continue
        if order_ref and str(row.get("order_ref", "")) != order_ref:
            continue
        order_index = i; break
    if order_index is None:
        return None
    order = copy.deepcopy(dict(orders[order_index]))
    packet = order.get("mission_packet") if isinstance(order.get("mission_packet"), Mapping) else None
    if not isinstance(packet, Mapping) or str(packet.get("mission_phase", "")) not in {"campaign_concentration_and_advance", "campaign_muster_and_staging"}:
        return None
    if str(packet.get("destination_ref", "")) != destination_ref or str(packet.get("phase_status", "")) == "completed":
        return None
    opposing_existing = {str(ref) for ref in operation.get("opposing_formation_refs", []) if isinstance(ref, str) and ref}
    participants = [str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str) and ref and ref not in opposing_existing]
    if not participants:
        participants = [str(ref) for ref in order.get("applies_to_formation_refs", []) if isinstance(ref, str) and ref]
    for ref in participants:
        formation = _formation(planner, ref)
        if not isinstance(formation, Mapping) or str(formation.get("location_ref", "")) != destination_ref:
            return None

    packet = copy.deepcopy(dict(packet)); packet["phase_status"] = "completed"; packet["completed_at"] = at; packet["actual_arrival_ref"] = destination_ref
    staged_only = str(packet.get("mission_phase", "")) == "campaign_muster_and_staging" and not bool(packet.get("hostile_entry_authorized"))

    # Once a lawful hostile advance physically reaches its destination, exact
    # co-located enemy formations become real operation participants. This is
    # contact proof, not ownership transfer and not an automatic battle command.
    contact_rows: list[dict[str, Any]] = []
    if not staged_only:
        locations = _location_rows(planner)
        friendly_state = _operation_state(planner, operation)
        target_state = _target_state(operation, friendly_state)
        contact_rows = _confirmed_hostile_contacts(
            planner, target_state_ref=target_state, location_ref=destination_ref,
            excluded=set(participants), locations=locations,
        )
        if contact_rows:
            contact_refs = [str(row["formation_ref"]) for row in contact_rows if row.get("formation_ref")]
            existing_refs = [str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str) and ref]
            operation["formation_refs"] = list(dict.fromkeys(existing_refs + contact_refs))
            operation["opposing_formation_refs"] = list(dict.fromkeys([*sorted(opposing_existing), *contact_refs]))
            operation["contact_location_ref"] = destination_ref
            operation["contact_established_at"] = at
            operation["contact_basis"] = "exact_co_location_after_lawful_campaign_advance"
            operation["status"] = "engaged"
    contact_established = bool(contact_rows)
    order["mission_packet"] = packet
    order["status"] = (
        "staged_awaiting_entry_authority" if staged_only else
        ("enemy_contact_awaiting_commander_decision" if contact_established else "phase_complete_awaiting_follow_on_direction")
    )
    order["actionability_status"] = "completed"
    order["follow_on_requirement"] = (
        "The field army is assembled at lawful friendly staging. Hostile entry into the target state requires a new exact war/entry authority or other lawful basis; the staff may continue reconnaissance and reporting without crossing the border or inventing tactics."
        if staged_only else
        (
            "Confirmed hostile formations share the operational location and are now exact targetable participants in this saved operation. Tang Wei must still choose whether to attack, maneuver, hold, reconnoiter, negotiate, or otherwise respond; contact does not auto-start battle."
            if contact_established else
            "The concentration/advance phase is complete. Further strategic movement or battle intent requires a new exact order, confirmed contact, or Tang Wei's own lawful initiative; routine staff screening and reporting may continue without inventing tactics."
        )
    )
    orders[order_index] = order
    operation["operational_orders"] = orders
    operation["order_status"] = (
        "awaiting_entry_authority" if staged_only else
        ("enemy_contact_awaiting_commander_decision" if contact_established else "awaiting_follow_on_direction")
    )
    operation["campaign_phase"] = (
        "awaiting_entry_authority" if staged_only else
        ("enemy_contact" if contact_established else "operational_area_arrival")
    )
    operation["location_ref"] = destination_ref
    operation["last_phase_completed_at"] = at
    planner.put(path, operation)

    dossier = build_campaign_dossier(planner, operation_ref)
    context = safe_campaign_context(dossier)
    context["phase"] = "awaiting_entry_authority" if staged_only else ("enemy_contact" if contact_established else "operational_area_arrival")
    context["completed_mission_phase"] = str(packet.get("mission_phase", ""))
    context["next_phase_requirement"] = order["follow_on_requirement"]
    forward_rows = [row for row in (unit_duties or []) if isinstance(row, Mapping) and str(row.get("duty_id", "")) == "forward_security"]
    forward_names: list[str] = []
    for row in forward_rows:
        formation = _formation(planner, str(row.get("formation_ref", "")))
        if isinstance(formation, Mapping):
            forward_names.append(str(formation.get("name") or row.get("formation_ref")))
    context["forward_security_units"] = sorted(set(forward_names))

    locations = _location_rows(planner)
    enemy = context.get("enemy_intelligence") if isinstance(context.get("enemy_intelligence"), Mapping) else {}
    low, high = int(enemy.get("estimated_strength_low", 0) or 0), int(enemy.get("estimated_strength_high", 0) or 0)
    strength_text = f"roughly {low:,}-{high:,} troops able to influence the theater" if high else "no reliable field-strength estimate yet"
    screen_text = ", ".join(context["forward_security_units"]) or "the army's assigned forward-security element"
    phase = "awaiting_entry_authority" if staged_only else ("enemy_contact" if contact_established else "operational_area_arrival")
    strategic_target = packet.get("strategic_target_name") or packet.get("strategic_target_ref") or "the target theater"
    if staged_only:
        summary = (
            f"Field-command staging report: Tang Wei's field army has assembled at {_location_name(locations, destination_ref)} on lawful friendly ground. "
            f"The strategic target remains {strategic_target}, but hostile entry is not yet authorized. March security placed {screen_text} on forward security/reconnaissance. "
            f"Current staff intelligence remains {strength_text}; {enemy.get('contact_status', 'contact not established')}. The army will not cross the border or begin battle merely because staging is complete."
        )
    elif contact_established:
        targets = (enemy.get("confirmed_contact") or {}).get("targetable_formations", []) if isinstance(enemy.get("confirmed_contact"), Mapping) else []
        names = ", ".join(str(row.get("name")) for row in targets if isinstance(row, Mapping) and row.get("name")) or "hostile formations"
        summary = (
            f"Field-command contact report: Tang Wei's field army has reached {_location_name(locations, destination_ref)} and completed deployment. "
            f"{names} are in confirmed physical contact at the same operational location. March security placed {screen_text} forward. "
            f"Staff estimate is {strength_text}. The hostile formations are now targetable participants in the saved operation, but no battle, pursuit, negotiation, or maneuver is chosen automatically."
        )
    else:
        summary = (
            f"Field-command arrival report: Tang Wei's field army has reached {_location_name(locations, destination_ref)} and completed the current concentration/advance phase. "
            f"March security placed {screen_text} on forward security/reconnaissance. Current staff intelligence remains {strength_text}; "
            f"{enemy.get('contact_status', 'contact not established')}. The army has not been committed to a battle or further advance by this report. "
            "The command remains ready for a follow-on order, confirmed enemy contact, or Tang Wei's own lawful reconnaissance and maneuver decisions."
        )
    summary = summary[:4000]
    info_ref = persist_campaign_phase_report(planner, operation_ref=operation_ref, arc_ref=campaign_arc_ref(operation), phase=phase, summary=summary, campaign_context=context, at=at)
    operation = copy.deepcopy(planner.read(path)); operation["last_phase_information_ref"] = info_ref; planner.put(path, operation)
    return {"operation_ref": operation_ref, "phase": phase, "information_ref": info_ref, "summary": summary, "campaign_context": context}


def latest_campaign_briefing_ref(store: Any, operation_ref: str, arc_ref: str | None) -> str | None:
    try:
        index = store.read_json(_INFO_INDEX); subject_index = store.read_json(_INFO_SUBJECT_INDEX)
    except (FileNotFoundError, KeyError):
        return None
    claims = index.get("claims") if isinstance(index, Mapping) else None
    subjects = subject_index.get("subjects") if isinstance(subject_index, Mapping) else None
    if not isinstance(claims, Mapping) or not isinstance(subjects, Mapping):
        return None
    refs: list[str] = []
    for subject in (operation_ref, arc_ref):
        if not isinstance(subject, str) or not subject:
            continue
        for ref in subjects.get(subject, []) if isinstance(subjects.get(subject), list) else []:
            if isinstance(ref, str) and ref not in refs:
                refs.append(ref)
    newest: tuple[str, str] | None = None
    for ref in refs:
        path = claims.get(ref)
        if not isinstance(path, str):
            continue
        try:
            claim = store.read_json(path)
        except FileNotFoundError:
            continue
        if not isinstance(claim, Mapping) or _PLAYER_REF not in claim.get("knowers", []):
            continue
        if str(claim.get("epistemic_kind", "")) != "official_military_briefing":
            continue
        candidate = (str(claim.get("created_at", "")), ref)
        if newest is None or candidate > newest:
            newest = candidate
    return newest[1] if newest is not None else None


__all__ = [
    "build_campaign_dossier", "campaign_arc_ref", "ensure_actionable_mission_packet", "latest_campaign_briefing_ref",
    "persist_campaign_briefing", "persist_campaign_phase_report", "reconcile_campaign_arrival", "render_campaign_briefing", "safe_campaign_context",
]
