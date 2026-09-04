"""Lightweight exact-combat geometry authority.

This module deliberately stays small.  It does not simulate the whole world or
replace contact physics.  It owns reusable local-plane questions that must have
one answer everywhere in exact combat: distance, bearing, body occupancy,
trajectory/lane intersection, line-of-sight obstruction, cones/radii and
relative arcs.

All functions are deterministic and side-neutral.  Team membership never makes
an actor a target: physical intersection does.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def normalize_angle(degrees: float) -> float:
    return float(degrees) % 360.0


def signed_angle_delta(target_deg: float, source_deg: float) -> float:
    return ((normalize_angle(target_deg) - normalize_angle(source_deg) + 180.0) % 360.0) - 180.0


def angle_delta(target_deg: float, source_deg: float) -> float:
    return abs(signed_angle_delta(target_deg, source_deg))


def distance_2d(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    return math.hypot(float(b.get("x_m", 0.0)) - float(a.get("x_m", 0.0)), float(b.get("y_m", 0.0)) - float(a.get("y_m", 0.0)))


def distance_3d(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    dx = float(b.get("x_m", 0.0)) - float(a.get("x_m", 0.0))
    dy = float(b.get("y_m", 0.0)) - float(a.get("y_m", 0.0))
    dz = float(b.get("elevation_m", 0.0)) - float(a.get("elevation_m", 0.0))
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def bearing_deg(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    return normalize_angle(math.degrees(math.atan2(float(b.get("y_m", 0.0)) - float(a.get("y_m", 0.0)), float(b.get("x_m", 0.0)) - float(a.get("x_m", 0.0)))))


def elevation_angle_deg(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    horizontal = max(1e-9, distance_2d(a, b))
    dz = float(b.get("elevation_m", 0.0)) - float(a.get("elevation_m", 0.0))
    return math.degrees(math.atan2(dz, horizontal))


def point_segment_projection(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    vx = x2 - x1
    vy = y2 - y1
    denom = vx * vx + vy * vy
    if denom <= 1e-12:
        return 0.0, math.hypot(px - x1, py - y1)
    t = clamp(((px - x1) * vx + (py - y1) * vy) / denom, 0.0, 1.0)
    qx = x1 + t * vx
    qy = y1 + t * vy
    return t, math.hypot(px - qx, py - qy)


def point_segment_distance(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    return point_segment_projection(px, py, x1, y1, x2, y2)[1]


def first_static_obstacle_on_segment(
    start: Mapping[str, Any],
    end: Mapping[str, Any],
    obstacles: Sequence[Mapping[str, Any]],
    *,
    clearance_m: float = 0.0,
) -> dict[str, Any] | None:
    """Return the first represented local obstacle intersecting a segment.

    Local combat obstacles are deliberately lightweight circles or wall-like
    segments.  This is the single static-obstruction authority used by LOS,
    melee contact paths and defensive movement.  It does not invent terrain.
    """
    x1 = float(start.get("x_m", 0.0)); y1 = float(start.get("y_m", 0.0))
    x2 = float(end.get("x_m", 0.0)); y2 = float(end.get("y_m", 0.0))
    distance = math.hypot(x2 - x1, y2 - y1)
    if distance <= 1e-9:
        return None
    extra = max(0.0, float(clearance_m))
    hits: list[tuple[float, str, dict[str, Any]]] = []
    for index, raw in enumerate(obstacles):
        if not isinstance(raw, Mapping):
            continue
        kind = str(raw.get("kind", ""))
        label = str(raw.get("label", f"obstacle_{index}"))
        t: float | None = None
        if kind == "circle":
            radius = max(0.01, float(raw.get("radius_m", 0.0) or 0.0)) + extra + max(0.0, float(raw.get("clearance_m", 0.0) or 0.0))
            t = segment_circle_first_t(
                x1, y1, x2, y2,
                float(raw.get("x_m", 0.0) or 0.0),
                float(raw.get("y_m", 0.0) or 0.0),
                radius,
            )
        elif kind == "segment":
            radius = max(0.01, float(raw.get("clearance_m", 0.0) or 0.0) + extra)
            # A wall segment with clearance is represented as a narrow capsule.
            # Deterministic sampling at 2.5 cm is sufficient for the bounded
            # local patch and matches the previous resolver precision while
            # keeping this logic centralized.
            steps = max(2, min(480, int(math.ceil(distance / 0.025))))
            for step in range(1, steps):
                candidate_t = step / steps
                px = x1 + (x2 - x1) * candidate_t
                py = y1 + (y2 - y1) * candidate_t
                if point_segment_distance(
                    px, py,
                    float(raw.get("x1_m", 0.0) or 0.0),
                    float(raw.get("y1_m", 0.0) or 0.0),
                    float(raw.get("x2_m", 0.0) or 0.0),
                    float(raw.get("y2_m", 0.0) or 0.0),
                ) <= radius:
                    t = candidate_t
                    break
        if t is None or t <= 1e-6 or t >= 1.0 - 1e-6:
            continue
        # Obstacles are vertically infinite only when no vertical dimensions
        # are supplied. Represented walls/carts/cover with explicit height do
        # not block a line that physically passes over or under them.
        if "height_m" in raw or "base_elevation_m" in raw:
            base_z = float(raw.get("base_elevation_m", 0.0) or 0.0)
            height_z = max(0.01, float(raw.get("height_m", 0.01) or 0.01))
            path_z = float(start.get("elevation_m", 0.0)) + (float(end.get("elevation_m", 0.0)) - float(start.get("elevation_m", 0.0))) * float(t)
            vertical_clearance = max(0.0, float(raw.get("vertical_clearance_m", 0.0) or 0.0))
            if path_z < base_z - vertical_clearance or path_z > base_z + height_z + vertical_clearance:
                continue
        row = dict(raw)
        row.update({
            "label": label,
            "path_t": round(float(t), 8),
            "distance_from_start_m": round(distance * float(t), 6),
            "x_m_at_intersection": round(x1 + (x2 - x1) * float(t), 6),
            "y_m_at_intersection": round(y1 + (y2 - y1) * float(t), 6),
        })
        hits.append((float(t), label, row))
    if not hits:
        return None
    hits.sort(key=lambda row: (row[0], row[1]))
    return hits[0][2]


def _line_of_sight_segment(
    start: Mapping[str, Any],
    end: Mapping[str, Any],
    positions: Mapping[str, Mapping[str, Any]],
    obstacles: Sequence[Mapping[str, Any]],
    *,
    exclude_refs: Iterable[str] = (),
) -> dict[str, Any]:
    static = first_static_obstacle_on_segment(start, end, obstacles, clearance_m=0.01)
    if static is not None:
        return {
            "clear": False,
            "visibility_factor": 0.0,
            "static_blocker": static,
            "body_screen_refs": [],
            "reason": "static_obstacle_blocks_line_of_sight",
        }
    screens = body_intersections_on_segment(
        start,
        end,
        positions,
        exclude_refs=exclude_refs,
        half_width_m=0.015,
        elevation_start_m=float(start.get("elevation_m", 0.0)),
        elevation_end_m=float(end.get("elevation_m", 0.0)),
        vertical_tolerance_m=0.05,
    )
    factor = 1.0
    for _ in screens:
        factor *= 0.58
    factor = clamp(factor, 0.12 if screens else 1.0, 1.0)
    return {
        "clear": True,
        "visibility_factor": round(factor, 6),
        "static_blocker": None,
        "body_screen_refs": [str(row.get("ref")) for row in screens],
        "reason": "body_screening" if screens else "clear_line_of_sight",
    }


def line_of_sight_query(
    observer_ref: str,
    target_ref: str,
    positions: Mapping[str, Mapping[str, Any]],
    obstacles: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return the authoritative local LOS/cover answer between two bodies."""
    if observer_ref not in positions or target_ref not in positions:
        return {"clear": False, "visibility_factor": 0.0, "reason": "missing_local_geometry"}
    observer = normalize_position(positions[observer_ref])
    target = normalize_position(positions[target_ref])
    observer_height = max(0.15, float(positions[observer_ref].get("height_m", 1.75) or 1.75))
    target_height = max(0.15, float(positions[target_ref].get("height_m", 1.75) or 1.75))
    start = {**observer, "elevation_m": observer["elevation_m"] + observer_height * 0.86}
    end = {**target, "elevation_m": target["elevation_m"] + target_height * 0.72}
    return _line_of_sight_segment(start, end, positions, obstacles, exclude_refs=(observer_ref, target_ref))


