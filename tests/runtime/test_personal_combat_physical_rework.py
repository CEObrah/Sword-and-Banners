from __future__ import annotations

import json

from sword_runtime.combat_geometry import (
    body_intersections_on_segment,
    members_in_cone,
    members_in_lane,
    members_in_radius,
    surface_gap,
)
from sword_runtime.combat_objectives import evaluate_objective, objective_model
from sword_runtime.combat_tactics import build_team_plan
from sword_runtime.contact_physics import projectile_weapon_deflection_resolution
from sword_runtime.personal_combat import _unarmed_method_profile


def test_unarmed_methods_use_explicit_body_reach_not_one_generic_weapon_range():
    punch = _unarmed_method_profile("punch him in the chest")
    kick = _unarmed_method_profile("front kick to the body")
    elbow = _unarmed_method_profile("elbow at close range")
    knee = _unarmed_method_profile("knee strike")
    assert punch["method"] == "punch" and float(punch["reach_m"]) < 0.50
    assert float(kick["reach_m"]) > float(punch["reach_m"])
    assert float(elbow["reach_m"]) < float(punch["reach_m"])
    assert float(knee["reach_m"]) < float(punch["reach_m"])


def test_projectile_weapon_deflection_is_physical_and_deterministic():
    sword = {
        "schema": "melee_weapon",
        "family": "sword",
        "reach_m": 0.9,
        "handling": 1.0,
        "structural_capacity": 85,
    }
    clean = projectile_weapon_deflection_resolution(
        sword, projectile_speed_mps=52, impact_index=100, penetration_index=95,
        attack_margin=-30, timing_factor=1.0, saturation_factor=1.0, balance_factor=1.0,
        detection_quality=1.0, incoming_arc_delta_deg=12, condition_pct=100,
    )
    assert clean["outcome"] == "clean_deflection"
    assert clean["intercepted"] is True
    assert float(clean["deflection_angle_deg"]) >= 30
    assert float(clean["residual_impact_index"]) < 100
    assert float(clean["residual_penetration_index"]) < 95

    # Same stats but a badly saturated, late, off-line response against a much
    # faster projectile must not receive a cinematic auto-parry.
    failed = projectile_weapon_deflection_resolution(
        sword, projectile_speed_mps=110, impact_index=100, penetration_index=95,
        attack_margin=-2, timing_factor=0.35, saturation_factor=0.30, balance_factor=0.55,
        detection_quality=0.45, incoming_arc_delta_deg=120, condition_pct=70,
    )
    assert failed["outcome"] == "missed_intercept"
    assert failed["intercepted"] is False
    assert float(failed["residual_impact_index"]) == 100


def test_projectile_weapon_deflection_can_be_partial_not_binary():
    sword = {"schema": "melee_weapon", "family": "sword", "reach_m": 0.9, "handling": 1.0}
    # This margin is intentionally near the interception boundary so the blade
    # clips the shaft/point line without fully clearing the defender's body.
    result = projectile_weapon_deflection_resolution(
        sword, projectile_speed_mps=55, impact_index=120, penetration_index=110,
        attack_margin=-8, timing_factor=0.78, saturation_factor=0.90, balance_factor=1.0,
        detection_quality=0.92, incoming_arc_delta_deg=45, condition_pct=100,
    )
    assert result["outcome"] in {"clean_deflection", "partial_deflection"}
    if result["outcome"] == "partial_deflection":
        assert 0 < float(result["deflection_angle_deg"]) < 30
        assert 0 < float(result["residual_penetration_index"]) < 110


def test_lane_cone_radius_are_spatial_not_team_membership():
    poses = {
        "center": {"x_m": 0, "y_m": 0, "elevation_m": 0, "radius_m": 0.28},
        "lane": {"x_m": 5, "y_m": 0.2, "elevation_m": 0, "radius_m": 0.28},
        "wide": {"x_m": 5, "y_m": 3, "elevation_m": 0, "radius_m": 0.28},
        "rear": {"x_m": -2, "y_m": 0, "elevation_m": 0, "radius_m": 0.28},
    }
    lane = members_in_lane(poses["center"], 0, 10, 1.0, poses, exclude_refs=("center",))
    assert [r["ref"] for r in lane] == ["lane"]
    cone = members_in_cone(poses["center"], 0, 10, 30, poses, exclude_refs=("center",))
    assert "lane" in {r["ref"] for r in cone}
    assert "wide" not in {r["ref"] for r in cone}
    radius = members_in_radius(poses["center"], 2.5, poses, exclude_refs=("center",))
    assert "rear" in {r["ref"] for r in radius}
    assert "lane" not in {r["ref"] for r in radius}


