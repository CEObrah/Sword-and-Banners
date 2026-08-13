import pytest
from fastapi.testclient import TestClient

from conftest import meta
from sword_runtime.api.interaction_surface import (
    INTERACTION_ATTEMPT_PREFIX,
    parse_interaction_attempt_summary,
    translate_interaction_command,
    triggered_interaction_handles,
    triggered_interaction_page,
    validate_interaction_payload,
)
from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS
from sword_runtime.commands import CommandEnvelope


class _FakeStore:
    def __init__(self, registry):
        self.registry = registry

    def read_json(self, path):
        if path == 'state/event/events-messages-and-movement.json':
            return self.registry
        raise FileNotFoundError(path)


def _command(payload, *, request_id='interaction-test'):
    return CommandEnvelope(
        campaign_id='campaign',
        request_id=request_id,
        actor_id='char_tang_wei',
        command_type='interaction_action',
        expected_revision=7,
        submitted_at='245-BCE-12-05T06:22:48+08:00',
        payload=payload,
        mode='gameplay',
    )


def test_interaction_action_is_surface_only_and_frozen_arrays_validate():
    assert 'interaction_action' not in COMMAND_PAYLOAD_KEYS
    assert 'scene_consequence' in COMMAND_PAYLOAD_KEYS
    command = _command({
        'target_ref': 'loc_kanyou',
        'action': 'seek_contact',
        'formation_refs': ['formation_tang_champions_first'],
        'posture': 'Seek lawful contact without forcing access.',
    })
    validated = validate_interaction_payload(command.payload)
    assert validated['formation_refs'] == ['formation_tang_champions_first']
    translated = translate_interaction_command(command)
    assert translated.command_type == 'scene_consequence'
    summary = translated.to_record()['payload']['summary']
    assert summary.startswith(INTERACTION_ATTEMPT_PREFIX)
    attempt = parse_interaction_attempt_summary(summary)
    assert attempt['surface_digest'] == command.digest
    assert attempt['world_response_status'] == 'not_established_by_attempt'


def test_interaction_surface_rejects_outcome_injection_and_control_breaks():
    with pytest.raises(ValueError, match='world or NPC outcomes'):
        validate_interaction_payload({
            'target_ref': 'loc_kanyou',
            'action': 'seek_contact',
            'posture': {'outcome': 'Qin appoints Tang Wei'},
        })
    with pytest.raises(ValueError, match='player_statement is invalid'):
        validate_interaction_payload({
            'target_ref': 'loc_kanyou',
            'action': 'seek_contact',
            'player_statement': 'first line\nsecond line',
        })
    with pytest.raises(ValueError, match='target_ref is invalid'):
        validate_interaction_payload({'target_ref': '../state/player.json', 'action': 'seek_contact'})


def test_surface_digest_survives_translation_for_strict_idempotency():
    first = _command(
        {'target_ref': 'loc_kanyou', 'action': 'seek_contact', 'player_statement': 'Present the summons.'},
        request_id='same-request',
    )
    second = _command(
        {'target_ref': 'loc_kanyou', 'action': 'seek_contact', 'player_statement': ' Present the summons. '},
        request_id='same-request',
    )
    assert first.digest != second.digest
    assert translate_interaction_command(first).digest != translate_interaction_command(second).digest


def test_interaction_handle_window_has_count_and_cursor_continuation():
    causal = {}
    for index in range(11):
        ref = f'event_interaction_{index:02d}'
        causal[ref] = {
            'event_ref': ref,
            'kind': 'institutional_response',
            'status': 'triggered',
            'triggered_at': f'245-BCE-12-05T{index:02d}:00:00+08:00',
            'summary': f'response {index}',
        }
    store = _FakeStore({'causal_events': causal})
    hot, count = triggered_interaction_handles(store, limit=3)
    assert count == 11
    assert [x['interaction_ref'] for x in hot] == [
        'event_interaction_08', 'event_interaction_09', 'event_interaction_10'
    ]
    page = triggered_interaction_page(store, cursor='3', limit=4)
    assert page['count'] == 11
    assert page['returned'] == 4
    assert page['next_cursor'] == '7'
    assert page['interaction_handles'][0]['interaction_ref'] == 'event_interaction_07'


