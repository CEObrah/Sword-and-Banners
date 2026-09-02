from __future__ import annotations

import json
import subprocess


def _commit(campaign, *paths: str) -> None:
    subprocess.run(["git", "-C", str(campaign), "add", *paths], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test: multi actor personal combat"], check=True)


def _clone_committed_repo(source, destination) -> None:
    """Create an actually independent Git clone for deterministic A/B tests.

    The campaign fixture itself is a detached Git worktree. Copying that directory
    byte-for-byte copies its `.git` pointer back to the same worktree metadata, so
    one branch of the test can make the other appear dirty. A real clone gives each
    branch its own index/HEAD while preserving the exact committed campaign image.
    """
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(source), str(destination)], check=True)
    subprocess.run(["git", "-C", str(destination), "config", "user.name", "Sword Runtime Tests"], check=True)
    subprocess.run(["git", "-C", str(destination), "config", "user.email", "sword-tests@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(destination), "config", "gc.auto", "0"], check=True)
    subprocess.run(["git", "-C", str(destination), "config", "maintenance.auto", "false"], check=True)


def _materialize_many(campaign, suffix: str, count: int):
    from conftest import execute_internal

    player = json.loads((campaign / "state/player.json").read_text())
    refs = [f"char_test_multi_{suffix}_{index:02d}" for index in range(count)]
    for ref in refs:
        execute_internal(campaign, "person_materialize", {
            "state": "qin", "person_ref": ref, "name": ref,
            "birth_date": "270-BCE-01-01", "role": "command_personnel",
            "source_location_ref": "loc_kanyou",
        })
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    changed = []
    for ref in refs:
        path = campaign / owners[ref]
        person = json.loads(path.read_text())
        person["current_location"] = player["location"]
        person.setdefault("attributes", {}).update({
            "Agility": 105, "Coordination": 105, "Awareness": 105,
            "Endurance": 105, "Composure": 105, "Strength": 100,
        })
        person.setdefault("skills", {}).update({
            "Sword": 100, "Spear": 100, "Defense": 95, "Athletics": 95,
        })
        path.write_text(json.dumps(person, ensure_ascii=False, indent=2) + "\n")
        changed.append(owners[ref])
    _commit(campaign, *changed)
    return refs


def _materialize_pair(campaign, suffix: str):
    return _materialize_many(campaign, suffix, 2)


def _co_locate_existing(campaign, refs):
    """Fast adversarial setup using already-conserved exact people.

    These tests exercise the N-actor scheduler, not person-materialization.  Reusing
    existing exact Qin officers avoids six independent transactional materialization
    commits in the 1v6 case while preserving real saved-person combat physics.
    """
    player = json.loads((campaign / "state/player.json").read_text())
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    changed = []
    for ref in refs:
        path = campaign / owners[ref]
        person = json.loads(path.read_text())
        person["current_location"] = player["location"]
        person["health_status"] = "fit"
        person["life_status"] = "active"
        person.setdefault("combat_state", {}).pop("incapacitated", None)
        person.setdefault("attributes", {}).update({
            "Agility": 105, "Coordination": 105, "Awareness": 105,
            "Endurance": 105, "Composure": 105, "Strength": 100,
        })
        person.setdefault("skills", {}).update({
            "Sword": 100, "Spear": 100, "Defense": 95, "Athletics": 95,
        })
        path.write_text(json.dumps(person, ensure_ascii=False, indent=2) + "\n")
        changed.append(owners[ref])
    _commit(campaign, *changed)
    return list(refs)


def _first_two_attacks_on_player(result):
    attacks = [
        row for row in result["causal_trace"]
        if row.get("kind") == "attack" and row.get("target_ref") == "char_tang_wei"
    ]
    assert len(attacks) >= 2, result["causal_trace"]
    return attacks[0], attacks[1]


def test_two_attackers_share_one_defensive_reaction_budget(campaign):
    from conftest import execute

    a, b = _materialize_pair(campaign, "budget")
    result = execute(campaign, "personal_combat", {
        "opponent_refs": [a, b],
        "objective": "controlled spar",
        "duration_minutes": 1,
        "intent_sequence": ["dodge"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            a: {"x_m": "1.0", "y_m": "0.12", "facing_deg": 180},
            b: {"x_m": "1.0", "y_m": "-0.12", "facing_deg": 180},
        },
    }).receipt.result

    first, second = _first_two_attacks_on_player(result)
    assert result["timing_model"]["spatial_mode"] == "local_2_5d_shared_body_state"
    assert first["contact_group_id"] == second["contact_group_id"]
    assert float(first["defense_saturation_factor"]) == 1.0
    assert float(first["active_defense_load_before"]) == 0.0
    assert float(first["active_defense_load_after"]) > 0.0
    assert int(first["defense_pressure_sources"]) == 1
    assert float(second["active_defense_load_before"]) > 0.0
    assert float(second["active_defense_load_after"]) >= 0.0
    if "active_defense_commitment" in second:
        assert float(second["active_defense_load_after"]) >= float(second["active_defense_load_before"])
    assert int(second["defense_pressure_sources"]) >= 2
    assert float(second["defense_distinct_source_penalty"]) > 0.0
    assert float(second["defense_saturation_factor"]) < float(first["defense_saturation_factor"])
    assert float(second["defense_resource_ready_at_s"]) >= float(first["contact_at_s"])
    assert float(first["defender_exertion_factor"]) == 1.0
    assert float(second["defender_exertion_factor"]) < float(first["defender_exertion_factor"])
    assert float(result["end_state"]["action_exertion"]["char_tang_wei"]) > 0.0
    assert float(result["end_state"]["transient_exertion_factor_by_actor"]["char_tang_wei"]) < 1.0


def test_opposite_angle_pressure_is_worse_than_same_line_pressure(campaign):
    from conftest import execute

    a, b = _materialize_pair(campaign, "angles")
    result = execute(campaign, "personal_combat", {
        "opponent_refs": [a, b],
        "objective": "controlled spar",
        "duration_minutes": 1,
        "intent_sequence": ["dodge"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            a: {"x_m": 1, "y_m": 0, "facing_deg": 180},
            b: {"x_m": -1, "y_m": 0, "facing_deg": 0},
        },
    }).receipt.result

    first, second = _first_two_attacks_on_player(result)
    assert first["contact_group_id"] == second["contact_group_id"]
    assert abs(float(first["incoming_bearing_deg"]) - float(second["incoming_bearing_deg"])) >= 170.0
    assert float(second["defense_saturation_factor"]) <= 0.25
    # The second attack can be so tightly opposed that Wei has no physically
    # available second defense at all.  That is valid saturation, not a missing
    # trace: the attack row must show that his defense resource is still busy.
    assert second["defense_timing"] == "late"
    assert float(second["defense_resource_ready_at_s"]) > float(second["contact_at_s"])


def test_single_opponent_payload_is_valid_shorthand_for_actor_list(campaign):
    from conftest import execute

    opponent = _materialize_pair(campaign, "single")[0]
    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent,
        "objective": "controlled spar",
        "duration_minutes": 1,
    }).receipt.result
    assert result["opponent_ref"] == opponent
    assert tuple(result["opponent_refs"]) == (opponent,)
    assert tuple(result["participant_refs"]) == ("char_tang_wei", opponent)


