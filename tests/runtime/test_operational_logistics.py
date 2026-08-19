import json
from pathlib import Path
import pytest

from conftest import execute_production_internal, meta


def _read(root, path):
    return json.loads((Path(root) / path).read_text())


def _owner(root, ref):
    idx = _read(root, 'state/index/owner-index.json')['owners']
    route = idx[ref]
    assert '#' not in route
    return _read(root, route)


def _materialize(root, ref, name, location='loc_qin_eastern_depot'):
    execute_production_internal(root, 'person_materialize', {
        'state': 'qin', 'person_ref': ref, 'name': name, 'birth_date': '270-BCE-01-01',
        'role': 'command_personnel', 'source_location_ref': location,
        'representation': 'exact',
    })


def _field_unit(root, ref, commander, n=1000, composition=None):
    payload = {
        'state': 'qin', 'formation_ref': ref, 'role': 'line_infantry', 'personnel': n,
        'location_ref': 'loc_qin_eastern_depot', 'commander_ref': commander,
    }
    if composition is not None:
        payload['composition'] = composition
    execute_production_internal(root, 'formation_create', payload)
    execute_production_internal(root, 'resupply', {
        'formation_ref': ref, 'food_kg': n * 20, 'fodder_kg': n * 10, 'war_arrows': n * 4,
    })
    execute_production_internal(root, 'formation_mobilize', {'formation_ref': ref})


def test_recursive_army_movement_uses_ordered_units_and_physical_deployment(campaign):
    _materialize(campaign, 'char_oplog_army', 'Operational Army Commander')
    _materialize(campaign, 'char_oplog_one', 'Operational Unit One')
    _materialize(campaign, 'char_oplog_two', 'Operational Unit Two')
    _field_unit(campaign, 'formation_oplog_one', 'char_oplog_one')
    _field_unit(campaign, 'formation_oplog_two', 'char_oplog_two')

    group_ref = 'cmdgrp.oplog.army'
    execute_production_internal(campaign, 'command_group_action', {
        'action': 'create', 'command_group_ref': group_ref,
        'commander_ref': 'char_oplog_army', 'display_name': 'Operational Test Army',
    })
    for ref in ('formation_oplog_one', 'formation_oplog_two'):
        execute_production_internal(campaign, 'command_group_action', {
            'action': 'attach_formation', 'command_group_ref': group_ref, 'formation_ref': ref,
        })

    before_time = meta(campaign)['time']
    receipt = execute_production_internal(campaign, 'command_group_action', {
        'action': 'move_army', 'command_group_ref': group_ref, 'location_ref': 'loc_kanyou',
    }).receipt.result
    assert receipt['origin_ref'] == 'loc_qin_eastern_depot'
    assert receipt['destination_ref'] == 'loc_kanyou'
    assert receipt['formation_count'] == 2
    plan = receipt['operational_plan']['ordered_units']
    assert [r['formation_ref'] for r in plan] == ['formation_oplog_one', 'formation_oplog_two']
    assert plan[1]['departure_offset_hours'] >= plan[0]['departure_offset_hours']
    assert meta(campaign)['time'] != before_time

    first = _owner(campaign, 'formation_oplog_one')
    second = _owner(campaign, 'formation_oplog_two')
    assert first['location_ref'] == second['location_ref'] == 'loc_kanyou'
    assert first['operational_movement']['road_column_order'] == 1
    assert second['operational_movement']['road_column_order'] == 2
    assert second['operational_movement']['deployment_ready_at'] >= second['operational_movement']['tail_arrived_at']
    assert second['status'] == 'arrived_forming'


def test_arrived_forming_unit_cannot_start_deliberate_battle(campaign):
    _materialize(campaign, 'char_oplog_army_b', 'Operational Army B')
    _materialize(campaign, 'char_oplog_attacker', 'Operational Attacker')
    _materialize(campaign, 'char_oplog_defender', 'Operational Defender')

    # Prepare the defender first and give it enough time to finish deployment.
    _field_unit(campaign, 'formation_oplog_defender', 'char_oplog_defender', 500)
    execute_production_internal(campaign, 'formation_move', {
        'formation_ref': 'formation_oplog_defender', 'destination_ref': 'loc_kanyou',
    })
    defender = _owner(campaign, 'formation_oplog_defender')
    execute_production_internal(campaign, 'advance_time', {
        'target_time': defender['operational_movement']['deployment_ready_at'],
    })

    # The attacker then arrives later and is still forming when contact is declared.
    _field_unit(campaign, 'formation_oplog_attacker', 'char_oplog_attacker', 30000, {
        'line_infantry': 15000, 'missile_crossbow': 6000, 'cavalry': 3000,
        'chariot': 1000, 'logistics': 2000, 'siege_engineering': 1000, 'signal': 2000,
    })
    group_ref = 'cmdgrp.oplog.army_b'
    execute_production_internal(campaign, 'command_group_action', {
        'action': 'create', 'command_group_ref': group_ref,
        'commander_ref': 'char_oplog_army_b', 'display_name': 'Operational Army B',
    })
    execute_production_internal(campaign, 'command_group_action', {
        'action': 'attach_formation', 'command_group_ref': group_ref,
        'formation_ref': 'formation_oplog_attacker',
    })
    execute_production_internal(campaign, 'command_group_action', {
        'action': 'move_army', 'command_group_ref': group_ref, 'location_ref': 'loc_kanyou',
    })
    attacker = _owner(campaign, 'formation_oplog_attacker')
    assert attacker['status'] == 'arrived_forming'

    execute_production_internal(campaign, 'operation_create', {
        'operation_ref': 'operation_oplog_contact', 'objective': 'deployment admission test',
        'formation_refs': ['formation_oplog_attacker', 'formation_oplog_defender'], 'location_ref': 'loc_kanyou',
    })
    execute_production_internal(campaign, 'operation_transition', {'operation_ref': 'operation_oplog_contact', 'status': 'mobilizing'})
    execute_production_internal(campaign, 'operation_transition', {'operation_ref': 'operation_oplog_contact', 'status': 'active'})
    with pytest.raises(ValueError, match='still deploying'):
        execute_production_internal(campaign, 'battle_resolve', {
            'attacker_formation_refs': ['formation_oplog_attacker'],
            'defender_formation_refs': ['formation_oplog_defender'],
            'operation_ref': 'operation_oplog_contact',
        })

