"""Lightweight team tactical planning for exact personal combat.

The planner chooses shared tactical intent and temporary roles.  It never decides
whether an attack, defense, movement, or grapple succeeds; the exact combat
resolver remains outcome authority.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.combat_geometry import angle_delta_deg, bearing_deg, distance_2d, surrounding_pressure


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stats(person: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    skills = person.get("skills", {}) if isinstance(person.get("skills"), Mapping) else {}
    attrs = person.get("attributes", {}) if isinstance(person.get("attributes"), Mapping) else {}
    if str(person.get("schema")) == "person-lite" and isinstance(person.get("stats"), Mapping):
        stats = person["stats"]
        skills = stats.get("skills", {}) if isinstance(stats.get("skills"), Mapping) else {}
        attrs = stats.get("attributes", {}) if isinstance(stats.get("attributes"), Mapping) else {}
    return skills, attrs


def _capabilities(ref: str, people: Mapping[str, Mapping[str, Any]], equipment: Mapping[str, Mapping[str, Any]], controls: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
    person = people[ref]
    skills, attrs = _stats(person)
    eq = equipment.get(ref, {})
    ctrl = controls.get(ref, {})
    weapon = eq.get("weapon", {}) if isinstance(eq.get("weapon"), Mapping) else {}
    ranged = eq.get("ranged_weapon", {}) if isinstance(eq.get("ranged_weapon"), Mapping) else {}
    shielded = bool((eq.get("loadout") or {}).get("shield")) if isinstance(eq.get("loadout"), Mapping) else False
    reach = max(0.55, _num(weapon.get("reach_m"), 0.55))
    attack = _num(ctrl.get("attack"))
    defense = max(_num(ctrl.get("parry")), _num(ctrl.get("block")), _num(ctrl.get("dodge")))
    awareness = _num(attrs.get("Awareness"))
    agility = _num(attrs.get("Agility"))
    coordination = _num(attrs.get("Coordination"))
    strength = _num(attrs.get("Strength"))
    leadership = _num(skills.get("Leadership", skills.get("Command", 0.0)))
    tactics = _num(skills.get("Tactics", skills.get("Formation Fighting", 0.0)))
    grappling = max(_num(skills.get("Grappling")), _num(skills.get("Wrestling")))
    ranged_value = max(_num(skills.get("Bow")), _num(skills.get("Crossbow"))) if ranged else 0.0
    return {
        "leadership": 0.55 * leadership + 0.30 * tactics + 0.15 * awareness,
        "control": 0.36 * grappling + 0.22 * strength + 0.18 * defense + 0.14 * coordination + 0.10 * (18.0 if shielded else reach * 10.0),
        "shape": 0.34 * ranged_value + 0.20 * reach * 10.0 + 0.18 * awareness + 0.16 * coordination + 0.12 * attack,
        "tracking": 0.38 * awareness + 0.30 * agility + 0.20 * coordination + 0.12 * defense,
        "interception": 0.32 * agility + 0.25 * defense + 0.20 * awareness + 0.13 * coordination + 0.10 * reach * 10.0,
        "pressure": 0.50 * attack + 0.20 * agility + 0.15 * reach * 10.0 + 0.15 * strength,
        "protection": 0.34 * defense + 0.24 * awareness + 0.16 * coordination + 0.14 * strength + 0.12 * (25.0 if shielded else 0.0),
        "exploit": 0.48 * attack + 0.22 * coordination + 0.18 * awareness + 0.12 * agility,
    }


def _health_pressure(person: Mapping[str, Any]) -> float:
    state = person.get("combat_state", {}) if isinstance(person.get("combat_state"), Mapping) else {}
    if state.get("incapacitated"):
        return -1000.0
    phys = person.get("physiology_state", {}) if isinstance(person.get("physiology_state"), Mapping) else {}
    blood = _num(phys.get("blood_loss_units"), 0.0)
    injuries = person.get("injuries", []) if isinstance(person.get("injuries"), list) else []
    return min(40.0, blood * 0.25 + len(injuries) * 2.0)


def build_team_plan(
    side_refs: Sequence[str],
    enemy_refs: Sequence[str],
    *,
    people: Mapping[str, Mapping[str, Any]],
    equipment: Mapping[str, Mapping[str, Any]],
    controls: Mapping[str, Mapping[str, Any]],
    positions: Mapping[str, Mapping[str, Any]],
    objective: str,
    at_s: float,
    doctrines: Mapping[str, Mapping[str, Any]] | None = None,
    knowledge_by_actor: Mapping[str, Sequence[str]] | None = None,
    recent_failures: Mapping[str, int] | None = None,
    protected_refs: Sequence[str] = (),
) -> dict[str, Any]:
    active_side = [r for r in side_refs if r in people and not bool((people[r].get("combat_state") or {}).get("incapacitated"))]
    active_enemy = [r for r in enemy_refs if r in people and not bool((people[r].get("combat_state") or {}).get("incapacitated"))]
    if not active_side or not active_enemy:
        return {"plan_id": "none", "leader_ref": active_side[0] if active_side else None, "primary_threat_ref": None, "desired_state": "hold", "assignments": {}}

    caps = {ref: _capabilities(ref, people, equipment, controls) for ref in active_side}
    leader = max(active_side, key=lambda r: (caps[r]["leadership"], caps[r]["tracking"], r))
    doctrines = doctrines or {}
    leader_doctrine = doctrines.get(leader, {}) if isinstance(doctrines.get(leader, {}), Mapping) else {}
    team_doctrine = leader_doctrine.get("team_tactics", {}) if isinstance(leader_doctrine.get("team_tactics"), Mapping) else {}
    risk_tolerance = str(team_doctrine.get("risk_tolerance", "moderate"))
    range_preference = str(team_doctrine.get("engagement_distance", "adaptive"))
    protect_priority = str(team_doctrine.get("protection_priority", "principal_if_objective_requires"))

    # Team coordination may use only threats known to the leader or lawfully
    # shared by a nearby ally.  Callers can omit this in benchmarks, in which
    # case the exact local roster is treated as mutually known.
    if knowledge_by_actor:
        leader_known = {str(x) for x in knowledge_by_actor.get(leader, ())}
        shared_known = set(leader_known)
        leader_pos = positions.get(leader)
        for ally in active_side:
            if ally == leader or ally not in positions or leader_pos is None:
                continue
            communication = 0.65 * caps[leader]["leadership"] + 0.35 * caps[ally]["tracking"]
            if distance_2d(leader_pos, positions[ally]) <= 8.0 and communication >= 38.0:
                shared_known.update(str(x) for x in knowledge_by_actor.get(ally, ()))
        coordinated_enemy = [r for r in active_enemy if r in shared_known]
        if coordinated_enemy:
            active_enemy = coordinated_enemy

    def enemy_role_value(enemy: str) -> dict[str, float]:
        skills, attrs = _stats(people[enemy])
        eq = equipment.get(enemy, {})
        ranged = eq.get("ranged_weapon", {}) if isinstance(eq.get("ranged_weapon"), Mapping) else {}
        return {
            "ranged": max(_num(skills.get("Bow")), _num(skills.get("Crossbow"))) if ranged else 0.0,
            "command": 0.60 * _num(skills.get("Leadership", skills.get("Command", 0.0))) + 0.25 * _num(skills.get("Tactics", skills.get("Formation Fighting", 0.0))) + 0.15 * _num(attrs.get("Awareness")),
            "mobility": 0.55 * _num(attrs.get("Agility")) + 0.25 * _num(skills.get("Athletics")) + 0.20 * _num(attrs.get("Coordination")),
        }

    enemy_roles = {enemy: enemy_role_value(enemy) for enemy in active_enemy}

    def threat_score(enemy: str) -> tuple[float, str]:
        ectrl = controls.get(enemy, {})
        attack = _num(ectrl.get("attack"))
        defense = max(_num(ectrl.get("parry")), _num(ectrl.get("block")), _num(ectrl.get("dodge")))
        proximity = 0.0
        if enemy in positions:
            distances = [distance_2d(positions[enemy], positions[r]) for r in active_side if r in positions]
            if distances:
                proximity = max(0.0, 18.0 - min(distances) * 3.0)
        wounded = _health_pressure(people[enemy])
        role = enemy_roles[enemy]
        risk_factor = {"low": 1.12, "moderate": 1.0, "high": 0.92, "extreme": 0.86}.get(risk_tolerance, 1.0)
        support_pressure = 0.08 * role["ranged"] + 0.05 * role["command"]
        return (attack * 0.52 + defense * 0.24 + proximity + support_pressure) * risk_factor - wounded * 0.15, enemy

    primary = max(active_enemy, key=lambda r: threat_score(r))
    objective_low = objective.lower()
    desired = "restrict_primary_threat"
    if any(token in objective_low for token in ("protect", "guard", "escort", "defend")):
        desired = "protect_principal_and_control_approaches"
    elif any(token in objective_low for token in ("escape", "withdraw", "extract", "retreat")):
        desired = "open_retreat_corridor"
    elif len(active_enemy) > len(active_side):
        desired = "avoid_encirclement_and_isolate_one_threat"
    elif len(active_side) > 1:
        surround = surrounding_pressure(primary, active_side, positions)
        desired = "compress_escape_arcs" if not surround["surrounded"] else "exploit_cross_angle_pressure"
    if range_preference == "ranged" and not desired.startswith("protect"):
        desired = "preserve_ranged_spacing_and_intercept_closers"
    elif range_preference == "close" and not desired.startswith("protect"):
        desired = "close_decisively_and_deny_enemy_space"

    roles = ["control", "shape", "tracking", "interception", "pressure", "exploit"]
    if "protect" in desired:
        roles.insert(0, "protection")
    assignments: dict[str, dict[str, Any]] = {}
    remaining = set(active_side)
    assigned_target_counts: dict[str, int] = {enemy: 0 for enemy in active_enemy}

    protected_ref = None
    if "protect" in desired and active_side:
        explicit_protected = [str(r) for r in protected_refs if str(r) in active_side]
        protected_ref = explicit_protected[0] if explicit_protected else min(active_side, key=lambda r: (caps[r]["tracking"], caps[r]["pressure"], r))

    def target_for_role(role: str, actor_ref: str) -> str:
        """Allocate real threat lanes before permitting gratuitous dog-piling.

        Concentrating on a dangerous primary threat remains lawful, but an equal
        3v3 should not have all three fighters ignore two active enemies merely
        because one primary scored a few points higher.  Every uncontained enemy
        represents independent attack/defense timing pressure.  The load penalty
        below is tactical target selection only; it grants no combat bonus and
        does not prevent a side from focusing fire when the primary threat is
        sufficiently more dangerous.
        """
        def role_value(enemy: str) -> float:
            base = float(threat_score(enemy)[0])
            role_data = enemy_roles[enemy]
            if role in {"control", "pressure"}:
                base += 22.0 if enemy == primary else 0.0
            elif role == "shape":
                base += .75 * role_data["ranged"] + .45 * role_data["command"] + .18 * role_data["mobility"]
            elif role == "interception":
                base += 1.00 * role_data["ranged"] + .34 * role_data["command"] + .32 * role_data["mobility"]
            elif role == "tracking":
                base += .34 * role_data["ranged"] + .38 * role_data["command"] + .72 * role_data["mobility"]
            elif role == "exploit":
                base += _health_pressure(people[enemy]) * 1.45
            elif role == "protection" and protected_ref in positions and enemy in positions:
                base += max(0.0, 30.0 - distance_2d(positions[protected_ref], positions[enemy]) * 5.0)
            if actor_ref in positions and enemy in positions:
                base += max(0.0, 10.0 - distance_2d(positions[actor_ref], positions[enemy]) * 1.5)

            already = assigned_target_counts.get(enemy, 0)
            # When the sides are equal/outnumbered, the first assignment to each
            # independent threat is strongly preferred.  With numerical surplus,
            # extra attackers can lawfully stack onto a target sooner.
            lane_penalty = 34.0 if len(active_side) <= len(active_enemy) else 21.0
            base -= already * lane_penalty
            if already == 0:
                base += 12.0
            return base
        return max(active_enemy, key=lambda enemy: (role_value(enemy), enemy))

    for role in roles:
        if not remaining:
            break
        chosen = max(remaining, key=lambda r: (caps[r].get(role, 0.0), caps[r]["tracking"], r))
        target = target_for_role(role, chosen)
        assignment = {"role": role, "target_ref": target, "capability_score": round(caps[chosen].get(role, 0.0), 4)}
        if role == "protection" and protected_ref and protect_priority != "ignore":
            assignment["protect_ref"] = protected_ref
        assignments[chosen] = assignment
        assigned_target_counts[target] = assigned_target_counts.get(target, 0) + 1
        remaining.remove(chosen)
    for ref in sorted(remaining):
        target = target_for_role("support", ref)
        assignments[ref] = {"role": "support", "target_ref": target, "capability_score": round(caps[ref]["tracking"], 4)}
        assigned_target_counts[target] = assigned_target_counts.get(target, 0) + 1

    # Plan identity is tactical-state identity, not wall-clock identity.  Using
    # `at_s` here caused the same unchanged plan to be re-created on every
    # scheduler callback and bloated plan history.  A new plan is born only
    # when the active participants, primary threat, desired state, or role/target
    # assignment changes.
    assignment_signature = ",".join(
        f"{ref}:{assignments[ref].get('role')}:{assignments[ref].get('target_ref')}"
        for ref in sorted(assignments)
    )
    primary_pressure = surrounding_pressure(primary, active_side, positions)
    pressure_bucket = int(_num(primary_pressure.get("covered_arc_deg"), 0.0) // 45.0)
    failure_bucket = min(3, sum(max(0, int(v)) for v in (recent_failures or {}).values()))
    token = "|".join([
        ",".join(sorted(active_side)), ",".join(sorted(active_enemy)),
        primary, desired, assignment_signature,
        f"surrounded:{int(bool(primary_pressure.get('surrounded')))}:{pressure_bucket}",
        f"failures:{failure_bucket}",
        f"doctrine:{range_preference}:{risk_tolerance}:{protect_priority}",
    ])
    plan_id = "teamplan_" + hashlib.sha256(token.encode()).hexdigest()[:12]
    return {
        "plan_id": plan_id,
        "at_s": round(at_s, 6),
        "leader_ref": leader,
        "primary_threat_ref": primary,
        "immediate_problem": "enemy freedom of movement and attack timing" if desired.startswith("restrict") else desired.replace("_", " "),
        "desired_state": desired,
        "assignments": assignments,
        "known_enemy_refs": list(active_enemy),
        "doctrine_inputs": {
            "engagement_distance": range_preference,
            "risk_tolerance": risk_tolerance,
            "protection_priority": protect_priority,
        },
        "replan_state": {
            "primary_surrounded": bool(primary_pressure.get("surrounded")),
            "covered_arc_bucket": pressure_bucket,
            "recent_failure_bucket": failure_bucket,
        },
        "decision_source": "team_ai",
    }


def _engagement_band(distance_m: float, *, withdrawing: bool = False) -> int:
    """Return a broad physical-engagement band, not weapon reach.

    Exact contact, reach and movement remain personal-combat resolver authority.
    This coarse band exists only so team doctrine cannot make an AI fighter
    ignore a person who is physically threatening them now in order to chase a
    remote or retreating preferred target.
    """
    distance = max(0.0, float(distance_m))
    if distance <= 2.5:
        band = 0
    elif distance <= 6.0:
        band = 1
    elif distance <= 12.0:
        band = 2
    elif distance <= 25.0:
        band = 3
    else:
        band = 4
    if withdrawing and band < 4:
        band += 1
    return band


def choose_tactical_target(
    actor_ref: str,
    candidates: Sequence[str],
    *,
    plan: Mapping[str, Any] | None,
    people: Mapping[str, Mapping[str, Any]],
    positions: Mapping[str, Mapping[str, Any]],
    motion_vectors: Mapping[str, Mapping[str, Any]] | None = None,
) -> str | None:
    """Choose an AI target with local geometry ahead of team preference.

    Team assignments remain meaningful among physically comparable threats, but
    they cannot force an actor to ignore immediate/near contact for a remote or
    actively withdrawing opponent.  This function never resolves reach/contact.
    """
    known = {str(x) for x in (plan or {}).get("known_enemy_refs", [])} if isinstance((plan or {}).get("known_enemy_refs"), list) else set()
    alive = [r for r in candidates if r in people and not bool((people[r].get("combat_state") or {}).get("incapacitated")) and (not known or r in known)]
    if not alive:
        return None
    assignment = (plan or {}).get("assignments", {}).get(actor_ref, {}) if isinstance((plan or {}).get("assignments"), Mapping) else {}
    role = str(assignment.get("role", "support"))
    primary = str(assignment.get("target_ref") or (plan or {}).get("primary_threat_ref") or "")
    motion_vectors = motion_vectors or {}

    def geometry(target: str) -> tuple[int, float, bool]:
        if actor_ref not in positions or target not in positions:
            return 4, 100.0, False
        actor = positions[actor_ref]
        target_pos = positions[target]
        distance = distance_2d(actor, target_pos)
        moving_away = False
        motion = motion_vectors.get(target, {})
        if isinstance(motion, Mapping) and distance > 1e-6:
            vx = _num(motion.get("vx_mps"))
            vy = _num(motion.get("vy_mps"))
            dx = _num(target_pos.get("x_m")) - _num(actor.get("x_m"))
            dy = _num(target_pos.get("y_m")) - _num(actor.get("y_m"))
            radial_velocity = (vx * dx + vy * dy) / max(distance, 1e-6)
            moving_away = radial_velocity > 0.15
        return _engagement_band(distance, withdrawing=moving_away), distance, moving_away

    geometry_by_target = {target: geometry(target) for target in alive}
    best_band = min(row[0] for row in geometry_by_target.values())

    # The standing assignment may win inside one adjacent physical band.  That
    # is enough room for doctrine/role coordination without permitting a chase
    # past an immediate threat.  Active withdrawal itself worsens the target's
    # band, so a retreating preferred target loses this privilege sooner.
    if role in {"control", "shape", "tracking", "interception", "pressure", "protection", "support"} and primary in alive:
        primary_band, _distance, primary_withdrawing = geometry_by_target[primary]
        if primary_band <= best_band + 1 and not (primary_withdrawing and primary_band > best_band):
            return primary

    comparable = [target for target in alive if geometry_by_target[target][0] <= best_band + 1]

    def score(target: str) -> tuple[float, str]:
        band, d, moving_away = geometry_by_target[target]
        injury = _health_pressure(people[target])
        assignment_bonus = 16.0 if target == primary else 0.0
        withdrawal_penalty = 12.0 if moving_away else 0.0
        geometry_penalty = max(0, band - best_band) * 18.0
        if role == "exploit":
            value = injury * 1.6 - d * 2.0 + assignment_bonus - withdrawal_penalty - geometry_penalty
        else:
            value = -d * 2.0 + injury * 0.4 + assignment_bonus - withdrawal_penalty - geometry_penalty
        return value, target
    return max(comparable, key=score)


def flank_vector(actor_ref: str, target_ref: str, positions: Mapping[str, Mapping[str, Any]], *, clockwise: bool) -> tuple[float, float]:
    if actor_ref not in positions or target_ref not in positions:
        return (0.0, 0.0)
    a = positions[actor_ref]
    t = positions[target_ref]
    dx = _num(a.get("x_m")) - _num(t.get("x_m"))
    dy = _num(a.get("y_m")) - _num(t.get("y_m"))
    mag = max(1e-6, math.hypot(dx, dy))
    ux, uy = dx / mag, dy / mag
    return ((uy, -ux) if clockwise else (-uy, ux))


def attack_detection_assessment(
    defender_ref: str,
    attacker_ref: str,
    *,
    controls: Mapping[str, Mapping[str, Any]],
    positions: Mapping[str, Mapping[str, Any]],
    facing_deg: float,
    reaction_seconds: float,
    contact_at_s: float,
    attack_start_at_s: float,
    awareness_factor: float = 1.0,
    visual_factor: float = 1.0,
    concealment_factor: float = 1.0,
    attention_factor: float = 1.0,
) -> dict[str, Any]:
    """Return bounded physical perception of one incoming attack.

    This is deliberately not a hidden binary skill roll.  It combines the
    defender's saved awareness/control, available startup time and relative
    facing into a deterministic quality.  Low quality restricts active defense;
    a pre-declared guard can still physically cover its existing lane.
    """
    if defender_ref not in positions or attacker_ref not in positions:
        return {"detected": False, "quality": 0.0, "reason": "missing_local_geometry"}
    defender = positions[defender_ref]
    attacker = positions[attacker_ref]
    incoming = bearing_deg(defender, attacker)
    facing_delta = angle_delta_deg(incoming, facing_deg)
    arc_factor = 1.0 if facing_delta <= 75.0 else (0.82 if facing_delta <= 120.0 else (0.58 if facing_delta <= 160.0 else 0.38))
    awareness = max(0.0, _num(controls.get(defender_ref, {}).get("awareness")))
    distance = distance_2d(defender, attacker)
    available = max(0.0, float(contact_at_s) - float(attack_start_at_s))
    reaction = max(0.04, float(reaction_seconds))
    time_factor = min(1.25, available / reaction) if reaction > 0 else 1.25
    base = 0.34 + math.sqrt(awareness) / 23.0
    visual_quality = (
        base
        * arc_factor
        * max(0.05, float(awareness_factor))
        * max(0.0, min(1.0, float(visual_factor)))
        * max(0.05, float(concealment_factor))
        * max(0.05, float(attention_factor))
        * max(0.08, min(1.25, time_factor))
    )
    # Sound, ground vibration, weapon contact and air movement still provide a
    # close-range warning path when vision is unavailable. It is intentionally
    # weaker, strongly distance-limited and does not gain a visual facing bonus.
    nonvisual_proximity = max(0.05, min(1.0, 1.0 - max(0.0, distance - 0.5) / 7.5))
    nonvisual_quality = (
        (0.16 + math.sqrt(awareness) / 34.0)
        * max(0.05, float(awareness_factor))
        * max(0.05, float(attention_factor))
        * nonvisual_proximity
        * max(0.08, min(1.10, time_factor))
    )
    quality = max(visual_quality, nonvisual_quality)
    quality = max(0.0, min(1.0, quality))
    return {
        "detected": quality >= 0.22,
        "meaningful_reaction": quality >= 0.38,
        "quality": round(quality, 6),
        "incoming_bearing_deg": round(incoming, 6),
        "facing_delta_deg": round(facing_delta, 6),
        "available_warning_seconds": round(available, 6),
        "reaction_seconds": round(reaction, 6),
        "visual_factor": round(max(0.0, min(1.0, float(visual_factor))), 6),
        "visual_quality": round(max(0.0, min(1.0, visual_quality)), 6),
        "nonvisual_quality": round(max(0.0, min(1.0, nonvisual_quality)), 6),
        "reason": "deterministic_local_perception",
    }


def physical_defense_preferences(
    defender_ref: str,
    attacker_ref: str,
    *,
    people: Mapping[str, Mapping[str, Any]],
    equipment: Mapping[str, Mapping[str, Any]],
    controls: Mapping[str, Mapping[str, Any]],
    positions: Mapping[str, Mapping[str, Any]],
    legal_methods: Sequence[str],
    detection_quality: float,
    surrounded: bool,
    incoming_angle_from_facing_deg: float,
    projectile: bool,
) -> dict[str, float]:
    """Score lawful *physical* responses from saved capability and geometry."""
    person = people[defender_ref]
    skills, attrs = _stats(person)
    eq = equipment.get(defender_ref, {})
    ctrl = controls.get(defender_ref, {})
    burden = eq.get("burden", {}) if isinstance(eq.get("burden"), Mapping) else {}
    move = max(0.25, _num(burden.get("movement_factor"), 1.0))
    armor = eq.get("armor", {}) if isinstance(eq.get("armor"), Mapping) else {}
    armor_mass = max(0.0, _num(armor.get("mass_kg"), 0.0))
    strength = max(0.0, _num(attrs.get("Strength")))
    endurance = max(0.0, _num(attrs.get("Endurance")))
    weapon_skill = max(0.0, _num(ctrl.get("weapon_skill")))
    grappling = max(_num(skills.get("Grappling")), _num(skills.get("Wrestling")))
    scores: dict[str, float] = {}
    for method in legal_methods:
        if method == "dodge":
            score = _num(ctrl.get("dodge")) * (0.78 + 0.22 * move)
            if surrounded:
                score *= 0.80
            if incoming_angle_from_facing_deg > 150:
                score *= 0.84
        elif method == "reposition":
            score = _num(ctrl.get("dodge")) * (0.88 + 0.18 * move)
            if surrounded:
                score *= 1.16
        elif method == "block":
            score = _num(ctrl.get("block")) + min(10.0, armor_mass * 0.20) + strength * 0.035
        elif method == "parry":
            score = _num(ctrl.get("parry")) + weapon_skill * 0.055
        elif method == "deflect":
            score = _num(ctrl.get("parry")) * 0.94 + weapon_skill * 0.045 + _num(attrs.get("Coordination")) * 0.035
            if projectile:
                score *= 0.62
        elif method == "brace":
            score = 0.28 * max(weapon_skill, _num(skills.get("Shield"))) + 0.28 * strength + 0.24 * endurance + 0.20 * _num(attrs.get("Composure"))
            score += min(12.0, armor_mass * 0.32)
        elif method == "counter_intercept":
            score = 0.38 * _num(ctrl.get("attack")) + 0.24 * weapon_skill + 0.16 * _num(attrs.get("Awareness")) + 0.12 * _num(attrs.get("Coordination")) + 0.10 * grappling
            if projectile:
                score *= 0.12
        else:
            score = 0.0
        scores[method] = max(0.0, score) * max(0.12, min(1.0, float(detection_quality)))
    return scores


__all__ = [
    "attack_detection_assessment",
    "build_team_plan",
    "choose_tactical_target",
    "flank_vector",
    "physical_defense_preferences",
]
