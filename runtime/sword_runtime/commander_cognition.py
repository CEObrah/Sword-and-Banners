"""Deterministic commander cognition and institutional decision policy.

This module changes what a commander notices and which lawful operational choice
that commander prefers. It never adds combat power or reveals hidden enemy state.
Explicit registered command staff may hold scoped order-transmission authority in
their own command subtree, but cognition itself never creates that authority.
Exact mutable facts remain in their normal owners; cognitive style is derived on
read from exact saved capability and small canonical static profiles.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.stat_access import merged_skill_map

COGNITION_PATH = "game/data/mil/commander-cognition.json"
STATE_IDENTITY_PATH = "game/data/balance/state-military-identities.json"
BEHAVIOR_INDEX_PATH = "game/data/people/behavior-profile-index.json"

_DIMENSIONS = (
    "analytical_planning",
    "pattern_recognition",
    "instinctive_opportunity_detection",
    "adaptability",
    "deception_literacy",
    "risk_tolerance",
    "initiative",
    "patience",
    "information_discipline",
    "command_presence",
)


def _clamp_milli(value: Any) -> int:
    try:
        return max(0, min(1000, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _person(planner: Any, person_ref: str | None) -> Mapping[str, Any] | None:
    if not isinstance(person_ref, str) or not person_ref:
        return None
    try:
        row = planner.read(planner.owner_path(person_ref))
    except (FileNotFoundError, KeyError, ValueError):
        return None
    if not isinstance(row, Mapping) or row.get("schema") not in {"sab_character", "sword-materialized-person", "person-lite"}:
        return None
    return row


def _read_optional(planner: Any, path: str) -> Mapping[str, Any]:
    try:
        row = planner.read(path)
    except (FileNotFoundError, KeyError, ValueError):
        return {}
    return row if isinstance(row, Mapping) else {}


def state_military_identity(planner: Any, side_ref: str | None) -> dict[str, Any]:
    """Return one canonical institutional profile without mutable-state duplication."""
    if not isinstance(side_ref, str) or not side_ref:
        return {}
    state = side_ref.lower().removeprefix("state_")
    registry = _read_optional(planner, STATE_IDENTITY_PATH)
    rows = registry.get("states", {}) if isinstance(registry.get("states"), Mapping) else {}
    raw = rows.get(state.upper()) or rows.get(state) or {}
    if not isinstance(raw, Mapping):
        return {"state": state, "summary": str(raw)} if raw else {}
    result = dict(raw)
    result.setdefault("state", state)
    return result


def _behavior_profile(planner: Any, person_ref: str | None, person: Mapping[str, Any] | None) -> tuple[str | None, Mapping[str, Any]]:
    """Load one cold static behavior profile when a registered decision system needs it.

    The profile remains non-authoritative guidance.  It is never copied into hot
    character state and never grants knowledge or capability.
    """
    path = person.get("behavior_profile_ref") if isinstance(person, Mapping) else None
    if not isinstance(path, str) or not path:
        index = _read_optional(planner, BEHAVIOR_INDEX_PATH)
        profiles = index.get("profiles", {}) if isinstance(index.get("profiles"), Mapping) else {}
        path = profiles.get(person_ref) if isinstance(person_ref, str) else None
    if not isinstance(path, str) or not path:
        return None, {}
    row = _read_optional(planner, path)
    if row.get("schema") != "behavior-profile" or row.get("person_id") != person_ref:
        return None, {}
    behavior = row.get("behavior", {})
    return path, behavior if isinstance(behavior, Mapping) else {}


def _behavior_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(_behavior_text(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_behavior_text(v) for v in value)
    return str(value or "")


def _apply_behavior_cues(
    dims: dict[str, int],
    behavior: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> list[str]:
    """Apply bounded, registered interpretation of existing static behavior text.

    Free prose never directly becomes mechanics.  Only phrases explicitly listed in
    the cognition registry can bias cognition, and the total shift per dimension is
    capped so capability remains the primary derived input.
    """
    cue_map = registry.get("behavior_cue_biases", {}) if isinstance(registry.get("behavior_cue_biases"), Mapping) else {}
    if not behavior or not cue_map:
        return []
    text = _behavior_text(behavior).casefold()
    shifts = {key: 0 for key in _DIMENSIONS}
    matched: list[str] = []
    for cue, raw_bias in cue_map.items():
        if not isinstance(cue, str) or cue.casefold() not in text or not isinstance(raw_bias, Mapping):
            continue
        matched.append(cue)
        for key, raw in raw_bias.items():
            if key not in shifts:
                continue
            try:
                shifts[key] += int(raw)
            except (TypeError, ValueError):
                continue
    for key, shift in shifts.items():
        dims[key] = _clamp_milli(dims[key] + max(-150, min(150, shift)))
    return sorted(set(matched))


def _base_dimensions(person: Mapping[str, Any] | None) -> dict[str, int]:
    if not isinstance(person, Mapping):
        return {key: 500 for key in _DIMENSIONS}
    skills = merged_skill_map(person)

    def s(name: str, default: float = 0.0) -> float:
        try:
            return max(0.0, min(200.0, float(skills.get(name, default) or 0.0)))
        except (TypeError, ValueError):
            return default

    strategy = s("Strategy")
    tactics = s("Tactics")
    formation = s("Formation Command")
    leadership = s("Leadership")
    logistics = s("Logistics")
    scouting = s("Scouting")
    stealth = s("Stealth")
    fighting = s("Formation Fighting")
    survival = s("Survival")

    def scale(raw: float) -> int:
        return _clamp_milli(raw * 5.0)

    return {
        "analytical_planning": scale(0.46 * strategy + 0.30 * tactics + 0.24 * formation),
        "pattern_recognition": scale(0.38 * tactics + 0.30 * formation + 0.18 * strategy + 0.14 * scouting),
        "instinctive_opportunity_detection": scale(0.32 * tactics + 0.22 * leadership + 0.20 * fighting + 0.14 * scouting + 0.12 * survival),
        "adaptability": scale(0.38 * tactics + 0.26 * strategy + 0.22 * leadership + 0.14 * formation),
        "deception_literacy": scale(0.42 * strategy + 0.30 * tactics + 0.16 * stealth + 0.12 * scouting),
        "risk_tolerance": scale(0.32 * leadership + 0.28 * fighting + 0.24 * tactics + 0.16 * survival),
        "initiative": scale(0.38 * tactics + 0.30 * leadership + 0.20 * fighting + 0.12 * scouting),
        "patience": scale(0.44 * strategy + 0.34 * logistics + 0.22 * formation),
        "information_discipline": scale(0.42 * strategy + 0.34 * logistics + 0.14 * scouting + 0.10 * tactics),
        "command_presence": scale(0.58 * leadership + 0.24 * formation + 0.18 * fighting),
    }


def commander_cognition(planner: Any, person_ref: str | None, *, side_ref: str | None = None) -> dict[str, Any]:
    """Derive one bounded cognition profile from capability plus canonical style.

    Specific canonical overrides describe *how* a famous commander uses capability;
    they do not grant extra troop strength.  Institutional style supplies a modest
    fallback/blend so leaderless state commands are not seven identical AIs.
    """
    person = _person(planner, person_ref)
    dims = _base_dimensions(person)
    registry = _read_optional(planner, COGNITION_PATH)
    behavior_profile_ref, behavior = _behavior_profile(planner, person_ref, person)
    behavior_cues = _apply_behavior_cues(dims, behavior, registry)
    overrides = registry.get("people", {}) if isinstance(registry.get("people"), Mapping) else {}
    override = overrides.get(person_ref, {}) if isinstance(overrides, Mapping) and person_ref else {}
    if isinstance(override, Mapping):
        specific = override.get("dimensions", {}) if isinstance(override.get("dimensions"), Mapping) else {}
        for key, value in specific.items():
            if key in dims:
                dims[key] = _clamp_milli(value)

    identity = state_military_identity(planner, side_ref)
    institutional = identity.get("cognition_bias_milli", {}) if isinstance(identity.get("cognition_bias_milli"), Mapping) else {}
    blend = 0.12 if person is not None else 0.45
    for key in _DIMENSIONS:
        if key not in institutional:
            continue
        target = _clamp_milli(institutional[key])
        dims[key] = _clamp_milli((1.0 - blend) * dims[key] + blend * target)

    archetype = str(override.get("archetype", "derived")) if isinstance(override, Mapping) else "derived"
    return {
        "person_ref": person_ref if person is not None else None,
        "archetype": archetype,
        "dimensions_milli": dims,
        "institutional_state": identity.get("state"),
        "behavior_profile_ref": behavior_profile_ref,
        "behavior_cues": behavior_cues,
        "rule": "Cognition changes observation discipline, revision thresholds, risk and reserve behavior; static behavior cues are bounded registered biases and never add direct combat strength or hidden knowledge.",
    }


def _primary_command_group(planner: Any, person_ref: str | None) -> Mapping[str, Any] | None:
    """Resolve one exact command group actually commanded by this person."""
    if not isinstance(person_ref, str) or not person_ref:
        return None
    index = _read_optional(planner, "state/cmd/command-groups/index.json")
    template = index.get("path_template")
    if not isinstance(template, str) or not template:
        return None
    primary = index.get("primary_person_group") if isinstance(index.get("primary_person_group"), Mapping) else {}
    routes = index.get("command_person_groups") if isinstance(index.get("command_person_groups"), Mapping) else {}
    candidates: list[str] = []
    primary_ref = primary.get(person_ref) if isinstance(primary, Mapping) else None
    if isinstance(primary_ref, str) and primary_ref:
        candidates.append(primary_ref)
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
        row = _read_optional(planner, path)
        if row.get("schema") == "command-group" and str(row.get("commander_ref") or "") == person_ref:
            return row
    return None


def _strategist_support(planner: Any, commander_ref: str | None, group: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return bounded support from explicitly assigned strategist staff.

    A strategist may improve report handling, plan revision, intent transmission and
    direct-command burden. The appointment also carries only the registered
    recursive operational-order scope of its command node. It never creates
    intelligence, combat strength, troop ownership, succession, or authority
    outside that subtree.
    """
    if not isinstance(group, Mapping):
        return {"strategist_refs": [], "support_milli": 0}
    assignments = group.get("role_assignments") if isinstance(group.get("role_assignments"), Mapping) else {}
    refs = sorted(
        str(ref) for ref, role in assignments.items()
        if str(role).casefold() == "strategist" and str(ref) != str(commander_ref or "")
    )
    if not refs:
        return {"strategist_refs": [], "support_milli": 0}
    scores: list[int] = []
    valid_refs: list[str] = []
    for ref in refs:
        person = _person(planner, ref)
        if not isinstance(person, Mapping):
            continue
        skills = merged_skill_map(person)

        def skill(name: str) -> float:
            try:
                return max(0.0, min(200.0, float(skills.get(name, 0) or 0)))
            except (TypeError, ValueError):
                return 0.0

        raw = (
            0.42 * skill("Strategy")
            + 0.24 * skill("Tactics")
            + 0.20 * skill("Logistics")
            + 0.14 * skill("Formation Command")
        )
        scores.append(_clamp_milli(raw * 5.0))
        valid_refs.append(ref)
    if not scores:
        return {"strategist_refs": [], "support_milli": 0}
    best = max(scores)
    secondary = sum(sorted(scores, reverse=True)[1:]) // max(1, 5 * (len(scores) - 1)) if len(scores) > 1 else 0
    support = max(0, min(900, best + secondary))
    return {
        "strategist_refs": valid_refs[:16],
        "strategist_count": len(valid_refs),
        "strategist_refs_truncated": len(valid_refs) > 16,
        "support_milli": support,
        "rule": "Every valid assigned strategist contributes to bounded staff support; strategist_refs is inspection-only and may be truncated. Strategist support affects report discipline, plan revision, intent transmission and direct-command burden. Any recursive order authority comes only from the explicit strategist appointment on that command group; it grants no hidden knowledge, combat strength, troop ownership or succession.",
    }