def line_of_sight_to_point(
    observer_ref: str,
    target_point: Mapping[str, Any],
    positions: Mapping[str, Mapping[str, Any]],
    obstacles: Sequence[Mapping[str, Any]] = (),
    *,
    exclude_refs: Iterable[str] = (),
) -> dict[str, Any]:
    """LOS from a represented actor to an exact origin/contact point.

    This is used for released attacks so perception is checked against the
    physical attack origin rather than the shooter's later position.
    """
    if observer_ref not in positions:
        return {"clear": False, "visibility_factor": 0.0, "reason": "missing_local_geometry"}
    observer = normalize_position(positions[observer_ref])
    observer_height = max(0.15, float(positions[observer_ref].get("height_m", 1.75) or 1.75))
    start = {**observer, "elevation_m": observer["elevation_m"] + observer_height * 0.86}
    end = normalize_position(target_point)
    return _line_of_sight_segment(start, end, positions, obstacles, exclude_refs=tuple({observer_ref, *[str(x) for x in exclude_refs]}))


def segment_circle_first_t(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    cx: float,
    cy: float,
    radius: float,
) -> float | None:
    """Return first normalized segment parameter entering a circle, if any."""
    dx = x2 - x1
    dy = y2 - y1
    fx = x1 - cx
    fy = y1 - cy
    a = dx * dx + dy * dy
    r = max(0.0, float(radius))
    if a <= 1e-12:
        return 0.0 if math.hypot(fx, fy) <= r else None
    b = 2.0 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    root = math.sqrt(max(0.0, disc))
    t1 = (-b - root) / (2.0 * a)
    t2 = (-b + root) / (2.0 * a)
    candidates = [t for t in (t1, t2) if -1e-9 <= t <= 1.0 + 1e-9]
    if candidates:
        return clamp(min(candidates), 0.0, 1.0)
    # Segment may start inside the circle.
    if c <= 0.0:
        return 0.0
    return None


