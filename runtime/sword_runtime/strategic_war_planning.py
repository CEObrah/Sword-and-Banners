"""Deterministic field-army allocation for interstate campaigns.

A war does not flatten every formation owned by a state into one army. Existing
field-army / frontier / garrison command groups remain intact zero-body command
organizations. This module chooses which commands are committed to which exact
front objective and which remain strategic reserve. Several commands may mass at
one decisive point, or split across physically distinct border axes when the map
and force balance justify it.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.command_units import authoritative_group_ref_for_formation, recursive_refs
from sword_runtime.commander_cognition import campaign_side_policy

MOBILE_CONTEXTS = {"state_field_army", "state_frontier_command", "independent_field_command"}
DEFENSIVE_CONTEXTS = {"state_garrison_command", "grand_pass_defense_army", "state_capital_guard_command"}


def _group_path(ref: str) -> str:
    return f"state/cmd/command-groups/{ref}.json"


def _side_owner(side: str) -> str:
    return side if str(side).startswith("polity_") else f"state_{side}"


def _formation_snapshot(planner: Any, ref: str) -> Mapping[str, Any] | None:
    try:
        _path, row = planner._load_formation(ref)
    except ValueError:
        return None
    return row if isinstance(row, Mapping) else None


def _command_catalog(planner: Any, side: str, eligible_refs: list[str]) -> list[dict[str, Any]]:
    """Resolve only command groups that can actually contain eligible formations.

    The routing index already maps persistent formations to their primary command
    groups. Reading every command group in the repository made long-horizon war
    planning scale with unrelated Houses/armies. Follow only those routed groups
    and their parent chain, then expand the resulting intact top-level commands.
    """
    owner = _side_owner(side)
    eligible = set(str(x) for x in eligible_refs)
    index = planner.read("state/cmd/command-groups/index.json")
    candidate_refs: set[str] = set()
    for ref in sorted(eligible):
        formation = _formation_snapshot(planner, ref)
        if not isinstance(formation, Mapping):
            continue
        group_ref = authoritative_group_ref_for_formation(
            index if isinstance(index, Mapping) else {},
            lambda group: planner.read(_group_path(group)),
            ref,
            formation,
        )
        if isinstance(group_ref, str) and group_ref:
            candidate_refs.add(group_ref)

    # Climb only the relevant parent chains. A primary formation group is usually
    # already the intact field army, but this preserves lawful nested commands.
    top_refs: set[str] = set()
    group_cache: dict[str, Mapping[str, Any]] = {}
    for seed in sorted(candidate_refs):
        current = seed
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            try:
                group = group_cache.get(current) or planner.read(_group_path(current))
            except (FileNotFoundError, KeyError, ValueError):
                break
            if not isinstance(group, Mapping):
                break
            group_cache[current] = group
            parent = group.get("parent_command_group_ref")
            if not isinstance(parent, str) or not parent:
                top_refs.add(current)
                break
            current = parent

    rows: list[dict[str, Any]] = []
    covered: set[str] = set()
    for group_ref in sorted(top_refs):
        try:
            group = group_cache.get(group_ref) or planner.read(_group_path(group_ref))
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if not isinstance(group, Mapping) or group.get("parent_command_group_ref") not in {None, ""}:
            continue
        if str(group.get("authority_ref", "")) != owner:
            continue
        context = str(group.get("context", ""))
        if context not in MOBILE_CONTEXTS | DEFENSIVE_CONTEXTS:
            continue
        commander = str(group.get("commander_ref", ""))
        if commander == str(getattr(planner, "PLAYER_ACTOR", "char_tang_wei")):
            continue
        try:
            descendants, _commands = recursive_refs(
                lambda ref: group_cache.get(ref) or planner.read(_group_path(ref)),
                group_ref,
            )
        except (ValueError, KeyError, FileNotFoundError):
            continue
        formations = sorted(ref for ref in descendants if ref in eligible)
        if not formations:
            continue
        personnel = 0
        readiness_sum = 0
        weighted = 0
        locations: dict[str, int] = {}
        for ref in formations:
            form = _formation_snapshot(planner, ref)
            if not form:
                continue
            n = max(0, int(form.get("personnel", 0)))
            if n <= 0:
                continue
            personnel += n
            readiness_sum += n * (
                int(form.get("readiness", 50))
                + int(form.get("cohesion", 50))
                + int(form.get("morale", 50))
            )
            weighted += n
            loc = str(form.get("location_ref", ""))
            if loc:
                locations[loc] = locations.get(loc, 0) + n
        if personnel <= 0:
            continue
        location = max(locations, key=lambda key: (locations[key], key)) if locations else str(group.get("location", ""))
        rows.append({
            "command_group_ref": group_ref,
            "commander_ref": commander or None,
            "context": context,
            "formation_refs": formations,
            "personnel": personnel,
            "readiness_score": round(readiness_sum / max(1, weighted) / 3.0, 3),
            "location_ref": location,
            "mobility": "mobile" if context in MOBILE_CONTEXTS else "defensive",
        })
        covered.update(formations)

    def add_independent(ref: str, form: Mapping[str, Any], *, context: str = "independent_formation") -> None:
        rows.append({
            "command_group_ref": None,
            "independent_formation_ref": ref,
            "commander_ref": form.get("commander_ref"),
            "context": context,
            "formation_refs": [ref],
            "personnel": int(form.get("personnel", 0)),
            "readiness_score": round((int(form.get("readiness", 50)) + int(form.get("cohesion", 50)) + int(form.get("morale", 50))) / 3.0, 3),
            "location_ref": str(form.get("location_ref", "")),
            "mobility": "mobile",
        })

    def is_explicit_standalone_commitment(ref: str, form: Mapping[str, Any]) -> bool:
        # Temporary state levies and field-contract mercenaries are already
        # explicit mobilization decisions.  They do not need to be silently
        # attached to an existing named general before the strategic planner can
        # hold them as an intact independent reserve command.  Ordinary
        # ungrouped standing formations remain at state disposal as before.
        if form.get("temporary_levy_ref"):
            return True
        owner_ref = str(form.get("owner_force_ref", ""))
        if not owner_ref:
            return False
        try:
            owner = planner.read(planner.owner_path(owner_ref))
        except (KeyError, ValueError, FileNotFoundError):
            return False
        if not isinstance(owner, Mapping) or str(owner.get("schema", "")) not in {"mercenary", "mercenary-company", "regional-mercenary-company"}:
            return False
        if str(form.get("administrative_owner", "")) != _side_owner(side):
            return False
        formation_ref = str(owner.get("tactical_formation_ref", ""))
        if formation_ref and formation_ref != ref:
            return False
        contracts = owner.get("contracts", [])
        if not isinstance(contracts, list):
            return False
        return any(
            isinstance(row, Mapping)
            and str(row.get("status", "")) == "active"
            and str(row.get("employer_ref", "")) == _side_owner(side)
            and str(row.get("engagement_kind", "")) in {"state_campaign", "state_contract"}
            for row in contracts
        )

    uncovered = sorted(eligible - covered)
    # A real allocated formation does not cease to exist merely because its state
    # also has formal command groups.  Ungrouped state formations are legitimate
    # independent commands until an exact organizational action attaches them to
    # an army.  Temporary levies and contracted mercenaries retain an explicit
    # mobilization context, but ordinary standing formations are admitted too.
    for ref in uncovered:
        form = _formation_snapshot(planner, ref)
        if not form or int(form.get("personnel", 0)) <= 0:
            continue
        commander = str(form.get("commander_ref", ""))
        authority = str(form.get("command_authority", ""))
        if commander == str(getattr(planner, "PLAYER_ACTOR", "char_tang_wei")) or authority == str(getattr(planner, "PLAYER_ACTOR", "char_tang_wei")):
            continue
        context = "standalone_mobilized_commitment" if is_explicit_standalone_commitment(ref, form) else "independent_state_formation"
        add_independent(ref, form, context=context)
    rows.sort(key=lambda row: (
        0 if row["mobility"] == "mobile" else 1,
        -int(row["personnel"]),
        str(row.get("command_group_ref") or row.get("independent_formation_ref")),
    ))
    return rows


def command_catalog(planner: Any, side: str, eligible_refs: list[str]) -> list[dict[str, Any]]:
    """Public bounded view of intact lawful commands for one sovereign side.

    Callers supply the exact eligible formation set. Permanent command-group
    parentage is honored; campaign selection never reparents or flattens armies.
    """
    return _command_catalog(planner, side, eligible_refs)


def _border_objectives(planner: Any, attacker: str, defender: str, primary_target: str) -> list[dict[str, Any]]:
    attacker_owner = _side_owner(attacker)
    defender_owner = _side_owner(defender)
    territory = planner.read("state/territory/control.json")
    sites = territory.get("sites", {}) if isinstance(territory, Mapping) else {}
    locations = {
        str(row.get("ref")): row
        for row in planner.read("game/data/world/locations.json").get("locations", [])
        if isinstance(row, Mapping) and row.get("ref")
    }
    routes = planner.read("game/data/world/routes.json").get("routes", [])
    refs: set[str] = {str(primary_target)}
    for route in routes if isinstance(routes, list) else []:
        if not isinstance(route, Mapping):
            continue
        a, b = str(route.get("a", "")), str(route.get("b", ""))
        ca = str((sites.get(a, {}) or {}).get("controller", "")) if isinstance(sites, Mapping) else ""
        cb = str((sites.get(b, {}) or {}).get("controller", "")) if isinstance(sites, Mapping) else ""
        if ca == attacker_owner and cb == defender_owner:
            refs.add(b)
        elif cb == attacker_owner and ca == defender_owner:
            refs.add(a)
    out: list[dict[str, Any]] = []
    for ref in refs:
        loc = locations.get(ref, {})
        site = sites.get(ref, {}) if isinstance(sites, Mapping) else {}
        if ref != primary_target and str(site.get("controller", "")) != defender_owner:
            continue
        kind = str(loc.get("kind", ""))
        score = 100 if ref == primary_target else 55
        if bool(loc.get("fortified")): score += 20
        if kind in {"capital", "major_city"}: score += 35
        elif kind in {"city", "fortress", "fort", "pass"}: score += 20
        if bool(loc.get("strategic_node")): score += 10
        out.append({"objective_ref": ref, "priority": score, "kind": kind, "fortified": bool(loc.get("fortified"))})
    out.sort(key=lambda row: (-int(row["priority"]), str(row["objective_ref"])))
    return out[:3]


def _assign_commands(commands: list[dict[str, Any]], objectives: list[dict[str, Any]], *, mode: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not commands or not objectives:
        return [], commands
    mobile = [dict(row) for row in commands if row.get("mobility") == "mobile"]
    defensive = [dict(row) for row in commands if row.get("mobility") != "mobile"]
    pool = mobile + defensive
    reserve_count = 0
    if len(pool) >= 3:
        reserve_count = 1
    if mode == "multi_axis" and len(pool) >= 5:
        reserve_count = max(1, len(pool) // 5)
    committed_count = max(1, len(pool) - reserve_count)
    committed = pool[:committed_count]
    reserve = pool[committed_count:]
    assignments: list[dict[str, Any]] = []
    if mode == "multi_axis" and len(objectives) > 1:
        # Give every real axis one intact command before reinforcing the main axis.
        for idx, command in enumerate(committed):
            objective = objectives[idx] if idx < len(objectives) else objectives[0]
            assignments.append({**command, "role": "main_effort" if objective is objectives[0] else "secondary_axis", "objective_ref": objective["objective_ref"]})
    else:
        for command in committed:
            assignments.append({**command, "role": "main_effort", "objective_ref": objectives[0]["objective_ref"]})
    return assignments, reserve


def integrate_reinforcement_reserves(
    planner: Any,
    plan: dict[str, Any],
    *,
    side: str,
    formation_refs: list[str],
    at: str,
) -> dict[str, Any]:
    """Admit newly mobilized standalone formations as intact strategic reserves.

    Existing front/command assignments are never rebuilt.  Only formations that
    are not already assigned or reserved are considered, and `_command_catalog`
    still enforces the distinction between explicit standalone mobilization and
    unrelated ungrouped state formations.
    """
    assigned: set[str] = set()
    objectives = plan.get("formation_objectives", {}) if isinstance(plan.get("formation_objectives"), Mapping) else {}
    side_objectives = objectives.get(side, {}) if isinstance(objectives.get(side), Mapping) else {}
    assigned.update(str(ref) for ref in side_objectives)
    reserves = plan.get("strategic_reserve_formation_refs", {}) if isinstance(plan.get("strategic_reserve_formation_refs"), Mapping) else {}
    side_reserves = reserves.get(side, []) if isinstance(reserves.get(side), list) else []
    assigned.update(str(ref) for ref in side_reserves)
    front_key = "attacker_formation_refs" if str(side) == str(plan.get("attacker_side")) else "defender_formation_refs"
    for front in plan.get("fronts", []) if isinstance(plan.get("fronts"), list) else []:
        if isinstance(front, Mapping):
            assigned.update(str(ref) for ref in front.get(front_key, []) if isinstance(ref, str))

    candidates = sorted({str(ref) for ref in formation_refs if isinstance(ref, str)} - assigned)
    if not candidates:
        return {"added_formation_refs": [], "added_commands": []}
    commands = _command_catalog(planner, side, candidates)
    if not commands:
        return {"added_formation_refs": [], "added_commands": []}

    reserve_commands = plan.setdefault("strategic_reserve_commands", {}).setdefault(side, [])
    if not isinstance(reserve_commands, list):
        raise ValueError("strategic reserve command registry must be a list")
    existing_command_ids = {
        str(row.get("command_group_ref") or row.get("independent_formation_ref"))
        for row in reserve_commands if isinstance(row, Mapping)
    }
    for row in plan.get("command_assignments", {}).get(side, []) if isinstance(plan.get("command_assignments", {}), Mapping) else []:
        if isinstance(row, Mapping):
            existing_command_ids.add(str(row.get("command_group_ref") or row.get("independent_formation_ref")))

    added_commands: list[dict[str, Any]] = []
    added_refs: list[str] = []
    for command in commands:
        command_id = str(command.get("command_group_ref") or command.get("independent_formation_ref") or "")
        refs = [str(ref) for ref in command.get("formation_refs", []) if isinstance(ref, str)]
        if not command_id or not refs or command_id in existing_command_ids:
            continue
        reserve_commands.append(dict(command))
        existing_command_ids.add(command_id)
        added_commands.append(dict(command))
        added_refs.extend(refs)

    if not added_refs:
        return {"added_formation_refs": [], "added_commands": []}
    reserve_map = plan.setdefault("strategic_reserve_formation_refs", {})
    reserve_map[side] = sorted(set([str(x) for x in reserve_map.get(side, []) if isinstance(x, str)] + added_refs))
    unassigned = plan.setdefault("unassigned_formation_refs", {})
    if isinstance(unassigned.get(side), list):
        unassigned[side] = [str(ref) for ref in unassigned[side] if str(ref) not in set(added_refs)]
    return {"added_formation_refs": sorted(set(added_refs)), "added_commands": added_commands}



def contingency_withdrawal_decision(
    plan: Mapping[str, Any],
    *,
    attacker: str,
    defender: str,
    attacker_power: float,
    defender_power: float,
    attacker_reserve_available: bool,
    defender_reserve_available: bool,
    fortified_contact: bool = False,
) -> dict[str, Any] | None:
    """Return a lawful open-field withdrawal triggered by the saved command plan.

    This is a decision boundary, not a combat modifier.  A side may decline an
    obviously bad open-field contact when its own saved contingency threshold is
    crossed and no intact strategic reserve remains to satisfy the plan.  Siege
    contacts are excluded because retreating inside/out of an enclosure requires
    different physical handling.
    """
    if fortified_contact or attacker_power <= 0 or defender_power <= 0:
        return None
    contingencies = plan.get("operational_contingencies", {}) if isinstance(plan.get("operational_contingencies"), Mapping) else {}
    attacker_cont = contingencies.get(attacker, {}) if isinstance(contingencies.get(attacker), Mapping) else {}
    defender_cont = contingencies.get(defender, {}) if isinstance(contingencies.get(defender), Mapping) else {}
    attacker_threshold = max(0.42, min(0.82, float(attacker_cont.get("withdraw_if_local_ratio_below_milli", 620) or 620) / 1000.0))
    defender_threshold = max(0.42, min(0.82, float(defender_cont.get("withdraw_if_local_ratio_below_milli", 620) or 620) / 1000.0))
    attacker_ratio = attacker_power / max(1.0, defender_power)
    defender_ratio = defender_power / max(1.0, attacker_power)
    if attacker_ratio < attacker_threshold and not attacker_reserve_available:
        return {
            "side": attacker,
            "local_ratio_milli": int(round(attacker_ratio * 1000)),
            "threshold_milli": int(round(attacker_threshold * 1000)),
            "reason": "saved command contingency rejects an unsupported unfavorable open-field contact",
        }
    if defender_ratio < defender_threshold and not defender_reserve_available:
        return {
            "side": defender,
            "local_ratio_milli": int(round(defender_ratio * 1000)),
            "threshold_milli": int(round(defender_threshold * 1000)),
            "reason": "saved command contingency orders withdrawal from an untenable open-field defense",
        }
    return None

def build_interstate_strategic_plan(
    planner: Any,
    *,
    theater_ref: str,
    attacker: str,
    defender: str,
    primary_target: str,
    attacker_formation_refs: list[str],
    defender_formation_refs: list[str],
    at: str,
) -> dict[str, Any]:
    attacker_commands = _command_catalog(planner, attacker, attacker_formation_refs)
    defender_commands = _command_catalog(planner, defender, defender_formation_refs)
    attacker_policy = campaign_side_policy(planner, attacker, attacker_commands)
    defender_policy = campaign_side_policy(planner, defender, defender_commands)
    objectives = _border_objectives(planner, attacker, defender, primary_target)
    if not objectives:
        objectives = [{"objective_ref": primary_target, "priority": 100, "kind": "strategic", "fortified": False}]
    attack_power = sum(int(row.get("personnel", 0)) * float(row.get("readiness_score", 50)) for row in attacker_commands)
    defense_power = sum(int(row.get("personnel", 0)) * float(row.get("readiness_score", 50)) for row in defender_commands)
    hard_primary = bool(objectives[0].get("fortified")) or str(objectives[0].get("kind", "")) in {"capital", "major_city", "pass", "fortress"}
    offensive_required = max(1.05, float(attacker_policy.get("offensive_advantage_required_milli", 1300)) / 1000.0)
    cognition = attacker_policy.get("cognition", {}) if isinstance(attacker_policy.get("cognition"), Mapping) else {}
    dimensions = cognition.get("dimensions_milli", {}) if isinstance(cognition.get("dimensions_milli"), Mapping) else {}
    adaptability = max(0.0, min(1.0, float(dimensions.get("adaptability", 500) or 500) / 1000.0))
    initiative = max(0.0, min(1.0, float(dimensions.get("initiative", 500) or 500) / 1000.0))
    split_floor = max(0.82, min(1.10, offensive_required - 0.22 - 0.08 * adaptability - 0.05 * initiative))
    if len(objectives) >= 2 and len(attacker_commands) >= 3 and attack_power >= split_floor * max(1.0, defense_power) and not (hard_primary and attack_power < offensive_required * max(1.0, defense_power)):
        mode = "multi_axis"
    else:
        mode = "decisive_concentration"

    attacker_assignments, attacker_reserve = _assign_commands(attacker_commands, objectives, mode=mode)

    # Defender reacts to the actual threatened axes. Local garrison commands are
    # attached to their own objective first; mobile armies then reinforce fronts
    # in descending attacker strength. One command remains strategic reserve when
    # force depth allows it.
    threatened = {str(row["objective_ref"]): 0 for row in objectives}
    for row in attacker_assignments:
        threatened[str(row["objective_ref"])] += int(row.get("personnel", 0))
    defender_pool = [dict(row) for row in defender_commands]
    defender_assignments: list[dict[str, Any]] = []
    used: set[str] = set()
    def key(row: Mapping[str, Any]) -> str:
        return str(row.get("command_group_ref") or row.get("independent_formation_ref"))
    for objective in objectives:
        obj = str(objective["objective_ref"])
        locals_here = [row for row in defender_pool if row.get("mobility") == "defensive" and str(row.get("location_ref", "")) == obj and key(row) not in used]
        for row in locals_here:
            used.add(key(row)); defender_assignments.append({**row, "role": "local_defense", "objective_ref": obj})
    remaining = [row for row in defender_pool if key(row) not in used]
    reserve_threshold = int(defender_policy.get("defender_reserve_commit_if_enemy_ratio_above_milli", 1150) or 1150)
    # Cautious institutions keep an intact mobile command in hand at shallower
    # force depth; aggressive institutions spend that depth on the threatened axes.
    reserve_count = 1 if len(remaining) >= 3 or (len(remaining) >= 2 and reserve_threshold >= 1240) else 0
    active_remaining = remaining[: max(0, len(remaining) - reserve_count)]
    defender_reserve = remaining[len(active_remaining):]
    ordered_fronts = sorted(threatened, key=lambda obj: (-threatened[obj], -next(int(x["priority"]) for x in objectives if x["objective_ref"] == obj), obj))
    for idx, row in enumerate(active_remaining):
        obj = ordered_fronts[idx % len(ordered_fronts)]
        defender_assignments.append({**row, "role": "mobile_defense", "objective_ref": obj})

    fronts: list[dict[str, Any]] = []
    for objective in objectives:
        obj = str(objective["objective_ref"])
        a_cmds = [row for row in attacker_assignments if str(row.get("objective_ref")) == obj]
        d_cmds = [row for row in defender_assignments if str(row.get("objective_ref")) == obj]
        if not a_cmds and obj != primary_target:
            continue
        fronts.append({
            "front_ref": f"{theater_ref}:front:{obj}",
            "objective_ref": obj,
            "priority": int(objective.get("priority", 0)),
            "status": "mobilizing",
            "attacker_command_refs": [str(row.get("command_group_ref") or row.get("independent_formation_ref")) for row in a_cmds],
            "defender_command_refs": [str(row.get("command_group_ref") or row.get("independent_formation_ref")) for row in d_cmds],
            "attacker_formation_refs": sorted({ref for row in a_cmds for ref in row.get("formation_refs", [])}),
            "defender_formation_refs": sorted({ref for row in d_cmds for ref in row.get("formation_refs", [])}),
        })
    attacker_policy_saved = {k: v for k, v in attacker_policy.items() if k != "cognition"}
    defender_policy_saved = {k: v for k, v in defender_policy.items() if k != "cognition"}
    attacker_policy_saved["cognitive_archetype"] = (attacker_policy.get("cognition", {}) or {}).get("archetype") if isinstance(attacker_policy.get("cognition"), Mapping) else None
    defender_policy_saved["cognitive_archetype"] = (defender_policy.get("cognition", {}) or {}).get("archetype") if isinstance(defender_policy.get("cognition"), Mapping) else None
    return {
        "planned_at": at,
        "theater_ref": theater_ref,
        "primary_objective_ref": primary_target,
        "concentration_mode": mode,
        "attacker_side": attacker,
        "defender_side": defender,
        "side_decision_policies": {attacker: attacker_policy_saved, defender: defender_policy_saved},
        "operational_contingencies": {
            attacker: {
                "reserve_commit_if_local_ratio_below_milli": int(attacker_policy.get("attacker_reserve_commit_if_ratio_below_milli", 1100)),
                "withdraw_if_local_ratio_below_milli": int(attacker_policy.get("withdraw_if_local_ratio_below_milli", 620)),
                "pursuit_limit_milli": int(attacker_policy.get("pursuit_limit_milli", 750)),
                "replan_on_route_block": True,
                "preserve_primary_objective": True
            },
            defender: {
                "reserve_commit_if_enemy_ratio_above_milli": int(defender_policy.get("defender_reserve_commit_if_enemy_ratio_above_milli", 1150)),
                "withdraw_if_local_ratio_below_milli": int(defender_policy.get("withdraw_if_local_ratio_below_milli", 620)),
                "pursuit_limit_milli": int(defender_policy.get("pursuit_limit_milli", 750)),
                "replan_on_route_block": True,
                "preserve_primary_objective": True
            }
        },
        "fronts": fronts,
        "command_assignments": {attacker: attacker_assignments, defender: defender_assignments},
        "strategic_reserve_commands": {attacker: attacker_reserve, defender: defender_reserve},
        "formation_objectives": {
            attacker: {ref: str(row["objective_ref"]) for row in attacker_assignments for ref in row.get("formation_refs", [])},
            defender: {ref: str(row["objective_ref"]) for row in defender_assignments for ref in row.get("formation_refs", [])},
        },
        "strategic_reserve_formation_refs": {
            attacker: sorted({ref for row in attacker_reserve for ref in row.get("formation_refs", [])}),
            defender: sorted({ref for row in defender_reserve for ref in row.get("formation_refs", [])}),
        },
        "unassigned_formation_refs": {
            attacker: sorted(set(attacker_formation_refs) - {ref for row in attacker_assignments + attacker_reserve for ref in row.get("formation_refs", [])}),
            defender: sorted(set(defender_formation_refs) - {ref for row in defender_assignments + defender_reserve for ref in row.get("formation_refs", [])}),
        },
        "rule": "Existing field armies remain intact command groups. The campaign may mass several commands, split across exact route-defined fronts, or retain a strategic reserve; no command grouping transfers manpower or ownership.",
    }