def command_decision_policy(planner: Any, person_ref: str | None, *, side_ref: str | None = None, command_group: Mapping[str, Any] | None = None) -> dict[str, Any]:
    cognition = commander_cognition(planner, person_ref, side_ref=side_ref)
    group = command_group if isinstance(command_group, Mapping) else _primary_command_group(planner, person_ref)
    strategist = _strategist_support(planner, person_ref, group)
    d = cognition["dimensions_milli"]
    identity = state_military_identity(planner, side_ref)
    institutional = identity.get("operational_bias_milli", {}) if isinstance(identity.get("operational_bias_milli"), Mapping) else {}

    risk = d["risk_tolerance"] / 1000.0
    patience = d["patience"] / 1000.0
    initiative = d["initiative"] / 1000.0
    info = d["information_discipline"] / 1000.0
    adapt = d["adaptability"] / 1000.0
    instinct = d["instinctive_opportunity_detection"] / 1000.0
    reserve_bias = max(0.0, min(1.0, float(institutional.get("reserve_bias", 500) or 500) / 1000.0))
    casualty_tolerance = max(0.0, min(1.0, float(institutional.get("casualty_tolerance", 500) or 500) / 1000.0))

    # Thresholds remain deliberately bounded so style cannot override physical reality.
    offensive_ratio = 1.30 + 0.22 * patience + 0.08 * info - 0.28 * risk - 0.08 * initiative
    neutral_ratio = 1.62 + 0.20 * patience + 0.08 * info - 0.22 * risk - 0.08 * instinct
    withdraw_ratio = 0.62 + 0.10 * (1.0 - risk) + 0.05 * info - 0.08 * casualty_tolerance
    attacker_reserve_need = 1.10 + 0.11 * reserve_bias + 0.06 * patience - 0.12 * risk
    defender_reserve_trigger = 1.15 + 0.10 * reserve_bias + 0.05 * patience - 0.10 * risk
    confidence_floor = 0.42 + 0.30 * info + 0.08 * patience
    revision_pressure = 0.55 + 0.18 * patience + 0.12 * info - 0.18 * adapt - 0.08 * instinct

    # Staff support changes command-processing burden, not the underlying facts.
    # The bounded adjustment is intentionally modest even for an exceptional strategist.
    staff = max(0.0, min(0.9, float(strategist.get("support_milli", 0) or 0) / 1000.0))
    confidence_floor -= 0.08 * staff
    revision_pressure -= 0.10 * staff

    return {
        "cognition": cognition,
        "offensive_advantage_required_milli": int(round(max(1.05, min(1.65, offensive_ratio)) * 1000)),
        "neutral_advantage_required_milli": int(round(max(1.20, min(1.95, neutral_ratio)) * 1000)),
        "withdraw_if_local_ratio_below_milli": int(round(max(0.42, min(0.82, withdraw_ratio)) * 1000)),
        "attacker_reserve_commit_if_ratio_below_milli": int(round(max(0.92, min(1.30, attacker_reserve_need)) * 1000)),
        "defender_reserve_commit_if_enemy_ratio_above_milli": int(round(max(1.02, min(1.42, defender_reserve_trigger)) * 1000)),
        "report_confidence_floor_milli": int(round(max(0.35, min(0.82, confidence_floor)) * 1000)),
        "revision_pressure_threshold_milli": int(round(max(0.35, min(0.82, revision_pressure)) * 1000)),
        "pursuit_limit_milli": int(round(max(450, min(1150, 540 + 430 * risk + 180 * initiative - 200 * patience)))),
        "subordinate_initiative_envelope_milli": int(round(max(300, min(950, 420 + 280 * adapt + 220 * initiative + 120 * instinct - 80 * patience + 90 * staff)))),
        "direct_command_capacity_support_milli": int(round(160 * staff)),
        "strategist_support": strategist,
        "institutional_identity_ref": STATE_IDENTITY_PATH if identity else None,
    }


