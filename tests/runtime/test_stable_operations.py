from __future__ import annotations

import pytest

from sword_runtime.api.operations import OperationError
from sword_runtime.api.stable_operations import StableCampaignOperations, transaction_failure_code
from sword_runtime.commands import CommandEnvelope
from sword_runtime.living_world import HighSalienceWakeRequired
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


def test_transaction_failure_codes_do_not_expose_git_output() -> None:
    assert transaction_failure_code(GitStageError(1, "secret-bearing stderr")) == "transaction_git_stage_failed"
    assert transaction_failure_code(GitCommitError(1, "secret-bearing stderr")) == "transaction_git_commit_failed"
    assert transaction_failure_code(WalError("bad wal")) == "transaction_wal_failed"
