import json
import subprocess
from pathlib import Path

from conftest import activate_operation, execute, execute_internal
from sword_runtime.sim.calendar import CampaignTime


def _operation(root: Path, operation_ref: str):
    index = json.load(open(root / 'state/operations/index.json'))['operations']
    return json.load(open(root / index[operation_ref]))


def _co_locate_formations_direct(campaign, formation_refs, location_ref: str) -> None:
    """Prepare existing conserved formations for an operational-layer test.

    Formation creation, mobilization logistics, and strategic movement are verified
    by their own suites. Battlefield tests only need exact saved formations at the
    contact site, so the disposable fixture may co-locate those owners in one commit.
    """
    owners = json.load(open(campaign / 'state/index/owner-index.json'))['owners']
    touched = []
    for ref in formation_refs:
        formation_path = campaign / owners[ref]
        formation = json.load(open(formation_path))
        formation['location_ref'] = location_ref
        formation['mobilized'] = True
        formation['status'] = 'ready'
        formation.setdefault('logistics', {})['food_kg'] = max(
            int(formation.get('logistics', {}).get('food_kg', 0)),
            max(1000, int(formation.get('personnel', 0)) * 2),
        )
        formation_path.write_text(json.dumps(formation, ensure_ascii=False, indent=2) + '\n')
        touched.append(str(formation_path.relative_to(campaign)))
    subprocess.run(['git', '-C', str(campaign), 'add', *touched], check=True)
    subprocess.run(['git', '-C', str(campaign), 'commit', '--quiet', '-m', 'test: operational battlefield fixture'], check=True)



def test_persistent_battlefield_redeployment_and_delayed_contact_report(campaign):
    enemy = 'formation_zhao_border_line'
    champion = 'formation_tang_champions_first'
    owner_index = json.load(open(campaign / 'state/index/owner-index.json'))['owners']
    battlefield_location = json.load(open(campaign / owner_index[champion]))['location_ref']
    _co_locate_formations_direct(campaign, [champion, enemy], battlefield_location)

    op = activate_operation(campaign, 'operation_live_battlefield', [champion, enemy], location=battlefield_location)
    battlefield = 'battlefield_live_test'
    execute(campaign, 'battlefield_control', {
        'action': 'open', 'operation_ref': op, 'battlefield_ref': battlefield,
        'name': 'Kanyou Field Exercise', 'side_refs': ['state_qin', 'state_zhao'],
        'layout_ref': 'battlefield.layout.line_three',
    })
    op_index = json.load(open(campaign / 'state/operations/index.json'))
    assert op in op_index['active_battlefield_operation_refs']
    execute(campaign, 'battlefield_control', {
        'action': 'assign', 'operation_ref': op, 'battlefield_ref': battlefield,
        'formation_ref': champion, 'side_ref': 'state_qin',
        'sector_ref': battlefield + '.sector.reserve', 'order': 'reserve',
    })
    execute_internal(campaign, 'battlefield_control', {
        'action': 'assign', 'operation_ref': op, 'battlefield_ref': battlefield,
        'formation_ref': enemy, 'side_ref': 'state_zhao',
        'sector_ref': battlefield + '.sector.left', 'order': 'hold',
    })
    execute(campaign, 'battlefield_control', {
        'action': 'redeploy', 'operation_ref': op, 'battlefield_ref': battlefield,
        'formation_ref': champion, 'target_sector_ref': battlefield + '.sector.left',
        'pace': 'forced', 'order': 'attack',
    })

    doc = _operation(campaign, op)
    assignment = doc['battlefields'][battlefield]['assignments'][champion]
    assert assignment['status'] == 'redeploying'
    assert champion not in doc['battlefields'][battlefield]['sectors'][battlefield + '.sector.reserve']['formation_refs']
    eta = CampaignTime.parse(assignment['leg_eta_at'])
    requested = eta.add_seconds(7200)

    result = execute(campaign, 'advance_time', {'target_time': str(requested)}).receipt.result
    assert result['world_time'] <= str(requested)
    doc = _operation(campaign, op)
    assignment = doc['battlefields'][battlefield]['assignments'][champion]
    assert assignment['status'] == 'holding'
    assert assignment['sector_ref'] == battlefield + '.sector.left'
    assert champion in doc['battlefields'][battlefield]['sectors'][battlefield + '.sector.left']['formation_refs']
    assert any(row.get('level') == 'contact' and row.get('status') == 'delivered' for row in doc['battlefields'][battlefield]['reports'])
    assert result['battlefield_reports']
    assert result['interrupted'] is True
    execute(campaign, 'battlefield_control', {
        'action': 'close', 'operation_ref': op, 'battlefield_ref': battlefield,
    })
    op_index = json.load(open(campaign / 'state/operations/index.json'))
    assert op not in op_index['active_battlefield_operation_refs']