def first_body_intersection(
    *,
    start: Mapping[str, Any],
    end: Mapping[str, Any],
    body_positions: Mapping[str, Mapping[str, Any]],
    radii: Mapping[str, float],
    exclude_refs: Iterable[str] = (),
    vertical_tolerance_m: float = 1.25,
) -> dict[str, Any] | None:
    """Find the first occupied body intersected by a fixed 3D-ish local lane.

    Horizontal geometry is exact in the local plane. Elevation is linearly
    interpolated and used as a lightweight vertical gate so a body far above or
    below the attack lane is not struck merely because its x/y footprint overlaps.
    """
    excluded = {str(x) for x in exclude_refs}
    x1 = float(start.get("x_m", 0.0)); y1 = float(start.get("y_m", 0.0)); z1 = float(start.get("elevation_m", 0.0))
    x2 = float(end.get("x_m", 0.0)); y2 = float(end.get("y_m", 0.0)); z2 = float(end.get("elevation_m", 0.0))
    length = math.hypot(x2 - x1, y2 - y1)
    hits: list[tuple[float, str, dict[str, Any]]] = []
    for ref, pose in body_positions.items():
        if str(ref) in excluded:
            continue
        radius = max(0.01, float(radii.get(str(ref), 0.28)))
        t = segment_circle_first_t(x1, y1, x2, y2, float(pose.get("x_m", 0.0)), float(pose.get("y_m", 0.0)), radius)
        if t is None:
            continue
        lane_z = z1 + (z2 - z1) * t
        body_z = float(pose.get("elevation_m", 0.0))
        body_height = max(0.15, float(pose.get("height_m", 1.75) or 1.75))
        vertical_margin = max(0.0, float(vertical_tolerance_m))
        if lane_z < body_z - vertical_margin or lane_z > body_z + body_height + vertical_margin:
            continue
        hits.append((t, str(ref), {
            "ref": str(ref),
            "t": round(t, 8),
            "distance_from_start_m": round(length * t, 6),
            "x_m": round(x1 + (x2 - x1) * t, 6),
            "y_m": round(y1 + (y2 - y1) * t, 6),
            "elevation_m": round(lane_z, 6),
            "radius_m": round(radius, 6),
        }))
    if not hits:
        return None
    hits.sort(key=lambda row: (row[0], row[1]))
    return hits[0][2]


