"""Integrity overlay for the final command-depth lifecycle.

This mixin owns no campaign state. It closes lifecycle and conservation edge cases
around ``WarfareDepthMixin``:

* secondary external Unit-command attachments are released before a merge deletes owners;
* routine staff/signal/logistics/medical functions never create mandatory support headcount;
* materialized officers embedded inside formation fighting strength are not counted
  a second time by top-level force conservation; and
* House Tang / Sword Manor command representation is inherited force-wide,
  while Qin uses the same standard only when Tang Wei lawfully holds command.
"""
from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import validate_cohort_ledger
from sword_runtime.warfare_depth import WarfareDepthMixin
from sword_runtime.unit_establishment import authorized_strength_for, classify_formation, hierarchy_counts


_SCOPED_OWNER_FORCES = frozenset({"force_house_tang", "force_sword_manor"})
_QIN_FORCE = "force_state_qin"
_WEI_REF = "char_tang_wei"
_MISSING = object()


def _formation_in_scoped_standard(formation: Mapping[str, Any]) -> str:
    owner_force = str(formation.get("owner_force_ref", ""))
    if owner_force in _SCOPED_OWNER_FORCES:
        return "house_or_sword_institution_wide"
    if owner_force == _QIN_FORCE and str(formation.get("command_authority", "")) == _WEI_REF:
        return "wei_assigned_qin"
    return ""


