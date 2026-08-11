from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from sword_runtime.causal_living_world import CausalLivingWorldSwordPlanner
from sword_runtime.commands import CommandEnvelope
from sword_runtime.development import ABSOLUTE_SKILL_HARD_CAP, settle_skill_training
from sword_runtime.living_world import (
    HighSalienceWakeRequired,
    LivingWorldSwordPlanner,
    OPERATIONAL_MEMORY_PATH,
)
from sword_runtime.service_runtime import ProductionSwordRuntime
from sword_runtime.sim.calendar import CampaignTime


def _state_host(planner: LivingWorldSwordPlanner, state: str):
    runtime = planner.read("state/runtime.json")
    for host in runtime.get("hosts", {}).values():
        owner = str(host.get("owner_ref", "")).replace("state_", "")
        if host.get("kind") == "state" and owner == state:
            return host
    raise AssertionError(f"missing state host for {state}")


def _state_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "state").rglob("*.json")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def _advance_days(root: Path, runtime_root: Path, days: int) -> str:
    runtime = ProductionSwordRuntime(root, runtime_root=runtime_root)
    for day in range(days):
        meta = runtime.store.read_json("state/meta.json")
        command = CommandEnvelope(
            campaign_id=str(meta["campaign_id"]),
            request_id=f"stability.day.{day + 1:02d}",
            actor_id=str(meta["player_id"]),
            command_type="advance_time",
            expected_revision=int(meta["revision"]),
            submitted_at=str(meta["time"]),
            payload={"hours": 24},
            mode="gameplay",
        )
        runtime.execute(command)
    return _state_digest(root)


def test_production_runtime_uses_living_world_planner(repo_copy: Path) -> None:
    runtime = ProductionSwordRuntime(repo_copy, runtime_root=repo_copy.parent / "runtime-production")
    assert isinstance(runtime.planner, CausalLivingWorldSwordPlanner)
    assert isinstance(runtime.planner, LivingWorldSwordPlanner)
    assert runtime.planner.PLAYER_ACTOR == runtime.store.read_json("state/meta.json")["player_id"]


def test_autonomous_state_uses_bounded_memory_and_objective_fit(repo_copy: Path) -> None:
    planner = LivingWorldSwordPlanner(repo_copy)
    planner.PLAYER_ACTOR = planner.read("state/meta.json")["player_id"]
    planner._reset()
    state_path = "state/states/qin.json"
    qin = dict(planner.read(state_path))
    qin["known_threats"] = {
        "fortress_breach": {"severity": 95, "kind": "siege"},
        "mobile_raid": {"severity": 85, "kind": "mobile"},
        "border_incursion": {"severity": 70, "kind": "border"},
    }
    planner.put(state_path, qin)
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._autonomy_state(_state_host(planner, "qin"), 1, at)

    memory = planner._writes[OPERATIONAL_MEMORY_PATH]
    state_memory = memory["state_memory"]["qin"]
    assert state_memory["operation_capacity"] == 3
    assert 1 <= len(state_memory["active_operation_refs"]) <= 3
    assert len(memory["formation_memory"]) <= 24

    operations = planner._writes.get("state/operations/index.json", planner.read("state/operations/index.json"))["operations"]
    first_ref = state_memory["active_operation_refs"][0]
    first = planner._writes[operations[first_ref]]
    assert first["autonomous"] is True
    assert len(first["formation_refs"]) <= 2
    # The highest-severity objective is a siege threat. Selection should use
    # the exact siege formation when it exists instead of blindly taking the
    # first two blueprint entries as the legacy autonomy did.
    if "formation_qin_siege_train" in planner._writes.get("state/index/owner-index-gold.json", planner.read("state/index/owner-index-gold.json"))["owners"]:
        assert "formation_qin_siege_train" in first["formation_refs"]


def test_player_commanded_autonomous_battle_requires_handoff(repo_copy: Path) -> None:
    planner = LivingWorldSwordPlanner(repo_copy)
    planner.PLAYER_ACTOR = planner.read("state/meta.json")["player_id"]
    planner._reset()
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._autonomy_state(_state_host(planner, "qin"), 1, at)
    owner_index = planner._writes.get("state/index/owner-index-gold.json", planner.read("state/index/owner-index-gold.json"))["owners"]
    formation_ref = next(ref for ref in sorted(owner_index) if ref.startswith("formation_qin_"))
    path = owner_index[formation_ref]
    formation = dict(planner._writes.get(path, planner.read(path)))
    formation["commander_ref"] = planner.PLAYER_ACTOR
    planner.put(path, formation)
    with pytest.raises(HighSalienceWakeRequired):
        planner._autonomy_apply_battle_losses(
            formation_ref,
            1,
            at,
            losing_side=False,
            opponent_state="zhao",
            seed_material="test-high-salience",
        )