def bodies_in_line_corridor(
    *,
    origin: Mapping[str, Any],
    direction_deg: float,
    length_m: float,
    width_m: float,
    body_positions: Mapping[str, Mapping[str, Any]],
    radii: Mapping[str, float],
    exclude_refs: Iterable[str] = (),
) -> list[dict[str, Any]]:
    rad = math.radians(normalize_angle(direction_deg))
    length = max(0.0, float(length_m))
    end = {
        "x_m": float(origin.get("x_m", 0.0)) + math.cos(rad) * length,
        "y_m": float(origin.get("y_m", 0.0)) + math.sin(rad) * length,
        "elevation_m": float(origin.get("elevation_m", 0.0)),
    }
    excluded = {str(x) for x in exclude_refs}
    x1 = float(origin.get("x_m", 0.0)); y1 = float(origin.get("y_m", 0.0)); x2 = float(end["x_m"]); y2 = float(end["y_m"])
    half = max(0.0, float(width_m)) / 2.0
    rows: list[dict[str, Any]] = []
    for ref, pose in body_positions.items():
        if str(ref) in excluded:
            continue
        t, lateral = point_segment_projection(float(pose.get("x_m", 0.0)), float(pose.get("y_m", 0.0)), x1, y1, x2, y2)
        radius = max(0.01, float(radii.get(str(ref), 0.28)))
        if lateral <= half + radius + 1e-9:
            rows.append({"ref": str(ref), "along_m": round(length * t, 6), "lateral_m": round(lateral, 6), "radius_m": round(radius, 6)})
    rows.sort(key=lambda row: (row["along_m"], row["ref"]))
    return rows


def bodies_in_radius(
    *,
    center: Mapping[str, Any],
    radius_m: float,
    body_positions: Mapping[str, Mapping[str, Any]],
    radii: Mapping[str, float],
    exclude_refs: Iterable[str] = (),
) -> list[dict[str, Any]]:
    excluded = {str(x) for x in exclude_refs}
    result: list[dict[str, Any]] = []
    cx = float(center.get("x_m", 0.0)); cy = float(center.get("y_m", 0.0)); cz = float(center.get("elevation_m", 0.0))
    radius = max(0.0, float(radius_m))
    for ref, pose in body_positions.items():
        if str(ref) in excluded:
            continue
        d = math.sqrt((float(pose.get("x_m", 0.0))-cx)**2 + (float(pose.get("y_m", 0.0))-cy)**2 + (float(pose.get("elevation_m", 0.0))-cz)**2)
        if d <= radius + max(0.01, float(radii.get(str(ref), 0.28))):
            result.append({"ref": str(ref), "distance_m": round(d, 6)})
    result.sort(key=lambda row: (row["distance_m"], row["ref"]))
    return result


def bodies_in_cone(
    *,
    origin: Mapping[str, Any],
    direction_deg: float,
    length_m: float,
    cone_angle_deg: float,
    body_positions: Mapping[str, Mapping[str, Any]],
    radii: Mapping[str, float],
    exclude_refs: Iterable[str] = (),
) -> list[dict[str, Any]]:
    excluded = {str(x) for x in exclude_refs}
    result: list[dict[str, Any]] = []
    ox = float(origin.get("x_m", 0.0)); oy = float(origin.get("y_m", 0.0))
    half = max(0.0, float(cone_angle_deg)) / 2.0
    length = max(0.0, float(length_m))
    for ref, pose in body_positions.items():
        if str(ref) in excluded:
            continue
        dx = float(pose.get("x_m", 0.0)) - ox; dy = float(pose.get("y_m", 0.0)) - oy
        d = math.hypot(dx, dy)
        radius = max(0.01, float(radii.get(str(ref), 0.28)))
        if d > length + radius:
            continue
        bearing = normalize_angle(math.degrees(math.atan2(dy, dx)))
        angular_radius = math.degrees(math.atan2(radius, max(0.01, d)))
        delta = angle_delta(bearing, direction_deg)
        if delta <= half + angular_radius:
            result.append({"ref": str(ref), "distance_m": round(d, 6), "angle_delta_deg": round(delta, 6)})
    result.sort(key=lambda row: (row["distance_m"], row["ref"]))
    return result


