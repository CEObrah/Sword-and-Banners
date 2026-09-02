"""Fast read-only integrity checks for a deployable live campaign.

This is intentionally not a release/soak suite.  It checks only compact state
relationships whose divergence can make ordinary gameplay stall or route through
contradictory current truth.  It never repairs state and never advances time.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sword_runtime.scheduler_frontier import assert_frontier_consistent, runtime_route_integrity
from sword_runtime.store.json_fragments import select_json_fragment, split_json_fragment
from sword_runtime.unit_establishment import authorized_strength_for, formation_class_for


class StartupIntegrityError(RuntimeError):
    """The campaign is structurally valid JSON but unsafe to serve for gameplay."""


def _read(root: Path, rel: str) -> Any:
    path = root / rel
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StartupIntegrityError(f"cannot read required campaign state: {rel}") from exc


def _direct_owner_path(owners: Mapping[str, Any], owner_ref: str) -> str | None:
    path = owners.get(owner_ref)
    if not isinstance(path, str) or not path or "#/" in path:
        return None
    return path


def _read_owner(root: Path, owner_path: str) -> Any:
    base, tokens = split_json_fragment(owner_path)
    value = _read(root, base)
    if not tokens:
        return value
    try:
        return select_json_fragment(value, tokens)
    except KeyError as exc:
        raise StartupIntegrityError(f"cannot resolve required campaign owner: {owner_path}") from exc


def _is_full_person_owner(path: str, person: Mapping[str, Any]) -> bool:
    """Return whether this direct owner is an exact/full person record.

    Representation is a property of the saved owner, not the spelling of the
    identity. Promoted command people may retain ``officer.*`` identities while
    living under ``state/person/`` as a full ``sab_character``.
    """
    if path == "state/player.json" or path.startswith("state/char/"):
        return str(person.get("schema", "")) in {"sab_character", "sword-materialized-person"}
    return (
        path.startswith("state/person/")
        and str(person.get("schema", "")) in {"sab_character", "sword-materialized-person"}
    )


def validate_startup_integrity(root: object) -> dict[str, Any]:
    """Validate the small cross-domain invariants most likely to break live flow."""
    root = Path(root).resolve()
    meta = _read(root, "state/meta.json")
    runtime = _read(root, "state/runtime.json")
    player = _read(root, "state/player.json")
    owner_index = _read(root, "state/index/owner-index.json")

    if not isinstance(meta, Mapping) or meta.get("game") != "sword_and_banners":
        raise StartupIntegrityError("campaign meta is not Sword & Banners authority")
    if not isinstance(runtime, Mapping):
        raise StartupIntegrityError("runtime state is invalid")
    if str(meta.get("time", "")) != str(runtime.get("world_time", "")):
        raise StartupIntegrityError("campaign meta time diverges from runtime world time")
    try:
        assert_frontier_consistent(runtime)
    except (TypeError, ValueError) as exc:
        raise StartupIntegrityError("scheduler causal frontier is inconsistent") from exc
    coverage = runtime_route_integrity(runtime)
    if coverage.get("complete") is not True:
        raise StartupIntegrityError(
            "scheduler registry is not gameplay-ready: "
            + ",".join(str(x) for x in (coverage.get("errors") or coverage.get("overdue_host_refs") or [])[:8])
        )

    if not isinstance(player, Mapping):
        raise StartupIntegrityError("player state is invalid")
    location = player.get("location")
    current_location = player.get("current_location")
    if (
        isinstance(location, str) and location
        and isinstance(current_location, str) and current_location
        and location != current_location
    ):
        raise StartupIntegrityError("player location aliases diverge")

    owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
    if not isinstance(owners, Mapping):
        raise StartupIntegrityError("owner index is invalid")

    checked_people = 0
    checked_commanders = 0
    prisoner_people: dict[str, tuple[str, str | None, str | None]] = {}
    for owner_ref, raw_path in owners.items():
        if not isinstance(owner_ref, str) or not isinstance(raw_path, str):
            continue
        if "#/" in raw_path or not (
            raw_path == "state/player.json"
            or raw_path.startswith("state/char/")
            or raw_path.startswith("state/person/")
        ):
            continue
        person = _read(root, raw_path)
        if not isinstance(person, Mapping) or not _is_full_person_owner(raw_path, person):
            continue
        checked_people += 1

        loc = person.get("location")
        cur = person.get("current_location")
        if isinstance(loc, str) and loc and isinstance(cur, str) and cur and loc != cur:
            raise StartupIntegrityError(f"exact-person location aliases diverge: {owner_ref}")
        custody = person.get("custody_state") if isinstance(person.get("custody_state"), Mapping) else None
        if isinstance(custody, Mapping) and str(custody.get("status", "")) == "prisoner":
            group_ref = custody.get("prisoner_group_ref")
            if not isinstance(group_ref, str) or not group_ref:
                raise StartupIntegrityError(f"named prisoner has no custody group: {owner_ref}")
            person_location = cur if isinstance(cur, str) and cur else loc if isinstance(loc, str) and loc else None
            custody_location = custody.get("location_ref") if isinstance(custody.get("location_ref"), str) else None
            prisoner_people[owner_ref] = (group_ref, person_location, custody_location)

    # Active named custody is bidirectional and physically exact.  The routing
    # index is intentionally small, so startup can validate every active group
    # without a repository-wide custody scan.
    try:
        custody_index = _read(root, "state/custody/index.json")
    except StartupIntegrityError:
        custody_index = {"groups": {}, "active_refs": []}
    groups = custody_index.get("groups", {}) if isinstance(custody_index, Mapping) else {}
    active_refs = custody_index.get("active_refs", []) if isinstance(custody_index, Mapping) else []
    if not isinstance(groups, Mapping) or not isinstance(active_refs, list):
        raise StartupIntegrityError("custody index is invalid")
    active_set = {str(x) for x in active_refs if isinstance(x, str)}
    checked_custody_groups = 0
    for group_ref in sorted(active_set):
        group_path = groups.get(group_ref)
        if not isinstance(group_path, str) or not group_path:
            raise StartupIntegrityError(f"active custody group route is missing: {group_ref}")
        group = _read_owner(root, group_path)
        if not isinstance(group, Mapping) or str(group.get("schema", "")) != "sword-prisoner-group":
            raise StartupIntegrityError(f"active custody group owner is invalid: {group_ref}")
        if str(group.get("status", "")) not in {"held", "in_transit"}:
            raise StartupIntegrityError(f"inactive custody group remains routed active: {group_ref}")
        checked_custody_groups += 1
        group_location = str(group.get("location_ref", ""))
        named_refs = group.get("named_prisoner_refs", [])
        if not isinstance(named_refs, list):
            raise StartupIntegrityError(f"named prisoner refs are invalid: {group_ref}")
        for person_ref in named_refs:
            if not isinstance(person_ref, str) or person_ref not in prisoner_people:
                raise StartupIntegrityError(f"active custody group has no matching exact prisoner: {group_ref}:{person_ref}")
            person_group, person_location, custody_location = prisoner_people[person_ref]
            if person_group != group_ref:
                raise StartupIntegrityError(f"named prisoner custody pointer diverges: {group_ref}:{person_ref}")
            if group_location and person_location != group_location:
                raise StartupIntegrityError(f"named prisoner location diverges from custody group: {group_ref}:{person_ref}")
            if group_location and custody_location != group_location:
                raise StartupIntegrityError(f"named prisoner custody location diverges: {group_ref}:{person_ref}")

    for person_ref, (group_ref, _person_location, _custody_location) in prisoner_people.items():
        if group_ref not in active_set:
            raise StartupIntegrityError(f"named prisoner points to inactive custody group: {person_ref}:{group_ref}")

    policy = _read(root, "game/data/mechanics/officer-representation.json")
    full_policy = policy.get("automatic_full_character", {}) if isinstance(policy, Mapping) else {}
    full_threshold = max(1, int(full_policy.get("minimum_persistent_commanded_personnel", 500) or 500))

    # Validate command custody formation-first.  This catches dangling commander
    # refs and fragment-backed person-lite owners that a full-character-only loop
    # cannot see.  Formation command is one bidirectional fact: the formation names
    # the person, and the person names the same formation/billet.
    for formation_ref, raw_path in owners.items():
        if not isinstance(formation_ref, str) or not formation_ref.startswith("formation_"):
            continue
        if not isinstance(raw_path, str) or not raw_path or "#/" in raw_path:
            raise StartupIntegrityError(f"formation owner route is invalid: {formation_ref}")
        formation = _read(root, raw_path)
        if not isinstance(formation, Mapping):
            raise StartupIntegrityError(f"formation owner is invalid: {formation_ref}")
        embedded_refs = formation.get("embedded_person_refs", [])
        if not isinstance(embedded_refs, list):
            raise StartupIntegrityError(f"formation embedded person refs are invalid: {formation_ref}")
        for embedded_ref in embedded_refs:
            if not isinstance(embedded_ref, str) or not embedded_ref:
                raise StartupIntegrityError(f"formation embedded person ref is invalid: {formation_ref}")
            embedded_path = owners.get(embedded_ref)
            if not isinstance(embedded_path, str) or not embedded_path:
                raise StartupIntegrityError(
                    f"formation embedded person has no authoritative owner: {formation_ref}:{embedded_ref}"
                )
            embedded_person = _read_owner(root, embedded_path)
            if not isinstance(embedded_person, Mapping) or str(embedded_person.get("schema", "")) not in {
                "sab_character", "sword-materialized-person", "person-lite",
            }:
                raise StartupIntegrityError(
                    f"formation embedded owner is not an individual person: {formation_ref}:{embedded_ref}"
                )
        commander_ref = formation.get("commander_ref")
        if not isinstance(commander_ref, str) or not commander_ref:
            continue
        commander_path = owners.get(commander_ref)
        if not isinstance(commander_path, str) or not commander_path:
            raise StartupIntegrityError(f"formation commander has no authoritative owner: {formation_ref}")
        person = _read_owner(root, commander_path)
        if not isinstance(person, Mapping) or str(person.get("schema", "")) not in {
            "sab_character", "sword-materialized-person", "person-lite",
        }:
            raise StartupIntegrityError(f"formation commander owner is not an individual person: {formation_ref}")

        current = max(0, int(formation.get("personnel", 0) or 0))
        klass = formation_class_for(formation, personnel=current, explicit=formation.get("formation_class"))
        authorized = authorized_strength_for(formation, personnel=current, formation_class=klass)
        if authorized >= full_threshold and str(person.get("schema", "")) == "person-lite":
            raise StartupIntegrityError(
                f"unit-scale formation commander is person-lite: {formation_ref}"
            )

        assignment = person.get("command_assignment")
        if not isinstance(assignment, Mapping) or str(assignment.get("formation_ref", "")) != formation_ref:
            raise StartupIntegrityError(f"commander assignment diverges: {commander_ref}")
        checked_commanders += 1
        expected = current
        if "current_command_span" in assignment and int(assignment.get("current_command_span", -1) or 0) != expected:
            raise StartupIntegrityError(f"commander assignment span diverges: {commander_ref}")
        career = person.get("career_state")
        if isinstance(career, Mapping) and "current_command_span" in career:
            if int(career.get("current_command_span", -1) or 0) != expected:
                raise StartupIntegrityError(f"commander career span diverges: {commander_ref}")
        military = person.get("military_command")
        level = military.get("level") if isinstance(military, Mapping) else None
        if isinstance(level, str) and level.endswith("_commander"):
            prefix = level[:-len("_commander")]
            if prefix.isdigit() and int(prefix) != expected:
                raise StartupIntegrityError(f"commander service level diverges: {commander_ref}")

    return {
        "ok": True,
        "campaign_id": str(meta.get("campaign_id", "")),
        "revision": int(meta.get("revision", 0) or 0),
        "world_time": str(runtime.get("world_time", "")),
        "scheduler_hosts": int(coverage.get("host_count", 0) or 0),
        "scheduler_events": int(coverage.get("event_count", 0) or 0),
        "exact_people_checked": checked_people,
        "formation_commanders_checked": checked_commanders,
        "active_custody_groups_checked": checked_custody_groups,
    }


__all__ = ["StartupIntegrityError", "validate_startup_integrity"]