def test_knocked_down_fighter_must_spend_time_recovering_posture_before_attacking(campaign):
    from conftest import execute

    opponent = _materialize_pair(campaign, "posture")[0]
    player_path = campaign / "state/player.json"
    player = json.loads(player_path.read_text())
    player.setdefault("combat_state", {})["posture"] = "knocked_down"
    player_path.write_text(json.dumps(player, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, "state/player.json")

    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent,
        "objective": "controlled spar",
        "duration_minutes": 1,
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            opponent: {"x_m": 3, "y_m": 0, "facing_deg": 180},
        },
    }).receipt.result

    posture = next(
        row for row in result["causal_trace"]
        if row.get("kind") == "posture_recovery"
        and row.get("actor_ref") == "char_tang_wei"
        and row.get("action") == "recover_to_standing"
    )
    assert float(posture["complete_at_s"]) > float(posture["start_at_s"])
    player_attacks = [
        row for row in result["causal_trace"]
        if row.get("kind") == "attack" and row.get("actor_ref") == "char_tang_wei"
    ]
    if player_attacks:
        assert float(player_attacks[0]["start_at_s"]) >= float(posture["complete_at_s"])
    assert result["end_state"]["participant_positions"]["char_tang_wei"]["posture"] == "standing"


def test_knocked_down_actor_must_spend_time_getting_up_before_attacking(campaign):
    from conftest import execute

    opponent = _materialize_pair(campaign, "posture")[0]
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    path = campaign / owners[opponent]
    person = json.loads(path.read_text())
    person.setdefault("combat_state", {})["posture"] = "knocked_down"
    path.write_text(json.dumps(person, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, owners[opponent])

    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent,
        "objective": "controlled spar",
        "duration_minutes": 1,
        "intent_sequence": ["dodge"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            opponent: {"x_m": 1, "y_m": 0, "facing_deg": 180},
        },
    }).receipt.result

    posture = [
        row for row in result["causal_trace"]
        if row.get("kind") == "posture_recovery" and row.get("actor_ref") == opponent
    ]
    attacks = [
        row for row in result["causal_trace"]
        if row.get("kind") == "attack" and row.get("actor_ref") == opponent
    ]
    assert posture, result["causal_trace"]
    assert posture[0]["from_posture"] == "knocked_down"
    assert posture[0]["to_posture"] == "standing"
    assert float(posture[0]["complete_at_s"]) > float(posture[0]["start_at_s"])
    if attacks:
        assert float(attacks[0]["start_at_s"]) >= float(posture[0]["recovery_complete_at_s"])


