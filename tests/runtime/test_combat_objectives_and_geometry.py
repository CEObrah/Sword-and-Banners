from sword_runtime.combat_geometry import first_static_obstacle_on_segment, line_of_sight_to_point
from sword_runtime.combat_objectives import objective_model, evaluate_objective


def _people(*refs):
    return {ref: {"life_status": "active", "combat_state": {}} for ref in refs}


def _active(people):
    return lambda ref: people[ref]["life_status"] == "active" and not people[ref].get("combat_state", {}).get("incapacitated")


def test_vertical_cover_does_not_block_a_line_above_it():
    obstacle = {"kind": "segment", "x1_m": 1, "y1_m": -2, "x2_m": 1, "y2_m": 2, "clearance_m": 0.05, "base_elevation_m": 0.0, "height_m": 1.0}
    assert first_static_obstacle_on_segment({"x_m": 0, "y_m": 0, "elevation_m": 2.0}, {"x_m": 2, "y_m": 0, "elevation_m": 2.0}, [obstacle]) is None
    assert first_static_obstacle_on_segment({"x_m": 0, "y_m": 0, "elevation_m": 0.5}, {"x_m": 2, "y_m": 0, "elevation_m": 0.5}, [obstacle]) is not None


def test_los_to_exact_release_origin_uses_same_obstruction_authority():
    positions = {"defender": {"x_m": 0, "y_m": 0, "elevation_m": 0, "height_m": 1.75, "radius_m": 0.28}}
    wall = {"kind": "segment", "x1_m": 1, "y1_m": -2, "x2_m": 1, "y2_m": 2, "clearance_m": 0.05, "base_elevation_m": 0, "height_m": 2.5}
    result = line_of_sight_to_point("defender", {"x_m": 2, "y_m": 0, "elevation_m": 1.4}, positions, [wall])
    assert result["clear"] is False
    assert result["reason"] == "static_obstacle_blocks_line_of_sight"


def test_capture_requires_targets_alive_and_neutralized():
    people = _people("enemy")
    model = objective_model("capture them alive", ["enemy"], actor_refs=["player"])
    people["enemy"]["combat_state"]["incapacitated"] = True
    result = evaluate_objective(model, people, _active(people))
    assert result["completed"] is True
    people["enemy"]["life_status"] = "dead"
    result = evaluate_objective(model, people, _active(people))
    assert result["completed"] is False
    assert result["failed"] is True


def test_protect_succeeds_only_after_threats_neutralized_and_protected_survives():
    people = _people("player", "enemy")
    model = objective_model("protect the player", ["enemy"], ["player"], actor_refs=["player"])
    assert evaluate_objective(model, people, _active(people))["completed"] is False
    people["enemy"]["combat_state"]["incapacitated"] = True
    assert evaluate_objective(model, people, _active(people))["completed"] is True
    people["player"]["combat_state"]["incapacitated"] = True
    assert evaluate_objective(model, people, _active(people))["failed"] is True


def test_escape_is_spatial_and_seize_hold_require_registered_point():
    people = _people("player", "enemy")
    active = _active(people)
    positions = {"player": {"x_m": 0, "y_m": 0, "elevation_m": 0}, "enemy": {"x_m": 12, "y_m": 0, "elevation_m": 0}}
    escape = objective_model("escape", ["enemy"], actor_refs=["player"], escape_distance_m=8)
    assert evaluate_objective(escape, people, active, positions=positions)["completed"] is True
    seize = objective_model("seize the gate", ["enemy"], actor_refs=["player"], objective_position={"x_m": 0, "y_m": 0}, objective_radius_m=1.0)
    assert evaluate_objective(seize, people, active, positions=positions)["completed"] is True
    hold = objective_model("hold position", ["enemy"], actor_refs=["player"], objective_position={"x_m": 0, "y_m": 0}, objective_radius_m=1.0, hold_seconds=5)
    assert evaluate_objective(hold, people, active, positions=positions, elapsed_seconds=4.9)["completed"] is False
    assert evaluate_objective(hold, people, active, positions=positions, elapsed_seconds=5.0)["completed"] is True