def test_autonomous_battle_provenance_is_bounded_and_explicit(repo_copy: Path) -> None:
    planner = CausalLivingWorldSwordPlanner(repo_copy)
    planner.PLAYER_ACTOR = planner.read("state/meta.json")["player_id"]
    planner._reset()
    at = str(planner.read("state/runtime.json")["world_time"])
    event = {
        "event_id": "event.test.provenance",
        "kind": "interstate_battle",
        "at": at,
        "theater_ref": "theater_test",
        "battlefield_ref": "loc_test_field",
        "attacker_state": "qin",
        "defender_state": "zhao",
        "attacker_formation_ref": "formation_qin_test",
        "defender_formation_ref": "formation_zhao_test",
        "winner_state": "qin",
        "losses": {},
    }
    planner._record_interstate_battle_memory(event, at)
    assert event["place_refs"] == ["loc_test_field"]
    assert event["causal_refs"] == ["theater_test"]
    assert event["affected_owner_refs"] == [
        "formation_qin_test",
        "formation_zhao_test",
        "state_qin",
        "state_zhao",
    ]
    assert event["actor_refs"] == []
    assert event["material_consequence_refs"] == []
    assert event["provenance"]["kind"] == "autonomous_runtime_resolution"


def test_house_review_does_not_invent_unverified_exact_training(repo_copy: Path) -> None:
    planner = CausalLivingWorldSwordPlanner(repo_copy)
    planner.PLAYER_ACTOR = planner.read("state/meta.json")["player_id"]
    planner._reset()
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._autonomy_house({"owner_ref": "house_tang"}, 1, at)
    # Tang family activity contracts explicitly say planned opportunity is not
    # automatic progress. Until Sword has a verified House activity ledger and
    # one owned progression cursor, a House review must not award exact skills.
    assert "state/char/tang-zhu.json" not in planner._writes
    assert "state/char/tang-ling.json" not in planner._writes
    assert "state/char/tang-kai.json" not in planner._writes
    assert "state/player.json" not in planner._writes


def test_skill_training_has_absolute_progression_bound(repo_copy: Path) -> None:
    training = LivingWorldSwordPlanner(repo_copy).read("game/data/mechanics/training.json")
    person = {
        "birth_date": "270-BCE-01-01",
        "health_status": "healthy",
        "skills": {"Sword": ABSOLUTE_SKILL_HARD_CAP - 1},
        "aptitude": {"physical_learning": 250},
        "development_state": {},
    }
    at = CampaignTime.parse("245-BCE-01-01T00:00:00+08:00")
    result = settle_skill_training(person, "Sword", 1_000_000, at, training)
    assert result["skill_score"] == ABSOLUTE_SKILL_HARD_CAP
    assert person["skills"]["Sword"] == ABSOLUTE_SKILL_HARD_CAP
    second = settle_skill_training(person, "Sword", 1_000_000, at, training)
    assert second["skill_score"] == ABSOLUTE_SKILL_HARD_CAP
    assert second["skill_points_gained"] == 0


def test_current_campaign_30_day_replay_is_deterministic(repo_copy: Path, tmp_path: Path) -> None:
    replay_a = tmp_path / "replay-a"
    replay_b = tmp_path / "replay-b"
    shutil.copytree(repo_copy, replay_a)
    shutil.copytree(repo_copy, replay_b)
    digest_a = _advance_days(replay_a, tmp_path / "runtime-a", 30)
    digest_b = _advance_days(replay_b, tmp_path / "runtime-b", 30)
    assert digest_a == digest_b
    meta_a = ProductionSwordRuntime(replay_a, runtime_root=tmp_path / "runtime-a-read").store.read_json("state/meta.json")
    meta_b = ProductionSwordRuntime(replay_b, runtime_root=tmp_path / "runtime-b-read").store.read_json("state/meta.json")
    assert meta_a["revision"] == meta_b["revision"]
    assert meta_a["time"] == meta_b["time"]