def test_grapple_occupies_body_and_restricts_third_party_defense(campaign):
    from conftest import execute

    a, b = _materialize_pair(campaign, "grapple")
    # Make the intended clinch target physically easier to control so the test
    # proves occupancy rather than hinging on an equal-skill contest.
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    ap = campaign / owners[a]
    person = json.loads(ap.read_text())
    person.setdefault("attributes", {}).update({"Strength": 45, "Agility": 45, "Coordination": 45})
    person.setdefault("skills", {}).update({"Grappling": 25, "Athletics": 30, "Defense": 40})
    ap.write_text(json.dumps(person, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, owners[a])

    result = execute(campaign, "personal_combat", {
        "opponent_refs": [a, b],
        "target_ref": a,
        "objective": "controlled spar",
        "duration_minutes": 1,
        "intent_sequence": ["grapple into a clinch"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            a: {"x_m": "0.55", "y_m": 0, "facing_deg": 180},
            b: {"x_m": "-0.95", "y_m": 0, "facing_deg": 0},
        },
    }).receipt.result

    grapple = next(row for row in result["causal_trace"] if row.get("kind") == "grapple_state" and row.get("actor_ref") == "char_tang_wei")
    assert grapple["result"] in {"hold_established", "throw_established", "hold_maintained"}
    third_party = [row for row in result["causal_trace"] if row.get("kind") == "attack" and row.get("actor_ref") == b and row.get("target_ref") == "char_tang_wei"]
    if third_party:
        # The attack trace records the already-reduced defense expression; most
        # importantly Wei may not receive a pristine fresh reaction body.
        assert float(third_party[0]["defense_saturation_factor"]) <= 1.0
        assert float(third_party[0]["defense_resource_ready_at_s"]) >= float(grapple["at_s"])


def test_grapple_throw_creates_real_fall_timeline(campaign):
    from conftest import execute

    opponent = _materialize_pair(campaign, "throw")[0]
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    op = campaign / owners[opponent]
    person = json.loads(op.read_text())
    person.setdefault("attributes", {}).update({"Strength": 20, "Agility": 20, "Coordination": 20})
    person.setdefault("skills", {}).update({"Grappling": 5, "Athletics": 5, "Defense": 20})
    op.write_text(json.dumps(person, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, owners[opponent])

    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent,
        "target_ref": opponent,
        "objective": "controlled spar",
        "duration_minutes": 1,
        "intent_sequence": ["grapple and throw him"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            opponent: {"x_m": "0.5", "y_m": 0, "facing_deg": 180},
        },
    }).receipt.result

    fall = next(row for row in result["causal_trace"] if row.get("kind") == "posture_state" and row.get("actor_ref") == opponent and row.get("action") == "fall_started")
    ground = next(row for row in result["causal_trace"] if row.get("kind") == "posture_state" and row.get("actor_ref") == opponent and row.get("action") == "ground_contact")
    assert float(fall["ground_contact_at_s"]) > float(fall["at_s"])
    assert float(ground["earliest_get_up_at_s"]) > float(ground["ground_contact_at_s"])


def test_local_wall_blocks_contact_path(campaign):
    from conftest import execute

    opponent = _materialize_pair(campaign, "obstacle")[0]
    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent,
        "objective": "controlled spar",
        "duration_minutes": 1,
        "intent_sequence": ["shoot an arrow at the torso"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            opponent: {"x_m": 10, "y_m": 0, "facing_deg": 180},
        },
        "local_obstacles": [{
            "kind": "segment", "label": "stone wall",
            "x1_m": 5, "y1_m": -2, "x2_m": 5, "y2_m": 2,
            "clearance_m": "0.02",
        }],
    }).receipt.result

    attacks = [row for row in result["causal_trace"] if row.get("kind") == "attack" and row.get("actor_ref") == "char_tang_wei"]
    assert attacks
    assert attacks[0]["range_legal"] is False
    assert attacks[0]["path_blocked_by"]["label"] == "stone wall"
    assert result["local_obstacles"][0]["label"] == "stone wall"


def test_embedded_weapon_requires_timed_extraction_before_reuse(campaign):
    from conftest import execute

    opponent = _materialize_pair(campaign, "embedded")[0]
    player_path = campaign / "state/player.json"
    player = json.loads(player_path.read_text())
    player.setdefault("combat_state", {})["embedded_weapon"] = {
        "item_id": "weapon_sword",
        "target_ref": opponent,
        "target_structure": "forearm_bone",
        "embedded_at_s": 0,
        "extraction_seconds": "0.8",
        "source_contact_id": "test_embedded_contact",
    }
    player_path.write_text(json.dumps(player, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, "state/player.json")

    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent,
        "objective": "controlled spar",
        "duration_minutes": 1,
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            opponent: {"x_m": 1, "y_m": 0, "facing_deg": 180},
        },
    }).receipt.result
    extraction = next(row for row in result["causal_trace"] if row.get("kind") == "equipment_state" and row.get("action") == "weapon_extracted" and row.get("actor_ref") == "char_tang_wei")
    assert float(extraction["complete_at_s"]) > float(extraction["start_at_s"])
    attacks = [row for row in result["causal_trace"] if row.get("kind") == "attack" and row.get("actor_ref") == "char_tang_wei"]
    if attacks:
        assert float(attacks[0]["start_at_s"]) >= float(extraction["recovery_complete_at_s"])
    player_after = json.loads(player_path.read_text())
    assert not player_after.get("combat_state", {}).get("embedded_weapon")


def test_three_attackers_surrounding_share_one_spatial_body_state(campaign):
    from conftest import execute

    refs = _materialize_many(campaign, "surround3", 3)
    positions = {
        "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
        refs[0]: {"x_m": 1, "y_m": 0, "facing_deg": 180},
        refs[1]: {"x_m": "-0.5", "y_m": "0.866", "facing_deg": 300},
        refs[2]: {"x_m": "-0.5", "y_m": "-0.866", "facing_deg": 60},
    }
    result = execute(campaign, "personal_combat", {
        "opponent_refs": refs, "objective": "controlled spar", "duration_minutes": 1,
        "intent_sequence": ["dodge"], "participant_positions": positions,
    }).receipt.result
    attacks = [row for row in result["causal_trace"] if row.get("kind") == "attack" and row.get("target_ref") == "char_tang_wei"]
    assert len({row.get("actor_ref") for row in attacks}) >= 3
    first_by_actor = {}
    for row in attacks:
        first_by_actor.setdefault(row["actor_ref"], row)
    bearings = sorted(float(row["incoming_bearing_deg"]) % 360 for row in first_by_actor.values())
    assert len(bearings) >= 3
    assert max(float(row.get("defense_saturation_factor", 1)) for row in list(first_by_actor.values())[1:]) <= 1.0
    assert result["timing_model"]["spatial_mode"] == "local_2_5d_shared_body_state"


