from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sword_runtime.api.operations import OperationError
from sword_runtime.api.stable_operations import StableCampaignOperations, transaction_failure_code
from sword_runtime.causal_living_world import _WAKE_RESPONSE_COMMANDS
from sword_runtime.commands import CommandEnvelope
from sword_runtime.living_world import HighSalienceWakeRequired
from sword_runtime.service_runtime import ProductionSwordRuntime
from sword_runtime.tx.errors import GitCommitError, GitStageError, WalError


def _commit_fixture(campaign: Path, *paths: str) -> None:
    subprocess.run(["git", "-C", str(campaign), "add", *paths], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "-q", "-m", "test: commit runtime fixture"], check=True)


class _Store:
    def read_json(self, path: str):
        if path == "state/meta.json":
            return {"player_id": "char_player"}
        raise AssertionError(path)


class _WakeRuntime:
    store = _Store()

    def preview_for_execution(self, command):
        raise HighSalienceWakeRequired("wake")


def test_high_salience_wake_has_stable_player_surface_code() -> None:
    operations = StableCampaignOperations(_WakeRuntime())
    command = CommandEnvelope(
        campaign_id="campaign",
        request_id="wake.test",
        actor_id="char_player",
        command_type="advance_time",
        expected_revision=0,
        submitted_at="245-BCE-01-01T00:00:00+08:00",
        payload={"hours": 24},
    )
    with pytest.raises(OperationError) as exc_info:
        operations.preview_command(command)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "high_salience_wake_required"


