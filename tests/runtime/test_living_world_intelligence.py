from __future__ import annotations

import hashlib
import json
import shutil
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from sword_runtime.causal_living_world import CausalLivingWorldSwordPlanner
from sword_runtime.commands import CommandEnvelope
from sword_runtime.development import ROUTINE_SKILL_TRAINING_CEILING, settle_skill_training
from sword_runtime.living_world import (
    HighSalienceWakeRequired,
    LivingWorldSwordPlanner,
    OPERATIONAL_MEMORY_PATH,
    _MAX_FORMATION_MEMORY,
)
from sword_runtime.production_living_world import ProductionLivingWorldSwordPlanner
from sword_runtime.service_runtime import ProductionSwordRuntime
from sword_runtime.sim.calendar import CampaignTime


def _state_host(planner: LivingWorldSwordPlanner, state: str):
    runtime = planner.read("state/runtime.json")
    for host in runtime.get("hosts", {}).values():
        owner = str(host.get("owner_ref", "")).replace("state_", "")
        if host.get("kind") == "state" and owner == state:
            return host
    raise AssertionError(f"missing state host for {state}")


def _read_json(root: Path, path: str):
    return json.loads((root / path).read_text(encoding="utf-8"))


def _write_json(root: Path, path: str, value) -> None:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _apply_plan(root: Path, plan) -> None:
    for path, raw in plan.writes.items():
        target = root / path
        if raw is None:
            if target.exists():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def _state_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "state").rglob("*.json")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def _advance_horizon(root: Path, runtime_root: Path, days: int) -> str:
    """Advance a disposable real-campaign clone through one fixed horizon.

    A future campaign snapshot may lawfully encounter player-agency wake
    boundaries. The stability replay deterministically acknowledges those wakes
    on the disposable clone and continues toward the same absolute target. Live
    campaign policy remains unchanged.
    """

    runtime = ProductionSwordRuntime(root, runtime_root=runtime_root)
    initial = runtime.store.read_json("state/meta.json")
    target = CampaignTime.parse(str(initial["time"])).add_seconds(days * 86400)
    previous_time = CampaignTime.parse(str(initial["time"]))

    for step in range(256):
        meta = runtime.store.read_json("state/meta.json")
        current = CampaignTime.parse(str(meta["time"]))
        if current >= target:
            return _state_digest(root)
        command = CommandEnvelope(
            campaign_id=str(meta["campaign_id"]),
            request_id=f"stability.horizon.{days}d.step.{step:03d}",
            actor_id=str(meta["player_id"]),
            command_type="advance_time",
            expected_revision=int(meta["revision"]),
            submitted_at=str(meta["time"]),
            payload={"target_time": str(target)},
            mode="gameplay",
        )
        runtime.execute(command)
        advanced = CampaignTime.parse(str(runtime.store.read_json("state/meta.json")["time"]))
        if advanced <= previous_time:
            raise AssertionError("stability replay made no causal time progress")
        previous_time = advanced

    raise AssertionError("stability replay exceeded bounded wake-resume iterations")


def test_production_runtime_uses_living_world_planner(campaign: Path) -> None:
    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-production")
    assert isinstance(runtime.planner, ProductionLivingWorldSwordPlanner)
    assert isinstance(runtime.planner, CausalLivingWorldSwordPlanner)
    assert isinstance(runtime.planner, LivingWorldSwordPlanner)
    assert runtime.planner.PLAYER_ACTOR == runtime.store.read_json("state/meta.json")["player_id"]


def test_autonomous_state_uses_bounded_memory_and_objective_fit(campaign: Path) -> None:
    planner = LivingWorldSwordPlanner(campaign)
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
    assert set(state_memory) == {"formation_candidate_cursor"}
    assert state_memory["formation_candidate_cursor"] >= 0
    # Current formation facts and active-operation lists are derived from exact
    # owners. Merely reviewing formations must not create a shadow diary.
    assert memory["formation_memory"] == {}

    operations = planner._writes.get("state/operations/index.json", planner.read("state/operations/index.json"))["operations"]
    active_refs = [
        ref
        for ref, path in operations.items()
        if ref.startswith("operation_auto_qin_")
        and planner._writes.get(path, planner.read(path)).get("status") in {"planned", "mobilizing", "active", "engaged", "occupied"}
    ]
    assert 1 <= len(active_refs) <= 3
    first = planner._writes.get(operations[active_refs[0]], planner.read(operations[active_refs[0]]))
    assert first["autonomous"] is True
    assert len(first["formation_refs"]) <= 2
    # The highest-severity objective is a siege threat. Inspect that exact
    # operation rather than relying on operation-ref lexical ordering.
    siege_ops = [
        planner._writes.get(operations[ref], planner.read(operations[ref]))
        for ref in active_refs
        if "fortress_breach" in planner._writes.get(operations[ref], planner.read(operations[ref])).get("objective_refs", [])
    ]
    assert siege_ops
    if "formation_qin_siege_train" in planner._writes.get("state/index/owner-index.json", planner.read("state/index/owner-index.json"))["owners"]:
        assert "formation_qin_siege_train" in siege_ops[0]["formation_refs"]


