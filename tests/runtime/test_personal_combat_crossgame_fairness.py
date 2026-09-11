from __future__ import annotations

import json
import math
import subprocess
from collections import Counter
from collections.abc import Mapping


def _commit(campaign, *paths: str) -> None:
    subprocess.run(["git", "-C", str(campaign), "add", *paths], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "personal combat fairness fixture"], check=True)


def _fighter(ref: str, *, role: str = "fighter", medicine: int = 0) -> dict:
    return {
        "owner_id": ref,
        "role": role,
        "combat_state": {},
        "fatigue": 0,
        "attributes": {
            "Strength": 100,
            "Agility": 100,
            "Coordination": 100,
            "Awareness": 100,
            "Composure": 100,
            "Endurance": 100,
        },
        "skills": {
            "Sword": 100,
            "Shield": 80,
            "Athletics": 100,
            "Medicine": medicine,
        },
    }


def _combat_profiles(refs):
    equipment = {
        ref: {
            "weapon": {"family": "sword", "reach_m": 0.85},
            "loadout": {},
        }
        for ref in refs
    }
    controls = {
        ref: {"attack": 100, "parry": 90, "block": 70, "dodge": 85}
        for ref in refs
    }
    return equipment, controls


def test_medical_profession_does_not_reserve_a_fighter_from_exact_melee():
    """Profession/capability is not a permanent combat posture.

    A medic may later receive a real treatment/extraction task, but merely being
    a medic cannot remove an otherwise fit present body from the combat planner.
    """
    from sword_runtime.combat_tactics import build_team_plan

    side = [f"ally_{i}" for i in range(12)]
    enemies = [f"enemy_{i}" for i in range(18)]
    people = {ref: _fighter(ref) for ref in side + enemies}
    people["ally_11"] = _fighter("ally_11", role="field_medic", medicine=220)
    equipment, controls = _combat_profiles(side + enemies)
    positions = {
        **{ref: {"x_m": 0.0, "y_m": float(i), "facing_deg": 0.0} for i, ref in enumerate(side)},
        **{ref: {"x_m": 2.0, "y_m": float(i), "facing_deg": 180.0} for i, ref in enumerate(enemies)},
    }
    plan = build_team_plan(
        side,
        enemies,
        people=people,
        equipment=equipment,
        controls=controls,
        positions=positions,
        objective="survive and defeat the attackers",
        at_s=0.0,
    )
    assert set(plan["assignments"]) == set(side)
    assert "ally_11" in plan["assignments"]
    assert plan["assignments"]["ally_11"]["target_ref"] in enemies
    assert plan["assignments"]["ally_11"]["role"] not in {"medical", "reserve", "hold"}

    # Being outnumbered does not silently subtract bodies from the fighting
    # side. Every fit ally receives an active enemy lane before any dog-pile.
    side_targets = [row["target_ref"] for row in plan["assignments"].values()]
    assert len(side_targets) == 12
    assert len(set(side_targets)) == 12

    enemy_plan = build_team_plan(
        enemies,
        side,
        people=people,
        equipment=equipment,
        controls=controls,
        positions=positions,
        objective="survive and defeat the defenders",
        at_s=0.0,
    )
    assert set(enemy_plan["assignments"]) == set(enemies)
    enemy_targets = [row["target_ref"] for row in enemy_plan["assignments"].values()]
    target_load = Counter(enemy_targets)
    assert set(target_load) == set(side)
    assert max(target_load.values()) <= 2


def test_unspecified_multi_person_geometry_starts_as_opposed_fronts_not_free_encirclement():
    from sword_runtime.personal_combat import _default_personal_combat_positions

    player_side = ["player"] + [f"ally_{i}" for i in range(11)]
    hostile_side = [f"enemy_{i}" for i in range(18)]
    positions = _default_personal_combat_positions(
        player_ref="player",
        player_side=player_side,
        hostile_side=hostile_side,
        start_distance=2.4,
        mounted_refs=set(),
    )

    assert positions["player"]["x_m"] == 0.0
    assert all(positions[ref]["x_m"] <= 0.0 for ref in player_side)
    assert all(positions[ref]["x_m"] >= 2.4 for ref in hostile_side)

    # An unspecified encounter may be dangerous because of numbers, reach and
    # skill. It may not silently grant the enemy a 360-degree encirclement.
    bearings = []
    px, py = positions["player"]["x_m"], positions["player"]["y_m"]
    for ref in hostile_side:
        dx = positions[ref]["x_m"] - px
        dy = positions[ref]["y_m"] - py
        bearings.append(math.degrees(math.atan2(dy, dx)))
    assert max(bearings) - min(bearings) < 180.0

    # Staging itself must not overlap bodies.
    refs = player_side + hostile_side
    for i, left in enumerate(refs):
        for right in refs[i + 1 :]:
            dx = positions[left]["x_m"] - positions[right]["x_m"]
            dy = positions[left]["y_m"] - positions[right]["y_m"]
            distance = math.hypot(dx, dy)
            minimum = positions[left]["radius_m"] + positions[right]["radius_m"]
            assert distance + 1e-9 >= minimum, (left, right, distance, minimum)

    # The same neutral fallback must remain physical for mounted bodies. A short
    # requested start distance cannot spawn opposing horses inside one another.
    mounted = _default_personal_combat_positions(
        player_ref="mounted_player",
        player_side=["mounted_player", "foot_ally"],
        hostile_side=["mounted_enemy", "foot_enemy"],
        start_distance=0.6,
        mounted_refs={"mounted_player", "mounted_enemy"},
        preserve_start_distance=True,
    )
    mounted_refs = list(mounted)
    for i, left in enumerate(mounted_refs):
        for right in mounted_refs[i + 1 :]:
            dx = mounted[left]["x_m"] - mounted[right]["x_m"]
            dy = mounted[left]["y_m"] - mounted[right]["y_m"]
            distance = math.hypot(dx, dy)
            minimum = mounted[left]["radius_m"] + mounted[right]["radius_m"]
            assert distance + 1e-9 >= minimum, (left, right, distance, minimum)


