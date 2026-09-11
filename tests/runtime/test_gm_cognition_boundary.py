"""A short real-transaction scene proving durable, private AI-authored meaning."""
import json
import subprocess
from dataclasses import replace

import pytest

from sword_runtime.api.app import _player_safe_transport
from sword_runtime.api.command_discovery import compact_play_context
from sword_runtime.api.operations import OperationError
from sword_runtime.api.reconnaissance_operations import ReconnaissanceAwareOperations
from sword_runtime.commands import CommandEnvelope
from sword_runtime.gm_cognition import cognition_path
from sword_runtime.scene_sessions import start_scene_session
from sword_runtime.service_runtime import ProductionSwordRuntime
from sword_runtime.store.repository import RepositoryStore


@pytest.fixture
def social_campaign(campaign):
    """Establish only the local scene preconditions in a disposable campaign.

    No world progression, recruitment or synthetic combat setup is performed.
    The current snapshot supplies schemas/world data, not the expected outcome.
    """
    store = RepositoryStore(campaign)
    class Writer:
        read = store.read_json
        def put(self, path, value):
            target = campaign / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')
    writer = Writer()
    player = store.read_json('state/player.json')
    npc = store.read_json('state/char/mou-gou.json')
    npc['location'] = npc['current_location'] = player['location']
    writer.put('state/char/mou-gou.json', npc)
    rt = store.read_json('state/runtime.json')
    rt.pop('pending_wake', None)
    writer.put('state/runtime.json', rt)
    meta = store.read_json('state/meta.json')
    start_scene_session(writer, session_ref='scene_session_cognition_test', kind='conversation',
        location_ref=player['location'], participant_refs=['char_tang_wei', 'char_mou_gou'],
        started_at=meta['time'], purpose='Review a disputed report')
    subprocess.run(['git', '-C', str(campaign), 'add', 'state'], check=True)
    subprocess.run(['git', '-C', str(campaign), 'commit', '-qm', 'isolated cognition scene preconditions'], check=True)
    return campaign


def operations(root):
    return ReconnaissanceAwareOperations(ProductionSwordRuntime(root, root.parent / 'recovery'))


def command(ops, kind, payload, request):
    meta = ops.store.read_json('state/meta.json')
    return CommandEnvelope(meta['campaign_id'], request, meta['player_id'], kind,
        meta['revision'], meta['time'], payload)


def speak(ops, text, request):
    cmd = command(ops, 'scene_session_action', {
        'action': 'record_speech', 'session_ref': 'scene_session_cognition_test',
        'speaker_ref': 'char_tang_wei', 'statement': text,
        'speech_kind': 'observation', 'basis_refs': [],
    }, request)
    result = ops.execute_command(cmd)
    return result['result']['speech_ref']


def proposal(evidence):
    return {
        'action': 'create', 'subject_ref': 'char_mou_gou', 'cognition_ref': 'mou_grain_suspicion',
        'kind': 'suspicion', 'statement': 'Mou Gou suspects that the wagon report is unreliable.',
        'epistemic_status': 'belief', 'basis_refs': [evidence],
        'reason': 'Wei has explicitly described conflicting accounts; Mou Gou remains uncertain.',
        'salience': 'important',
    }


