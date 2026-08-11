from __future__ import annotations

import json
from pathlib import Path

import pytest

from sword_runtime.api.operations import OperationError
from sword_runtime.api.stable_operations import StableCampaignOperations, transaction_failure_code
from sword_runtime.causal_living_world import _WAKE_RESPONSE_COMMANDS
from sword_runtime.commands import CommandEnvelope
from sword_runtime.living_world import HighSalienceWakeRequired
from sword_runtime.service_runtime import ProductionSwordRuntime
from sword_runtime.tx.errors import GitCommitError, GitStageError, WalError


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
        "formation_ref": "formation_qin_border_line",
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

    runtime = ProductionSwordRuntime(
        campaign,
        runtime_root=campaign.parent / "runtime-wake-contract",
    )
    operations = StableCampaignOperations(runtime)
    context = operations.play_context()
    assert context["decision_required"] is True
    assert context["decision_reason"] == "high_salience_autonomous_contact"
    assert context["pending_wake"]["response_command_types"] == sorted(_WAKE_RESPONSE_COMMANDS)
    assert context["pending_wake"]["continue_contact_command"] == "advance_time"
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


def test_transaction_failure_codes_do_not_expose_git_output() -> None:
    assert transaction_failure_code(GitStageError(1, "secret-bearing stderr")) == "transaction_git_stage_failed"
    assert transaction_failure_code(GitCommitError(1, "secret-bearing stderr")) == "transaction_git_commit_failed"
    assert transaction_failure_code(WalError("bad wal")) == "transaction_wal_failed"
