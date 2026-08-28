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
    for owner_ref, raw_path in owners.items():
        if not isinstance(owner_ref, str) or not isinstance(raw_path, str):
            continue
        if "#/" in raw_path or not raw_path.startswith("state/char/"):
            continue
        person = _read(root, raw_path)
        if not isinstance(person, Mapping) or str(person.get("schema", "")) != "sab_character":
            continue
        checked_people += 1

        loc = person.get("location")
        cur = person.get("current_location")
        if isinstance(loc, str) and loc and isinstance(cur, str) and cur and loc != cur:
            raise StartupIntegrityError(f"exact-person location aliases diverge: {owner_ref}")

        assignment = person.get("command_assignment")
        formation_ref = assignment.get("formation_ref") if isinstance(assignment, Mapping) else None
        if not isinstance(formation_ref, str) or not formation_ref.startswith("formation_"):
            continue
        formation_path = _direct_owner_path(owners, formation_ref)
        if formation_path is None:
            continue
        formation = _read(root, formation_path)
        if not isinstance(formation, Mapping) or str(formation.get("commander_ref", "")) != owner_ref:
            continue
        checked_commanders += 1
        expected = max(0, int(formation.get("personnel", 0) or 0))
        if "current_command_span" in assignment and int(assignment.get("current_command_span", -1) or 0) != expected:
            raise StartupIntegrityError(f"commander assignment span diverges: {owner_ref}")
        career = person.get("career_state")
        if isinstance(career, Mapping) and "current_command_span" in career:
            if int(career.get("current_command_span", -1) or 0) != expected:
                raise StartupIntegrityError(f"commander career span diverges: {owner_ref}")
        military = person.get("military_command")
        level = military.get("level") if isinstance(military, Mapping) else None
        if isinstance(level, str) and level.endswith("_commander"):
            prefix = level[:-len("_commander")]
            if prefix.isdigit() and int(prefix) != expected:
                raise StartupIntegrityError(f"commander service level diverges: {owner_ref}")

    return {
        "ok": True,
        "campaign_id": str(meta.get("campaign_id", "")),
        "revision": int(meta.get("revision", 0) or 0),
        "world_time": str(runtime.get("world_time", "")),
        "scheduler_hosts": int(coverage.get("host_count", 0) or 0),
        "scheduler_events": int(coverage.get("event_count", 0) or 0),
        "exact_people_checked": checked_people,
        "formation_commanders_checked": checked_commanders,
    }


__all__ = ["StartupIntegrityError", "validate_startup_integrity"]