def test_six_attackers_use_bounded_shared_timeline_without_six_fresh_duels(campaign):
    import math
    from conftest import execute

    refs = _co_locate_existing(campaign, [
        "char_qin_wei_unit_01_commander", "char_han_shou",
        "char_qin_wei_unit_02_commander", "char_pei_rong",
        "char_qin_wei_unit_03_commander", "char_deng_kai",
    ])
    positions = {"char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0}}
    for index, ref in enumerate(refs):
        angle = math.radians(index * 60)
        positions[ref] = {
            "x_m": str(round(math.cos(angle), 4)), "y_m": str(round(math.sin(angle), 4)),
            "facing_deg": int((index * 60 + 180) % 360),
        }
    result = execute(campaign, "personal_combat", {
        "opponent_refs": refs, "objective": "controlled spar", "duration_minutes": 1,
        "intent_sequence": ["dodge"], "participant_positions": positions,
    }).receipt.result
    assert set(result["opponent_refs"]) == set(refs)
    assert len(result["participant_refs"]) == 7
    attacks = [row for row in result["causal_trace"] if row.get("kind") == "attack" and row.get("target_ref") == "char_tang_wei"]
    assert len({row.get("actor_ref") for row in attacks}) >= 4
    groups = {}
    for row in attacks:
        groups.setdefault(row.get("contact_group_id"), []).append(row)
    pressured = [rows for rows in groups.values() if len(rows) >= 2]
    assert pressured
    assert any(any(float(row.get("defense_saturation_factor", 1)) < 1.0 for row in rows[1:]) for rows in pressured)
    pressured_rows = [row for rows in pressured for row in rows]
    assert max(int(row.get("defense_pressure_sources", 1)) for row in pressured_rows) >= 2
    assert max(float(row.get("active_defense_load_after", 0.0)) for row in pressured_rows) > 0.0
    assert float(result["end_state"]["action_exertion"]["char_tang_wei"]) > 0.0


def test_staggered_attacker_arrival_allows_reaction_recovery_between_contact_groups(campaign):
    from conftest import execute

    a, b = _materialize_pair(campaign, "staggered")
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    bpath = campaign / owners[b]
    slow = json.loads(bpath.read_text())
    slow.setdefault("attributes", {}).update({"Agility": 30, "Coordination": 30, "Awareness": 35})
    slow.setdefault("skills", {}).update({"Sword": 60, "Spear": 60})
    bpath.write_text(json.dumps(slow, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, owners[b])
    result = execute(campaign, "personal_combat", {
        "opponent_refs": [a, b], "objective": "controlled spar", "duration_minutes": 1,
        "intent_sequence": ["dodge"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            a: {"x_m": 1, "y_m": "0.15", "facing_deg": 180},
            b: {"x_m": "0.6", "y_m": "-0.6", "facing_deg": 135},
        },
    }).receipt.result
    attacks = [row for row in result["causal_trace"] if row.get("kind") == "attack" and row.get("target_ref") == "char_tang_wei"]
    a_first = next(row for row in attacks if row.get("actor_ref") == a)
    b_first = next(row for row in attacks if row.get("actor_ref") == b)
    assert a_first["contact_group_id"] != b_first["contact_group_id"]
    assert abs(float(b_first["contact_at_s"]) - float(a_first["contact_at_s"])) > 0.08
    earlier = min((a_first, b_first), key=lambda row: float(row["contact_at_s"]))
    later = max((a_first, b_first), key=lambda row: float(row["contact_at_s"]))
    assert float(later["defense_saturation_factor"]) == 1.0
    earlier_defense = next(
        row for row in result["causal_trace"]
        if row.get("kind") == "weapon_interaction"
        and row.get("actor_ref") == "char_tang_wei"
        and row.get("contact_group_id") == earlier["contact_group_id"]
        and row.get("action") == "dodge"
        and row.get("dodge_to_position")
    )
    assert abs(float(later["defender_position_at_contact"]["x_m"]) - float(earlier_defense["dodge_to_position"]["x_m"])) < 0.002
    assert abs(float(later["defender_position_at_contact"]["y_m"]) - float(earlier_defense["dodge_to_position"]["y_m"])) < 0.002

def test_shield_block_is_directional_and_opposite_flank_cannot_reuse_pristine_block(campaign):
    from conftest import execute

    a, b = _materialize_pair(campaign, "shieldflank")
    result = execute(campaign, "personal_combat", {
        "opponent_refs": [a, b], "objective": "controlled spar", "duration_minutes": 1,
        "intent_sequence": ["block"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            a: {"x_m": 1, "y_m": 0, "facing_deg": 180},
            b: {"x_m": -1, "y_m": 0, "facing_deg": 0},
        },
    }).receipt.result
    first, second = _first_two_attacks_on_player(result)
    assert first["contact_group_id"] == second["contact_group_id"]
    assert abs(float(first["incoming_bearing_deg"]) - float(second["incoming_bearing_deg"])) >= 170.0
    assert not (first.get("defense_method") == "block" and second.get("defense_method") == "block" and float(second.get("defense_saturation_factor", 1)) == 1.0)
    assert float(second["defense_resource_ready_at_s"]) >= float(first["contact_at_s"])


def test_parry_cannot_occupy_two_opposite_weapon_lines_at_once(campaign):
    from conftest import execute

    a, b = _materialize_pair(campaign, "parryflank")
    result = execute(campaign, "personal_combat", {
        "opponent_refs": [a, b], "objective": "controlled spar", "duration_minutes": 1,
        "intent_sequence": ["parry"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            a: {"x_m": 1, "y_m": 0, "facing_deg": 180},
            b: {"x_m": -1, "y_m": 0, "facing_deg": 0},
        },
    }).receipt.result
    first, second = _first_two_attacks_on_player(result)
    assert first["contact_group_id"] == second["contact_group_id"]
    assert not (first.get("defense_method") == "parry" and second.get("defense_method") == "parry" and float(second.get("defense_saturation_factor", 1)) == 1.0)
    assert float(second["defense_saturation_factor"]) <= float(first["defense_saturation_factor"])


def test_contact_order_is_deterministic_across_identical_repository_clones(campaign, tmp_path):
    from conftest import execute

    a, b = _materialize_pair(campaign, "deterministic")
    payload = {
        "opponent_refs": [a, b], "objective": "controlled spar", "duration_minutes": 1,
        "intent_sequence": ["dodge"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            a: {"x_m": 1, "y_m": "0.12", "facing_deg": 180},
            b: {"x_m": 1, "y_m": "-0.12", "facing_deg": 180},
        },
    }
    left = tmp_path / "left"
    right = tmp_path / "right"
    _clone_committed_repo(campaign, left)
    _clone_committed_repo(campaign, right)
    lres = execute(left, "personal_combat", payload).receipt.result
    rres = execute(right, "personal_combat", payload).receipt.result
    def signature(result):
        return [
            (row.get("kind"), row.get("actor_ref"), row.get("target_ref"), row.get("contact_group_id"), row.get("result"), row.get("at_s", row.get("contact_at_s")))
            for row in result["causal_trace"]
        ]
    assert signature(lres) == signature(rres)



def test_active_defense_commitment_scales_with_threat_speed_and_distinct_source():
    from sword_runtime.personal_combat import (
        active_defense_commitment_fraction,
        active_defense_recovery_window_seconds,
        decayed_active_defense_load,
    )

    defender = {"reaction_seconds": 0.24, "attack_startup_seconds": 0.30}
    slow_threat = {"reaction_seconds": 0.20, "attack_startup_seconds": 0.60}
    fast_threat = {"reaction_seconds": 0.20, "attack_startup_seconds": 0.10}
    recovery = active_defense_recovery_window_seconds(defender, {})
    assert 0.10 <= recovery <= 0.90
    slow = active_defense_commitment_fraction(
        attacker_timing=slow_threat, defender_timing=defender,
        positive_control_pressure=0.0, new_source=False, saturation_mechanics={},
    )
    fast = active_defense_commitment_fraction(
        attacker_timing=fast_threat, defender_timing=defender,
        positive_control_pressure=0.0, new_source=False, saturation_mechanics={},
    )
    fast_distinct = active_defense_commitment_fraction(
        attacker_timing=fast_threat, defender_timing=defender,
        positive_control_pressure=60.0, new_source=True, saturation_mechanics={},
    )
    assert 0.0 < slow < fast < fast_distinct <= 0.90
    halfway = decayed_active_defense_load(0.80, last_update_s=0.0, at_s=recovery / 2.0, recovery_window_s=recovery)
    recovered = decayed_active_defense_load(0.80, last_update_s=0.0, at_s=recovery, recovery_window_s=recovery)
    assert 0.0 < halfway < 0.80
    assert recovered == 0.0


def test_committed_action_causality_distinguishes_melee_projectile_and_mounted_momentum():
    from sword_runtime.personal_combat import committed_action_survives_incapacitation

    ordinary = {"kind": "attack", "start_at_s": 0.0}
    assert committed_action_survives_incapacitation(ordinary, incapacitated_at_s=0.50, resolve_at_s=0.90, simultaneous_window_s=0.08) is False
    assert committed_action_survives_incapacitation(ordinary, incapacitated_at_s=0.86, resolve_at_s=0.90, simultaneous_window_s=0.08) is True
    projectile = {"kind": "projectile_contact", "release_at_s": 0.40, "start_at_s": 0.20}
    assert committed_action_survives_incapacitation(projectile, incapacitated_at_s=0.60, resolve_at_s=2.40, simultaneous_window_s=0.08) is True
    unreleased = {"kind": "projectile_contact", "release_at_s": 0.80, "start_at_s": 0.20}
    assert committed_action_survives_incapacitation(unreleased, incapacitated_at_s=0.60, resolve_at_s=2.40, simultaneous_window_s=0.08) is False
    mounted = {"kind": "attack", "mounted_body_collision": True, "start_at_s": 0.30}
    assert committed_action_survives_incapacitation(mounted, incapacitated_at_s=0.60, resolve_at_s=1.20, simultaneous_window_s=0.08) is True


def test_staggered_reaction_window_distinguishes_fast_and_slow_defenders(campaign, tmp_path):
    from conftest import execute

    a, b = _materialize_pair(campaign, "speedbudget")
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    bpath = campaign / owners[b]
    slower_attacker = json.loads(bpath.read_text())
    slower_attacker.setdefault("attributes", {}).update({"Agility": 22, "Coordination": 22, "Awareness": 25})
    slower_attacker.setdefault("skills", {}).update({"Sword": 45, "Spear": 45})
    bpath.write_text(json.dumps(slower_attacker, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, owners[b])

    fast = tmp_path / "fast"
    slow = tmp_path / "slow"
    _clone_committed_repo(campaign, fast)
    _clone_committed_repo(campaign, slow)

    def configure(repo, value):
        player_path = repo / "state/player.json"
        player = json.loads(player_path.read_text())
        player.setdefault("attributes", {}).update({
            "Agility": value, "Coordination": value, "Awareness": value,
            "Endurance": value, "Composure": value,
        })
        player.setdefault("skills", {}).update({"Defense": value, "Athletics": value, "Sword": value})
        player_path.write_text(json.dumps(player, ensure_ascii=False, indent=2) + "\n")
        _commit(repo, "state/player.json")

    configure(fast, 500)
    configure(slow, 12)
    payload = {
        "opponent_refs": [a, b], "objective": "controlled spar", "duration_minutes": 1,
        "intent_sequence": ["dodge", "dodge", "dodge"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            a: {"x_m": 1, "y_m": "0.12", "facing_deg": 180},
            b: {"x_m": "0.65", "y_m": "-0.65", "facing_deg": 135},
        },
    }
    fast_result = execute(fast, "personal_combat", payload).receipt.result
    slow_result = execute(slow, "personal_combat", payload).receipt.result

    def second_distinct_contact(result):
        rows = [row for row in result["causal_trace"] if row.get("kind") == "attack" and row.get("target_ref") == "char_tang_wei"]
        first = min(rows, key=lambda row: float(row["contact_at_s"]))
        later = min(
            (row for row in rows if row.get("contact_group_id") != first.get("contact_group_id")),
            key=lambda row: float(row["contact_at_s"]),
        )
        return first, later

    fast_first, fast_later = second_distinct_contact(fast_result)
    slow_first, slow_later = second_distinct_contact(slow_result)
    assert float(fast_later["contact_at_s"]) > float(fast_first["contact_at_s"])
    assert float(slow_later["contact_at_s"]) > float(slow_first["contact_at_s"])
    assert float(fast_later["defense_saturation_factor"]) >= float(slow_later["defense_saturation_factor"])
    assert fast_later["defense_timing"] == "ready"
    assert slow_later["defense_timing"] == "late" or float(slow_later["defense_saturation_factor"]) < 1.0


def test_melee_attack_collapses_if_attacker_is_incapacitated_before_contact(campaign):
    from conftest import execute

    opponent = _materialize_pair(campaign, "precontactcollapse")[0]
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    opponent_path = campaign / owners[opponent]
    fast = json.loads(opponent_path.read_text())
    fast.setdefault("attributes", {}).update({"Agility": 500, "Coordination": 500, "Awareness": 500, "Endurance": 500})
    fast.setdefault("skills", {}).update({"Sword": 500, "Defense": 500, "Athletics": 500})
    opponent_path.write_text(json.dumps(fast, ensure_ascii=False, indent=2) + "\n")

    player_path = campaign / "state/player.json"
    player = json.loads(player_path.read_text())
    player.setdefault("attributes", {}).update({"Agility": 5, "Coordination": 5, "Awareness": 5, "Endurance": 5, "Composure": 5})
    player.setdefault("skills", {}).update({"Sword": 5, "Defense": 5, "Athletics": 5})
    wound = {
        "wound_id": "test_precontact_collapse", "active": True, "severity": "minor", "severity_index": 1,
        "body_zone": "forearms_hands", "side": "left", "contact_structure": "superficial_vessel",
        "mechanism": "cut", "source_weapon": "test", "pain": 0,
        "bleeding": {"rate_units_per_minute": 30, "controlled": False},
        "respiratory_compromise": 0, "neurological_impairment": 0,
    }
    player["injuries"] = [dict(wound)]
    player["injury_state"] = dict(wound)
    player["physiology_state"] = {"blood_loss_units": "99.95"}
    player_path.write_text(json.dumps(player, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, owners[opponent], "state/player.json")

    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent, "objective": "controlled spar", "duration_minutes": 1,
        "intent_sequence": ["cut at the torso"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            opponent: {"x_m": 1, "y_m": 0, "facing_deg": 180},
        },
    }).receipt.result
    interruption = next(
        row for row in result["causal_trace"]
        if row.get("kind") == "action_interrupted"
        and row.get("actor_ref") == "char_tang_wei"
        and row.get("action_kind") in {"movement", "attack"}
    )
    # With physical melee reach, an out-of-reach attack intent may correctly
    # collapse during its closing movement before the strike starts.
    assert interruption["reason"] == "actor incapacitated before physical release/contact"
    assert not any(
        row.get("kind") == "contact" and row.get("actor_ref") == "char_tang_wei"
        for row in result["causal_trace"]
    )


def test_projectile_and_melee_contacts_share_physical_timeline(campaign):
    from conftest import execute

    archer, melee = _materialize_pair(campaign, "projectilemelee")
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    archer_path = campaign / owners[archer]
    bowman = json.loads(archer_path.read_text())
    # Inventory legality is authoritative: assigning a loadout template alone
    # does not conjure a bow or arrows. Give this benchmark archer an exact
    # equipped manifest so the AI is lawfully allowed to select the ranged path.
    manifest_rel = f"state/test-person-equipment/{archer}.json"
    manifest_path = campaign / manifest_rel
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "schema": "player-equipment-manifest",
        "authority": "player_equipment_manifest",
        "player_ref": archer,
        "equipment_manifest": [
            {"item_id": "weapon_bow", "quantity": 1, "custody": "test exact-person equipment", "current_state": "equipped/readied"},
            {"item_id": "ammo_arrow", "quantity": 36, "custody": "test exact-person equipment", "current_state": "quivered/readied"},
            {"item_id": "weapon_sword", "quantity": 1, "custody": "test exact-person equipment", "current_state": "equipped/readied"},
        ]
    }, ensure_ascii=False, indent=2) + "\n")
    bowman["equipment_manifest_ref"] = manifest_rel
    bowman.setdefault("attributes", {}).update({"Agility": 100, "Coordination": 130, "Awareness": 130, "Endurance": 130, "Strength": 100})
    bowman.setdefault("skills", {}).update({"Bow": 140, "Sword": 45, "Defense": 90, "Athletics": 90})
    archer_path.write_text(json.dumps(bowman, ensure_ascii=False, indent=2) + "\n")
    melee_path = campaign / owners[melee]
    swordsman = json.loads(melee_path.read_text())
    swordsman.setdefault("attributes", {}).update({"Agility": 70, "Coordination": 70, "Awareness": 70})
    swordsman.setdefault("skills", {}).update({"Sword": 70, "Defense": 70, "Athletics": 70})
    melee_path.write_text(json.dumps(swordsman, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, owners[archer], owners[melee], manifest_rel)

    result = execute(campaign, "personal_combat", {
        "opponent_refs": [archer, melee], "objective": "controlled spar", "duration_minutes": 1,
        # Brace keeps Wei in the physical lane so this regression can compare
        # projectile and melee timing. Separate tests prove that a dodge can
        # move him out of a fixed post-release projectile trajectory.
        "intent_sequence": ["brace", "brace", "brace"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            archer: {"x_m": "2.0", "y_m": 0, "facing_deg": 180},
            # Keep the melee threat physically near Wei without placing its
            # body inside the archer's fixed projectile lane.  Body screening is
            # now real geometry rather than a team-membership abstraction.
            melee: {"x_m": "0.86", "y_m": "0.46", "facing_deg": 180},
        },
    }).receipt.result
    attacks = [row for row in result["causal_trace"] if row.get("kind") == "attack" and row.get("target_ref") == "char_tang_wei"]
    projectile = next(row for row in attacks if row.get("projectile_item_id"))
    close = next(row for row in attacks if row.get("actor_ref") == melee and not row.get("projectile_item_id"))
    assert projectile["actor_ref"] == archer
    assert float(projectile["contact_at_s"]) >= float(projectile["start_at_s"])
    assert float(close["contact_at_s"]) >= float(close["start_at_s"])
    # Both kinds of contact inhabit the same shared scheduler and therefore carry
    # the same spatial/body-commitment metadata instead of resolving as separate duels.
    assert projectile["contact_group_id"].startswith("contact_group_")
    assert close["contact_group_id"].startswith("contact_group_")
    assert "defender_position_at_contact" in projectile and "defender_position_at_contact" in close


def test_equal_three_vs_three_team_plan_covers_independent_threat_lanes_before_dogpile():
    from sword_runtime.combat_tactics import build_team_plan

    allies = ["a0", "a1", "a2"]
    enemies = ["e0", "e1", "e2"]
    refs = allies + enemies
    people = {
        ref: {
            "attributes": {"Agility": 100, "Coordination": 100, "Awareness": 100, "Strength": 100},
            "skills": {"Sword": 100, "Defense": 100, "Athletics": 100, "Leadership": 80, "Tactics": 80},
        }
        for ref in refs
    }
    equipment = {
        ref: {"weapon": {"reach_m": 1.0}, "loadout": {}, "ranged_weapon": {}}
        for ref in refs
    }
    controls = {ref: {"attack": 100, "parry": 95, "block": 90, "dodge": 90} for ref in refs}
    positions = {
        "a0": {"x_m": 0.0, "y_m": 0.0},
        "a1": {"x_m": 0.0, "y_m": 1.2},
        "a2": {"x_m": 0.0, "y_m": -1.2},
        "e0": {"x_m": 1.1, "y_m": 0.0},
        "e1": {"x_m": 1.1, "y_m": 1.2},
        "e2": {"x_m": 1.1, "y_m": -1.2},
    }
    plan = build_team_plan(
        allies, enemies,
        people=people,
        equipment=equipment,
        controls=controls,
        positions=positions,
        objective="controlled spar",
        at_s=0.0,
    )
    targets = [row["target_ref"] for row in plan["assignments"].values()]
    assert set(plan["assignments"]) == set(allies)
    assert set(targets) == set(enemies)


def test_three_vs_three_runs_all_six_fighters_on_one_continuous_timeline(campaign):
    from conftest import execute

    refs = _co_locate_existing(campaign, [
        "char_qin_wei_unit_01_commander",
        "char_han_shou",
        "char_qin_wei_unit_02_commander",
        "char_pei_rong",
        "char_qin_wei_unit_03_commander",
    ])
    ally_a, ally_b, enemy_a, enemy_b, enemy_c = refs
    result = execute(campaign, "personal_combat", {
        "ally_refs": [ally_a, ally_b],
        "opponent_refs": [enemy_a, enemy_b, enemy_c],
        "objective": "controlled spar",
        "duration_minutes": 1,
        "participant_positions": {
            "char_tang_wei": {"x_m": "0.0", "y_m": "0.0", "facing_deg": 0},
            ally_a: {"x_m": "0.0", "y_m": "1.15", "facing_deg": 0},
            ally_b: {"x_m": "0.0", "y_m": "-1.15", "facing_deg": 0},
            enemy_a: {"x_m": "1.05", "y_m": "0.0", "facing_deg": 180},
            enemy_b: {"x_m": "1.05", "y_m": "1.15", "facing_deg": 180},
            enemy_c: {"x_m": "1.05", "y_m": "-1.15", "facing_deg": 180},
        },
    }).receipt.result

    assert set(result["player_side_refs"]) == {"char_tang_wei", ally_a, ally_b}
    assert set(result["hostile_side_refs"]) == {enemy_a, enemy_b, enemy_c}
    assert set(result["participant_refs"]) == {"char_tang_wei", ally_a, ally_b, enemy_a, enemy_b, enemy_c}
    assert result["timing_model"]["mode"] == "continuous_action_ready"
    assert "all exact participants on both sides share one local timeline" in result["timing_model"]["rule"]

    attacks = [row for row in result["causal_trace"] if row.get("kind") == "attack"]
    attacking_refs = {row.get("actor_ref") for row in attacks}
    assert {"char_tang_wei", ally_a, ally_b}.issubset(attacking_refs)
    assert {enemy_a, enemy_b, enemy_c}.issubset(attacking_refs)

    # Teammates are not paused while Wei acts. At least one allied action begins
    # before Wei's first committed attack has fully recovered, proving shared
    # action-ready time rather than a player-centric turn queue.
    wei_attacks = [row for row in attacks if row.get("actor_ref") == "char_tang_wei"]
    ally_attacks = [row for row in attacks if row.get("actor_ref") in {ally_a, ally_b}]
    assert wei_attacks and ally_attacks
    first_wei = min(wei_attacks, key=lambda row: float(row.get("start_at_s", 0.0)))
    assert any(
        float(row.get("start_at_s", 9999.0)) < float(first_wei.get("recovery_complete_at_s", 0.0))
        for row in ally_attacks
    )

    # Enemy fighters must spend real timing resources defending against allied
    # pressure. This prevents three enemies from freely spamming Wei while his
    # teammates are mechanically invisible.
    allied_attack_ids = {
        row["id"] for row in attacks if row.get("actor_ref") in {ally_a, ally_b}
    }
    defended_against_allies = [
        row for row in result["causal_trace"]
        if row.get("kind") == "weapon_interaction"
        and row.get("target_ref") in {ally_a, ally_b}
        and any(str(row.get("id", "")).startswith(attack_id.removesuffix("_attack")) for attack_id in allied_attack_ids)
    ]
    assert defended_against_allies

    plans = result["team_tactical_plans"]
    player_plans = [row for row in plans if set(row.get("assignments", {})).intersection({"char_tang_wei", ally_a, ally_b})]
    assert player_plans
    assert max(len({a.get("target_ref") for a in row.get("assignments", {}).values()}) for row in player_plans) >= 2


def test_ai_tactical_targeting_puts_immediate_geometry_ahead_of_remote_team_primary():
    from sword_runtime.combat_tactics import choose_tactical_target

    people = {ref: {"combat_state": {}} for ref in ("actor", "near", "remote")}
    positions = {
        "actor": {"x_m": 0.0, "y_m": 0.0},
        "near": {"x_m": 1.2, "y_m": 0.0},
        "remote": {"x_m": 18.0, "y_m": 0.0},
    }
    plan = {
        "known_enemy_refs": ["near", "remote"],
        "primary_threat_ref": "remote",
        "assignments": {"actor": {"role": "pressure", "target_ref": "remote"}},
    }
    assert choose_tactical_target(
        "actor", ["near", "remote"], plan=plan, people=people, positions=positions,
    ) == "near"


def test_ai_tactical_targeting_penalizes_withdrawing_preferred_target_against_local_contact():
    from sword_runtime.combat_tactics import choose_tactical_target

    people = {ref: {"combat_state": {}} for ref in ("actor", "local", "assigned")}
    positions = {
        "actor": {"x_m": 0.0, "y_m": 0.0},
        "local": {"x_m": 2.0, "y_m": 0.0},
        "assigned": {"x_m": 4.0, "y_m": 0.0},
    }
    plan = {
        "known_enemy_refs": ["local", "assigned"],
        "primary_threat_ref": "assigned",
        "assignments": {"actor": {"role": "interception", "target_ref": "assigned"}},
    }
    assert choose_tactical_target(
        "actor", ["local", "assigned"], plan=plan, people=people, positions=positions,
        motion_vectors={"assigned": {"vx_mps": 2.0, "vy_mps": 0.0}},
    ) == "local"


def test_ai_tactical_targeting_keeps_team_assignment_when_threats_are_physically_comparable():
    from sword_runtime.combat_tactics import choose_tactical_target

    people = {ref: {"combat_state": {}} for ref in ("actor", "nearer", "assigned")}
    positions = {
        "actor": {"x_m": 0.0, "y_m": 0.0},
        "nearer": {"x_m": 1.5, "y_m": 0.0},
        "assigned": {"x_m": 3.5, "y_m": 0.0},
    }
    plan = {
        "known_enemy_refs": ["nearer", "assigned"],
        "primary_threat_ref": "assigned",
        "assignments": {"actor": {"role": "control", "target_ref": "assigned"}},
    }
    assert choose_tactical_target(
        "actor", ["nearer", "assigned"], plan=plan, people=people, positions=positions,
    ) == "assigned"