def test_rest_surface_blocks_new_raw_scene_consequence_and_commits_attempt_only(campaign):
    from sword_runtime.api.app import create_app

    token = 'i' * 48
    headers = {'Authorization': f'Bearer {token}'}
    with TestClient(create_app(campaign, token)) as client:
        context = client.get('/v1/play/context', headers=headers).json()
        assert 'interaction_action' in context['commands']['supported_command_types']
        assert 'scene_consequence' not in context['commands']['supported_command_types']
        before = context['campaign']

        raw = {
            'campaign_id': before['campaign_id'],
            'request_id': 'raw-scene-write-rejected',
            'actor_id': before['player_id'],
            'command_type': 'scene_consequence',
            'expected_revision': before['revision'],
            'submitted_at': before['world_time'],
            'payload': {'summary': 'Qin grants an unsupported appointment.'},
            'mode': 'gameplay',
        }
        preview = client.post('/v1/commands/preview', headers=headers, json=raw)
        execute = client.post('/v1/commands/execute', headers=headers, json=raw)
        assert preview.status_code == 422
        assert execute.status_code == 422
        assert preview.json()['detail']['code'] == 'legacy_scene_consequence_not_player_authored'
        assert execute.json()['detail']['code'] == 'legacy_scene_consequence_not_player_authored'

        attempt = {
            'campaign_id': before['campaign_id'],
            'request_id': 'safe-seek-contact',
            'actor_id': before['player_id'],
            'command_type': 'interaction_action',
            'expected_revision': before['revision'],
            'submitted_at': before['world_time'],
            'payload': {
                'target_ref': context['player']['location'],
                'action': 'seek_contact',
                'posture': 'Seek the lawful receiving channel without forcing access or claiming Qin office.',
            },
            'mode': 'gameplay',
        }
        preview = client.post('/v1/commands/preview', headers=headers, json=attempt)
        assert preview.status_code == 200
        assert preview.json()['surface_command_type'] == 'interaction_action'
        assert preview.json()['world_response_status'] == 'not_established_by_attempt'

        receipt = client.post('/v1/commands/execute', headers=headers, json=attempt)
        assert receipt.status_code == 200
        assert receipt.json()['status'] in {'committed', 'duplicate'}
        assert receipt.json()['surface_command_type'] == 'interaction_action'

        after = client.get('/v1/play/context', headers=headers).json()
        assert after['campaign']['revision'] == before['revision'] + 1
        assert after['campaign']['world_time'] == before['world_time']
        assert after['scene']['projection_status'] == 'fresh_runtime_projection'
        assert after['scene']['projected_revision'] == after['campaign']['revision']
        latest = after['recent_interaction_attempts'][0]
        assert latest['request_id'] == 'safe-seek-contact'
        assert latest['action'] == 'seek_contact'
        assert latest['world_response_status'] == 'not_established_by_attempt'


def test_exact_legacy_scene_duplicate_remains_recoverable(campaign):
    from sword_runtime.api.app import create_app
    from sword_runtime.engine import SwordRuntime

    before = meta(campaign)
    legacy = CommandEnvelope(
        campaign_id=before['campaign_id'],
        request_id='legacy-scene-duplicate',
        actor_id=before['player_id'],
        command_type='scene_consequence',
        expected_revision=before['revision'],
        submitted_at=before['time'],
        payload={'summary': 'legacy attempt record'},
        mode='gameplay',
    )
    first = SwordRuntime(campaign).execute(legacy)
    assert first.status == 'committed'

    token = 'd' * 48
    body = {
        'campaign_id': legacy.campaign_id,
        'request_id': legacy.request_id,
        'actor_id': legacy.actor_id,
        'command_type': legacy.command_type,
        'expected_revision': legacy.expected_revision,
        'submitted_at': legacy.submitted_at,
        'payload': {'summary': 'legacy attempt record'},
        'mode': legacy.mode,
    }
    with TestClient(create_app(campaign, token)) as client:
        response = client.post(
            '/v1/commands/execute',
            headers={'Authorization': f'Bearer {token}'},
            json=body,
        )
    assert response.status_code == 200
    assert response.json()['status'] == 'duplicate'
