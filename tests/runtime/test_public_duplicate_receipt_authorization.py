from types import SimpleNamespace

import pytest

from sword_runtime.api.operations import CampaignOperations, OperationError
from sword_runtime.api.stable_operations import StableCampaignOperations
from sword_runtime.commands import CommandEnvelope


class _Store:
    def read_json(self, path):
        assert path == "state/meta.json"
        return {"player_id": "char_tang_wei"}


def _command(*, actor="char_intruder", mode="gameplay", command_type="interaction_action"):
    return CommandEnvelope(
        campaign_id="campaign.test",
        request_id="request.test",
        actor_id=actor,
        command_type=command_type,
        expected_revision=1,
        submitted_at="244-BCE-09-17T18:22:48+08:00",
        payload={},
        mode=mode,
    )


def _base_operations(cls=CampaignOperations):
    operations = object.__new__(cls)
    operations.store = _Store()
    operations.runtime = SimpleNamespace(
        coordinator=SimpleNamespace(
            lookup_receipt=lambda _command: (_ for _ in ()).throw(AssertionError("receipt lookup must not run"))
        )
    )
    return operations


def test_public_duplicate_lookup_rejects_wrong_actor_before_receipt_recovery():
    operations = _base_operations()
    with pytest.raises(OperationError) as exc:
        operations.lookup_command_receipt(_command())
    assert exc.value.status_code == 403
    assert exc.value.code == "player_surface_forbids_internal_mode"


def test_stable_surface_authorizes_before_translation_or_raw_receipt_special_case():
    operations = _base_operations(StableCampaignOperations)
    operations._translate_surface_command = lambda _command: (_ for _ in ()).throw(AssertionError("translation must not run"))
    with pytest.raises(OperationError) as exc:
        operations.lookup_command_receipt(_command(command_type="scene_consequence", mode="autonomous"))
    assert exc.value.status_code == 403
    assert exc.value.code == "player_surface_forbids_internal_mode"
