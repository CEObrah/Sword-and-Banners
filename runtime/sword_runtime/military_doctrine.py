"""Registered standing doctrine for armies and fighting formations.

Doctrine is persistent command procedure, not combat power.  Command-group
standing doctrine governs how an army applies its mission and delegates within
it; formation doctrine governs the local fighting method of one conserved body.
Commander cognition decides how well and how flexibly those procedures are
applied.  No doctrine creates manpower, knowledge, equipment or a flat strength
bonus.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Callable

from sword_runtime.static_records import load_doctrine_record, load_loadout
from sword_runtime.military_loadouts import institutional_role_loadout_id

_POLICY_REGISTRY_PATH = "game/data/mil/doctrine-policy-registry.json"

_STATE_ARMY_DOCTRINES = {
    state: f"doc.state_{state}.field_army"
    for state in ("qin", "zhao", "wei", "chu", "yan", "qi", "han")
}


def _dominant_role(formation: Mapping[str, Any]) -> str:
    composition = formation.get("composition") if isinstance(formation.get("composition"), Mapping) else {}
    rows: list[tuple[int, str]] = []
    for role, raw in composition.items():
        try:
            count = max(0, int(raw))
        except (TypeError, ValueError):
            continue
        if count:
            rows.append((count, str(role)))
    return max(rows, default=(0, "line_infantry"))[1]


def role_doctrine_defaults(role: str) -> dict[str, Any]:
    """Return bounded local behavior defaults for one fighting role."""
    key = str(role or "").lower()
    if any(token in key for token in ("cavalry", "mounted", "chariot")):
        return {"casualty_tolerance": "moderate", "reserve_commitment": 70, "withdrawal_threshold": 35}
    if "artillery" in key:
        return {"casualty_tolerance": "low", "reserve_commitment": 35, "withdrawal_threshold": 45}
    if any(token in key for token in ("missile", "archer", "crossbow")):
        return {"casualty_tolerance": "low", "reserve_commitment": 55, "withdrawal_threshold": 40}
    if any(token in key for token in ("guard", "heavy")):
        return {"casualty_tolerance": "moderate", "reserve_commitment": 45, "withdrawal_threshold": 25}
    return {"casualty_tolerance": "moderate", "reserve_commitment": 50, "withdrawal_threshold": 30}


def default_formation_doctrine_ref(formation: Mapping[str, Any]) -> str:
    """Choose one registered doctrine from ownership and actual role mix."""
    admin = str(formation.get("administrative_owner") or "")
    force_ref = str(formation.get("owner_force_ref") or "")
    role = _dominant_role(formation).lower()

    if admin in {"polity_northern_steppe", "state_northern_steppe"}:
        return "doc.organization.steppe_confederation"
    if admin in {"polity_yotanwa_confederation", "state_yotanwa_confederation"}:
        return "doc.organization.mountain_force"
    if admin in {"polity_quanrong", "state_quanrong"}:
        return "doc.organization.raider_band"
    if admin == "house_tang" or force_ref.startswith("force_house_tang") or force_ref == "force_tang_wei_personal":
        if "cavalry" in role or "mounted" in role:
            return "doc.house_tang.house_cavalry"
        return "doc.house_tang.house_infantry"
    if admin.startswith("house_") or force_ref.startswith("force_house_"):
        return "household_combined_arms"
    if admin.startswith("state_"):
        if "chariot" in role:
            return "doc.external_state_force.chariot"
        if "heavy_cavalry" in role:
            return "doc.external_state_force.heavy_cavalry"
        if "mounted_archer" in role:
            return "doc.external_state_force.mounted_archer"
        if "cavalry" in role or "mounted" in role:
            return "doc.external_state_force.cavalry"
        if role == "archer" or role.endswith("_archer"):
            return "doc.external_state_force.archer"
        if any(token in role for token in ("missile", "crossbow")):
            return "doc.external_state_force.missile_crossbow"
        return "doc.external_state_force.line_infantry"
    return "doc.world_force.standard"


def default_command_group_doctrine_ref(group: Mapping[str, Any]) -> str:
    """Return the standing command doctrine for one zero-body army command."""
    existing = group.get("standing_doctrine_ref")
    if isinstance(existing, str) and existing:
        return existing
    ref = str(group.get("id") or "")
    authority = str(group.get("authority_ref") or "")
    context = str(group.get("context") or "").lower()
    if ref == "cmdgrp.tang_wei.field_army":
        return "doc.tang_wei.field_army"
    if authority.startswith("state_"):
        state = authority.removeprefix("state_").lower()
        if state in _STATE_ARMY_DOCTRINES:
            return _STATE_ARMY_DOCTRINES[state]
    if authority == "house_tang" or ref.startswith("cmdgrp.house_tang"):
        return "doc.house_tang.core"
    if authority == "pforce.tang_wei" or ref == "cmdgrp.tang_wei.personal_force":
        return "doc.house_tang.core"
    if authority.startswith("house_") or context == "private_house_field_army":
        return "household_combined_arms"
    return "doc.world_force.standard"



def formation_doctrine_ref_for_role(read_json: Callable[[str], Any], formation: Mapping[str, Any], role: str) -> str:
    per_role = formation.get("doctrine_refs_by_role") if isinstance(formation.get("doctrine_refs_by_role"), Mapping) else {}
    explicit = per_role.get(str(role)) if isinstance(per_role, Mapping) else None
    if isinstance(explicit, str) and explicit:
        return explicit
    parent_ref = str(formation.get("doctrine_ref") or default_formation_doctrine_ref(formation))
    parent = load_doctrine_record(read_json, parent_ref)
    doctrine = parent.get("doctrine", {}) if isinstance(parent.get("doctrine"), Mapping) else {}
    role_refs = doctrine.get("role_policy_refs") if isinstance(doctrine.get("role_policy_refs"), Mapping) else {}
    child = role_refs.get(str(role)) if isinstance(role_refs, Mapping) else None
    if isinstance(child, str) and child:
        return child
    return parent_ref


def _loadout_capabilities(loadout: Mapping[str, Any]) -> set[str]:
    caps: set[str] = set()
    ranged = str(loadout.get("ranged_weapon") or "")
    melee = " ".join(str(loadout.get(k) or "") for k in ("primary_melee_weapon", "sidearm"))
    ammo = str(loadout.get("ammunition_item") or "")
    armor = str(loadout.get("body_armor") or "")
    if loadout.get("mount"): caps.add("mount")
    if loadout.get("tack"): caps.add("tack")
    if loadout.get("shield"): caps.add("shield")
    if "bow" in ranged and "crossbow" not in ranged: caps.add("bow")
    if "crossbow" in ranged: caps.add("crossbow")
    if ammo == "ammo_arrow": caps.add("arrows")
    if ammo == "ammo_bolt": caps.add("bolts")
    if any(t in melee for t in ("spear", "lance", "glaive", "polearm")): caps.add("spear")
    if "sword" in melee: caps.add("sword")
    if "heavy" in armor: caps.add("heavy_body_armor")
    return caps


def doctrine_compatibility(read_json: Callable[[str], Any], formation: Mapping[str, Any], doctrine_ref: str, *, role: str | None = None) -> dict[str, Any]:
    record = load_doctrine_record(read_json, doctrine_ref)
    doctrine = record.get("doctrine", {}) if isinstance(record.get("doctrine"), Mapping) else {}
    requirements = read_json(_POLICY_REGISTRY_PATH).get("compatibility_requirements", {})
    actual_role = str(role or _dominant_role(formation))
    profile = {}
    loadout_ref = institutional_role_loadout_id(read_json, formation, actual_role, profile=profile)
    loadout = load_loadout(read_json, loadout_ref) if loadout_ref else {}
    caps = _loadout_capabilities(loadout)
    missing: dict[str, list[str]] = {}
    for capability in doctrine.get("compatibility", []) if isinstance(doctrine.get("compatibility"), list) else []:
        row = requirements.get(str(capability), {}) if isinstance(requirements, Mapping) else {}
        need = [str(x) for x in row.get("requires", [])] if isinstance(row, Mapping) else []
        absent = [x for x in need if x not in caps]
        if absent:
            missing[str(capability)] = absent
    return {"compatible": not missing, "doctrine_ref": doctrine_ref, "role": actual_role, "loadout_ref": loadout_ref or None, "missing": missing}


def _closed_formation_behavior(read_json: Callable[[str], Any], doctrine: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve executable local behavior from the closed formation policy registry.

    ``formation_policy_v2`` is canonical. ``formation_policy`` remains readable
    for older registered doctrines during campaign migration. Registry rows own
    effects; prose/principles never become executable policy.
    """
    raw = doctrine.get("formation_policy_v2")
    if not isinstance(raw, Mapping):
        raw = doctrine.get("formation_policy") if isinstance(doctrine.get("formation_policy"), Mapping) else {}
    registry = read_json(_POLICY_REGISTRY_PATH)
    choices = registry.get("formation_choices", {}) if isinstance(registry, Mapping) else {}
    out: dict[str, Any] = {}
    for dimension, choice in raw.items():
        rows = choices.get(str(dimension), {}) if isinstance(choices, Mapping) else {}
        row = rows.get(str(choice), {}) if isinstance(rows, Mapping) else {}
        effects = row.get("behavior", {}) if isinstance(row, Mapping) else {}
        if isinstance(effects, Mapping):
            for field, value in effects.items():
                out[str(field)] = copy.deepcopy(value)
    return out