def test_cognition_commit_reload_private_context_and_resolution(social_campaign):
    ops = operations(social_campaign)
    evidence = speak(ops, 'I have heard two conflicting accounts of the wagon arrival.', 'speech-one')
    before = {path: ops.store.read_bytes(path) for path in (
        'state/player.json', 'state/char/mou-gou.json', 'state/economy/player-wallet.json',
        'state/relationships.json', 'state/runtime.json', 'state/information/index.json',
    )}
    cmd = command(ops, 'gm_cognition_action', proposal(evidence), 'cognition-one')
    assert ops.preview_command(cmd)['status'] == 'ready'
    assert ops.store.read_optional_bytes(cognition_path('char_mou_gou')) is None
    result = ops.execute_command(cmd)
    accepted = result['result']['gm_private_cognition']['accepted']
    assert accepted['world_truth_authority'] is False
    assert accepted['basis'][0]['attribution'] == 'char_tang_wei'
    assert _player_safe_transport(result)['result'].get('gm_private_cognition') is None
    assert all(ops.store.read_bytes(path) == value for path, value in before.items())
    fresh = operations(social_campaign)
    assert fresh.execute_command(cmd)['status'] == 'duplicate'
    with pytest.raises(OperationError) as stale:
        fresh.execute_command(replace(cmd, request_id='stale-cognition'))
    assert stale.value.code == 'stale_revision'
    with pytest.raises(OperationError):
        fresh.execute_command(command(fresh, 'gm_cognition_action',
            {**proposal(evidence), 'action': 'update'}, 'no-new-cause'))
    context = compact_play_context(fresh.play_context())
    text = json.dumps(context)
    assert accepted['statement'] in text
    assert accepted['statement'] not in json.dumps(_player_safe_transport(context))
    sheet = fresh.person_sheet('char_mou_gou')
    assert sheet['npc_response_envelope']['gm_private_cognition']['authored_cognition'][0] == accepted
    new_evidence = speak(fresh, 'I retract my earlier account; it was a misunderstanding.', 'speech-two')
    revised = {**proposal(new_evidence), 'action': 'resolve',
        'statement': 'Mou Gou considers the report discrepancy explained.',
        'reason': 'Wei has corrected the original account.'}
    resolution = fresh.execute_command(command(fresh, 'gm_cognition_action', revised, 'cognition-resolve'))
    row = resolution['result']['gm_private_cognition']['accepted']
    assert row['status'] == 'resolved'
    history = fresh.store.read_json('state/cognition/history/' + row['previous_history_ref'] + '.json')
    assert history['previous'] == accepted
    retrieved = fresh.inspect_game_object(row['previous_history_ref'])
    assert retrieved['object'] == history
    assert _player_safe_transport(retrieved) == {}


@pytest.mark.parametrize('change', [
    {'subject_ref': 'char_tang_wei'}, {'basis_refs': ['invented_evidence']},
    {'money': 90000}, {'epistemic_status': 'objective_truth'},
])
def test_cognition_rejects_authority_and_evidence_bypasses(social_campaign, change):
    ops = operations(social_campaign)
    evidence = speak(ops, 'I cannot reconcile these two accounts.', 'speech-guard')
    before = ops.store.read_json('state/meta.json')['revision']
    cmd = command(ops, 'gm_cognition_action', {**proposal(evidence), **change}, 'rejected-cognition')
    with pytest.raises(OperationError):
        ops.execute_command(cmd)
    assert ops.store.read_json('state/meta.json')['revision'] == before
    assert ops.store.read_optional_bytes(cognition_path('char_mou_gou')) is None


@pytest.mark.parametrize('legacy_receipt', [False, True])
def test_exact_scene_close_retry_ignores_changed_scene_preconditions(social_campaign, legacy_receipt):
    ops = operations(social_campaign)
    cmd = command(ops, 'scene_session_action', {
        'action': 'close', 'session_ref': 'scene_session_cognition_test', 'close_reason': 'completed',
    }, 'close-once')
    if legacy_receipt:
        from sword_runtime.api.interaction_surface import translate_scene_action_command
        ops.runtime.execute(translate_scene_action_command(cmd))
        first = ops.lookup_command_receipt(cmd)
    else:
        first = ops.execute_command(cmd)
    fresh = operations(social_campaign)
    for retry in (fresh.lookup_command_receipt(cmd), fresh.execute_command(cmd)):
        assert retry['status'] == 'duplicate'
        assert retry['result'] == first['result']
        assert retry['committed_revision'] == first['committed_revision']
    assert fresh.store.read_json('state/meta.json')['revision'] == first['committed_revision']