def test_pending_wake_context_and_preview_share_one_response_contract(campaign: Path) -> None:
    runtime_path = campaign / "state/runtime.json"
    runtime_state = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime_state["pending_wake"] = {
        "wake_ref": "wake.test.contract",
        "kind": "interstate_contact",
        "at": runtime_state["world_time"],
        "theater_ref": "qin_zhao_gyou",
        "formation_ref": "formation_qin_wei_unit_01",
        "location_ref": "loc_gyou",
        "opponent_state": "zhao",
        "reason": "test decision boundary",
        "target_host": "host_interstate_wars",
        "event_id": "event_host_interstate_wars_review",
    }
    runtime_path.write_text(
        json.dumps(runtime_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _commit_fixture(campaign, "state/runtime.json")

    runtime = ProductionSwordRuntime(
        campaign,
        runtime_root=campaign.parent / "runtime-wake-contract",
    )
    operations = StableCampaignOperations(runtime)
    context = operations.play_context()
    response_types = sorted(set(_WAKE_RESPONSE_COMMANDS) | {'interaction_action'})
    assert context["decision_required"] is True
    assert context["decision_reason"] == "high_salience_autonomous_contact"
    assert context["pending_wake"]["requires_player_decision"] is True
    assert context["pending_wake"]["response_command_types"] == response_types
    assert context["pending_wake"]["continue_contact_command"] == "advance_time"
    assert context["commands"]["availability_scope"] == "pending_wake_response"
    assert context["commands"]["temporarily_available_command_types"] == response_types
    assert "target_host" not in context["pending_wake"]
    assert "event_id" not in context["pending_wake"]

    meta = runtime.store.read_json("state/meta.json")
    blocked = CommandEnvelope(
        campaign_id=meta["campaign_id"],
        request_id="wake.preview.blocked-battle",
        actor_id=meta["player_id"],
        command_type="battle_resolve",
        expected_revision=meta["revision"],
        submitted_at=meta["time"],
        payload={},
        mode="gameplay",
    )
    with pytest.raises(OperationError) as exc_info:
        operations.preview_command(blocked)
    assert exc_info.value.code == "high_salience_wake_required"

    allowed = CommandEnvelope(
        campaign_id=meta["campaign_id"],
        request_id="wake.preview.continue-contact",
        actor_id=meta["player_id"],
        command_type="advance_time",
        expected_revision=meta["revision"],
        submitted_at=meta["time"],
        payload={"hours": 1},
        mode="gameplay",
    )
    preview = operations.preview_command(allowed)
    assert preview["status"] == "ready_execute_only"
    assert preview["contested_outcome_hidden"] is True


def test_persisted_campaign_event_wake_is_invalid_state(campaign: Path) -> None:
    runtime_path = campaign / "state/runtime.json"
    runtime_state = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime_state["pending_wake"] = {
        "wake_ref": "wake.campaign_event.test",
        "kind": "campaign_event",
        "at": runtime_state["world_time"],
        "campaign_event_ref": "event_test_staff_response",
        "reason": "The staff channel returns a procedural response.",
        "target_host": "host_campaign_event_test",
        "event_id": "event_campaign_event_test",
    }
    runtime_path.write_text(json.dumps(runtime_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _commit_fixture(campaign, "state/runtime.json")

    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-campaign-wake")
    with pytest.raises(OperationError) as exc_info:
        StableCampaignOperations(runtime).play_context()
    assert exc_info.value.code == "invalid_persisted_campaign_event_wake"


def test_durable_offer_requires_decision_without_blocking_unrelated_commands(campaign: Path) -> None:
    player_path = campaign / "state/player.json"
    player = json.loads(player_path.read_text(encoding="utf-8"))
    career = player.setdefault("career_state", {})
    offer_ref = "event_test_qin_command_offer"
    career["pending_qin_command_offer_refs"] = [offer_ref]
    career["pending_qin_command_offers"] = {
        offer_ref: {
            "formation_ref": "formation_qin_mobile_reserve",
            "formation_name": "Qin Mobile Reserve",
            "personnel": 5000,
            "location_ref": "loc_qin_regional_01",
            "operation_ref": "operation_arc_73745d7ca38d929e0e",
        }
    }
    player_path.write_text(json.dumps(player, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _commit_fixture(campaign, "state/player.json")

    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-durable-decision")
    context = StableCampaignOperations(runtime).play_context()
    assert context["decision_required"] is True
    assert context["decision_reason"] == "durable_player_decision"
    assert context["unresolved_decision"]["decision_ref"] == offer_ref
    assert context["unresolved_decision"]["kind"] == "qin_field_command_offer"
    assert context["commands"].get("availability_scope", "normal") == "normal"
    assert context.get("pending_wake") is None


def test_campaign_event_settlement_commits_through_production_transaction(campaign: Path) -> None:
    meta_path = campaign / "state/meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    work_path = campaign / "state/index/campaign-causal-work.json"
    work = {
        "authority": False,
        "purpose": "test one-shot production transaction routing",
        "targets": [
            {
                "work_ref": "event_test_transactional_staff_response",
                "source_owner_ref": "events_messages_and_movement",
                "kind": "institutional_response",
                "due_at": meta["time"],
                "priority": 50,
                "status": "pending",
                "effect": {"summary": "The transactional test staff response arrives."},
                "wake": True,
            }
        ],
    }
    work_path.write_text(
        json.dumps(work, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    # Production transactions fail closed on dirty repositories. Make this
    # disposable routing fixture part of the test clone's committed baseline;
    # gameplay must read it but never mutate it.
    subprocess.run(
        ["git", "-C", str(campaign), "add", "state/index/campaign-causal-work.json"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(campaign), "commit", "-q", "-m", "test: add campaign causal work fixture"],
        check=True,
    )

    runtime = ProductionSwordRuntime(
        campaign,
        runtime_root=campaign.parent / "runtime-campaign-event-transaction",
    )
    command = CommandEnvelope(
        campaign_id=meta["campaign_id"],
        request_id="campaign-event.transaction.advance",
        actor_id=meta["player_id"],
        command_type="advance_time",
        expected_revision=meta["revision"],
        submitted_at=meta["time"],
        payload={"hours": 1},
        mode="gameplay",
    )
    execution = runtime.execute(command)
    assert execution.receipt.committed_revision == meta["revision"] + 1
    assert execution.receipt.result.get("wake_required") is not True
    assert execution.receipt.result["events_processed"] == 1
    notices = execution.receipt.result["campaign_event_notices"]
    assert len(notices) == 1
    assert notices[0]["campaign_event_ref"] == "event_test_transactional_staff_response"

    operations = StableCampaignOperations(runtime)
    context = operations.play_context()
    assert context.get("pending_wake") is None
    owners = runtime.store.read_json("state/index/owner-index.json")["owners"]
    event_owner = runtime.store.read_json(owners["events_messages_and_movement"])
    event = event_owner["causal_events"]["event_test_transactional_staff_response"]
    assert event["status"] == "triggered"
    assert event["triggered_at"] == meta["time"]
    assert event["provenance"]["late_catch_up"] is False
    assert runtime.store.read_json("state/index/campaign-causal-work.json") == work


def test_transaction_failure_codes_do_not_expose_git_output() -> None:
    assert transaction_failure_code(GitStageError(1, "secret-bearing stderr")) == "transaction_git_stage_failed"
    assert transaction_failure_code(GitCommitError(1, "secret-bearing stderr")) == "transaction_git_commit_failed"
    assert transaction_failure_code(WalError("bad wal")) == "transaction_wal_failed"
