"""Institution-aware physical military issue and officer equipment resolution.

Troop role, institutional identity, command billet, and personal equipment are
separate authorities.

Rank-and-file issue resolution:
  explicit formation role issue -> institutional role issue -> generic role profile.

Individual officer/person resolution:
  explicit personal loadout -> institutional officer profile -> homogeneous-role
  officer profile -> generic command-personnel fallback.

A mixed formation never lends one arbitrary troop role's kit to its commander.
Representation type (exact vs person-lite) never changes this precedence.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

ISSUE_MAP_PATH = "game/data/mil/institutional-loadouts.json"
DEFAULT_OFFICER_LOADOUT = "loadout_state_command_personnel"


def _institution_key(formation: Mapping[str, Any]) -> str:
    admin = str(formation.get("administrative_owner") or "")
    force = str(formation.get("owner_force_ref") or "")
    if admin:
        return admin
    if force.startswith("force_state_"):
        return force.removeprefix("force_")
    if force.startswith("force_house_tang") or force == "force_tang_wei_personal":
        return "house_tang"
    if force == "force_northern_steppe":
        return "polity_northern_steppe"
    if force == "force_yotanwa_confederation":
        return "polity_yotanwa_confederation"
    if "house_mou" in force:
        return "house_mou"
    if "house_ou" in force:
        return "house_ou"
    return ""


def explicit_personal_loadout_id(person: Mapping[str, Any]) -> str:
    """Return the person's explicit equipment authority, if any.

    ``personal_loadout_ref`` is the current canonical field. Older saved fields
    remain readable as compatibility inputs while the campaign is rebaselined.
    They are never derived from formation composition here.
    """
    for key in (
        "personal_loadout_ref",
        "equipment_loadout_id",
        "equipment_standard",
        "loadout_ref",
        "loadout_id",
    ):
        value = person.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def institutional_role_loadout_id(
    read_json: Callable[[str], Any],
    formation: Mapping[str, Any],
    role: str,
    *,
    profile: Mapping[str, Any] | None = None,
) -> str:
    per_role = formation.get("registered_loadouts_by_role") if isinstance(formation.get("registered_loadouts_by_role"), Mapping) else {}
    explicit = per_role.get(str(role)) if isinstance(per_role, Mapping) else None
    if isinstance(explicit, str) and explicit:
        return explicit
    single = formation.get("registered_loadout_ref")
    comp = formation.get("composition") if isinstance(formation.get("composition"), Mapping) else {}
    if isinstance(single, str) and single and len([k for k, v in comp.items() if int(v or 0) > 0]) <= 1:
        return single
    try:
        issue = read_json(ISSUE_MAP_PATH)
    except Exception:
        issue = {}
    institutions = issue.get("institutions", {}) if isinstance(issue, Mapping) else {}
    row = institutions.get(_institution_key(formation), {}) if isinstance(institutions, Mapping) else {}
    value = row.get(str(role)) if isinstance(row, Mapping) else None
    if isinstance(value, str) and value:
        return value
    if isinstance(profile, Mapping):
        value = profile.get("loadout_id")
        if isinstance(value, str):
            return value
    return ""


def officer_loadout_id(
    read_json: Callable[[str], Any],
    person: Mapping[str, Any],
    formation: Mapping[str, Any] | None = None,
    *,
    command_role: str | None = None,
) -> str:
    """Resolve one officer/person loadout without borrowing arbitrary troop kit.

    Mixed formations use an institutional command profile. A homogeneous
    formation may use a registered role-specific officer profile when one exists.
    Explicit personal equipment always wins, regardless of representation.
    """
    explicit = explicit_personal_loadout_id(person)
    if explicit:
        return explicit

    formation = formation if isinstance(formation, Mapping) else {}
    try:
        issue = read_json(ISSUE_MAP_PATH)
    except Exception:
        issue = {}
    institution = _institution_key(formation)
    officer_defaults = issue.get("officer_defaults", {}) if isinstance(issue, Mapping) else {}
    officer_by_role = issue.get("officer_by_role", {}) if isinstance(issue, Mapping) else {}

    comp = formation.get("composition") if isinstance(formation.get("composition"), Mapping) else {}
    active_roles = [str(k) for k, raw in comp.items() if max(0, int(raw or 0)) > 0]
    if len(active_roles) == 1:
        inst_roles = officer_by_role.get(institution, {}) if isinstance(officer_by_role, Mapping) else {}
        role_ref = inst_roles.get(active_roles[0]) if isinstance(inst_roles, Mapping) else None
        if isinstance(role_ref, str) and role_ref:
            return role_ref

    default_ref = officer_defaults.get(institution) if isinstance(officer_defaults, Mapping) else None
    if isinstance(default_ref, str) and default_ref:
        return default_ref

    # A command-role-specific fallback can be added to the registry later without
    # changing this contract. Until then generic command personnel is deliberately
    # safer than copying one child troop arm in a composite command.
    return DEFAULT_OFFICER_LOADOUT


def formation_registered_loadouts(
    read_json: Callable[[str], Any],
    formation: Mapping[str, Any],
    combat_profile_resolver: Callable[[str], Mapping[str, Any]],
) -> dict[str, str]:
    out: dict[str, str] = {}
    comp = formation.get("composition") if isinstance(formation.get("composition"), Mapping) else {}
    for role, raw in comp.items():
        if max(0, int(raw or 0)) <= 0:
            continue
        profile = combat_profile_resolver(str(role))
        ref = institutional_role_loadout_id(read_json, formation, str(role), profile=profile)
        if ref:
            out[str(role)] = ref
    return out


__all__ = [
    "ISSUE_MAP_PATH",
    "DEFAULT_OFFICER_LOADOUT",
    "explicit_personal_loadout_id",
    "officer_loadout_id",
    "institutional_role_loadout_id",
    "formation_registered_loadouts",
]
