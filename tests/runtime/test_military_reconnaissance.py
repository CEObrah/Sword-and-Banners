from fastapi.testclient import TestClient

from sword_runtime.api.app import create_app
from sword_runtime.geography import location_chain
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner as HostedProductionPlanner
from sword_runtime.reconnaissance import (
    RECON_SURFACE_COMMAND,
    parse_reconnaissance_transport,
    reconnaissance_transport,
)
from sword_runtime.scheduler_frontier import runtime_route_integrity
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.time_integration import ProductionTimeIntegrationMixin


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


def test_reconnaissance_transport_is_strict_and_hosted_time_owner_is_unchanged():
    record = {
        'schema': 'sword-military-reconnaissance.v1',
        'surface_digest': 'a' * 64,
        'formation_ref': 'formation_scout',
        'operation_ref': 'operation_parent',
        'region_ref': 'loc_region',
        'target_state_ref': 'state_wei',
        'scout_commander_ref': 'char_scout',
        'report_to_ref': 'char_tang_wei',
        'observation_hours': 6,
    }
    encoded = reconnaissance_transport(record)
    assert parse_reconnaissance_transport(encoded) == record
    assert parse_reconnaissance_transport(encoded.replace('"observation_hours":6', '"observation_hours":0')) is None
    assert HostedProductionPlanner.mro()[1] is ProductionTimeIntegrationMixin
    assert HostedProductionPlanner._advance_runtime is ProductionTimeIntegrationMixin._advance_runtime