def campaign_side_policy(planner: Any, side_ref: str, commands: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Select the represented lead planner and return a compact side policy."""
    ranked: list[tuple[float, str]] = []
    for row in commands:
        person_ref = row.get("commander_ref")
        if not isinstance(person_ref, str) or _person(planner, person_ref) is None:
            continue
        cog = commander_cognition(planner, person_ref, side_ref=side_ref)
        d = cog["dimensions_milli"]
        score = (
            d["analytical_planning"] * 0.30
            + d["adaptability"] * 0.22
            + d["information_discipline"] * 0.20
            + d["pattern_recognition"] * 0.16
            + d["command_presence"] * 0.12
        )
        ranked.append((score, person_ref))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    lead = ranked[0][1] if ranked else None
    policy = command_decision_policy(planner, lead, side_ref=side_ref)
    policy["lead_commander_ref"] = lead
    policy["authority_envelope"] = {
        "may_improvise_within_assigned_objective": policy["subordinate_initiative_envelope_milli"] >= 500,
        "must_preserve_campaign_objective": True,
        "cannot_invent_enemy_knowledge": True,
        "cannot_transfer_manpower_or_ownership": True,
    }
    return policy


__all__ = [
    "COGNITION_PATH",
    "STATE_IDENTITY_PATH",
    "commander_cognition",
    "command_decision_policy",
    "campaign_side_policy",
    "state_military_identity",
]