__all__ = [
    "angle_delta",
    "bearing_deg",
    "bodies_in_cone",
    "bodies_in_line_corridor",
    "bodies_in_radius",
    "clamp",
    "distance_2d",
    "distance_3d",
    "elevation_angle_deg",
    "first_body_intersection",
    "first_static_obstacle_on_segment",
    "line_of_sight_query",
    "normalize_angle",
    "point_segment_distance",
    "point_segment_projection",
    "segment_circle_first_t",
    "signed_angle_delta",
]

# Compatibility/public helpers used by the exact-combat planner.  These names
# intentionally describe combat semantics rather than geometry implementation.
def angle_delta_deg(a_deg: float, b_deg: float) -> float:
    return angle_delta(a_deg, b_deg)


def normalize_position(row: Mapping[str, Any] | None, *, radius_m: float = 0.28) -> dict[str, float]:
    source = row if isinstance(row, Mapping) else {}
    return {
        "x_m": float(source.get("x_m", 0.0) or 0.0),
        "y_m": float(source.get("y_m", 0.0) or 0.0),
        "elevation_m": float(source.get("elevation_m", 0.0) or 0.0),
        "facing_deg": normalize_angle(float(source.get("facing_deg", 0.0) or 0.0)),
        "radius_m": max(0.05, float(source.get("radius_m", radius_m) or radius_m)),
    }


def body_intersections_on_segment(
    start: Mapping[str, Any] | Sequence[float],
    end: Mapping[str, Any] | Sequence[float],
    positions: Mapping[str, Mapping[str, Any]],
    *,
    exclude_refs: Iterable[str] = (),
    extra_radius_m: float = 0.0,
    half_width_m: float | None = None,
    elevation_start_m: float | None = None,
    elevation_end_m: float | None = None,
    vertical_tolerance_m: float = 1.25,
) -> list[dict[str, Any]]:
    """Return bodies physically intersected by a fixed post-commitment lane.

    The helper accepts either pose mappings or ``(x, y)`` tuples because older
    exact-combat callers used tuples.  ``half_width_m`` represents the physical
    projectile/attack corridor around the centerline and is added to each body's
    occupancy radius.  Results are ordered from origin outward; team membership
    is deliberately irrelevant.
    """
    excluded = {str(x) for x in exclude_refs}
    def pose(value, *, fallback_z=0.0):
        if isinstance(value, Mapping):
            return (float(value.get("x_m",0.0)), float(value.get("y_m",0.0)), float(value.get("elevation_m",fallback_z)))
        seq=list(value) if isinstance(value, Sequence) and not isinstance(value,(str,bytes,bytearray)) else []
        return (float(seq[0] if len(seq)>0 else 0.0), float(seq[1] if len(seq)>1 else 0.0), float(seq[2] if len(seq)>2 else fallback_z))
    x1,y1,z1=pose(start, fallback_z=0.0 if elevation_start_m is None else float(elevation_start_m))
    x2,y2,z2=pose(end, fallback_z=0.0 if elevation_end_m is None else float(elevation_end_m))
    if elevation_start_m is not None: z1=float(elevation_start_m)
    if elevation_end_m is not None: z2=float(elevation_end_m)
    length=math.hypot(x2-x1,y2-y1)
    lane=max(0.0,float(extra_radius_m)) + max(0.0,float(half_width_m or 0.0))
    rows=[]
    for ref, body in positions.items():
        if str(ref) in excluded: continue
        body_radius=max(0.05,float(body.get("radius_m",0.28) or 0.28))
        collision_radius=body_radius+lane
        t=segment_circle_first_t(x1,y1,x2,y2,float(body.get("x_m",0.0)),float(body.get("y_m",0.0)),collision_radius)
        if t is None: continue
        lane_z=z1+(z2-z1)*t
        body_base_z=float(body.get("elevation_m",0.0))
        body_height=max(0.15,float(body.get("height_m",1.75) or 1.75))
        vertical_margin=max(0.0,float(vertical_tolerance_m))
        if lane_z < body_base_z-vertical_margin or lane_z > body_base_z+body_height+vertical_margin:
            continue
        cx=x1+(x2-x1)*t; cy=y1+(y2-y1)*t
        _, centerline_offset=point_segment_projection(float(body.get("x_m",0.0)),float(body.get("y_m",0.0)),x1,y1,x2,y2)
        rows.append({
            "ref":str(ref), "t":round(t,8),
            "distance_along_m":round(length*t,6), "distance_from_start_m":round(length*t,6),
            "centerline_offset_m":round(centerline_offset,6),
            "x_m":round(cx,6), "y_m":round(cy,6), "elevation_m":round(lane_z,6),
            "body_radius_m":round(body_radius,6), "collision_radius_m":round(collision_radius,6),
        })
    rows.sort(key=lambda row:(float(row["t"]),row["ref"]))
    return rows


