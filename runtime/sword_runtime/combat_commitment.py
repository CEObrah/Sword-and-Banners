"""Small policy helpers for exact personal-combat commitment integrity.

These helpers keep two independent physical invariants explicit:

* a non-displacing brace consumes defensive readiness but does not retroactively
  erase an offensive action that has already started;
* a linear melee thrust cannot pass through another represented body on the way
  to its intended target.

The helpers are deterministic and side-neutral.  They own no campaign state.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.combat_geometry import body_intersections_on_segment


def pending_action_preservation(
    defense_method: str,
    pending_action: Mapping[str, Any] | None,
    *,
    resolve_at_s: float,
    simultaneous_window_s: float,
) -> str | None:
    """Return why a pending attack survives the current defensive response.

    Only an attack that has physically started can survive.  Brace is
    non-displacing, so it preserves that started offense even when its contact is
    later than the simultaneous-contact window.  All defenses preserve a contact
    already inside the simultaneous window.  Other cases return ``None`` and the
    resolver may interrupt the pending action as before.
    """
    if not isinstance(pending_action, Mapping):
        return None
    if str(pending_action.get("kind", "")) != "attack":
        return None
    resolve_at = float(resolve_at_s)
    start_at = float(pending_action.get("start_at_s", resolve_at) or resolve_at)
    if start_at > resolve_at + 1e-9:
        return None
    if str(defense_method or "").lower() == "brace":
        return "brace_preserves_started_offense"
    contact_at = float(pending_action.get("resolve_at_s", resolve_at + 999.0) or (resolve_at + 999.0))
    if contact_at <= resolve_at + max(0.0, float(simultaneous_window_s)) + 1e-9:
        return "simultaneous_contact"
    return None


def first_linear_melee_body_blocker(
    *,
    actor_ref: str,
    target_ref: str,
    attack_mode: str,
    start: Mapping[str, Any],
    end: Mapping[str, Any],
    positions: Mapping[str, Mapping[str, Any]],
    lane_half_width_m: float = 0.025,
) -> dict[str, Any] | None:
    """Return the first body that blocks an ordinary linear melee thrust.

    Cuts and other arcing contacts are deliberately excluded because their full
    swept path is not represented by the centerline segment.  Thrusts are linear
    commitments, so an intervening represented body is a real frontage blocker.
    """
    if str(attack_mode or "").lower() != "thrust":
        return None
    if actor_ref not in positions or target_ref not in positions:
        return None

    actor_pose = positions[actor_ref]
    target_pose = positions[target_ref]
    start_z = float(actor_pose.get("elevation_m", 0.0) or 0.0) + min(
        1.10, max(0.35, float(actor_pose.get("height_m", 1.75) or 1.75) * 0.62)
    )
    end_z = float(target_pose.get("elevation_m", 0.0) or 0.0) + min(
        1.05, max(0.30, float(target_pose.get("height_m", 1.75) or 1.75) * 0.58)
    )
    hits = body_intersections_on_segment(
        start,
        end,
        positions,
        exclude_refs=(actor_ref, target_ref),
        half_width_m=max(0.0, float(lane_half_width_m)),
        elevation_start_m=start_z,
        elevation_end_m=end_z,
        vertical_tolerance_m=0.08,
    )
    for hit in hits:
        # Ignore only near-zero centerline overlap at the attacker's own origin.
        # Existing crowded geometry can place touching body radii very close to
        # that origin without meaning the body actually occupies the thrust lane.
        if float(hit.get("distance_along_m", 0.0) or 0.0) <= 0.08:
            continue
        blocker = dict(hit)
        blocker.update(
            {
                "kind": "body",
                "label": str(hit.get("ref", "intervening_body")),
                "path_t": float(hit.get("t", 0.0) or 0.0),
                "reason": "intervening_body_blocks_linear_melee_lane",
            }
        )
        return blocker
    return None


__all__ = ["first_linear_melee_body_blocker", "pending_action_preservation"]
