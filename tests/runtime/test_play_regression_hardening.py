from __future__ import annotations

import copy
import json
import subprocess

import pytest

def _commit(campaign, *paths: str) -> None:
    subprocess.run(["git", "-C", str(campaign), "add", *paths], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "play-regression hardening fixture"], check=True)


def test_actual_revision7_force_projection_uses_three_peer_primary_commands(campaign):
    from sword_runtime.api.stable_operations import StableCampaignOperations
    from sword_runtime.service_runtime import ProductionSwordRuntime

    meta = json.loads((campaign / "state/meta.json").read_text())
    if meta.get("revision") != 7:
        pytest.skip("historical revision-7 force-projection replay requires its exact supplied save")
    ops = StableCampaignOperations(ProductionSwordRuntime(campaign))
    rows = ops._controlled_force_echelon_views(meta["player_id"])
    assert len(rows) == 1
    army = rows[0]
    assert army["total_strength"] == 9500
    assert army["primary_command_count"] == 3
    assert army["tactical_leaf_formation_count"] == 19
    assert {
        row["display_name"]: row["strength"] for row in army["primary_commands"]
    } == {
        "High Guard": 4500,
        "Black Banner": 4000,
        "Red Lance": 1000,
    }
    assert {
        row["display_name"]: row["tactical_leaf_count"] for row in army["primary_commands"]
    } == {
        "High Guard": 9,
        "Black Banner": 8,
        "Red Lance": 2,
    }

    context = ops.play_context()
    assert context["controlled_force_echelons"][0]["primary_command_count"] == 3
    assert "peer operational commands" in context["controlled_force_echelons"][0]["comparison_rule"]


def test_actual_revision7_semantic_hold_executes_across_campaign_march_frontier(campaign):
    """Regression for Choice 2: keep holding for Mou Gou's answer.

    The exact supplied revision-7 save has several autonomous Qin march hosts due
    later that day. A semantic wait must commit through those boundaries instead
    of previewing successfully and failing during execution.
    """
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.service_runtime import ProductionSwordRuntime

    before = json.loads((campaign / "state/meta.json").read_text())
    if before.get("revision") != 7 or before.get("time") != "244-BCE-10-16T06:00:00+08:00":
        pytest.skip("historical revision-7 standing-hold replay requires its exact supplied save")
    command = CommandEnvelope(
        before["campaign_id"],
        "regression.actual-rev7-standing-hold",
        before["player_id"],
        "advance_time",
        before["revision"],
        before["time"],
        {
            "target_time": "244-BCE-10-16T21:00:00+08:00",
            "wait_policy": {"topic_terms": ["junction response from Mou Gou"]},
        },
        mode="gameplay",
    )
    runtime = ProductionSwordRuntime(campaign)
    preview = runtime.preview_for_execution(command)
    assert preview["status"] in {"ready", "ready_execute_only"}
    execution = runtime.execute(command)
    assert execution.status == "committed"
    assert execution.receipt.committed_revision == 8

    after = json.loads((campaign / "state/meta.json").read_text())
    assert after["revision"] == 8
    assert after["time"] == "244-BCE-10-16T21:00:00+08:00"
    mou_gou = json.loads((campaign / "state/formations/qin-mou-gou-central.json").read_text())
    assert mou_gou["location_ref"] == "loc_sanyou"
    result = execution.receipt.result
    assert result["semantic_wait_policy"]
    assert int(result["events_processed"]) >= 1