def test_battle_contact_must_match_saved_operational_sector(campaign):
    enemy = 'formation_zhao_border_line'
    champion = 'formation_tang_champions_first'
    owner_index = json.load(open(campaign / 'state/index/owner-index.json'))['owners']
    battlefield_location = json.load(open(campaign / owner_index[champion]))['location_ref']
    _co_locate_formations_direct(campaign, [champion, enemy], battlefield_location)
    op = activate_operation(campaign, 'operation_sector_validation', [champion, enemy], location=battlefield_location)
    battlefield = 'battlefield_sector_validation'
    execute(campaign, 'battlefield_control', {
        'action': 'open', 'operation_ref': op, 'battlefield_ref': battlefield,
        'name': 'Sector Validation', 'side_refs': ['state_qin', 'state_zhao'],
        'layout_ref': 'battlefield.layout.line_three',
    })
    execute(campaign, 'battlefield_control', {
        'action': 'assign', 'operation_ref': op, 'battlefield_ref': battlefield,
        'formation_ref': champion, 'side_ref': 'state_qin',
        'sector_ref': battlefield + '.sector.left', 'order': 'hold',
    })
    execute_internal(campaign, 'battlefield_control', {
        'action': 'assign', 'operation_ref': op, 'battlefield_ref': battlefield,
        'formation_ref': enemy, 'side_ref': 'state_zhao',
        'sector_ref': battlefield + '.sector.right', 'order': 'hold',
    })
    import pytest
    with pytest.raises(Exception):
        execute_internal(campaign, 'battle_resolve', {
            'attacker_formation_refs': [champion], 'defender_formation_refs': [enemy],
            'operation_ref': op, 'battlefield_ref': battlefield,
            'sector_ref': battlefield + '.sector.left', 'objective': 'invalid remote contact',
        })