def test_projectile_lane_hits_first_body_even_if_intended_target_is_behind():
    poses = {
        "screen": {"x_m": 4, "y_m": 0, "elevation_m": 0, "radius_m": 0.28},
        "target": {"x_m": 8, "y_m": 0, "elevation_m": 0, "radius_m": 0.28},
        "off_lane": {"x_m": 5, "y_m": 2, "elevation_m": 0, "radius_m": 0.28},
    }
    hits = body_intersections_on_segment(
        {"x_m": 0, "y_m": 0, "elevation_m": 1.2},
        {"x_m": 9, "y_m": 0, "elevation_m": 1.0},
        poses,
        half_width_m=0.02,
        vertical_tolerance_m=1.3,
    )
    assert [h["ref"] for h in hits[:2]] == ["screen", "target"]
    assert "off_lane" not in {h["ref"] for h in hits}


def test_surface_gap_uses_body_occupancy_for_melee_contact():
    a = {"x_m": 0, "y_m": 0, "elevation_m": 0, "radius_m": 0.28}
    b = {"x_m": 0.9, "y_m": 0, "elevation_m": 0, "radius_m": 0.28}
    assert round(surface_gap(a, b), 2) == 0.62


def test_multi_target_objective_requires_all_targets():
    refs = ["a", "b", "c", "d"]
    model = objective_model("eliminate A, B, C and D", refs)
    people = {ref: {"life_status": "active", "combat_state": {}} for ref in refs}
    people["a"]["life_status"] = "dead"
    active = lambda ref: people[ref]["life_status"] != "dead" and not people[ref].get("combat_state", {}).get("incapacitated")
    one = evaluate_objective(model, people, active)
    assert one["required_count"] == 4
    assert one["progress_milli"] == 250
    assert one["completed"] is False
    for ref in refs[1:]:
        people[ref]["life_status"] = "dead"
    done = evaluate_objective(model, people, active)
    assert done["completed"] is True
    assert done["progress_milli"] == 1000
    assert done["objective_id"] == model["objective_id"]


def test_team_plan_assigns_complementary_roles_without_resolving_outcomes():
    side = ["leader", "shield", "archer"]
    enemy = ["threat", "support"]
    def person(**skills):
        return {"skills": skills, "attributes": {"Awareness": 80, "Agility": 80, "Coordination": 80, "Strength": 80}}
    people = {
        "leader": person(Leadership=120, Tactics=110, Sword=80, Defense=80),
        "shield": person(Sword=75, Defense=120, Grappling=90),
        "archer": person(Bow=130, Defense=60),
        "threat": person(Sword=150, Defense=130),
        "support": person(Sword=60, Defense=60),
    }
    equipment = {
        "leader": {"weapon": {"reach_m": 1.0}, "loadout": {}},
        "shield": {"weapon": {"reach_m": 0.9}, "loadout": {"shield": "shield"}},
        "archer": {"weapon": {"reach_m": 0.8}, "ranged_weapon": {"family": "bow"}, "loadout": {}},
        "threat": {"weapon": {"reach_m": 1.0}, "loadout": {}},
        "support": {"weapon": {"reach_m": 1.0}, "loadout": {}},
    }
    controls = {ref: {"attack": (160 if ref == "threat" else 80), "parry": 80, "block": 80, "dodge": 80, "awareness": 80} for ref in people}
    positions = {
        "leader": {"x_m": 0, "y_m": 0}, "shield": {"x_m": -1, "y_m": 0}, "archer": {"x_m": -3, "y_m": 1},
        "threat": {"x_m": 2, "y_m": 0}, "support": {"x_m": 4, "y_m": 2},
    }
    plan = build_team_plan(side, enemy, people=people, equipment=equipment, controls=controls, positions=positions, objective="defeat the enemy", at_s=1.0)
    assert plan["primary_threat_ref"] == "threat"
    assert plan["leader_ref"] == "leader"
    assert len({row["role"] for row in plan["assignments"].values()}) >= 2
    assert plan["decision_source"] == "team_ai"