def test_active_manual_operation_reserves_its_formation(campaign: Path) -> None:
    owner_index = _read_json(campaign, "state/index/owner-index.json")["owners"]
    reserved_ref = "formation_qin_siege_train"
    if reserved_ref not in owner_index:
        pytest.skip("current campaign has no exact Qin siege train")
    operation_ref = "operation_test_manual_reservation"
    operation_path = f"state/operations/{operation_ref}.json"
    operation = {
        "schema": "sword-operation",
        "owner_id": operation_ref,
        "operation_ref": operation_ref,
        "objective": "manual player-authorized siege preparation",
        "status": "active",
        "formation_refs": [reserved_ref],
        "location_ref": _read_json(campaign, owner_index[reserved_ref])["location_ref"],
        "created_at": _read_json(campaign, "state/meta.json")["time"],
        "autonomous": False,
    }
    _write_json(campaign, operation_path, operation)
    index = _read_json(campaign, "state/operations/index.json")
    index["operations"][operation_ref] = operation_path
    _write_json(campaign, "state/operations/index.json", index)

    planner = CausalLivingWorldSwordPlanner(campaign)
    planner.PLAYER_ACTOR = planner.read("state/meta.json")["player_id"]
    planner._reset()
    at = str(planner.read("state/runtime.json")["world_time"])
    memory = planner._operational_memory(at)
    selected = planner._select_formations(
        "qin",
        "siege and breach a fortified position",
        memory,
        reserved=set(),
        count=2,
    )
    assert reserved_ref not in selected


def test_player_commanded_autonomous_battle_requires_handoff(campaign: Path) -> None:
    planner = LivingWorldSwordPlanner(campaign)
    planner.PLAYER_ACTOR = planner.read("state/meta.json")["player_id"]
    planner._reset()
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._autonomy_state(_state_host(planner, "qin"), 1, at)
    owner_index = planner._writes.get("state/index/owner-index.json", planner.read("state/index/owner-index.json"))["owners"]
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


def test_interstate_contact_commits_resumable_wake_before_battle(campaign: Path) -> None:
    meta = _read_json(campaign, "state/meta.json")
    current = CampaignTime.parse(meta["time"])
    due = current.add_seconds(3600)
    target = current.add_seconds(2 * 3600)

    runtime = _read_json(campaign, "state/runtime.json")
    host = runtime["hosts"]["host_interstate_wars"]
    host["next_due"] = str(due)
    host["resolved_through"] = str(current)
    host["safe_through"] = str(due.add_seconds(-1))
    event = next(row for row in runtime["events"] if row["event_id"] == "event_host_interstate_wars_review")
    event["due_at"] = str(due)
    event.pop("suspended", None)
    _write_json(campaign, "state/runtime.json", runtime)

    interstate = _read_json(campaign, "state/politics/interstate-history.json")
    theater = interstate["theaters"]["qin_zhao_gyou"]
    theater.update(
        {
            "phase": "advancing",
            "cycle": max(1, int(theater.get("cycle", 0))),
            "attacker_state": "qin",
            "defender_state": "zhao",
            "started_at": str(current),
            "battle_count": 0,
        }
    )
    _write_json(campaign, "state/politics/interstate-history.json", interstate)

    config = _read_json(campaign, "game/data/world/autonomous-theaters.json")
    cfg = next(row for row in config["theaters"] if row["theater_ref"] == "qin_zhao_gyou")
    target_location = cfg["target_location_ref"]
    qin_ref = cfg["formation_refs"]["qin"]
    zhao_ref = cfg["formation_refs"]["zhao"]
    owner_index = _read_json(campaign, "state/index/owner-index.json")["owners"]
    for formation_ref in (qin_ref, zhao_ref):
        formation = _read_json(campaign, owner_index[formation_ref])
        formation["location_ref"] = target_location
        formation["mobilized"] = True
        formation["status"] = "deployed"
        if formation_ref == qin_ref:
            formation["commander_ref"] = meta["player_id"]
        _write_json(campaign, owner_index[formation_ref], formation)
    player = _read_json(campaign, "state/player.json")
    player["location"] = target_location
    _write_json(campaign, "state/player.json", player)

    planner = CausalLivingWorldSwordPlanner(campaign)
    planner.PLAYER_ACTOR = meta["player_id"]
    command = CommandEnvelope(
        campaign_id=meta["campaign_id"],
        request_id="test.interstate.contact.wake",
        actor_id=meta["player_id"],
        command_type="advance_time",
        expected_revision=meta["revision"],
        submitted_at=meta["time"],
        payload={"target_time": str(target)},
        mode="gameplay",
    )
    plan = planner.preview(command)
    assert plan.result["interrupted"] is True
    assert plan.result["wake_required"] is True
    assert plan.result["world_time"] == str(due)
    assert plan.result["wake"]["formation_ref"] == qin_ref
    planned_runtime = json.loads(plan.writes["state/runtime.json"].decode("utf-8"))
    assert planned_runtime["pending_wake"]["kind"] == "interstate_contact"
    assert planned_runtime["hosts"]["host_interstate_wars"]["next_due"] is None
    planned_event = next(row for row in planned_runtime["events"] if row["event_id"] == "event_host_interstate_wars_review")
    assert planned_event["suspended"] is True
    planned_history = json.loads(plan.writes["state/history/events/index.json"].decode("utf-8")) if "state/history/events/index.json" in plan.writes else _read_json(campaign, "state/history/events/index.json")
    assert not any(row.get("kind") == "interstate_battle" and row.get("at") == str(due) for row in planned_history.get("events", []))

    # Apply the planned after-image to the disposable fixture only. A second
    # explicit time continuation acknowledges and resumes this exact wake.
    _apply_plan(campaign, plan)
    meta_after = _read_json(campaign, "state/meta.json")
    planner2 = CausalLivingWorldSwordPlanner(campaign)
    planner2.PLAYER_ACTOR = meta_after["player_id"]
    second = CommandEnvelope(
        campaign_id=meta_after["campaign_id"],
        request_id="test.interstate.contact.resume",
        actor_id=meta_after["player_id"],
        command_type="advance_time",
        expected_revision=meta_after["revision"],
        submitted_at=meta_after["time"],
        payload={"hours": 1},
        mode="gameplay",
    )
    second_plan = planner2.preview(second)
    second_runtime = json.loads(second_plan.writes["state/runtime.json"].decode("utf-8"))
    assert "pending_wake" not in second_runtime
    assert "acknowledged_wake" not in second_runtime
    second_history = json.loads(second_plan.writes["state/history/events/index.json"].decode("utf-8"))
    assert any(row.get("kind") == "interstate_battle" for row in second_history.get("events", []))


