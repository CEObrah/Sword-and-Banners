from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from conftest import meta


def _command_and_receipt(root):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.tx.receipts import IdempotencyReceipt

    current = meta(root)
    command = CommandEnvelope(
        current['campaign_id'],
        'repair-invalidation-regression-request',
        current['player_id'],
        'scene_consequence',
        current['revision'],
        current['time'],
        {'summary': 'transaction used only for repair-integrity regression coverage'},
        mode='gameplay',
    )
    transaction_id = 'sword-' + hashlib.sha256(
        (command.digest + ':' + str(current['revision'])).encode('utf-8')
    ).hexdigest()[:24]
    receipt = IdempotencyReceipt.for_command(
        command,
        transaction_id=transaction_id,
        committed_revision=current['revision'] + 1,
        committed_at=current['time'],
        result={'test_only': True},
    )
    return current, command, receipt


def test_scene_projection_requires_revision_as_well_as_world_time(campaign):
    from sword_runtime.api.operations import CampaignOperations

    current = meta(campaign)
    player = json.load(open(campaign/'state/player.json'))
    scene = json.load(open(campaign/'state/scene.json'))
    assert scene['world_time'] == current['time']
    assert scene['projection_revision'] == current['revision']
    assert CampaignOperations._safe_scene(current, player, scene)['projection_status'] == 'fresh'

    same_time_stale = dict(scene)
    same_time_stale['projection_revision'] = current['revision'] - 1
    stale = CampaignOperations._safe_scene(current, player, same_time_stale)
    assert stale['projection_status'] == 'stale_after_state_change'
    assert stale['unresolved_decision'] is None
    assert stale['observable_pressures'] == []


def test_empty_transaction_invalidation_registry_is_valid(campaign):
    from sword_runtime.store.repository import RepositoryStore
    from sword_runtime.tx.invalidations import load_transaction_invalidations

    assert load_transaction_invalidations(RepositoryStore(campaign)) == ()


def test_unexplained_future_receipt_fails_recovery(campaign, tmp_path):
    from sword_runtime.service_runtime import ProductionSwordRuntime
    from sword_runtime.tx.errors import RecoveryError

    _current, _command, receipt = _command_and_receipt(campaign)
    runtime = ProductionSwordRuntime(campaign, tmp_path/'runtime')
    runtime.coordinator.receipts.put(receipt)
    with pytest.raises(RecoveryError, match='future campaign revision'):
        runtime.recover()


def test_exact_repair_invalidation_allows_recovery_and_reserves_request_id(campaign, tmp_path):
    from sword_runtime.service_runtime import ProductionSwordRuntime
    from sword_runtime.tx.errors import IdempotencyConflictError

    current, command, receipt = _command_and_receipt(campaign)
    head = subprocess.check_output(
        ['git','-C',str(campaign),'rev-parse','HEAD'], text=True
    ).strip()
    registry = {
        'schema': 'sword.transaction-invalidations',
        'version': 1,
        'records': [
            {
                'campaign_id': current['campaign_id'],
                'transaction_id': receipt.transaction_id,
                'request_id': receipt.request_id,
                'request_digest': receipt.request_digest,
                'invalidated_revision': receipt.committed_revision,
                'restored_revision': current['revision'],
                'bad_commit': '0' * 40,
                'repair_commit': head,
                'reason': 'Disposable regression fixture simulates an explicitly reviewed rollback repair.',
            }
        ],
    }
    path = campaign/'runtime/contracts/transaction-invalidations.json'
    path.write_text(json.dumps(registry, indent=2) + '\n')
    subprocess.run(['git','-C',str(campaign),'add','runtime/contracts/transaction-invalidations.json'],check=True)
    subprocess.run(['git','-C',str(campaign),'commit','-m','Register disposable repair invalidation'],check=True,stdout=subprocess.DEVNULL)

    runtime = ProductionSwordRuntime(campaign, tmp_path/'runtime')
    runtime.coordinator.receipts.put(receipt)
    assert runtime.recover() == ()
    with pytest.raises(IdempotencyConflictError, match='explicitly invalidated'):
        runtime.coordinator.lookup_receipt(command)
