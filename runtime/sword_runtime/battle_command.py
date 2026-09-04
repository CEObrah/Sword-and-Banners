"""Compact superior-command layer for operational battlefields.

The operational battlefield already owns geometry, assignments, redeployment,
reports and exact battle contact.  This module does not create another battle
simulation.  It groups already-conserved formations under their real command
people, chooses one lawful side commander from saved capability when the
operation has not named one, and records subordinate missions directly on the
battlefield owner.

A mission is an order/briefing, not an outcome.  It never moves formations,
resolves contact, grants knowledge of hidden enemy identity, or transfers troop
ownership.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.stat_access import merged_skill_map
from sword_runtime.commander_cognition import command_decision_policy
from sword_runtime.command_authority import strategist_refs
from sword_runtime.military_doctrine import apply_command_doctrine_policy, default_command_group_doctrine_ref
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.environment import daylight_window
from sword_runtime.military_supply import evaluate_military_supply
from sword_runtime.command_units import authoritative_group_ref_for_formation
from sword_runtime.operational_intent import operational_intent_contract

_PLAYER_REF = "char_tang_wei"
_COMMAND_SKILLS = (
    ("Strategy", 5),
    ("Formation Command", 5),
    ("Leadership", 3),
    ("Tactics", 2),
    ("Logistics", 1),
)


def _person(planner: Any, ref: str) -> Mapping[str, Any] | None:
    if not isinstance(ref, str) or not ref:
        return None
    try:
        row = planner.read(planner.owner_path(ref))
    except (FileNotFoundError, KeyError, ValueError):
        return None
    if not isinstance(row, Mapping) or row.get("schema") not in {"sab_character", "sword-materialized-person", "person-lite"}:
        return None
    return row


def _strategist_transmitter(planner: Any, group: Mapping[str, Any] | None) -> str | None:
    """Choose one explicit strategist who may transmit orders for this group.

    The strategist does not replace the commander's decision authority. The
    transmitted order remains bounded by this exact group's recursive subtree and
    normal battlefield communication latency.
    """
    if not isinstance(group, Mapping):
        return None
    for ref in strategist_refs(group):
        if _person(planner, ref) is not None:
            return ref
    return None


def _command_group_for_formation(planner: Any, formation_ref: str) -> Mapping[str, Any] | None:
    index = planner.read("state/cmd/command-groups/index.json")
    if not isinstance(index, Mapping):
        raise ValueError("battle command-group index is invalid")
    _formation_path, formation = planner._load_formation(formation_ref)
    group_ref = authoritative_group_ref_for_formation(
        index,
        lambda ref: planner.read(f"state/cmd/command-groups/{ref}.json"),
        formation_ref,
        formation,
    )
    template = index.get("path_template") if isinstance(index, Mapping) else None
    if not isinstance(group_ref, str) or not group_ref or not isinstance(template, str):
        return None
    path = template.replace("{command_group_id}", group_ref).replace("{ref}", group_ref)
    row = planner.read(path)
    if not isinstance(row, Mapping):
        raise ValueError("battle command group is invalid")
    return row


def _command_group_by_ref(planner: Any, group_ref: str | None) -> Mapping[str, Any] | None:
    if not isinstance(group_ref, str) or not group_ref:
        return None
    row = planner.read(f"state/cmd/command-groups/{group_ref}.json")
    if not isinstance(row, Mapping):
        raise ValueError("battle command group is invalid")
    return row


def _highest_lawful_command_group_for_formation(
    planner: Any,
    formation_ref: str,
    *,
    operation: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    """Return the highest command node that is actually superior in this operation.

    Permanent army parentage and temporary operational superiority are separate
    authorities.  A formation in Ousen's organic army does not become a Mou Gou
    battlefield mission merely because Mou Gou is Ousen's permanent parent when
    the current operation detached only Ousen's army.  Conversely, an operation
    that explicitly deploys the Mou Gou parent command must keep its descendants
    grouped beneath Mou Gou rather than tasking every nested army as a peer.

    With no explicit operational root, keep the formation's primary command
    group.  When the operation identifies a command_group_ref (or an appointed
    campaign commander's own group), climb only as far as that exact ancestor.
    """
    group = _command_group_for_formation(planner, formation_ref)
    if not isinstance(group, Mapping):
        return None

    allowed_root_ref: str | None = None
    if isinstance(operation, Mapping):
        explicit_root = operation.get("command_group_ref")
        if isinstance(explicit_root, str) and explicit_root:
            allowed_root_ref = explicit_root
        else:
            campaign_commander = operation.get("campaign_commander_ref") or operation.get("supreme_commander_ref")
            campaign_group = _command_group_for_person(
                planner, campaign_commander if isinstance(campaign_commander, str) else None
            )
            campaign_group_ref = campaign_group.get("id") if isinstance(campaign_group, Mapping) else None
            if isinstance(campaign_group_ref, str) and campaign_group_ref:
                allowed_root_ref = campaign_group_ref

    if not allowed_root_ref:
        # Player-facing battle missions remain at the player's highest lawful
        # command node so a subordinate formation does not turn the player's own
        # army into an NPC-issued mission.  NPC organic parents are *not* inferred
        # as operational superiors without an explicit operation root.
        player_ref = getattr(planner, "PLAYER_ACTOR", None)
        current = group
        seen: set[str] = set()
        highest_player_group = group if group.get("commander_ref") == player_ref else None
        while isinstance(current, Mapping):
            current_ref = current.get("id")
            if isinstance(current_ref, str):
                if current_ref in seen:
                    break
                seen.add(current_ref)
            parent_ref = current.get("parent_command_group_ref")
            if not isinstance(parent_ref, str) or not parent_ref:
                break
            parent = _command_group_by_ref(planner, parent_ref)
            if not isinstance(parent, Mapping):
                break
            current = parent
            if current.get("commander_ref") == player_ref:
                highest_player_group = current
        return highest_player_group if isinstance(highest_player_group, Mapping) else group

    current = group
    seen: set[str] = set()
    while isinstance(current, Mapping):
        current_ref = current.get("id")
        if isinstance(current_ref, str):
            if current_ref == allowed_root_ref:
                return current
            if current_ref in seen:
                break
            seen.add(current_ref)
        parent_ref = current.get("parent_command_group_ref")
        if not isinstance(parent_ref, str) or not parent_ref:
            break
        current = _command_group_by_ref(planner, parent_ref)

    # The operation's explicit root is not an ancestor of this formation.  The
    # formation therefore remains under its own primary command instead of being
    # silently reparented for battle planning.
    return group


def _command_group_for_person(planner: Any, person_ref: str | None) -> Mapping[str, Any] | None:
    """Return one exact command group actually commanded by this person.

    Battle missions are issued to command recipients, not to doctrine buckets.
    Child formations may keep different local doctrines while the recipient's
    own command-group doctrine governs how that officer applies the mission.
    Person routing is authority:false, so every nominated group is revalidated
    against its exact ``commander_ref`` before use.
    """
    if not isinstance(person_ref, str) or not person_ref:
        return None
    try:
        index = planner.read("state/cmd/command-groups/index.json")
    except (FileNotFoundError, KeyError, ValueError):
        return None
    template = index.get("path_template") if isinstance(index, Mapping) else None
    if not isinstance(template, str):
        return None
    primary = index.get("primary_person_group") if isinstance(index, Mapping) else None
    routes = index.get("command_person_groups") if isinstance(index, Mapping) else None
    candidates: list[str] = []
    routed_primary = primary.get(person_ref) if isinstance(primary, Mapping) else None
    if isinstance(routed_primary, str) and routed_primary:
        candidates.append(routed_primary)
    if isinstance(routes, Mapping):
        for ref in routes.get(person_ref, []) if isinstance(routes.get(person_ref), list) else []:
            if isinstance(ref, str) and ref and ref not in candidates:
                candidates.append(ref)
    person = _person(planner, person_ref)
    assignment = person.get("command_assignment") if isinstance(person, Mapping) and isinstance(person.get("command_assignment"), Mapping) else {}
    saved_ref = assignment.get("command_group_ref") if isinstance(assignment, Mapping) else None
    if isinstance(saved_ref, str) and saved_ref and saved_ref not in candidates:
        candidates.append(saved_ref)
    for group_ref in candidates:
        path = template.replace("{command_group_id}", group_ref).replace("{ref}", group_ref)
        try:
            row = planner.read(path)
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if isinstance(row, Mapping) and str(row.get("commander_ref") or "") == person_ref:
            return row
    return None


def formation_command_person(planner: Any, formation_ref: str, formation: Mapping[str, Any]) -> str | None:
    """Return the exact person who actually commands this battlefield body.

    Player command authority outranks a state institutional placeholder.  A
    formation commander outranks command-group fallback.  State/House refs are
    authorities, not invented people, so they return no exact commander.
    """
    authority = formation.get("command_authority")
    if isinstance(authority, str) and _person(planner, authority) is not None:
        return authority
    commander = formation.get("commander_ref")
    if isinstance(commander, str) and commander:
        person = _person(planner, commander)
        if person is None:
            raise ValueError(f"formation commander_ref does not resolve to an exact person: {commander}")
        return commander
    group = _command_group_for_formation(planner, formation_ref)
    if isinstance(group, Mapping):
        commander = group.get("commander_ref")
        if isinstance(commander, str) and commander:
            person = _person(planner, commander)
            if person is None:
                raise ValueError(f"command-group commander_ref does not resolve to an exact person: {commander}")
            return commander
    return None


def _command_score(planner: Any, person_ref: str) -> float:
    person = _person(planner, person_ref)
    if not isinstance(person, Mapping):
        return 0.0
    skills = merged_skill_map(person)
    score = 0.0
    for skill, weight in _COMMAND_SKILLS:
        try:
            score += float(skills.get(skill, 0) or 0) * weight
        except (TypeError, ValueError):
            continue
    # Senior exact rank is a tie-breaker, not a replacement for competence.
    military_rank = person.get("military_rank") if isinstance(person.get("military_rank"), Mapping) else {}
    grade = str(military_rank.get("grade", ""))
    rank_hint = {
        "general": 40,
        "great_general": 60,
        "commander": 15,
        "captain": 5,
    }
    score += max((bonus for token, bonus in rank_hint.items() if token in grade.lower()), default=0)
    return score


def _sector_roles(battlefield: Mapping[str, Any]) -> tuple[list[str], str | None, str | None]:
    sectors = battlefield.get("sectors") if isinstance(battlefield.get("sectors"), Mapping) else {}
    frontline: list[tuple[int, int, str]] = []
    reserves: list[tuple[int, str]] = []
    command = None
    for ref, row in sectors.items():
        if not isinstance(ref, str) or not isinstance(row, Mapping):
            continue
        role = str(row.get("role", "")).lower()
        name = str(row.get("name", "")).lower()
        position = row.get("position") if isinstance(row.get("position"), Mapping) else {}
        y_units = int(position.get("y_units", 0) or 0)
        if role == "reserve" or "reserve" in name:
            # If a generated battlefield has more than one reserve region, the
            # closest one to the fighting line is the generic reserve anchor.
            # Exact assignments still retain whichever reserve sector they
            # actually occupy.
            reserves.append((-y_units, ref))
            continue
        if role == "command" or "command" in name or "headquarters" in name:
            command = ref
            continue
        frontage_slot = row.get("frontage_slot")
        if isinstance(frontage_slot, int) and not isinstance(frontage_slot, bool):
            # Generated geometry owns a real left-to-right frontage ordering.
            frontline.append((0, frontage_slot, ref))
            continue
        priority = 1
        if "center" in name or "forward" in name:
            priority = 0
        elif "left" in name:
            priority = 1
        elif "right" in name:
            priority = 2
        frontline.append((1, priority, ref))
    reserve = sorted(reserves)[0][1] if reserves else None
    return [ref for _kind, _priority, ref in sorted(frontline)], reserve, command


def _sector_mission_name(sector: Mapping[str, Any], order: str) -> str:
    name = str(sector.get("name", "sector"))
    lower = name.lower()
    objective = sector.get("operational_objective") if isinstance(sector.get("operational_objective"), Mapping) else {}
    objective_mission = str(objective.get("mission") or "").strip()
    if objective_mission:
        task = objective_mission
    elif "left" in lower:
        task = "secure the left wing, deny an enemy turning movement, and exploit only within superior-command constraints"
    elif "right" in lower:
        task = "secure the right wing, protect the army flank, and exploit only within superior-command constraints"
    elif "center" in lower or "forward" in lower:
        task = "contest the central frontage and achieve the army plan's local objective without abandoning adjacent support"
    elif "reserve" in lower:
        task = "remain a responsive reserve until committed by lawful command or immediate self-defense requires action"
    else:
        task = f"hold and contest {name} according to the army plan"
    if order == "attack" and objective_mission:
        return f"attack to {task}"
    if order == "attack":
        return task.replace("hold and contest", "attack and secure")
    return task


def _rebuild_sector_membership(planner: Any, battlefield: dict[str, Any]) -> None:
    sectors = battlefield.get("sectors")
    assignments = battlefield.get("assignments")
    if not isinstance(sectors, dict) or not isinstance(assignments, Mapping):
        raise ValueError("battlefield command planning requires assignments and sectors")
    for row in sectors.values():
        if isinstance(row, dict):
            row["formation_refs"] = []
    for formation_ref, assignment in assignments.items():
        if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping):
            continue
        for sector_ref in sectors:
            if planner._battlefield_assignment_sector_commitment_milli(assignment, str(sector_ref)) > 0:
                sectors[sector_ref].setdefault("formation_refs", []).append(formation_ref)
    for row in sectors.values():
        if isinstance(row, dict):
            row["formation_refs"] = sorted(set(str(ref) for ref in row.get("formation_refs", []) if isinstance(ref, str)))


def _initial_side_orders(planner: Any, operation: Mapping[str, Any], battlefield: Mapping[str, Any]) -> dict[str, str]:
    """Infer only the broad offensive/defensive posture from physical geography.

    A battlefield inside one side's home state makes that side the default defender
    and the opposing side the default attacker.  Ambiguous/neutral ground stays
    conservative rather than inventing an attacker.
    """
    sides = [str(ref) for ref in battlefield.get("side_refs", []) if isinstance(ref, str)]
    orders = {side: "hold" for side in sides}
    location_ref = str(battlefield.get("location_ref") or operation.get("location_ref") or "")
    location = planner._location_record(location_ref) if location_ref else {}
    home = str(location.get("state", "")) if isinstance(location, Mapping) else ""
    home_side = f"state_{home}" if home and not home.startswith("state_") else home
    if home_side in orders and len(sides) == 2:
        other = next(side for side in sides if side != home_side)
        orders[home_side] = "hold"
        orders[other] = "attack"
    return orders



def _bounded_ratio(value: Any, *, low: float = 0.0, high: float = 100.0, default: float = 75.0) -> float:
    try:
        raw = float(value)
    except (TypeError, ValueError):
        raw = default
    if high <= low:
        return 1.0
    return max(0.0, min(1.0, (raw - low) / (high - low)))


def _formation_operational_strength(planner: Any, formation_ref: str, formation: Mapping[str, Any], *, at: str) -> dict[str, Any]:
    personnel = max(0, int(formation.get("personnel", 0) or 0))
    readiness = 0.55 + 0.45 * _bounded_ratio(formation.get("readiness"), default=70)
    morale = 0.55 + 0.45 * _bounded_ratio(formation.get("morale"), default=70)
    cohesion = 0.55 + 0.45 * _bounded_ratio(formation.get("cohesion"), default=70)
    fatigue = max(0.38, 1.0 - min(100.0, max(0.0, float(formation.get("fatigue", 0) or 0))) / 125.0)
    # Supply is a real contributor to operational strength. Its evaluator already
    # handles legitimately absent optional ledgers. A programming/schema failure
    # here must fail the command review closed rather than silently granting a
    # neutral 1.0 supply factor.
    supply = evaluate_military_supply(planner, formation, at=at)
    supply_factor = max(0.45, min(1.05, float(supply.get("combat_factor", 1.0) or 1.0)))
    supply_condition = str(supply.get("condition", "unknown"))
    composition = formation.get("composition") if isinstance(formation.get("composition"), Mapping) else {}
    missile = sum(max(0, int(count or 0)) for role, count in composition.items() if any(token in str(role).lower() for token in ("bow", "crossbow", "archer", "missile")))
    missile_share = missile / max(1, personnel)
    logistics = formation.get("logistics") if isinstance(formation.get("logistics"), Mapping) else {}
    ammo_factor = 1.0
    if missile_share >= 0.20 and int(logistics.get("war_arrows", 0) or 0) + int(logistics.get("war_bolts", 0) or 0) <= 0:
        ammo_factor = 0.78
    effective = personnel * readiness * morale * cohesion * fatigue * supply_factor * ammo_factor
    return {
        "formation_ref": formation_ref, "personnel": personnel, "effective_strength": round(effective, 3),
        "readiness_factor": round(readiness, 4), "morale_factor": round(morale, 4), "cohesion_factor": round(cohesion, 4),
        "fatigue_factor": round(fatigue, 4), "supply_factor": round(supply_factor, 4), "supply_condition": supply_condition,
        "ammo_factor": round(ammo_factor, 4),
    }


def _sector_side_strength(planner: Any, battlefield: Mapping[str, Any], sector_ref: str, side_ref: str | None, *, at: str) -> dict[str, Any]:
    if not side_ref:
        return {"formation_refs": [], "personnel": 0, "effective_strength": 0.0, "supply_conditions": []}
    assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
    rows: list[dict[str, Any]] = []
    for formation_ref, assignment in sorted(assignments.items()):
        if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping):
            continue
        if assignment.get("side_ref") != side_ref:
            continue
        commitment_milli = planner._battlefield_assignment_sector_commitment_milli(assignment, sector_ref)
        if commitment_milli <= 0:
            continue
        _path, formation = planner._load_formation(formation_ref)
        rows.append(_formation_operational_strength(planner, formation_ref, formation, at=at))
        rows[-1]["personnel"] = int(round(int(rows[-1]["personnel"]) * commitment_milli / 1000.0))
        rows[-1]["effective_strength"] = round(float(rows[-1]["effective_strength"]) * commitment_milli / 1000.0, 3)
    return {"formation_refs": [row["formation_ref"] for row in rows], "personnel": sum(int(row["personnel"]) for row in rows),
            "effective_strength": round(sum(float(row["effective_strength"]) for row in rows), 3),
            "supply_conditions": sorted({str(row["supply_condition"]) for row in rows})}




def _observed_enemy_sector_strength(planner: Any, battlefield: Mapping[str, Any], sector_ref: str, side_ref: str | None, *, pressure_milli: int) -> dict[str, Any]:
    """Estimate hostile local strength without reading hidden readiness/morale/supply.

    Once formations share an operational sector, approximate mass is physically
    observable, while exact internal condition is not. Sector pressure is already
    an operational contact signal. This deliberately prevents superior-command AI
    from using the opponent's private morale, fatigue, cohesion or supply state.
    """
    if not isinstance(side_ref, str) or not side_ref:
        return {"personnel_estimate": 0, "effective_strength": 0.0, "confidence_milli": 0, "basis": "no_single_enemy_side"}
    assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
    total = 0
    rows = 0
    for formation_ref, assignment in assignments.items():
        if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping):
            continue
        if str(assignment.get("side_ref", "")) != side_ref:
            continue
        commitment_milli = planner._battlefield_assignment_sector_commitment_milli(assignment, sector_ref)
        if commitment_milli <= 0:
            continue
        _path, formation = planner._load_formation(formation_ref)
        personnel = max(0, int(formation.get("personnel", 0) or 0))
        if personnel <= 0:
            continue
        # Round mass to a coarse observed band so the command layer does not gain
        # exact hostile headcount merely because the simulator owns it.
        local_personnel = max(1, int(round(personnel * commitment_milli / 1000.0)))
        observed = max(100, int(round(local_personnel / 100.0)) * 100)
        total += observed
        rows += 1
    pressure = max(0, min(1000, int(pressure_milli or 0)))
    contact_factor = 0.92 - 0.28 * (pressure / 1000.0)
    effective = total * max(0.55, min(0.95, contact_factor))
    confidence = 880 if pressure > 0 else (680 if rows else 0)
    return {
        "personnel_estimate": total,
        "effective_strength": round(effective, 3),
        "confidence_milli": confidence,
        "basis": "coarse_observed_mass_plus_sector_contact_pressure",
    }

def _battle_daylight_hours_remaining(at: str) -> float:
    now = CampaignTime.parse(at)
    sunrise, sunset = daylight_window(now)
    if not (now < sunset):
        return 0.0
    start = sunrise if now < sunrise else now
    return max(0.0, start.seconds_until(sunset) / 3600.0)


def _objective_posture(operation: Mapping[str, Any]) -> str:
    # Exact operational semantics outrank prose token matching. In particular,
    # contact development/reconnaissance/probing are information missions and
    # cannot be promoted into a general attack merely because an objective
    # mentions advancing to, finding, or making contact with the enemy.
    current_order = None
    orders = operation.get("operational_orders")
    if isinstance(orders, list):
        last_ref = operation.get("last_operational_order_ref")
        if isinstance(last_ref, str) and last_ref:
            current_order = next(
                (row for row in reversed(orders) if isinstance(row, Mapping) and row.get("order_ref") == last_ref),
                None,
            )
        if current_order is None:
            current_order = next((row for row in reversed(orders) if isinstance(row, Mapping)), None)
    intent_contract = operational_intent_contract(operation, current_order)
    if isinstance(intent_contract, Mapping):
        intent = str(intent_contract.get("operational_intent") or "")
        if intent in {"attack", "assault", "breakthrough", "pursue", "harass", "fix"}:
            return "offensive"
        if intent in {"screen", "delay"}:
            return "defensive"
        if intent in {"probe", "reconnoiter", "develop_contact", "demonstrate"}:
            return "neutral"
    text = " ".join(str(operation.get(key, "")) for key in ("objective", "current_operational_order", "campaign_phase")).lower()
    if any(token in text for token in ("seize", "capture", "breakthrough", "advance", "attack", "assault", "pursue", "relieve")):
        return "offensive"
    if any(token in text for token in ("defend", "hold", "protect", "delay", "screen", "cover withdrawal")):
        return "defensive"
    return "neutral"

def review_battle_command_plan(planner: Any, operation: Mapping[str, Any], battlefield: dict[str, Any], *, at: str) -> list[dict[str, Any]]:
    """Issue bounded superior-command directives from the current exact field."""
    plan = battlefield.get("command_plan") if isinstance(battlefield.get("command_plan"), Mapping) else None
    if not isinstance(plan, Mapping):
        return []
    missions = plan.get("mission_index") if isinstance(plan.get("mission_index"), Mapping) else {}
    sectors = battlefield.get("sectors") if isinstance(battlefield.get("sectors"), Mapping) else {}
    assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
    # Registered battlefield pressure thresholds are part of battle-command law.
    # Do not hide a broken/missing rules read behind plausible-looking defaults.
    critical, collapse, _reset = planner._battlefield_pressure_thresholds()
    changes: list[dict[str, Any]] = []
    objective_posture = _objective_posture(operation)
    daylight_hours = _battle_daylight_hours_remaining(at)
    reserve_ref = _sector_roles(battlefield)[1]
    for mission_ref, mission_raw in sorted(missions.items()):
        if not isinstance(mission_ref, str) or not isinstance(mission_raw, dict):
            continue
        mission = mission_raw
        primary_sector_ref = mission.get("sector_ref")
        if not isinstance(primary_sector_ref, str) or not isinstance(sectors.get(primary_sector_ref), Mapping):
            continue
        side_ref = None
        formation_refs = [str(ref) for ref in mission.get("formation_refs", []) if isinstance(ref, str)]
        active_all_refs: list[str] = []
        for ref in formation_refs:
            row = assignments.get(ref)
            if not isinstance(row, Mapping) or row.get("status") == "redeploying":
                continue
            if isinstance(row.get("side_ref"), str):
                if side_ref is not None and side_ref != str(row["side_ref"]):
                    raise ValueError("battlefield mission spans opposing sides")
                side_ref = str(row["side_ref"]); active_all_refs.append(ref)
        if not side_ref or not active_all_refs:
            continue
        mission_sector_refs = [
            str(ref) for ref in mission.get("sector_refs", [])
            if isinstance(ref, str) and isinstance(sectors.get(str(ref)), Mapping)
        ] if isinstance(mission.get("sector_refs"), list) else []
        if not mission_sector_refs:
            mission_sector_refs = [primary_sector_ref]
        physically_covered = [
            sector_candidate
            for sector_candidate in mission_sector_refs
            if any(
                isinstance(assignments.get(ref), Mapping)
                and planner._battlefield_assignment_sector_commitment_milli(assignments[ref], sector_candidate) > 0
                for ref in active_all_refs
            )
        ]
        if not physically_covered:
            continue
        # One coarse exact formation may span several operational sectors. Its
        # superior command must review the most urgent covered sector rather than
        # looking only at the arbitrary command anchor and ignoring a collapsing
        # flank. Ties prefer the anchor for stable behavior.
        def sector_urgency(candidate_ref: str) -> tuple[int, int, int, str]:
            candidate = sectors[candidate_ref]
            pressure_row = candidate.get("pressure_milli") if isinstance(candidate.get("pressure_milli"), Mapping) else {}
            own = max(0, min(1000, int(pressure_row.get(side_ref, 0) or 0)))
            enemy = max(
                [max(0, min(1000, int(v or 0))) for k, v in pressure_row.items() if str(k) != side_ref],
                default=0,
            )
            return (max(own, enemy), own, 1 if candidate_ref == primary_sector_ref else 0, candidate_ref)

        sector_ref = max(physically_covered, key=sector_urgency)
        active_mission_refs = [
            ref for ref in active_all_refs
            if planner._battlefield_assignment_sector_commitment_milli(assignments[ref], sector_ref) > 0
        ]
        if not active_mission_refs:
            continue
        sector = sectors[sector_ref]
        pressure = sector.get("pressure_milli") if isinstance(sector.get("pressure_milli"), Mapping) else {}
        own_pressure = max(0, min(1000, int(pressure.get(side_ref, 0) or 0)))
        enemy_pressure = max([max(0, min(1000, int(v or 0))) for k,v in pressure.items() if str(k) != side_ref], default=0)
        enemy_sides = [str(x) for x in battlefield.get("side_refs", []) if isinstance(x, str) and str(x) != side_ref]
        enemy_side = enemy_sides[0] if len(enemy_sides) == 1 else None
        own_field = _sector_side_strength(planner, battlefield, sector_ref, side_ref, at=at)
        enemy_field = _observed_enemy_sector_strength(planner, battlefield, sector_ref, enemy_side, pressure_milli=enemy_pressure)
        own_strength = float(own_field.get("effective_strength", 0.0) or 0.0); enemy_strength = float(enemy_field.get("effective_strength", 0.0) or 0.0)
        local_ratio = own_strength / max(1.0, enemy_strength) if enemy_strength > 0 else (3.0 if own_strength > 0 else 1.0)
        decision_ref_raw = mission.get("decision_authority_ref") or mission.get("issuer_ref")
        decision_ref = str(decision_ref_raw) if isinstance(decision_ref_raw, str) and _person(planner, str(decision_ref_raw)) is not None else None
        decision = command_decision_policy(planner, decision_ref, side_ref=side_ref)
        decision = apply_command_doctrine_policy(planner.read, decision, mission.get("standing_doctrine_ref"))
        offensive_ratio = max(1.05, min(1.65, float(decision.get("offensive_advantage_required_milli", 1300) or 1300) / 1000.0))
        neutral_ratio = max(1.20, min(1.95, float(decision.get("neutral_advantage_required_milli", 1650) or 1650) / 1000.0))
        withdraw_ratio = max(0.42, min(0.82, float(decision.get("withdraw_if_local_ratio_below_milli", 620) or 620) / 1000.0))
        confidence_floor = max(0, min(1000, int(decision.get("report_confidence_floor_milli", 600) or 600)))
        enemy_confidence = max(0, min(1000, int(enemy_field.get("confidence_milli", 0) or 0)))
        cognition = decision.get("cognition", {}) if isinstance(decision.get("cognition"), Mapping) else {}
        dimensions = cognition.get("dimensions_milli", {}) if isinstance(cognition.get("dimensions_milli"), Mapping) else {}
        initiative_milli = max(0, min(1000, int(dimensions.get("initiative", 500) or 500)))
        instinct_milli = max(0, min(1000, int(dimensions.get("instinctive_opportunity_detection", 500) or 500)))
        willing_on_partial_information = max(initiative_milli, instinct_milli) >= 820
        reserve_field = _sector_side_strength(planner, battlefield, reserve_ref, side_ref, at=at) if reserve_ref and reserve_ref != sector_ref else {"effective_strength": 0.0}
        reserve_strength = float(reserve_field.get("effective_strength", 0.0) or 0.0)
        own_supply = set(str(x) for x in own_field.get("supply_conditions", []))
        if own_pressure >= collapse:
            directive, desired_order, reason = "withdraw_or_seek_immediate_relief", "withdraw", "assigned sector is at collapse risk"
        elif own_pressure >= critical:
            directive, desired_order, reason = "hold_and_request_relief", "hold", "assigned sector is under critical pressure"
        elif enemy_pressure >= collapse:
            directive, desired_order, reason = "exploit_enemy_collapse", "breakthrough", "opposing sector is at collapse risk"
        elif enemy_pressure >= critical:
            directive, desired_order, reason = "press_local_advantage", "attack", "opposing sector is under critical pressure"
        elif own_supply.intersection({"critical", "isolated"}) and objective_posture == "offensive":
            directive, desired_order, reason = "restore_support_before_further_commitment", "hold", "derived strategic supply is too weak for a fresh offensive commitment"
        elif daylight_hours < 0.75 and mission.get("order") in {"attack", "breakthrough"}:
            directive, desired_order, reason = "consolidate_before_dusk", "hold", "insufficient daylight remains for a fresh organized commitment"
        elif enemy_strength > 0 and local_ratio <= withdraw_ratio and reserve_strength < enemy_strength * 0.35:
            directive, desired_order, reason = "hold_and_request_relief", "hold", "commander policy judges the observed local balance unacceptable without substantial reserve support"
        elif objective_posture == "offensive" and enemy_strength > 0 and local_ratio >= offensive_ratio and daylight_hours >= 1.5 and (enemy_confidence >= confidence_floor or willing_on_partial_information):
            directive, desired_order, reason = "advance_on_assigned_objective", "attack", "observed local balance, command risk policy, support condition, and daylight favor the assigned offensive objective"
        elif objective_posture == "neutral" and enemy_strength > 0 and local_ratio >= neutral_ratio and daylight_hours >= 2.0 and (enemy_confidence >= confidence_floor or willing_on_partial_information):
            directive, desired_order, reason = "press_local_advantage", "attack", "commander cognition judges the observed advantage sufficient to exploit"
        else:
            continue
        key = f"{directive}:{desired_order}:{reason}"
        if mission.get("last_directive_key") == key:
            continue
        mission["last_directive_key"] = key
        directive_row = {"issued_at": at, "issuer_ref": mission.get("issuer_ref"), "decision_authority_ref": mission.get("decision_authority_ref"), "transmitted_by_ref": mission.get("transmitted_by_ref"), "mission_ref": mission_ref,
            "directive": directive, "desired_order": desired_order, "reason": reason, "sector_ref": sector_ref, "sector_name": sector.get("name"),
            "own_pressure_milli": own_pressure, "enemy_pressure_milli": enemy_pressure,
            "local_effective_strength_ratio_milli": int(round(local_ratio*1000)), "own_effective_strength": round(own_strength,3),
            "enemy_effective_strength_estimate": round(enemy_strength,3), "enemy_estimate_confidence_milli": enemy_confidence,
            "enemy_estimate_basis": enemy_field.get("basis"), "friendly_reserve_effective_strength": round(reserve_strength,3),
            "daylight_hours_remaining": round(daylight_hours,3), "objective_posture": objective_posture,
            "standing_doctrine_ref": decision.get("standing_doctrine_ref"),
            "decision_thresholds": {"offensive_ratio_milli": int(round(offensive_ratio*1000)), "neutral_ratio_milli": int(round(neutral_ratio*1000)), "withdraw_ratio_milli": int(round(withdraw_ratio*1000)), "confidence_floor_milli": confidence_floor},
            "derived_supply_conditions": sorted(own_supply), "formation_refs": active_mission_refs}
        tail = mission.setdefault("directive_tail", [])
        if isinstance(tail, list): tail.append(dict(directive_row)); del tail[:-8]
        recipient = str(mission.get("recipient_ref") or "")
        player_controlled = recipient == _PLAYER_REF or any(getattr(planner,"_battlefield_player_controls_formation",lambda _r:False)(ref) for ref in active_mission_refs)
        if player_controlled:
            report=planner._battlefield_queue_report(battlefield, sector_ref=sector_ref, side_ref=side_ref, level="new_order", pressure_milli=own_pressure,
                at=CampaignTime.parse(at), summary=f"Superior command issues a new directive for {sector.get('name',sector_ref)}: {directive.replace('_',' ')} ({reason}).", interrupt_player=True)
            if isinstance(report, dict): report.update({k:v for k,v in directive_row.items() if k!="issued_at"}); report["issued_at"]=at
            changes.append({"kind":"player_superior_directive_queued", **directive_row, "report_id": report.get("report_id") if isinstance(report,dict) else None}); continue
        for ref in active_mission_refs:
            assignment=assignments.get(ref)
            if not isinstance(assignment,dict) or assignment.get("status")=="redeploying": continue
            if assignment.get("order")==desired_order or assignment.get("pending_order")==desired_order: continue
            delay=planner._battlefield_report_latency(battlefield,sector_ref,side_ref)
            if delay<=0: assignment["order"]=desired_order; assignment["pending_order"]=None; assignment["order_eta_at"]=None
            else: assignment["pending_order"]=desired_order; assignment["order_eta_at"]=str(CampaignTime.parse(at).add_seconds(delay))
            assignment["updated_at"]=at
        changes.append({"kind":"npc_superior_directive_issued", **directive_row})
    if changes: battlefield["updated_at"]=at
    return changes

def initialize_battle_command_plan(planner: Any, operation: Mapping[str, Any], battlefield: dict[str, Any], *, at: str) -> dict[str, Any]:
    """Create one compact mission plan from the battlefield's exact participants."""
    existing = battlefield.get("command_plan")
    if isinstance(existing, Mapping) and existing.get("plan_ref"):
        return dict(existing)
    assignments = battlefield.get("assignments")
    sectors = battlefield.get("sectors")
    if not isinstance(assignments, dict) or not isinstance(sectors, Mapping):
        raise ValueError("battlefield command plan requires exact assignments")

    side_refs = [str(ref) for ref in battlefield.get("side_refs", []) if isinstance(ref, str)]
    frontline, reserve_ref, _command_ref = _sector_roles(battlefield)
    if not frontline:
        raise ValueError("battlefield command plan requires at least one frontline sector")
    initial_orders = _initial_side_orders(planner, operation, battlefield)

    blocks_by_side: dict[str, dict[str, dict[str, Any]]] = {side: {} for side in side_refs}
    for formation_ref, assignment in sorted(assignments.items()):
        if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping):
            continue
        side = str(assignment.get("side_ref", ""))
        if side not in blocks_by_side:
            continue
        sector_ref = assignment.get("sector_ref")
        if not isinstance(sector_ref, str) or sector_ref not in sectors:
            raise ValueError("battlefield command plan requires every participating formation to have a physical sector assignment")
        _path, formation = planner._load_formation(formation_ref)
        leaf_commander = formation_command_person(planner, formation_ref, formation)
        authority_key = str(formation.get('command_authority') or formation.get('administrative_owner') or side)
        command_group = _highest_lawful_command_group_for_formation(planner, formation_ref, operation=operation)
        commander = command_group.get("commander_ref") if isinstance(command_group, Mapping) else leaf_commander
        if not (isinstance(commander, str) and _person(planner, commander) is not None):
            commander = leaf_commander
        # A mission is layered over the physical battlefield; it never chooses
        # where a formation is deployed.  If one command currently spans two
        # sectors, it receives one sector-specific mission block for each rather
        # than collapsing those bodies onto a newly selected frontage.
        command_key = commander or f"authority:{authority_key}"
        block_key = f"{command_key}|sector:{sector_ref}"
        standing_doctrine_ref = default_command_group_doctrine_ref(command_group) if isinstance(command_group, Mapping) else None
        block = blocks_by_side[side].setdefault(block_key, {
            "recipient_ref": commander,
            "authority_ref": authority_key,
            "command_group_ref": command_group.get("id") if isinstance(command_group, Mapping) else None,
            "standing_doctrine_ref": standing_doctrine_ref,
            "sector_ref": sector_ref,
            "sector_refs": [],
            "formation_refs": [],
            "personnel": 0,
        })
        if not block.get("standing_doctrine_ref") and standing_doctrine_ref:
            block["standing_doctrine_ref"] = standing_doctrine_ref
        block["formation_refs"].append(formation_ref)
        block["personnel"] += max(0, int(formation.get("personnel", 0) or 0))
        for presence_ref in planner._battlefield_assignment_presence_refs(assignment):
            if presence_ref not in block["sector_refs"]:
                block["sector_refs"].append(presence_ref)
        block["sector_refs"] = sorted(block["sector_refs"])

    plan_sides: dict[str, Any] = {}
    mission_index: dict[str, Any] = {}
    for side in side_refs:
        blocks = list(blocks_by_side.get(side, {}).values())
        exact_commanders = sorted(
            {str(block["recipient_ref"]) for block in blocks if isinstance(block.get("recipient_ref"), str)},
            key=lambda ref: (-_command_score(planner, ref), ref),
        )
        explicit = operation.get("campaign_commander_ref") or operation.get("supreme_commander_ref")
        supreme = str(explicit) if isinstance(explicit, str) and explicit in exact_commanders else (exact_commanders[0] if exact_commanders else None)
        supreme_block = next((row for row in blocks if row.get("recipient_ref") == supreme), None)
        supreme_group = _command_group_by_ref(planner, supreme_block.get("command_group_ref") if isinstance(supreme_block, Mapping) else None)
        supreme_strategist = _strategist_transmitter(planner, supreme_group)
        # Physical deployment was already established by the battlefield owner.
        # Command planning adds an objective/order to that deployment; it does
        # not teleport forces by choosing a new sector.
        blocks.sort(key=lambda row: (
            str(row.get("sector_ref") or ""),
            -int(row.get("personnel", 0)),
            str(row.get("recipient_ref") or row.get("authority_ref")),
        ))
        side_missions: list[dict[str, Any]] = []
        for block in blocks:
            sector_ref = str(block.get("sector_ref") or "")
            if sector_ref not in sectors:
                raise ValueError("battlefield command block lost its physical sector assignment")
            sector = sectors[sector_ref]
            sector_role = str(sector.get("role") or "")
            order = "reserve" if sector_role == "reserve" or sector_ref == reserve_ref else str(initial_orders.get(side, "hold"))
            recipient = block.get("recipient_ref")
            token = hashlib.sha256(
                f"{battlefield.get('battlefield_ref')}|{side}|{recipient or block.get('authority_ref')}|{sector_ref}".encode()
            ).hexdigest()[:16]
            mission_ref = f"battle_mission_{token}"
            mission = {
                "mission_ref": mission_ref,
                "issued_at": at,
                "decision_authority_ref": supreme or side,
                "issuer_ref": supreme_strategist or supreme or side,
                "transmitted_by_ref": supreme_strategist,
                "recipient_ref": recipient,
                "authority_ref": block.get("authority_ref"),
                "standing_doctrine_ref": block.get("standing_doctrine_ref"),
                "formation_refs": sorted(set(block.get("formation_refs", []))),
                "personnel": int(block.get("personnel", 0)),
                "sector_ref": sector_ref,
                "sector_refs": sorted(set(str(ref) for ref in block.get("sector_refs", []) if isinstance(ref, str))) or [sector_ref],
                "sector_name": sector.get("name"),
                "order": order,
                "objective": _sector_mission_name(sector, order),
                "status": "active",
                "enemy_information_rule": "Mission assignment proves the sector and friendly task only. Enemy identity/strength must come from player-visible intelligence, observation or delivered reports.",
                "agency_rule": "Superior command may assign the military objective and formations under its authority; it does not choose Tang Wei's detailed tactics, dialogue, mercy, pursuit, or other protected voluntary decisions.",
            }
            side_missions.append(mission)
            mission_index[mission_ref] = mission
            for formation_ref in mission["formation_refs"]:
                assignment = assignments.get(formation_ref)
                if not isinstance(assignment, dict):
                    continue
                assignment.update({
                    "order": order,
                    "mission_ref": mission_ref,
                    "mission_recipient_ref": recipient,
                    "mission_objective": mission["objective"],
                    "mission_issuer_ref": mission["issuer_ref"],
                    "updated_at": at,
                })
        supreme_doctrine_ref = next((row.get("standing_doctrine_ref") for row in blocks if row.get("recipient_ref") == supreme and row.get("standing_doctrine_ref")), None)
        decision_profile = command_decision_policy(planner, supreme, side_ref=side)
        decision_profile = apply_command_doctrine_policy(planner.read, decision_profile, supreme_doctrine_ref)
        cognition = decision_profile.pop("cognition", {}) if isinstance(decision_profile.get("cognition"), Mapping) else {}
        decision_profile["cognitive_archetype"] = cognition.get("archetype") if isinstance(cognition, Mapping) else None
        plan_sides[side] = {
            "supreme_commander_ref": supreme,
            "supreme_strategist_ref": supreme_strategist,
            "standing_doctrine_ref": supreme_doctrine_ref,
            "decision_profile": decision_profile,
            "command_block_count": len(blocks),
            "formation_count": sum(len(row.get("formation_refs", [])) for row in blocks),
            "personnel": sum(int(row.get("personnel", 0)) for row in blocks),
            "missions": side_missions,
        }

    _rebuild_sector_membership(planner, battlefield)
    plan_ref = "battle_plan_" + hashlib.sha256(
        f"{battlefield.get('battlefield_ref')}|{at}|{'|'.join(side_refs)}".encode()
    ).hexdigest()[:18]
    plan = {
        "plan_ref": plan_ref,
        "created_at": at,
        "operation_ref": operation.get("operation_ref"),
        "battlefield_ref": battlefield.get("battlefield_ref"),
        "objective": operation.get("objective"),
        "sides": plan_sides,
        "mission_index": mission_index,
        "rule": "This is a command/mission layer over the existing battlefield. It creates no troops, casualties, enemy knowledge, movement or battle outcome.",
    }
    battlefield["command_plan"] = plan
    battlefield["updated_at"] = at
    return plan


def player_battle_missions(battlefield: Mapping[str, Any], controlled_refs: set[str], *, player_ref: str = _PLAYER_REF) -> list[dict[str, Any]]:
    plan = battlefield.get("command_plan") if isinstance(battlefield.get("command_plan"), Mapping) else None
    if not isinstance(plan, Mapping):
        return []
    missions: list[dict[str, Any]] = []
    index = plan.get("mission_index") if isinstance(plan.get("mission_index"), Mapping) else {}
    for mission in index.values():
        if not isinstance(mission, Mapping):
            continue
        refs = {str(ref) for ref in mission.get("formation_refs", []) if isinstance(ref, str)}
        if str(mission.get("recipient_ref", "")) != player_ref and not refs.intersection(controlled_refs):
            continue
        missions.append({
            key: mission.get(key)
            for key in (
                "mission_ref", "issued_at", "issuer_ref", "recipient_ref", "formation_refs", "personnel",
                "sector_ref", "sector_name", "order", "objective", "status", "agency_rule", "enemy_information_rule",
            )
            if key in mission
        })
    return sorted(missions, key=lambda row: str(row.get("mission_ref", "")))


__all__ = ["formation_command_person", "initialize_battle_command_plan", "review_battle_command_plan", "player_battle_missions"]
