from __future__ import annotations

from sword_runtime.combat_geometry import first_static_obstacle_on_segment, line_of_sight_query


def _wall():
    return {
        "kind": "segment",
        "label": "stone wall",
        "x1_m": 5.0,
        "y1_m": -2.0,
        "x2_m": 5.0,
        "y2_m": 2.0,
        "clearance_m": "0.02",
    }


def test_static_wall_blocks_direct_contact_segment():
    blocker = first_static_obstacle_on_segment(
        {"x_m": 0.0, "y_m": 0.0},
        {"x_m": 10.0, "y_m": 0.0},
        [_wall()],
        clearance_m=0.01,
    )
    assert blocker is not None
    assert blocker["label"] == "stone wall"
    assert 0.0 < float(blocker["path_t"]) < 1.0


def test_static_wall_blocks_target_acquisition_line_of_sight():
    positions = {
        "observer": {"x_m": 0.0, "y_m": 0.0, "elevation_m": 0.0, "height_m": 1.75, "radius_m": 0.28},
        "target": {"x_m": 10.0, "y_m": 0.0, "elevation_m": 0.0, "height_m": 1.75, "radius_m": 0.28},
    }
    los = line_of_sight_query("observer", "target", positions, [_wall()])
    assert los["clear"] is False
    assert los["reason"] == "static_obstacle_blocks_line_of_sight"
    assert los["static_blocker"]["label"] == "stone wall"
