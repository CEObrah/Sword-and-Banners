from fastapi.testclient import TestClient

from sword_runtime.api.app import create_app
from sword_runtime.geography import location_chain
from sword_runtime.reconnaissance import RECON_SURFACE_COMMAND
from sword_runtime.sim.calendar import CampaignTime


def _body(context, *, request_id, command_type, payload):
    campaign = context['campaign']
    return {
        'campaign_id': campaign['campaign_id'],
        'request_id': request_id,
        'actor_id': campaign['player_id'],
        'command_type': command_type,
        'expected_revision': campaign['revision'],
        'submitted_at': campaign['world_time'],
        'payload': payload,
        'mode': 'gameplay',
    }


def _preview_execute(client, headers, body):
    preview = client.post('/v1/commands/preview', headers=headers, json=body)
    assert preview.status_code == 200, preview.text
    executed = client.post('/v1/commands/execute', headers=headers, json=body)
    assert executed.status_code == 200, executed.text
    assert executed.json()['status'] in {'committed', 'duplicate'}
    return executed.json()


def test_semantic_wait_stops_when_causal_owner_report_is_delivered(campaign):
    token = 'w' * 48
    headers = {'Authorization': f'Bearer {token}'}
    with TestClient(create_app(campaign, token)) as client:
        operations = client.app.state.campaign_operations
        context = client.get('/v1/play/context', headers=headers).json()
        player_ref = context['campaign']['player_id']
        formation_ref = 'formation_high_guard_cavalry'

        scout = next(
            row for row in operations._all_controlled_formations(player_ref)
            if row.get('formation_ref') == formation_ref
        )
        scout_location = scout['location_ref']
        region_ref = context.get('map_context', {}).get('region_ref')
        if not isinstance(region_ref, str) or region_ref not in location_chain(operations.store.read_json, scout_location):
            region_ref = next(
                ref for ref in location_chain(operations.store.read_json, scout_location)
                if ref in set(context.get('permitted_object_refs', []))
            )
        parent = next(
            row for row in context['controlled_operations']
            if formation_ref in row.get('controlled_formation_refs', [])
            and isinstance(row.get('campaign_context'), dict)
            and row['campaign_context'].get('target_state_ref')
        )
        operation_ref = parent['operation_ref']

        started = _preview_execute(
            client,
            headers,
            _body(
                context,
                request_id='semantic-wait-recon-start',
                command_type=RECON_SURFACE_COMMAND,
                payload={
                    'formation_ref': formation_ref,
                    'operation_ref': operation_ref,
                    'region_ref': region_ref,
                    'observation_hours': 2,
                },
            ),
        )
        recon_ref = started['result']['reconnaissance_ref']
        observation_due_at = started['result']['observation_due_at']

        after_start = client.get('/v1/play/context', headers=headers).json()
        _preview_execute(
            client,
            headers,
            _body(
                after_start,
                request_id='semantic-wait-recon-observation',
                command_type='advance_time',
                payload={'target_time': observation_due_at},
            ),
        )

        after_observation = client.get('/v1/play/context', headers=headers).json()
        exact_index = operations.store.read_json('state/index/military-reconnaissance.json')
        exact_path = exact_index['reconnaissance'][recon_ref]
        exact = operations.store.read_json(exact_path)
        assert exact['phase'] == 'report_in_transit'
        report_ref = exact['report_ref']
        report_index = operations.store.read_json('state/index/military-reconnaissance-reports.json')
        report_path = report_index['reports'][report_ref]
        report = operations.store.read_json(report_path)
        delivery_due = CampaignTime.parse(report['delivery_due_at'])
        requested_end = delivery_due.add_seconds(24 * 3600)

        wait_body = _body(
            after_observation,
            request_id='semantic-wait-causal-source',
            command_type='advance_time',
            payload={
                'target_time': str(requested_end),
                'stop_on_player_event': False,
                'wait_policy': {'source_refs': [recon_ref]},
            },
        )
        waited = _preview_execute(client, headers, wait_body)
        result = waited['result']
        final = client.get('/v1/play/context', headers=headers).json()

        assert final['campaign']['world_time'] == str(delivery_due)
        assert result['interrupted'] is True
        assert result['interrupt_reason'] == 'player_facing_event'
        assert result['player_facing_event_boundary'] is True
        assert result['requested_time'] == str(requested_end)
        reports = [
            row for row in final.get('known_information', [])
            if row.get('provenance') == 'military_reconnaissance'
        ]
        assert reports
        assert reports[-1]['learned_at'] == str(delivery_due)