def test_exact_gate_and_operational_object_consequences_are_persisted_without_transferring_sovereignty(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    enemy = 'formation_zhao_border_line'
    champion = 'formation_tang_champions_first'
    gate = 'loc_sword_manor_outer_gate'

    _co_locate_formations_direct(campaign, [champion, enemy], gate)
    op = activate_operation(campaign, 'operation_gate_object_test', [champion, enemy], location=gate)
    battlefield = 'battlefield_gate_object_test'
    execute(campaign, 'battlefield_control', {
        'action': 'open', 'operation_ref': op, 'battlefield_ref': battlefield,
        'name': 'Outer Gate Contact', 'side_refs': ['state_qin', 'state_zhao'],
        'layout_ref': 'battlefield.layout.line_three',
    })
    center = battlefield + '.sector.center'
    execute(campaign, 'battlefield_control', {
        'action': 'assign', 'operation_ref': op, 'battlefield_ref': battlefield,
        'formation_ref': champion, 'side_ref': 'state_qin', 'sector_ref': center, 'order': 'attack',
    })
    execute_internal(campaign, 'battlefield_control', {
        'action': 'assign', 'operation_ref': op, 'battlefield_ref': battlefield,
        'formation_ref': enemy, 'side_ref': 'state_zhao', 'sector_ref': center, 'order': 'hold',
    })
    planner = RepositoryCommandPlanner(campaign)
    consequences = planner._battlefield_apply_battle_result(
        operation_ref=op, battlefield_ref=battlefield, sector_ref=center,
        attacker_refs=[champion], defender_refs=[enemy], winner='attacker',
        event_id='battle_gate_object_test', at=planner._world_time(),
        hero_object_pressure={'officer_pressure': 35.0, 'cohesion_shock_pressure': 45.0, 'artillery_pressure': 50.0},
        local_breach_summary={'breached_sector_count': 1},
    )
    op_path = planner.read('state/operations/index.json')['operations'][op]
    doc = planner.read(op_path)
    bf = doc['battlefields'][battlefield]
    assert any(row['kind'] == 'exact_gate_seized' and row['object_ref'] == gate for row in consequences)
    assert bf['tactical_object_control'][gate]['held_by_side_ref'] == 'state_qin'
    assert any(row['kind'] == 'exact_signal_network_disrupted' for row in consequences)
    artillery = next(row for row in consequences if row['kind'] == 'exact_fixed_artillery_neutralized')
    art_doc = planner.read(planner.owner_path(artillery['object_ref']))
    assert float(art_doc['condition']['condition_percent']) < 100.0
    # Tactical gate possession is deliberately contained in the battle owner.
    # It may not rewrite strategic/territorial control by itself.
    territory = json.load(open(campaign / 'state/territory/control.json'))
    gate_row = territory.get('sites', {}).get(gate, {})
    assert 'held_by_side_ref' not in gate_row


def test_exact_bridge_binding_requires_saved_materialized_crossing_route(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    battlefield = {
        'location_ref': 'loc_retsubi',
        'sectors': {'battlefield_bridge.sector.center': {'name': 'Center'}},
    }
    bindings = planner._battlefield_exact_object_bindings(
        {'location_ref': 'loc_retsubi', 'route_refs': ['route_retsubi_gyou']}, battlefield
    )
    assert {'kind': 'bridge_crossing', 'object_ref': 'route_retsubi_gyou', 'sector_ref': 'battlefield_bridge.sector.center'} in bindings
    no_guess = planner._battlefield_exact_object_bindings(
        {'location_ref': 'loc_retsubi', 'route_refs': []}, battlefield
    )
    assert not any(row['kind'] == 'bridge_crossing' for row in no_guess)


def test_empty_battlefield_routing_does_not_scan_strategic_operation_owners(campaign):
    from copy import deepcopy
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    index = deepcopy(planner.read('state/operations/index.json'))
    index.setdefault('operations', {})['operation_should_not_be_read'] = 'state/operations/does-not-exist.json'
    index['active_battlefield_operation_refs'] = []
    planner.put('state/operations/index.json', index)
    start = planner._world_time()
    result = planner._settle_operational_battlefields(start, start.add_seconds(30 * 86400))
    assert result['changed'] is False
    assert result['reviews'] == []
    assert result['delivered_reports'] == []


def test_battlefield_boundary_order_uses_bce_chronology_not_timestamp_text(campaign):
    from copy import deepcopy
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    index = deepcopy(planner.read('state/operations/index.json'))
    operation_ref = 'operation_bce_boundary_order_test'
    operation_path = 'state/operations/bce-boundary-order-test.json'
    index.setdefault('operations', {})[operation_ref] = operation_path
    index.setdefault('active_battlefield_operation_refs', []).append(operation_ref)
    planner.put('state/operations/index.json', index)
    planner.put(operation_path, {
        'schema': 'sword-operation',
        'operation_ref': operation_ref,
        'status': 'active',
        'battlefields': {
            'battlefield_bce_boundary_order_test': {
                'status': 'active',
                'side_refs': [],
                'sectors': {},
                'reports': [],
                'assignments': {
                    'formation_later': {
                        'status': 'redeploying',
                        'leg_eta_at': '243-BCE-01-01T01:00:00+08:00',
                    },
                    'formation_earlier': {
                        'status': 'redeploying',
                        'leg_eta_at': '244-BCE-12-31T23:00:00+08:00',
                    },
                },
            }
        },
    })
    boundary, detail = planner._battlefield_next_boundary_time(
        CampaignTime.parse('244-BCE-12-31T22:00:00+08:00'),
        CampaignTime.parse('243-BCE-01-01T02:00:00+08:00'),
    )
    assert str(boundary) == '244-BCE-12-31T23:00:00+08:00'
    assert detail['formation_ref'] == 'formation_earlier'