def test_unrouted_operation_response_fails_closed_and_recon_report_arrives(campaign):
    token = 'r' * 48
    headers = {'Authorization': f'Bearer {token}'}
    with TestClient(create_app(campaign, token)) as client:
        operations = client.app.state.campaign_operations
        context = client.get('/v1/play/context', headers=headers).json()
        campaign_state = context['campaign']
        player_ref = campaign_state['player_id']

        assert RECON_SURFACE_COMMAND in context['commands']['supported_command_types']
        contract = operations.get_command_contract(RECON_SURFACE_COMMAND)
        assert contract['accepted_payload_keys'] == [
            'formation_ref', 'observation_hours', 'operation_ref', 'region_ref'
        ]
        assert 'result' not in contract['accepted_payload_keys']
        assert contract['input_guidance']['outcome_rule'].startswith('the caller chooses only scout')

        formation_ref = 'formation_high_guard_cavalry'
        formations = operations._all_controlled_formations(player_ref)
        scout = next(row for row in formations if row.get('formation_ref') == formation_ref)
        scout_location = scout['location_ref']
        scout_commander_ref = scout['commander_ref']
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

        # Regression for issue #157: the old generic operation request must not
        # promise a response when no causal responder route exists.
        dead_end = _body(
            context,
            request_id='recon-unrouted-operation-response',
            command_type='interaction_action',
            payload={
                'target_ref': operation_ref,
                'process_ref': operation_ref,
                'formation_refs': [formation_ref],
                'action': 'request',
                'expects_response': True,
                'player_statement': 'Scout the area and report enemy formations and approach conditions.',
                'topic': 'forward reconnaissance',
            },
        )
        rejected = client.post('/v1/commands/preview', headers=headers, json=dead_end)
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()['detail']['code'] == 'interaction_response_route_unavailable'
        unchanged = client.get('/v1/play/context', headers=headers).json()
        assert unchanged['campaign']['revision'] == campaign_state['revision']

        recon = _body(
            unchanged,
            request_id='recon-causal-lifecycle',
            command_type=RECON_SURFACE_COMMAND,
            payload={
                'formation_ref': formation_ref,
                'operation_ref': operation_ref,
                'region_ref': region_ref,
                'observation_hours': 2,
            },
        )
        preview = client.post('/v1/commands/preview', headers=headers, json=recon)
        assert preview.status_code == 200, preview.text
        receipt = client.post('/v1/commands/execute', headers=headers, json=recon)
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()['status'] in {'committed', 'duplicate'}
        committed = receipt.json()['result']
        assert committed['status'] == 'active'
        assert committed['phase'] == 'observing'
        assert committed['formation_ref'] == formation_ref
        observation_due_at = committed['observation_due_at']
        recon_ref = committed['reconnaissance_ref']

        after_start = client.get('/v1/play/context', headers=headers).json()
        active = [row for row in after_start.get('active_player_processes', []) if row.get('process_ref') == recon_ref]
        assert active and active[0]['kind'] == 'military_reconnaissance'
        assert active[0]['phase'] == 'observing'
        runtime_after_start = operations.store.read_json('state/runtime.json')
        recon_hosts = [
            (host_id, host) for host_id, host in runtime_after_start.get('hosts', {}).items()
            if isinstance(host, dict) and host.get('reconnaissance_ref') == recon_ref
        ]
        assert len(recon_hosts) == 1, recon_hosts
        recon_host_id, recon_host = recon_hosts[0]
        assert recon_host['kind'] == 'military_reconnaissance'
        assert recon_host['next_due'] == observation_due_at
        recon_events = [
            row for row in runtime_after_start.get('events', [])
            if isinstance(row, dict) and row.get('target_host') == recon_host_id
        ]
        assert len(recon_events) == 1, recon_events
        assert recon_events[0]['due_at'] == observation_due_at
        integrity = runtime_route_integrity(runtime_after_start)
        assert integrity['complete'], integrity

        # Observation completion is a causal process boundary, not a delivered
        # player-facing event. Advance to that exact instant without asking the
        # semantic wait layer to stop on unrelated operation traffic.
        observe_wait = _body(
            after_start,
            request_id='recon-await-observation',
            command_type='advance_time',
            payload={'target_time': observation_due_at},
        )
        wait_preview = client.post('/v1/commands/preview', headers=headers, json=observe_wait)
        assert wait_preview.status_code == 200, wait_preview.text
        observed = client.post('/v1/commands/execute', headers=headers, json=observe_wait)
        assert observed.status_code == 200, observed.text
        assert observed.json()['status'] in {'committed', 'duplicate'}

        after_observation = client.get('/v1/play/context', headers=headers).json()
        assert after_observation['campaign']['world_time'] == observation_due_at, observed.json()['result']
        in_transit = [row for row in after_observation.get('active_player_processes', []) if row.get('process_ref') == recon_ref]
        assert in_transit and in_transit[0]['phase'] == 'report_in_transit', {
            'active': in_transit,
            'advance_result': observed.json()['result'],
            'runtime': operations.store.read_json('state/runtime.json'),
        }
        assert not [
            row for row in after_observation.get('known_information', [])
            if row.get('provenance') == 'military_reconnaissance'
        ]

        exact_index = operations.store.read_json('state/index/military-reconnaissance.json')
        exact_path = exact_index['reconnaissance'][recon_ref]
        exact = operations.store.read_json(exact_path)
        assert exact['report_dispatched_at'] == after_observation['campaign']['world_time']
        assert exact['courier_origin_ref'] == scout_location
        assert exact['report_target_location_ref'] == after_observation['player']['location']
        information_ref = exact['report_information_ref']
        info_path = operations.store.read_json('state/information/index.json')['claims'][information_ref]
        commander_report = operations.store.read_json(info_path)
        assert commander_report['knowers'] == [scout_commander_ref]
        assert player_ref not in commander_report['knowers']

        courier_hours = operations.runtime.planner._route_travel_hours(
            exact['courier_origin_ref'],
            exact['report_target_location_ref'],
            modes=('courier',),
        )
        assert courier_hours > 0
        delivery_due = CampaignTime.parse(exact['report_dispatched_at']).add_seconds(courier_hours * 3600)
        delivery_wait = _body(
            after_observation,
            request_id='recon-await-delivery',
            command_type='advance_time',
            payload={
                'target_time': str(delivery_due),
                'stop_on_player_event': True,
                'wait_policy': {
                    'event_kinds': ['military_reconnaissance_report'],
                    'operation_refs': [operation_ref],
                    'topic_terms': ['reconnaissance'],
                },
            },
        )
        delivery_preview = client.post('/v1/commands/preview', headers=headers, json=delivery_wait)
        assert delivery_preview.status_code == 200, delivery_preview.text
        delivered = client.post('/v1/commands/execute', headers=headers, json=delivery_wait)
        assert delivered.status_code == 200, delivered.text
        assert delivered.json()['status'] in {'committed', 'duplicate'}

        final = client.get('/v1/play/context', headers=headers).json()
        reports = [
            row for row in final.get('known_information', [])
            if row.get('provenance') == 'military_reconnaissance'
        ]
        assert reports, final.get('known_information')
        assert reports[-1]['classification'] == 'command_intelligence'
        assert reports[-1]['world_truth_authority'] is False
        assert 'Forward reconnaissance' in reports[-1]['claim']
        assert not [row for row in final.get('active_player_processes', []) if row.get('process_ref') == recon_ref]

        exact = operations.store.read_json(exact_path)
        assert exact['status'] == 'completed'
        assert exact['report_delivered_at'] == final['campaign']['world_time']
        assert exact['report_information_ref'] == reports[-1]['information_ref']
        delivered_report = operations.store.read_json(info_path)
        assert player_ref in delivered_report['knowers']
        delivery = delivered_report['deliveries'][-1]
        assert delivery['source_location_ref'] == scout_location
        assert delivery['target_location_ref'] == final['player']['location']
        assert delivery['travel_hours'] == courier_hours