def test_autonomous_battle_provenance_is_bounded_and_explicit(campaign: Path) -> None:
    planner = CausalLivingWorldSwordPlanner(campaign)
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


def test_house_review_does_not_invent_unverified_exact_training(campaign: Path) -> None:
    planner = CausalLivingWorldSwordPlanner(campaign)
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


def test_skill_training_has_absolute_progression_bound(campaign: Path) -> None:
    training = LivingWorldSwordPlanner(campaign).read("game/data/mechanics/training.json")
    person = {
        "birth_date": "270-BCE-01-01",
        "health_status": "healthy",
        "skills": {"Sword": ROUTINE_SKILL_TRAINING_CEILING - 1},
        "aptitude": {"physical_learning": 250},
        "development_state": {},
    }
    at = CampaignTime.parse("245-BCE-01-01T00:00:00+08:00")
    result = settle_skill_training(person, "Sword", 1_000_000, at, training)
    assert result["skill_score"] == ROUTINE_SKILL_TRAINING_CEILING
    assert person["skills"]["Sword"] == ROUTINE_SKILL_TRAINING_CEILING
    second = settle_skill_training(person, "Sword", 1_000_000, at, training)
    assert second["skill_score"] == ROUTINE_SKILL_TRAINING_CEILING
    assert second["skill_points_gained"] == 0


def _advance_horizon_snapshot(args: tuple[Path, Path, int]) -> tuple[str, int, str]:
    root, runtime_root, days = args
    digest = _advance_horizon(root, runtime_root, days)
    meta = ProductionSwordRuntime(root, runtime_root=runtime_root.parent / f"{runtime_root.name}-read").store.read_json("state/meta.json")
    return digest, int(meta["revision"]), str(meta["time"])


def test_current_campaign_120_day_replay_is_stable_for_same_saved_seed(campaign: Path, tmp_path: Path) -> None:
    # The two replays are causally independent and intentionally run in separate
    # worker processes. This preserves the full 120-day production horizon while
    # also proving that process/hash ordering is not secret entropy.
    source_digest = _state_digest(campaign)
    jobs = []
    import subprocess
    for label in ("a", "b"):
        replay = tmp_path / f"replay-{label}"
        runtime_root = tmp_path / f"runtime-{label}"
        subprocess.run(["git", "clone", "--quiet", "--shared", str(campaign), str(replay)], check=True)
        jobs.append((replay, runtime_root, 120))

    with ProcessPoolExecutor(max_workers=2) as pool:
        snapshots = list(pool.map(_advance_horizon_snapshot, jobs))

    assert _state_digest(campaign) == source_digest
    # This is a replay-integrity check only. Living-world vitality is tested
    # separately and need not force every alternate seeded future into one story.
    assert snapshots[0] == snapshots[1]