def surface_gap(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    """Center distance minus the target body's occupied radius.

    Weapon ``reach_m`` is interpreted as distance from the attacker's action
    origin to the contacted surface, not to the target's center.  This keeps
    contact-range unarmed attacks compatible with nonzero body occupancy.
    """
    return max(0.0, distance_3d(a,b)-max(0.0,float(b.get("radius_m",0.28) or 0.28)))

def members_in_lane(
    origin: Mapping[str, Any],
    direction_deg: float,
    length_m: float,
    width_m: float,
    positions: Mapping[str, Mapping[str, Any]],
    *,
    exclude_refs: Iterable[str] = (),
) -> list[dict[str, Any]]:
    radii = {str(ref): float(pose.get("radius_m",0.28) or 0.28) for ref, pose in positions.items()}
    return bodies_in_line_corridor(origin=origin,direction_deg=direction_deg,length_m=length_m,width_m=width_m,body_positions=positions,radii=radii,exclude_refs=exclude_refs)


def members_in_radius(
    center: Mapping[str, Any],
    radius_m: float,
    positions: Mapping[str, Mapping[str, Any]],
    *,
    exclude_refs: Iterable[str] = (),
) -> list[dict[str, Any]]:
    radii = {str(ref): float(pose.get("radius_m",0.28) or 0.28) for ref, pose in positions.items()}
    return bodies_in_radius(center=center,radius_m=radius_m,body_positions=positions,radii=radii,exclude_refs=exclude_refs)


def members_in_cone(
    origin: Mapping[str, Any],
    direction_deg: float,
    length_m: float,
    cone_angle_deg: float,
    positions: Mapping[str, Mapping[str, Any]],
    *,
    exclude_refs: Iterable[str] = (),
) -> list[dict[str, Any]]:
    radii = {str(ref): float(pose.get("radius_m",0.28) or 0.28) for ref, pose in positions.items()}
    return bodies_in_cone(origin=origin,direction_deg=direction_deg,length_m=length_m,cone_angle_deg=cone_angle_deg,body_positions=positions,radii=radii,exclude_refs=exclude_refs)


def surrounding_pressure(target_ref: str, hostile_refs: Sequence[str], positions: Mapping[str, Mapping[str, Any]], *, engagement_radius_m: float = 3.0) -> dict[str, Any]:
    if target_ref not in positions:
        return {"surrounded": False, "covered_arc_deg": 0.0, "largest_escape_gap_deg": 360.0, "bearings": []}
    target = positions[target_ref]
    bearings: list[float] = []
    for ref in hostile_refs:
        if ref == target_ref or ref not in positions:
            continue
        if distance_2d(target, positions[ref]) <= max(0.1,float(engagement_radius_m)) + float(positions[ref].get("radius_m",0.28)):
            bearings.append(bearing_deg(target, positions[ref]))
    if not bearings:
        return {"surrounded": False, "covered_arc_deg": 0.0, "largest_escape_gap_deg": 360.0, "bearings": []}
    bearings = sorted(bearings)
    gaps=[]
    for i,b in enumerate(bearings):
        nxt = bearings[(i+1)%len(bearings)] + (360.0 if i==len(bearings)-1 else 0.0)
        gaps.append(nxt-b)
    largest=max(gaps)
    covered=360.0-largest
    return {"surrounded": len(bearings)>=3 and largest<=145.0, "covered_arc_deg": round(covered,3), "largest_escape_gap_deg": round(largest,3), "bearings": [round(x,3) for x in bearings]}


def safest_escape_vector(
    target_ref: str,
    hostile_refs: Sequence[str],
    positions: Mapping[str, Mapping[str, Any]],
    *,
    preferred_distance_m: float = 1.0,
    obstacles: Sequence[Mapping[str, Any]] = (),
    clearance_radius_m: float | None = None,
) -> tuple[float, float]:
    """Choose a deterministic physically valid local escape ray.

    The old helper maximized distance from threats but could point directly
    through a wall or another occupied body.  This version rejects rays whose
    movement segment is obstructed and scores the remaining endpoints against
    *all* represented bodies, while still prioritizing separation from hostile
    bodies.  It remains intentionally lightweight: the exact resolver still
    clamps the final movement segment and owns the authoritative position.
    """
    if target_ref not in positions:
        return (0.0, 0.0)
    target = positions[target_ref]
    tx = float(target.get("x_m", 0.0)); ty = float(target.get("y_m", 0.0))
    relevant = [r for r in hostile_refs if r in positions and r != target_ref]
    occupied = [r for r in positions if r != target_ref]
    self_radius = max(0.05, float(clearance_radius_m if clearance_radius_m is not None else target.get("radius_m", 0.28) or 0.28))
    distance = max(0.05, float(preferred_distance_m))

    candidates: list[tuple[float, float, float, int, float, float]] = []
    for deg in range(0, 360, 15):
        rad = math.radians(deg); vx = math.cos(rad); vy = math.sin(rad)
        nx = tx + vx * distance; ny = ty + vy * distance
        blocker = first_static_obstacle_on_segment(
            {"x_m": tx, "y_m": ty},
            {"x_m": nx, "y_m": ny},
            obstacles,
            clearance_m=self_radius,
        )
        if blocker is not None:
            continue
        body_clearance = 999.0
        invalid_body = False
        for ref in occupied:
            pose = positions[ref]
            radius = max(0.05, float(pose.get("radius_m", 0.28) or 0.28))
            sep = math.hypot(nx - float(pose.get("x_m", 0.0)), ny - float(pose.get("y_m", 0.0)))
            body_clearance = min(body_clearance, sep - self_radius - radius)
            if sep < self_radius + radius - 1e-6:
                invalid_body = True
                break
        if invalid_body:
            continue
        hostile_clearance = min(
            [math.hypot(nx-float(positions[r].get("x_m",0.0)), ny-float(positions[r].get("y_m",0.0))) for r in relevant] or [999.0]
        )
        # Secondary term rewards opening a generally uncluttered route, not
        # merely fleeing one attacker into an ally or another enemy.
        candidates.append((hostile_clearance, body_clearance, -abs(signed_angle_delta(deg, float(target.get("facing_deg", 0.0)))), -deg, vx, vy))

    if candidates:
        _, _, _, _, vx, vy = max(candidates)
        return (vx, vy)

    # If every full-length ray is blocked, return the deterministic rearward
    # direction and let the authoritative movement clamp reduce it to whatever
    # physically valid displacement remains.
    facing = math.radians(normalize_angle(float(target.get("facing_deg", 0.0))) + 180.0)
    return (math.cos(facing), math.sin(facing))

# Extend public export list for runtime consumers.
__all__ += [
    "angle_delta_deg", "body_intersections_on_segment", "members_in_cone",
    "members_in_lane", "members_in_radius", "normalize_position",
    "safest_escape_vector", "surrounding_pressure", "surface_gap", "line_of_sight_to_point",
]
