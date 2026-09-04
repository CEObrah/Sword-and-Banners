"""Stable exact-combat objective identity and progress evaluation.

Objectives are intentionally small. They do not replace commissions/missions;
they only tell the continuous exact-combat resolver when the current local
physical objective has actually succeeded or failed.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any


def normalize_objective(value: str) -> str:
    return " ".join(str(value or "combat").strip().lower().split())


def _point(value: Mapping[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return {
            "x_m": float(value.get("x_m", 0.0)),
            "y_m": float(value.get("y_m", 0.0)),
            "elevation_m": float(value.get("elevation_m", 0.0)),
        }
    except (TypeError, ValueError):
        return None


def objective_model(
    objective: str,
    hostile_refs: Sequence[str],
    protected_refs: Sequence[str] = (),
    *,
    actor_refs: Sequence[str] = (),
    objective_position: Mapping[str, Any] | None = None,
    objective_radius_m: float = 1.5,
    escape_distance_m: float = 8.0,
    hold_seconds: float = 10.0,
) -> dict[str, Any]:
    normalized = normalize_objective(objective)
    required_targets = sorted({str(x) for x in hostile_refs})
    actors = sorted({str(x) for x in actor_refs})
    protected = sorted({str(x) for x in protected_refs})
    mode = "engage"
    if any(token in normalized for token in ("kill", "eliminate", "execute")):
        mode = "eliminate_all"
    elif any(token in normalized for token in ("capture", "take alive", "alive capture")):
        mode = "capture_all"
    elif any(token in normalized for token in ("defeat", "neutralize", "subdue")):
        mode = "neutralize_all"
    elif any(token in normalized for token in ("escape", "withdraw", "retreat", "extract")):
        mode = "escape"
    elif any(token in normalized for token in ("protect", "guard", "escort", "defend")):
        mode = "protect"
    elif any(token in normalized for token in ("hold", "hold position", "hold ground")):
        mode = "hold"
    elif any(token in normalized for token in ("seize", "take position", "capture position", "occupy")):
        mode = "seize"
    elif any(token in normalized for token in ("spar", "controlled")):
        mode = "spar"
    point = _point(objective_position)
    token = "|".join((
        normalized,
        ",".join(required_targets),
        ",".join(protected),
        ",".join(actors),
        "" if point is None else f"{point['x_m']:.4f},{point['y_m']:.4f},{point['elevation_m']:.4f}",
        f"r={max(0.25, float(objective_radius_m)):.4f}",
        f"e={max(0.5, float(escape_distance_m)):.4f}",
        f"h={max(0.0, float(hold_seconds)):.4f}",
    ))
    return {
        "objective_id": "combatobj_" + hashlib.sha256(token.encode()).hexdigest()[:16],
        "description": objective,
        "normalized": normalized,
        "mode": mode,
        "required_target_refs": required_targets,
        "protected_refs": protected,
        "actor_refs": actors,
        "objective_position": point,
        "objective_radius_m": max(0.25, float(objective_radius_m)),
        "escape_distance_m": max(0.5, float(escape_distance_m)),
        "hold_seconds": max(0.0, float(hold_seconds)),
    }


def _distance(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    dx = float(a.get("x_m", 0.0)) - float(b.get("x_m", 0.0))
    dy = float(a.get("y_m", 0.0)) - float(b.get("y_m", 0.0))
    dz = float(a.get("elevation_m", 0.0)) - float(b.get("elevation_m", 0.0))
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def evaluate_objective(
    model: Mapping[str, Any],
    people: Mapping[str, Mapping[str, Any]],
    active_fn,
    *,
    positions: Mapping[str, Mapping[str, Any]] | None = None,
    elapsed_seconds: float = 0.0,
) -> dict[str, Any]:
    targets = [str(x) for x in model.get("required_target_refs", [])]
    mode = str(model.get("mode", "engage"))
    neutralized = [ref for ref in targets if ref in people and not active_fn(ref)]
    dead = [
        ref for ref in targets
        if ref in people
        and str(people[ref].get("life_status", people[ref].get("status", "active"))).lower()
        in {"dead", "deceased", "killed", "destroyed"}
    ]
    alive_neutralized = [ref for ref in neutralized if ref not in dead]
    required = len(targets)
    completed = False
    failed = False
    progress = 0 if required <= 0 else int(round(1000 * len(neutralized) / required))

    protected = [str(x) for x in model.get("protected_refs", [])]
    actors = [str(x) for x in model.get("actor_refs", [])]
    point = _point(model.get("objective_position") if isinstance(model.get("objective_position"), Mapping) else None)
    pos = positions or {}

    if mode == "eliminate_all":
        completed = required > 0 and len(dead) == required
        progress = 0 if required <= 0 else int(round(1000 * len(dead) / required))
    elif mode == "neutralize_all":
        completed = required > 0 and len(neutralized) == required
    elif mode == "capture_all":
        completed = required > 0 and len(alive_neutralized) == required
        failed = any(ref in dead for ref in targets)
        progress = 0 if required <= 0 else int(round(1000 * len(alive_neutralized) / required))
    elif mode == "protect":
        failed = any(ref in people and not active_fn(ref) for ref in protected)
        completed = bool(protected) and not failed and required > 0 and len(neutralized) == required
    elif mode == "escape":
        escaping = [ref for ref in (actors or protected) if ref in people and active_fn(ref)]
        live_hostiles = [ref for ref in targets if ref in people and active_fn(ref)]
        threshold = max(0.5, float(model.get("escape_distance_m", 8.0) or 8.0))
        if escaping:
            if point is not None:
                distances = [_distance(pos[ref], point) for ref in escaping if ref in pos]
                completed = len(distances) == len(escaping) and all(value <= max(0.25, float(model.get("objective_radius_m", 1.5) or 1.5)) for value in distances)
                progress = 0 if not distances else int(round(1000 * sum(max(0.0, 1.0 - d / max(threshold, 0.5)) for d in distances) / len(distances)))
            elif not live_hostiles:
                completed = True
                progress = 1000
            else:
                separations = []
                for ref in escaping:
                    if ref not in pos:
                        continue
                    distances = [_distance(pos[ref], pos[h]) for h in live_hostiles if h in pos]
                    if distances:
                        separations.append(min(distances))
                completed = len(separations) == len(escaping) and all(value >= threshold for value in separations)
                progress = 0 if not separations else int(round(1000 * sum(min(1.0, d / threshold) for d in separations) / len(separations)))
        failed = not bool(escaping)
    elif mode in {"seize", "hold"}:
        if point is None:
            # A spatial objective without a registered point cannot silently
            # succeed from prose alone.
            completed = False
            progress = 0
        else:
            radius = max(0.25, float(model.get("objective_radius_m", 1.5) or 1.5))
            friendly_inside = [ref for ref in actors if ref in pos and active_fn(ref) and _distance(pos[ref], point) <= radius]
            hostile_inside = [ref for ref in targets if ref in pos and active_fn(ref) and _distance(pos[ref], point) <= radius]
            physically_controlled = bool(friendly_inside) and not hostile_inside
            if mode == "seize":
                completed = physically_controlled
            else:
                completed = physically_controlled and float(elapsed_seconds) >= max(0.0, float(model.get("hold_seconds", 10.0) or 10.0))
            progress = 1000 if completed else (650 if physically_controlled else (250 if friendly_inside else 0))
    elif mode in {"spar", "engage"}:
        completed = False

    return {
        **dict(model),
        "required_count": required,
        "neutralized_refs": neutralized,
        "dead_refs": dead,
        "captured_refs": alive_neutralized if mode == "capture_all" else [],
        "progress_milli": max(0, min(1000, progress)),
        "completed": bool(completed),
        "failed": bool(failed),
    }