def _closed_command_effects(read_json: Callable[[str], Any], doctrine: Mapping[str, Any]) -> dict[str, int]:
    policy = doctrine.get("command_policy_v2") if isinstance(doctrine.get("command_policy_v2"), Mapping) else {}
    registry = read_json(_POLICY_REGISTRY_PATH)
    choices = registry.get("command_choices", {}) if isinstance(registry, Mapping) else {}
    out: dict[str, int] = {}
    for dimension, choice in policy.items():
        rows = choices.get(str(dimension), {}) if isinstance(choices, Mapping) else {}
        row = rows.get(str(choice), {}) if isinstance(rows, Mapping) else {}
        effects = row.get("effects", {}) if isinstance(row, Mapping) else {}
        for field, raw in effects.items():
            try: out[str(field)] = out.get(str(field), 0) + int(raw)
            except (TypeError, ValueError): pass
    return out

def doctrine_behavior(
    read_json: Callable[[str], Any],
    formation: Mapping[str, Any],
    *,
    explicit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve local fighting behavior from the registered doctrine plus overrides.

    The doctrine record chooses the role profile when one exists.  Explicit saved
    behavior remains the current commander's deliberate local override.
    """
    role = _dominant_role(formation)
    doctrine_ref = str(formation.get("doctrine_ref") or default_formation_doctrine_ref(formation))
    record = load_doctrine_record(read_json, doctrine_ref)
    doctrine = record.get("doctrine", {}) if isinstance(record.get("doctrine"), Mapping) else {}
    profile_ref = str(doctrine.get("role_profile_ref") or "")
    if "#" in profile_ref:
        role = profile_ref.rsplit("#", 1)[-1] or role

    result = role_doctrine_defaults(role)
    result.update(_closed_formation_behavior(read_json, doctrine))
    current = formation.get("doctrine_behavior") if isinstance(formation.get("doctrine_behavior"), Mapping) else {}
    for source in (current, explicit or {}):
        # Mutable overrides remain deliberately narrow. Structural doctrine
        # permissions (anchors, pursuit, autonomous detachment) can only come
        # from a registered doctrine choice, never an ad-hoc payload.
        for key in ("reserve_commitment", "withdrawal_threshold", "casualty_tolerance", "extraction_priority"):
            if key in source:
                result[key] = copy.deepcopy(source[key])
    result["reserve_commitment"] = max(0, min(100, int(result.get("reserve_commitment", 50))))
    result["withdrawal_threshold"] = max(0, min(100, int(result.get("withdrawal_threshold", 30))))
    if str(result.get("casualty_tolerance", "moderate")) not in {"low", "moderate", "high", "extreme"}:
        result["casualty_tolerance"] = "moderate"
    if "extraction_priority" in result:
        result["extraction_priority"] = max(0, min(100, int(result["extraction_priority"])))
    result["deep_pursuit"] = bool(result.get("deep_pursuit", False))
    for key, allowed, default in (
        ("charge_permission", {"avoid_frontal", "advantage_required", "opportunity_only", "shock_window", "not_applicable"}, "advantage_required"),
        ("pursuit_permission", {"none", "controlled", "aggressive_bounded"}, "controlled"),
        ("autonomous_redeployment", {"forbidden", "bounded", "normal"}, "normal"),
        ("detachment_permission", {"explicit_order_only", "bounded", "normal"}, "normal"),
        ("anchor_policy", {"army_commander_position", "headquarters", "assigned_objective", "local_mission"}, "local_mission"),
        ("protected_asset", {"army_commander", "headquarters_command", "mission_objective", "none"}, "none"),
    ):
        if str(result.get(key, default)) not in allowed:
            result[key] = default
    result["mission_first"] = bool(result.get("mission_first", False))
    role_policies: dict[str, Any] = {}
    composition = formation.get("composition") if isinstance(formation.get("composition"), Mapping) else {}
    for physical_role, count in composition.items():
        if max(0, int(count or 0)) <= 0:
            continue
        child_ref = formation_doctrine_ref_for_role(read_json, formation, str(physical_role))
        child = load_doctrine_record(read_json, child_ref)
        child_doc = child.get("doctrine", {}) if isinstance(child.get("doctrine"), Mapping) else {}
        role_policies[str(physical_role)] = {
            "doctrine_ref": child_ref,
            "formation_policy": copy.deepcopy(
                child_doc.get("formation_policy_v2", child_doc.get("formation_policy", {}))
            ) if isinstance(child_doc.get("formation_policy_v2", child_doc.get("formation_policy", {})), Mapping) else {},
            "compatibility": doctrine_compatibility(read_json, formation, child_ref, role=str(physical_role)),
        }
    if role_policies:
        result["role_policies"] = role_policies
    return result


def apply_command_doctrine_policy(
    read_json: Callable[[str], Any],
    decision: Mapping[str, Any],
    doctrine_ref: str | None,
) -> dict[str, Any]:
    """Apply explicit registered army-doctrine deltas to command decisions.

    State identity and commander cognition remain primary.  Doctrine may shift
    bounded decision thresholds, never physical combat capability or knowledge.
    """
    out = copy.deepcopy(dict(decision))
    ref = str(doctrine_ref or "")
    out["standing_doctrine_ref"] = ref or None
    if not ref:
        return out
    record = load_doctrine_record(read_json, ref)
    doctrine = record.get("doctrine", {}) if isinstance(record.get("doctrine"), Mapping) else {}
    policy = doctrine.get("command_policy") if isinstance(doctrine.get("command_policy"), Mapping) else {}
    closed_effects = _closed_command_effects(read_json, doctrine)
    delta_fields = {
        "offensive_advantage_required_milli": (1050, 1650),
        "neutral_advantage_required_milli": (1200, 1950),
        "withdraw_if_local_ratio_below_milli": (420, 820),
        "attacker_reserve_commit_if_ratio_below_milli": (920, 1300),
        "defender_reserve_commit_if_enemy_ratio_above_milli": (1020, 1420),
        "report_confidence_floor_milli": (350, 820),
        "revision_pressure_threshold_milli": (350, 820),
        "pursuit_limit_milli": (450, 1150),
        "subordinate_initiative_envelope_milli": (300, 950),
    }
    for field, (low, high) in delta_fields.items():
        delta_key = field + "_delta"
        if delta_key not in policy:
            continue
        try:
            base = int(out.get(field, (low + high) // 2) or 0)
            delta = int(policy[delta_key])
        except (TypeError, ValueError):
            continue
        out[field] = max(low, min(high, base + delta))
    for field, delta in closed_effects.items():
        if field not in delta_fields:
            continue
        low, high = delta_fields[field]
        try: base = int(out.get(field, (low + high) // 2) or 0)
        except (TypeError, ValueError): base = (low + high) // 2
        out[field] = max(low, min(high, base + int(delta)))
    out["doctrine_policy_applied"] = bool(policy or closed_effects)
    return out


__all__ = [
    "apply_command_doctrine_policy",
    "default_command_group_doctrine_ref",
    "default_formation_doctrine_ref",
    "doctrine_behavior",
    "doctrine_compatibility",
    "formation_doctrine_ref_for_role",
    "role_doctrine_defaults",
]