def test_generic_autonomous_targeting_is_actor_conditioned_not_synchronized_body_part_spam(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    target = {"owner_id": "target", "anatomy_state": {"structures": {}}}
    aims = []
    for i in range(16):
        actor = _fighter(f"generic_spear_{i}")
        aim = planner._personal_aim_plan(
            None,
            lethal_intent=False,
            seed=991,
            sequence=1,
            actor=actor,
            target_person=target,
            target_eq={"loadout": {}},
            attack_bearing_deg=(i * 11.0) % 360.0,
        )
        aims.append((aim["side"], aim["structure"]))

    assert len(set(aims)) >= 3, aims

    # Same actor + same physical state remains deterministic for replay/idempotency.
    actor = _fighter("generic_spear_3")
    first = planner._personal_aim_plan(
        None, lethal_intent=False, seed=991, sequence=1,
        actor=actor, target_person=target, target_eq={"loadout": {}}, attack_bearing_deg=33.0,
    )
    second = planner._personal_aim_plan(
        None, lethal_intent=False, seed=991, sequence=1,
        actor=actor, target_person=target, target_eq={"loadout": {}}, attack_bearing_deg=33.0,
    )
    assert first == second

    # Geometry is causal, not merely another hash input. From the target's left
    # flank a paired limb target resolves left; mirror the same actor to the right
    # flank and the side mirrors with it.
    left_flank = planner._personal_aim_plan(
        None, lethal_intent=False, seed=991, sequence=1,
        actor=actor, target_person=target, target_eq={"loadout": {}},
        attack_bearing_deg=90.0, target_facing_deg=0.0,
    )
    right_flank = planner._personal_aim_plan(
        None, lethal_intent=False, seed=991, sequence=1,
        actor=actor, target_person=target, target_eq={"loadout": {}},
        attack_bearing_deg=270.0, target_facing_deg=0.0,
    )
    assert left_flank["side"] == "left", left_flank
    assert right_flank["side"] == "right", right_flank



def test_shared_registered_doctrine_is_preference_not_synchronized_anatomy_script(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    target = {"owner_id": "shared_doctrine_target", "anatomy_state": {"structures": {}}}
    structures = []
    for i in range(18):
        actor = _fighter(f"doctrine_fighter_{i}")
        actor["combat_doctrine_ref"] = "doc.tang_wei.personal_combat"
        aim = planner._personal_aim_plan(
            None,
            lethal_intent=False,
            seed=1771,
            sequence=1,
            actor=actor,
            target_person=target,
            target_eq={"loadout": {}},
            attack_bearing_deg=(i * 13.0) % 360.0,
        )
        assert aim["selection_basis"] == "registered_combat_doctrine"
        structures.append(aim["structure"])

    # A common doctrine may bias the group toward efficient function-denial
    # targets, but actor identity and local attack geometry must prevent the
    # doctrine record from becoming one synchronized anatomy macro.
    assert len(set(structures)) >= 2, structures
    assert structures.count("wrist") >= 9, structures

    actor = _fighter("doctrine_fighter_5")
    actor["combat_doctrine_ref"] = "doc.tang_wei.personal_combat"
    first = planner._personal_aim_plan(
        None, lethal_intent=False, seed=1771, sequence=1, actor=actor,
        target_person=target, target_eq={"loadout": {}}, attack_bearing_deg=65.0,
    )
    second = planner._personal_aim_plan(
        None, lethal_intent=False, seed=1771, sequence=1, actor=actor,
        target_person=target, target_eq={"loadout": {}}, attack_bearing_deg=65.0,
    )
    assert first == second

def _materialize_spearman(campaign, ref: str, name: str) -> str:
    from conftest import execute_internal

    player = json.loads((campaign / "state/player.json").read_text())
    execute_internal(campaign, "person_materialize", {
        "state": "qin",
        "person_ref": ref,
        "name": name,
        "birth_date": "270-BCE-01-01",
        "role": "command_personnel",
        "source_location_ref": player["location"],
    })
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    path = campaign / owners[ref]
    person = json.loads(path.read_text())
    person.setdefault("attributes", {}).update({
        "Strength": 100, "Agility": 100, "Coordination": 100,
        "Awareness": 100, "Composure": 100, "Endurance": 100,
    })
    person.setdefault("skills", {}).update({"Polearms": 130, "Sword": 20, "Athletics": 100, "Shield": 40})
    manifest_rel = f"state/test-person-equipment/{ref}.json"
    manifest_path = campaign / manifest_rel
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "schema": "player-equipment-manifest",
        "authority": "player_equipment_manifest",
        "player_ref": ref,
        "equipment_manifest": [
            {"item_id": "weapon_spear", "quantity": 1, "custody": "fairness fixture", "current_state": "equipped/readied"},
        ],
    }, ensure_ascii=False, indent=2) + "\n")
    person["equipment_manifest_ref"] = manifest_rel
    path.write_text(json.dumps(person, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, owners[ref], manifest_rel)
    return owners[ref]


def test_blocked_rear_spear_does_not_consume_intended_targets_defense_bandwidth(campaign):
    from conftest import execute

    rear = "char_test_rear_spear"
    front = "char_test_front_spear"
    _materialize_spearman(campaign, rear, "Rear Spearman")
    _materialize_spearman(campaign, front, "Front Spearman")

    result = execute(campaign, "personal_combat", {
        "opponent_refs": [rear, front],
        "objective": "defend the position",
        "duration_minutes": 1,
        "intent_sequence": ["brace", "brace", "brace"],
        "participant_positions": {
            rear: {"x_m": 0, "y_m": 0, "facing_deg": 0},
            front: {"x_m": 1, "y_m": 0, "facing_deg": 0},
            "char_tang_wei": {"x_m": 3, "y_m": 0, "facing_deg": 180},
        },
    }).receipt.result

    blocked = [
        row for row in result["causal_trace"]
        if row.get("kind") == "attack"
        and row.get("actor_ref") == rear
        and isinstance(row.get("path_blocked_by"), Mapping)
        and row["path_blocked_by"].get("ref") == front
    ]
    assert blocked, result["causal_trace"]
    for row in blocked:
        assert row["range_legal"] is False
        assert row["defense_method"] == "none"
        assert float(row["active_defense_load_after"]) == float(row["active_defense_load_before"])
        blocked_action_id = row["id"].removesuffix("_attack")
        assert not any(
            event.get("kind") == "weapon_interaction"
            and event.get("id") == blocked_action_id + "_defense"
            for event in result["causal_trace"]
        )


def test_linear_melee_body_blocking_is_side_neutral():
    from sword_runtime.combat_commitment import first_linear_melee_body_blocker

    forward = {
        "rear": {"x_m": 0.0, "y_m": 0.0, "elevation_m": 0.0, "height_m": 1.75, "radius_m": 0.28},
        "screen": {"x_m": 1.0, "y_m": 0.0, "elevation_m": 0.0, "height_m": 1.75, "radius_m": 0.28},
        "target": {"x_m": 3.0, "y_m": 0.0, "elevation_m": 0.0, "height_m": 1.75, "radius_m": 0.28},
    }
    first = first_linear_melee_body_blocker(
        actor_ref="rear", target_ref="target", attack_mode="thrust",
        start=forward["rear"], end=forward["target"], positions=forward,
    )
    assert first and first["ref"] == "screen"

    # Mirror the exact geometry and rename the participants. Team identity is
    # intentionally absent from the blocker authority, so the answer must be
    # identical for the other side of a fight.
    mirrored = {
        "other_rear": {"x_m": 3.0, "y_m": 0.0, "elevation_m": 0.0, "height_m": 1.75, "radius_m": 0.28},
        "other_screen": {"x_m": 2.0, "y_m": 0.0, "elevation_m": 0.0, "height_m": 1.75, "radius_m": 0.28},
        "other_target": {"x_m": 0.0, "y_m": 0.0, "elevation_m": 0.0, "height_m": 1.75, "radius_m": 0.28},
    }
    second = first_linear_melee_body_blocker(
        actor_ref="other_rear", target_ref="other_target", attack_mode="thrust",
        start=mirrored["other_rear"], end=mirrored["other_target"], positions=mirrored,
    )
    assert second and second["ref"] == "other_screen"
    assert abs(float(first["path_t"]) - float(second["path_t"])) < 1e-9
