import json
from pathlib import Path
import pytest

from conftest import execute_hosted_production_internal, execute_production_internal, meta


def _read(root, path):
    return json.loads((Path(root) / path).read_text())


def _owner(root, ref):
    idx = _read(root, 'state/index/owner-index.json')['owners']
    route = idx[ref]
    assert '#' not in route
    return _read(root, route)




def _recursive_group_formations(root, group_ref):
    refs = []
    group_path = Path(root) / 'state/cmd/command-groups' / f'{group_ref}.json'
    group = json.loads(group_path.read_text())
    for row in group.get('units', []):
        if not isinstance(row, dict):
            continue
        if row.get('kind') == 'formation':
            refs.append(str(row['ref']))
        elif row.get('kind') == 'nested_army':
            refs.extend(_recursive_group_formations(root, str(row['ref'])))
    return refs

def _materialize(root, ref, name, location='loc_qin_eastern_depot'):
    execute_production_internal(root, 'person_materialize', {
        'state': 'qin', 'person_ref': ref, 'name': name, 'birth_date': '270-BCE-01-01',
        'role': 'command_personnel', 'source_location_ref': location,
        'representation': 'exact',
    })


def _field_unit(root, ref, commander, n=1000, composition=None, location='loc_qin_eastern_depot'):
    payload = {
        'state': 'qin', 'formation_ref': ref, 'role': 'line_infantry', 'personnel': n,
        'location_ref': location, 'commander_ref': commander,
    }
    if composition is not None:
        payload['composition'] = composition
    execute_production_internal(root, 'formation_create', payload)
    execute_production_internal(root, 'resupply', {
        'formation_ref': ref, 'war_arrows': n * 4,
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
    receipt = execute_hosted_production_internal(campaign, 'command_group_action', {
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

    # Baggage is an aggregate route burden and strategic supply is derived from
    # current world facts. Army movement must not mint/consume ration inventory or
    # create a second persistent train owner.
    assert receipt['required_wagon_equivalents'] > 0
    assert receipt.get('army_train_ref') is None
    for ref, row in zip(('formation_oplog_one', 'formation_oplog_two'), plan):
        after = _owner(campaign, ref)
        assert row['supply_condition'] in {'secure','adequate','strained','poor','critical','isolated'}
        assert 0 <= int(row['supply_score_milli']) <= 1000
        assert 'route_supply_consumed' not in after['operational_movement']


def test_arrived_forming_unit_cannot_start_deliberate_battle(campaign):
    # The eastern depot is intentionally thinner after Tang Wei/Hi Shin's
    # current deployment. Keep this artificial force within the exact manpower
    # still present there so the test reaches deployment admission rather than
    # failing on a stale 30,000-man muster assumption.
    source_location = 'loc_qin_eastern_depot'
    target_location = 'loc_kanyou'
    _materialize(campaign, 'char_oplog_army_b', 'Operational Army B', source_location)
    _materialize(campaign, 'char_oplog_attacker', 'Operational Attacker', source_location)
    _materialize(campaign, 'char_oplog_defender', 'Operational Defender', source_location)

    # Prepare the defender first and give it enough time to finish deployment.
    _field_unit(campaign, 'formation_oplog_defender', 'char_oplog_defender', 500, location=source_location)
    execute_production_internal(campaign, 'formation_move', {
        'formation_ref': 'formation_oplog_defender', 'destination_ref': target_location,
    })
    defender = _owner(campaign, 'formation_oplog_defender')
    execute_production_internal(campaign, 'advance_time', {
        'target_time': defender['operational_movement']['deployment_ready_at'],
    })

    # The attacker then arrives later and is still forming when contact is declared.
    _field_unit(campaign, 'formation_oplog_attacker', 'char_oplog_attacker', 20000, {
        'line_infantry': 15500, 'missile_crossbow': 3500, 'chariot': 1000,
    }, location=source_location)
    group_ref = 'cmdgrp.oplog.army_b'
    execute_production_internal(campaign, 'command_group_action', {
        'action': 'create', 'command_group_ref': group_ref,
        'commander_ref': 'char_oplog_army_b', 'display_name': 'Operational Army B',
    })
    execute_production_internal(campaign, 'command_group_action', {
        'action': 'attach_formation', 'command_group_ref': group_ref,
        'formation_ref': 'formation_oplog_attacker',
    })
    execute_production_internal(campaign, 'operation_create', {
        'operation_ref': 'operation_oplog_contact', 'objective': 'deployment admission test',
        'formation_refs': ['formation_oplog_attacker', 'formation_oplog_defender'], 'location_ref': target_location,
    })
    execute_production_internal(campaign, 'operation_transition', {'operation_ref': 'operation_oplog_contact', 'status': 'mobilizing'})
    execute_production_internal(campaign, 'command_group_action', {
        'action': 'move_army', 'command_group_ref': group_ref, 'location_ref': target_location,
    })
    attacker = _owner(campaign, 'formation_oplog_attacker')
    assert attacker['status'] == 'arrived_forming'
    execute_production_internal(campaign, 'operation_transition', {'operation_ref': 'operation_oplog_contact', 'status': 'active'})
    attacker = _owner(campaign, 'formation_oplog_attacker')
    assert meta(campaign)['time'] < attacker['operational_movement']['deployment_ready_at']

    with pytest.raises(ValueError, match='still deploying'):
        execute_production_internal(campaign, 'battle_resolve', {
            'attacker_formation_refs': ['formation_oplog_attacker'],
            'defender_formation_refs': ['formation_oplog_defender'],
            'operation_ref': 'operation_oplog_contact',
        })



def test_operation_army_movement_may_bring_lawful_house_auxiliaries_without_transferring_ownership(campaign):
    """A commander may bring household/House troops without turning them into Qin manpower."""
    operation_ref = 'operation_arc_131572c4e8a2892bbc'
    group_ref = 'cmdgrp.tang_wei.field_army'
    assigned_refs = [
        'formation_high_guard_qin_a', 'formation_high_guard_qin_b',
        'formation_black_banner_01a', 'formation_black_banner_01b',
        'formation_black_banner_02a', 'formation_black_banner_02b',
        'formation_black_banner_03a', 'formation_black_banner_03b',
        'formation_black_banner_04a', 'formation_black_banner_04b',
    ]
    private_refs = [
        'formation_red_lance_a', 'formation_red_lance_b',
        'formation_high_guard_infantry_01a', 'formation_high_guard_infantry_01b',
        'formation_high_guard_infantry_02a', 'formation_high_guard_infantry_02b',
        'formation_high_guard_infantry_03a', 'formation_high_guard_infantry_03b',
        'formation_high_guard_cavalry',
    ]
    expected = _recursive_group_formations(campaign, group_ref)
    assert len(expected) == 19
    assert sum(int(_owner(campaign, ref)['personnel']) for ref in expected) == 9500
    assert set(assigned_refs).issubset(expected)
    assert set(private_refs).issubset(expected)
    private_owners = {
        ref: (_owner(campaign, ref).get('administrative_owner'), _owner(campaign, ref).get('owner_force_ref'))
        for ref in private_refs
    }

    # The complete recursive 9,500-man Tang Wei Army is physically assembled at
    # the operation's exact staging location. Wei himself need not still be
    # standing there in the current save: move_army lawfully musters detached
    # command staff to the column before departure instead of teleporting them.
    # The Qin operational order legally compels the 5,000 state-owned Qin bodies,
    # while Wei may march the 4,500 House Tang auxiliaries without transferring
    # anyone's institutional ownership.
    staging_location = _read(campaign, 'state/operations/operation_arc_131572c4e8a2892bbc.json')['location_ref']
    assert {_owner(campaign, ref)['location_ref'] for ref in expected} == {staging_location}
    revision_before = int(_read(campaign, 'state/meta.json')['revision'])

    result = execute_hosted_production_internal(campaign, 'command_group_action', {
        'action': 'move_army',
        'command_group_ref': group_ref,
        'operation_ref': operation_ref,
        'location_ref': 'loc_qin_regional_02',
    }).receipt.result

    expected_set = set(expected)
    assigned_set = set(assigned_refs)
    auxiliary_set = expected_set - assigned_set
    assert result['operation_ref'] == operation_ref
    assert set(result['operation_assigned_formation_refs']) == assigned_set
    assert set(result['participating_formation_refs']) == expected_set
    assert set(result['auxiliary_formation_refs']) == auxiliary_set
    assert set(result['moved_formation_refs']) == expected_set
    assert not result['prepositioned_formation_refs']
    assert result['assembled_total_personnel'] == 9500
    assert result['command_staff_muster_hours'] > 0
    assert 'char_tang_wei' in result['command_staff_mustered']
    assert {_owner(campaign, ref)['location_ref'] for ref in expected} == {'loc_qin_regional_02'}
    assert _read(campaign, 'state/player.json')['location'] == 'loc_qin_regional_02'
    assert _owner(campaign, 'char_lin_zhen')['current_location'] == 'loc_qin_regional_02'
    assert int(_read(campaign, 'state/meta.json')['revision']) == revision_before + 1

    operation = _read(campaign, 'state/operations/operation_arc_131572c4e8a2892bbc.json')
    assert set(operation['formation_refs']) >= expected_set
    assert set(operation['auxiliary_formation_refs']) == auxiliary_set
    latest_order = operation['operational_orders'][-1]
    assert set(latest_order['applies_to_formation_refs']) == assigned_set
    for ref in private_refs:
        row = _owner(campaign, ref)
        assert (row.get('administrative_owner'), row.get('owner_force_ref')) == private_owners[ref]