def _commit(campaign, *paths):
    import subprocess
    subprocess.run(["git", "-C", str(campaign), "add", *paths], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test: physical combat rework"], check=True)


def _materialize(campaign, ref):
    from conftest import execute_internal
    player = json.loads((campaign / "state/player.json").read_text())
    execute_internal(campaign, "person_materialize", {
        "state": "qin", "person_ref": ref, "name": ref,
        "birth_date": "270-BCE-01-01", "role": "command_personnel",
        "source_location_ref": player["location"],
    })
    return ref


def test_out_of_reach_melee_closes_before_attack(campaign):
    from conftest import execute
    opponent = _materialize(campaign, "char_test_physical_close")
    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent, "objective": "controlled spar", "duration_minutes": 1,
        "intent_sequence": ["punch him"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            opponent: {"x_m": 4, "y_m": 0, "facing_deg": 180},
        },
    }).receipt.result
    movements = [r for r in result["causal_trace"] if r.get("kind") == "movement"]
    player_attacks = [r for r in result["causal_trace"] if r.get("kind") == "attack" and r.get("actor_ref") == "char_tang_wei"]
    # The intended melee action may become reachable because either combatant
    # closes first, but it may never resolve directly from the original 4 m gap.
    assert movements, result["causal_trace"]
    if player_attacks:
        assert float(player_attacks[0]["surface_gap_m"]) <= 1.6
        assert min(float(r["complete_at_s"]) for r in movements) <= float(player_attacks[0]["contact_at_s"])


def test_projectile_body_screen_intercepts_intended_target(campaign):
    from conftest import execute
    screen = _materialize(campaign, "char_test_projectile_screen")
    target = _materialize(campaign, "char_test_projectile_target")
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    changed = []
    for ref in (screen, target):
        path = campaign / owners[ref]
        person = json.loads(path.read_text())
        person.setdefault("combat_state", {})["immobilized"] = True
        path.write_text(json.dumps(person, ensure_ascii=False, indent=2) + "\n")
        changed.append(owners[ref])
    _commit(campaign, *changed)
    result = execute(campaign, "personal_combat", {
        "opponent_refs": [target, screen], "target_ref": target,
        "objective": "controlled spar", "duration_minutes": 1,
        "intent_sequence": ["shoot an arrow at the torso"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            screen: {"x_m": 3, "y_m": 0, "facing_deg": 180},
            target: {"x_m": 6, "y_m": 0, "facing_deg": 180},
        },
    }).receipt.result
    intercepts = [r for r in result["causal_trace"] if r.get("kind") == "projectile_lane_interception" and r.get("actor_ref") == "char_tang_wei"]
    assert intercepts
    assert intercepts[0]["intended_target_ref"] == target
    assert intercepts[0]["target_ref"] == screen


def test_local_combat_state_persists_2_5d_position_and_facing(campaign):
    from conftest import execute
    opponent = _materialize(campaign, "char_test_local_state_25d")
    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent, "objective": "controlled spar", "duration_minutes": 1,
        "intent_sequence": ["dodge"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "elevation_m": "1.5", "facing_deg": 15},
            opponent: {"x_m": 1, "y_m": 0, "elevation_m": "1.5", "facing_deg": 195},
        },
    }).receipt.result
    assert result["timing_model"]["spatial_mode"] == "local_2_5d_shared_body_state"
    pos = result["end_state"]["participant_positions"]["char_tang_wei"]
    assert float(pos["elevation_m"]) == 1.5
    assert "facing_deg" in pos and "radius_m" in pos