def _normalize_scoped_explicit_profile(
    formation: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Apply institutional representation invariants to an explicit profile.

    Explicit organizational geometry remains authoritative. This only fills the
    combined unit-command representation marker when the scoped policy already
    declares both formal billets full characters, avoiding an aggregate fallback
    from an omitted combined-representation marker.
    """
    if not _formation_in_scoped_standard(formation):
        return profile
    normalized = copy.deepcopy(dict(profile))
    unit = normalized.get("external_unit_command")
    if not isinstance(unit, MutableMapping):
        return normalized
    commander_rep = str(unit.get("commander_representation", ""))
    deputy_rep = str(unit.get("deputy_representation", ""))
    if commander_rep == "full_character" and deputy_rep == "full_character":
        unit.setdefault("representation", "full_character_unit_command")
    return normalized


def _synthesized_scoped_formation_profile(formation: Mapping[str, Any]) -> dict[str, Any]:
    """Return the institutional default command profile for one scoped formation.

    This is representation policy only. It does not materialize a body, grant a
    command, or change manpower. Existing exact formation/force owners remain the
    authority for commander assignment and personnel conservation.
    """
    owner_force = str(formation.get("owner_force_ref", ""))
    scope = _formation_in_scoped_standard(formation)
    if not scope:
        return {}

    personnel = max(0, int(formation.get("personnel", 0) or 0))
    klass = classify_formation(personnel=personnel, explicit=formation.get("formation_class"))
    authorized = authorized_strength_for(formation, personnel=personnel, formation_class=klass)
    counts = hierarchy_counts(authorized_strength=authorized, formation_class=klass)
    internal: list[dict[str, Any]] = []
    for scale, representation in ((1000, "person_lite"), (500, "person_lite"), (100, "aggregate")):
        count = max(0, int(counts.get(scale, 0)))
        if count <= 0:
            continue
        internal.append(
            {
                "scale": scale,
                "count": count,
                "representation": representation,
                "loadout_ref": "loadout_house_guard",
            }
        )

    return {
        "label": "Institution-scoped formation command standard",
        "fighting_establishment": personnel,
        "authorized_strength": authorized,
        "formation_class": klass,
        "scope": scope,
        "external_unit_command": {
            "commander_billets": 1 if personnel else 0,
            "deputy_billets": 1 if personnel else 0,
            "commander_representation": "full_character",
            "deputy_representation": "full_character",
            "source_force_ref": owner_force,
            "source_role": "command_personnel",
            "representation": "full_character_unit_command",
            "outside_fighting_establishment": True,
            "loadout_ref": "loadout_house_champion",
        },
        "internal_hierarchy": internal,
        "hierarchy_rule": (
            "House Tang and Sword Manor inherit full-character persistent unit commander/deputy "
            "plus person-lite 1,000/500 internal command institution-wide. Qin inherits the same "
            "standard only while Tang Wei lawfully holds command authority. 100-man and below "
            "remain aggregate unless separately salient."
        ),
    }


def resolve_scoped_formation_profile(
    formation: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Resolve explicit geometry first, normalized by the scoped institution rule."""
    profiles = rules.get("formation_profiles", {}) if isinstance(rules, Mapping) else {}
    ref = str(formation.get("formation_ref", ""))
    explicit = profiles.get(ref) if isinstance(profiles, Mapping) else None
    if isinstance(explicit, Mapping):
        return _normalize_scoped_explicit_profile(formation, explicit)
    return _synthesized_scoped_formation_profile(formation)


class _ScopedFormationProfiles(Mapping[str, Any]):
    """Lazy profile adapter so all production WarfareDepth calls share one scope rule."""

    def __init__(self, planner: Any, explicit: Mapping[str, Any]) -> None:
        self._planner = planner
        self._explicit = explicit

    def __iter__(self) -> Iterator[str]:
        return iter(self._explicit)

    def __len__(self) -> int:
        return len(self._explicit)

    def __getitem__(self, key: str) -> Any:
        value = self.get(key, _MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def get(self, key: object, default: Any = None) -> Any:
        if not isinstance(key, str) or not key:
            return default
        explicit = self._explicit.get(key)
        try:
            _path, formation = self._planner._load_formation(key)
        except (KeyError, ValueError, FileNotFoundError):
            return explicit if isinstance(explicit, Mapping) else default
        if not isinstance(formation, Mapping):
            return explicit if isinstance(explicit, Mapping) else default
        if isinstance(explicit, Mapping):
            return _normalize_scoped_explicit_profile(formation, explicit)
        scoped = _synthesized_scoped_formation_profile(formation)
        return scoped if scoped else default


class WarfareDepthIntegrityMixin:
    """Production integrity hooks layered immediately above WarfareDepthMixin."""

    def _warfare_depth_rules(self) -> Mapping[str, Any]:
        """Overlay lazy institutional formation profiles onto static warfare rules."""
        cached = getattr(self, "_warfare_depth_integrity_rules_cache", None)
        if isinstance(cached, Mapping):
            return cached
        base = super()._warfare_depth_rules()
        rules = copy.deepcopy(dict(base))
        explicit = base.get("formation_profiles", {}) if isinstance(base, Mapping) else {}
        if not isinstance(explicit, Mapping):
            explicit = {}
        rules["formation_profiles"] = _ScopedFormationProfiles(self, explicit)
        self._warfare_depth_integrity_rules_cache = rules
        return rules

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "formation_merge":
            refs = payload.get("formation_refs", [])
            if isinstance(refs, list):
                for ref in refs[1:]:
                    if isinstance(ref, str) and ref:
                        self._release_formation_external_personnel(ref)
        return super()._dispatch(command, payload)

    def _ensure_mercenary_command_structure(self, mercenary_ref: str) -> Mapping[str, Any]:
        """Use the base conserved mercenary structure without fixed support quotas.

        Existing saved support pools remain historical company composition. The
        engine never carves a mandatory 7-per-500 (or any other) routine-support
        allowance from fighting strength.
        """
        return super()._ensure_mercenary_command_structure(mercenary_ref)

    def _validate_invariants(self, overlay: Any, paths: Any) -> None:
        """Validate canonical force conservation once, then cohort ledgers.

        The base engine accounts for external personnel allocations and excludes
        materialized bodies already assigned inside formations. Keep that single
        force-conservation equation authoritative and layer only cohort-ledger
        validation here.
        """
        super(WarfareDepthMixin, self)._validate_invariants(overlay, paths)
        for path in paths:
            path = str(path)
            if not path.startswith("state/forces/") or overlay.read_optional_bytes(path) is None:
                continue
            force = overlay.read_json(path)
            if isinstance(force, Mapping):
                validate_cohort_ledger(force)
