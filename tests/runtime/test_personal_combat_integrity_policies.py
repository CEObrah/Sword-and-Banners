from __future__ import annotations

from pathlib import Path

from sword_runtime.combat_commitment import (
    first_linear_melee_body_blocker,
    pending_action_preservation,
)


def _attack(*, start_at_s: float = 0.2, resolve_at_s: float = 1.2):
    return {
        "kind": "attack",
        "actor_ref": "defender",
        "target_ref": "attacker",
        "start_at_s": start_at_s,
        "resolve_at_s": resolve_at_s,
    }


def _poses():
    return {
        "rear": {"x_m": 0.0, "y_m": 0.0, "elevation_m": 0.0, "height_m": 1.75, "radius_m": 0.28},
        "front": {"x_m": 1.0, "y_m": 0.0, "elevation_m": 0.0, "height_m": 1.75, "radius_m": 0.28},
        "target": {"x_m": 2.0, "y_m": 0.0, "elevation_m": 0.0, "height_m": 1.75, "radius_m": 0.28},
    }


def test_brace_preserves_started_offense_outside_simultaneous_window():
    reason = pending_action_preservation(
        "brace",
        _attack(start_at_s=0.2, resolve_at_s=1.8),
        resolve_at_s=0.8,
        simultaneous_window_s=0.08,
    )
    assert reason == "brace_preserves_started_offense"


def test_brace_does_not_preserve_attack_that_has_not_started():
    assert pending_action_preservation(
        "brace",
        _attack(start_at_s=1.0, resolve_at_s=1.8),
        resolve_at_s=0.8,
        simultaneous_window_s=0.08,
    ) is None


def test_hard_defense_preserves_only_actual_simultaneous_contact():
    near = _attack(start_at_s=0.2, resolve_at_s=0.84)
    far = _attack(start_at_s=0.2, resolve_at_s=1.40)
    assert pending_action_preservation(
        "parry", near, resolve_at_s=0.8, simultaneous_window_s=0.08
    ) == "simultaneous_contact"
    assert pending_action_preservation(
        "parry", far, resolve_at_s=0.8, simultaneous_window_s=0.08
    ) is None


def test_non_attack_pending_action_is_not_protected_by_brace():
    movement = {
        "kind": "movement",
        "start_at_s": 0.2,
        "resolve_at_s": 1.2,
    }
    assert pending_action_preservation(
        "brace", movement, resolve_at_s=0.8, simultaneous_window_s=0.08
    ) is None


def test_linear_thrust_is_blocked_by_intervening_body():
    poses = _poses()
    blocker = first_linear_melee_body_blocker(
        actor_ref="rear",
        target_ref="target",
        attack_mode="thrust",
        start=poses["rear"],
        end=poses["target"],
        positions=poses,
    )
    assert blocker is not None
    assert blocker["kind"] == "body"
    assert blocker["ref"] == "front"
    assert blocker["reason"] == "intervening_body_blocks_linear_melee_lane"
    assert 0.0 < float(blocker["path_t"]) < 1.0


def test_linear_thrust_allows_open_side_lane():
    poses = _poses()
    poses["front"] = {**poses["front"], "y_m": 0.75}
    assert first_linear_melee_body_blocker(
        actor_ref="rear",
        target_ref="target",
        attack_mode="thrust",
        start=poses["rear"],
        end=poses["target"],
        positions=poses,
    ) is None


def test_centerline_body_does_not_fake_block_for_cut_arc():
    poses = _poses()
    assert first_linear_melee_body_blocker(
        actor_ref="rear",
        target_ref="target",
        attack_mode="cut",
        start=poses["rear"],
        end=poses["target"],
        positions=poses,
    ) is None


def test_personal_combat_wires_commitment_and_melee_lane_policies():
    root = Path(__file__).resolve().parents[2]
    source = (root / "runtime/sword_runtime/personal_combat.py").read_text(encoding="utf-8")
    assert "pending_action_preservation(" in source
    assert "first_linear_melee_body_blocker(" in source
    assert "pending_offense_preserved" in source