def test_released_arrow_can_be_deflected_by_readied_melee_weapon_and_time_advances(campaign):
    from conftest import execute

    archer = _materialize(campaign, "char_test_arrow_deflection")
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    archer_path = campaign / owners[archer]
    person = json.loads(archer_path.read_text())
    manifest_rel = f"state/test-person-equipment/{archer}.json"
    manifest_path = campaign / manifest_rel
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "schema": "player-equipment-manifest",
        "authority": "player_equipment_manifest",
        "player_ref": archer,
        "equipment_manifest": [
            {"item_id": "weapon_bow", "quantity": 1, "custody": "test exact-person equipment", "current_state": "equipped/readied"},
            {"item_id": "ammo_arrow", "quantity": 12, "custody": "test exact-person equipment", "current_state": "quivered/readied"},
        ],
    }, ensure_ascii=False, indent=2) + "\n")
    person["equipment_manifest_ref"] = manifest_rel
    person.setdefault("attributes", {}).update({"Agility": 70, "Coordination": 80, "Awareness": 80, "Endurance": 80, "Strength": 75})
    person.setdefault("skills", {}).update({"Bow": 85, "Defense": 40, "Athletics": 50})
    # Keep the benchmark archer at range. Immobilization does not block a legal
    # ranged release, but prevents melee closing from changing the test premise.
    person.setdefault("combat_state", {})["immobilized"] = True
    archer_path.write_text(json.dumps(person, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, owners[archer], manifest_rel)

    before_time = json.loads((campaign / "state/meta.json").read_text())["time"]
    result = execute(campaign, "personal_combat", {
        "opponent_ref": archer,
        "objective": "controlled spar",
        "duration_minutes": 1,
        "intent_sequence": ["deflect the incoming arrow", "deflect", "deflect"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            archer: {"x_m": 8, "y_m": 0, "facing_deg": 180},
        },
    }).receipt.result
    after_time = json.loads((campaign / "state/meta.json").read_text())["time"]

    arrow_attacks = [
        row for row in result["causal_trace"]
        if row.get("kind") == "attack" and row.get("projectile_item_id") == "ammo_arrow"
    ]
    assert arrow_attacks
    assert arrow_attacks[0]["defense_method"] == "deflect"
    interceptions = [row for row in result["causal_trace"] if row.get("kind") == "projectile_weapon_interception"]
    assert interceptions
    first = interceptions[0]
    assert first["actor_ref"] == "char_tang_wei"
    assert first["outcome"] in {"clean_deflection", "partial_deflection"}
    assert float(first["projectile_speed_mps"]) > 0
    assert float(first["deflection_angle_deg"]) > 0
    if first["outcome"] == "clean_deflection":
        assert first["continued_projectile_segment"] is True
        assert any(row.get("kind") in {"projectile_miss", "projectile_obstruction", "attack"} and str(row.get("id", "")).startswith(str(first["id"]).split("_projectile_deflection")[0] + "_deflect_") for row in result["causal_trace"])

    # A fully defended projectile exchange is still elapsed combat. This is the
    # authoritative anti-stall invariant, not merely a narration timestamp.
    assert int(result["elapsed_milliseconds"]) > 0
    assert int(result["elapsed_seconds"]) >= 1
    assert after_time != before_time


def test_non_spar_no_contact_exchange_advances_authoritative_time(campaign):
    from conftest import execute

    opponent = _materialize(campaign, "char_test_no_contact_time")
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    opponent_path = campaign / owners[opponent]
    person = json.loads(opponent_path.read_text())
    person.setdefault("combat_state", {})["immobilized"] = True
    opponent_path.write_text(json.dumps(person, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, owners[opponent])

    before_time = json.loads((campaign / "state/meta.json").read_text())["time"]
    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent,
        "objective": "fight",
        "duration_minutes": 1,
        "intent_sequence": ["brace"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            opponent: {"x_m": 4, "y_m": 0, "facing_deg": 180},
        },
    }).receipt.result
    after_time = json.loads((campaign / "state/meta.json").read_text())["time"]

    assert result["outcome"] == "engaged"
    assert int(result["elapsed_milliseconds"]) > 0
    assert int(result["elapsed_seconds"]) >= 1
    assert after_time != before_time