def test_personal_combat_result_carries_scale_appropriate_accounting(campaign):
    from conftest import execute, execute_internal

    opponent = "char_test_combat_accounting"
    execute_internal(campaign, "person_materialize", {
        "state": "qin",
        "person_ref": opponent,
        "name": "Combat Accounting Opponent",
        "birth_date": "270-BCE-01-01",
        "role": "command_personnel",
        "source_location_ref": "loc_qin_eastern_depot",
    })
    player = json.loads((campaign / "state/player.json").read_text())
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    opponent_path = campaign / owners[opponent]
    person = json.loads(opponent_path.read_text())
    person["current_location"] = player["location"]
    person["health_status"] = "fit"
    person["life_status"] = "active"
    opponent_path.write_text(json.dumps(person, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, owners[opponent])

    receipt = execute(campaign, "personal_combat", {
        "opponent_ref": opponent,
        "objective": "controlled spar",
        "duration_minutes": 1,
    }).receipt
    result = receipt.result
    info = result["combat_information"]
    assert info["scale"] == "exact_personal_combat"
    assert info["registered_hostiles"] == 1
    assert info["hostiles_active"] + info["hostiles_incapacitated"] + info["hostiles_dead"] == 1
    assert info["player_confirmed_defeats_this_resolution"] >= 0
    assert info["player_confirmed_defeats_encounter"] >= info["player_confirmed_defeats_this_resolution"]

    updated_player = json.loads((campaign / "state/player.json").read_text())
    tally = updated_player["combat_state"]["local_combat_state"]["personal_tally"]
    assert tally["confirmed_defeats"] == info["player_confirmed_defeats_encounter"]
    assert tally["confirmed_kills"] == info["player_confirmed_kills_encounter"]


def test_formation_battle_result_carries_scale_rule_without_personal_kill_fabrication(campaign):
    """Static integration guard for the battle-result accounting contract.

    Full battle fixtures are intentionally expensive. This test guards the
    returned contract while dedicated battle tests continue to cover casualty
    conservation and contact resolution.
    """
    source = (campaign / "runtime/sword_runtime/engine.py").read_text()
    assert '"scale": "formation_battle"' in source
    assert '"personal_takedown_rule"' in source
    assert "Formation casualties are never personal takedowns" in source


def test_skill_requires_peer_echelons_and_scale_appropriate_accounting(campaign):
    text = (campaign / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/combat-and-warfare.md").read_text()
    assert "When a committed personal-combat result exposes `player_visible_combat_information`" in text
    assert "raw `combat_information` as GM-private" in text
    assert "controlled_force_echelons" in text
    assert "do not compare its 500-person leaf-formation count" in text
    assert "Never convert aggregate formation casualties" in text


def test_autonomous_battlefield_authority_lookup_fails_closed(monkeypatch, campaign):
    """Broken authority routing must never turn Wei's force into an NPC force."""
    import pytest
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)

    def broken_authority(*_args, **_kwargs):
        raise ValueError("corrupt authority route")

    monkeypatch.setattr(planner, "_has_formation_authority", broken_authority)
    with pytest.raises(ValueError, match="corrupt authority route"):
        planner._battlefield_player_controls_formation("formation_qin_wei_high_guard_01")


def _place_player_for_medical_fixture(campaign, location_ref: str) -> None:
    player_path = campaign / "state/player.json"
    player = json.loads(player_path.read_text())
    player["location"] = location_ref
    player["current_location"] = location_ref
    player_path.write_text(json.dumps(player, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, "state/player.json")


def test_medical_treatment_consumes_exact_fortified_stock(campaign):
    """Sword care must conserve medical stock like the Shinobi medic path."""
    from conftest import execute, execute_production

    _place_player_for_medical_fixture(campaign, "loc_kanyou")
    execute(campaign, "health_injury", {"injury": "fixture cut", "severity": "moderate"})
    depot_path = campaign / "state/depots/fort-kanyou.json"
    before = json.loads(depot_path.read_text())["stocks"]["medicine_lots"]

    result = execute_production(campaign, "medical_treatment", {
        "target_ref": "char_tang_wei",
        "practitioner_ref": "char_tang_wei",
        "treatment": "treat",
        "hours": 1,
    }).receipt.result

    after = json.loads(depot_path.read_text())["stocks"]["medicine_lots"]
    assert result["medical_supply_ref"] == "depot_fort_kanyou"
    assert result["medicine_lots_before"] == before
    assert result["medicine_lots_consumed"] == 1
    assert result["medicine_lots_after"] == before - 1
    assert after == before - 1


def test_medical_treatment_fails_closed_without_exact_stock(campaign):
    import pytest
    from conftest import execute, execute_production, meta

    _place_player_for_medical_fixture(campaign, "loc_kanyou")
    depot_path = campaign / "state/depots/fort-kanyou.json"
    depot = json.loads(depot_path.read_text())
    depot["stocks"]["medicine_lots"] = 0
    depot_path.write_text(json.dumps(depot, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, "state/depots/fort-kanyou.json")
    execute(campaign, "health_injury", {"injury": "fixture cut", "severity": "moderate"})
    revision_before = meta(campaign)["revision"]

    with pytest.raises(ValueError, match="medicine_lots"):
        execute_production(campaign, "medical_treatment", {
            "target_ref": "char_tang_wei",
            "practitioner_ref": "char_tang_wei",
            "treatment": "treat",
            "hours": 1,
        })

    assert meta(campaign)["revision"] == revision_before
    assert json.loads(depot_path.read_text())["stocks"]["medicine_lots"] == 0


def test_all_live_fortification_depot_routes_resolve_exactly(campaign):
    fort_index = json.loads((campaign / "state/fortifications/index.json").read_text())
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    for site_ref, row in fort_index["static_profiles"].items():
        depot_ref = row.get("live_logistics_depot_ref")
        if depot_ref is None:
            continue
        assert depot_ref in owners, (site_ref, depot_ref)
        depot = json.loads((campaign / owners[depot_ref]).read_text())
        assert depot["owner_id"] == depot_ref
        assert depot["schema"] == "sword-depot"
        assert site_ref in {depot.get("site_ref"), depot.get("location_ref")}


def test_battle_rejects_unresolved_exact_commander(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    _, formation = planner._load_formation("formation_red_lance_a")
    broken = copy.deepcopy(formation)
    broken["commander_ref"] = "char_missing_exact_commander"
    with pytest.raises(ValueError, match="exact commander unresolved"):
        planner._combat_command_admission(broken)


def test_battle_named_participant_location_authority_failure_propagates(campaign, monkeypatch):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    _, formation, force = planner._combat_prepare_formation("formation_red_lance_a")
    def broken_location(_person):
        raise ValueError("broken exact location owner")
    monkeypatch.setattr(planner, "_person_location", broken_location)
    with pytest.raises(ValueError, match="broken exact location owner"):
        planner._combat_named_participants(formation, force)


def test_battle_named_participant_equipment_failure_propagates(campaign, monkeypatch):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    _, formation, force = planner._combat_prepare_formation("formation_red_lance_a")
    def broken_equipment(_ref, _person):
        raise ValueError("broken exact equipment owner")
    monkeypatch.setattr(planner, "_personal_equipment_profile", broken_equipment)
    with pytest.raises(ValueError, match="broken exact equipment owner"):
        planner._combat_named_participants(formation, force)


def test_battle_rejects_unresolved_higher_command_group(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    _, formation = planner._load_formation("formation_red_lance_a")
    broken = copy.deepcopy(formation)
    broken["higher_command_ref"] = "cmdgrp.missing.battle.authority"
    with pytest.raises(ValueError, match="higher command unresolved"):
        planner._combat_higher_command_participants(broken)


def test_court_candidate_projection_fails_closed_on_unresolved_exact_person(campaign):
    from sword_runtime.court_presence import court_session_projection
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    index = copy.deepcopy(planner.read("state/index/court-attendance-index.json"))
    state_ref, profile = next(iter(index["courts"].items()))
    profile.setdefault("candidate_rows", []).append({"person_ref": "char_missing_court_candidate"})
    planner.put("state/index/court-attendance-index.json", index)
    with pytest.raises(ValueError, match="court attendance candidate unresolved"):
        court_session_projection(planner, state_ref=state_ref, venue_ref=str(profile.get("venue_ref") or "loc_kanyou"))


def test_standing_training_location_authority_failure_propagates(campaign, monkeypatch):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.sim.calendar import CampaignTime

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    current = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    player = copy.deepcopy(planner.read("state/player.json"))
    ds = player.setdefault("development_state", {})
    ds["standing_training_time_credit_hours"] = 1.0
    ds["standing_training_credit_window_start"] = str(current.add_hours(-1))
    planner.put("state/player.json", player)
    def broken_location(_person):
        raise ValueError("standing training exact location broken")
    monkeypatch.setattr(planner, "_person_location", broken_location)
    with pytest.raises(ValueError, match="standing training exact location broken"):
        planner._consume_player_standing_credit(current, "test:broken-location")


def test_campaign_participant_command_group_failure_propagates(campaign):
    from sword_runtime.campaign_command_cycle import _operation_commander_refs
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    operation = {"command_group_ref": "cmdgrp.missing.campaign", "formation_refs": []}
    with pytest.raises((FileNotFoundError, KeyError, ValueError)):
        _operation_commander_refs(planner, operation, include_nested=False)


def test_current_force_projection_preserves_split_command_geography(campaign):
    from sword_runtime.api.stable_operations import StableCampaignOperations
    from sword_runtime.service_runtime import ProductionSwordRuntime

    meta = json.loads((campaign / "state/meta.json").read_text())
    ops = StableCampaignOperations(ProductionSwordRuntime(campaign))
    rows = ops._controlled_force_echelon_views(meta["player_id"])
    assert rows
    army = rows[0]
    assert "headquarters_location_ref" in army
    assert isinstance(army.get("formation_location_refs"), list)
    assert army.get("formation_location_refs")
    for command in army.get("primary_commands", []):
        assert "headquarters_location_ref" in command
        assert "formation_location_refs" in command
        assert isinstance(command["formation_location_refs"], list)
        assert "commander_location_ref" in command
        assert "commander_physically_with_command" in command

    context = ops.play_context()
    compact = context["controlled_force_echelons"][0]
    assert compact.get("headquarters_location_ref") == army.get("headquarters_location_ref")
    assert compact.get("formation_location_refs") == army.get("formation_location_refs")
    assert all("formation_location_refs" in row for row in compact.get("primary_commands", []))