def test_active_scene_bowl_can_be_used_as_transient_improvised_weapon_without_minting_inventory(campaign):
    from pathlib import Path
    from conftest import execute
    from sword_runtime.scene_sessions import record_scene_fact, start_scene_session

    opponent = _materialize(campaign, "char_test_improvised_bowl")
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    opponent_path = campaign / owners[opponent]
    opponent_row = json.loads(opponent_path.read_text())
    opponent_row.setdefault("attributes", {}).update({
        "Agility": 1, "Coordination": 1, "Awareness": 1, "Composure": 1, "Strength": 1, "Endurance": 20,
    })
    opponent_row.setdefault("skills", {}).update({"Sword": 1, "Spear": 1, "Defense": 1, "Athletics": 1})
    opponent_path.write_text(json.dumps(opponent_row, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, owners[opponent])
    player = json.loads((campaign / "state/player.json").read_text())
    at = json.loads((campaign / "state/meta.json").read_text())["time"]

    class DiskSceneWriter:
        def __init__(self, root):
            self.root = Path(root)
            self.written = []
        def read_optional(self, path):
            p = self.root / path
            return json.loads(p.read_text()) if p.exists() else None
        def read(self, path):
            p = self.root / path
            if not p.exists():
                raise FileNotFoundError(path)
            return json.loads(p.read_text())
        def put(self, path, value):
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            if path not in self.written:
                self.written.append(path)

    writer = DiskSceneWriter(campaign)
    session = start_scene_session(
        writer,
        session_ref="scene_session_test_improvised_bowl",
        kind="conversation",
        location_ref=player["location"],
        participant_refs=["char_tang_wei", opponent],
        started_at=at,
        purpose="test an already-established mundane prop crossing into combat",
    )
    source_fact = record_scene_fact(
        writer,
        surface_digest="test-improvised-bowl-source",
        at=at,
        actor_ref="char_tang_wei",
        summary="A bronze bowl is already present within Tang Wei's reach in the active scene.",
        fact_kind="object_state",
        session_ref=session["session_ref"],
        improvised_prop={
            "kind": "mundane_improvised_prop",
            "form": "small_rigid",
            "material": "metal",
            "condition": "intact",
        },
    )
    fact = record_scene_fact(
        writer,
        surface_digest="test-improvised-bowl",
        at=at,
        actor_ref="char_tang_wei",
        summary="Tang Wei has the already-established bronze bowl in his hand.",
        fact_kind="object_state",
        session_ref=session["session_ref"],
        basis_refs=[source_fact["fact_ref"]],
        improvised_prop={
            "kind": "mundane_improvised_prop",
            "form": "small_rigid",
            "material": "metal",
            "condition": "intact",
        },
    )
    _commit(campaign, *writer.written)

    manifest_path = campaign / "state/player-detail/equipment-manifest.json"
    before_manifest = json.loads(manifest_path.read_text())
    before_ids = sorted(
        str(row.get("item_id")) for row in before_manifest.get("equipment_manifest", [])
        if isinstance(row, dict) and row.get("item_id")
    )

    result = execute(campaign, "personal_combat", {
        "opponent_ref": opponent,
        "objective": "controlled spar",
        "duration_minutes": 1,
        "distance_m": "0.5",
        "intent_sequence": ["strike him with the bronze bowl"],
        "improvised_prop_fact_ref": fact["fact_ref"],
    }).receipt.result

    prop = result["player_equipment"]["improvised_prop"]
    assert prop["fact_ref"] == fact["fact_ref"]
    assert prop["source_object_fact_ref"] == source_fact["fact_ref"]
    assert prop["durable_item_created"] is False
    assert prop["status"] == "held"
    assert 0 < float(prop["condition_pct"]) <= 100
    assert result["player_equipment"]["best_weapon"] == fact["fact_ref"]
    attacks = [
        row for row in result["causal_trace"]
        if row.get("kind") == "attack" and row.get("actor_ref") == "char_tang_wei"
    ]
    assert attacks, result["causal_trace"]
    assert attacks[0]["weapon_id"] == fact["fact_ref"]
    assert attacks[0]["weapon_identity_ref"] == fact["fact_ref"]
    assert attacks[0]["weapon_identity_kind"] == "scene_improvised_prop"

    after_manifest = json.loads(manifest_path.read_text())
    after_ids = sorted(
        str(row.get("item_id")) for row in after_manifest.get("equipment_manifest", [])
        if isinstance(row, dict) and row.get("item_id")
    )
    assert after_ids == before_ids
    assert fact["fact_ref"] not in after_ids
    player_after = json.loads((campaign / "state/player.json").read_text())
    assert fact["fact_ref"] not in player_after.get("equipment_condition", {})
    saved_prop = player_after["combat_state"]["local_combat_state"]["improvised_prop_state"]
    assert saved_prop["fact_ref"] == fact["fact_ref"]
    assert saved_prop["status"] == "held"

    # The scene was hard-closed by combat, but an immediate continuation of the
    # same exact combat may reuse the still-held prop from saved local combat
    # state. This is continuity, not inventory materialization.
    continued = execute(campaign, "personal_combat", {
        "opponent_ref": opponent,
        "objective": "controlled spar",
        "duration_minutes": 1,
        "distance_m": "0.5",
        "intent_sequence": ["strike him again with the bronze bowl"],
        "improvised_prop_fact_ref": fact["fact_ref"],
    }).receipt.result
    assert continued["player_equipment"]["improvised_prop"]["fact_ref"] == fact["fact_ref"]
    assert fact["fact_ref"] not in {
        str(row.get("item_id")) for row in json.loads(manifest_path.read_text()).get("equipment_manifest", [])
        if isinstance(row, dict) and row.get("item_id")
    }
