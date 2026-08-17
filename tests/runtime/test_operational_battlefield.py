import json
from pathlib import Path

from conftest import activate_operation, execute, execute_internal, prepare_field_formation
from sword_runtime.sim.calendar import CampaignTime


def _operation(root: Path, operation_ref: str):
    index = json.load(open(root / 'state/operations/index.json'))['operations']
    return json.load(open(root / index[operation_ref]))


def test_persistent_battlefield_redeployment_and_delayed_contact_report(campaign):
    enemy = 'formation_qin_battlefield_enemy'
    execute_internal(campaign, 'formation_create', {
        'state': 'zhao', 'formation_ref': enemy, 'role': 'line_infantry', 'personnel': 600,
        'commander_ref': 'char_bananji',
    })
    prepare_field_formation(campaign, enemy, 'loc_kanyou')

    champion = 'formation_tang_champions_first'
    op = activate_operation(campaign, 'operation_live_battlefield', [champion, enemy], location='loc_kanyou')
    battlefield = 'battlefield_live_test'
    execute(campaign, 'battlefield_control', {
        'action': 'open', 'operation_ref': op, 'battlefield_ref': battlefield,
        'name': 'Kanyou Field Exercise', 'side_refs': ['state_qin', 'state_zhao'],
        'layout_ref': 'battlefield.layout.line_three',
    })
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


def test_battle_contact_must_match_saved_operational_sector(campaign):
    enemy = 'formation_qin_battlefield_guard'
    execute_internal(campaign, 'formation_create', {
        'state': 'zhao', 'formation_ref': enemy, 'role': 'line_infantry', 'personnel': 300,
        'commander_ref': 'char_bananji',
    })
    prepare_field_formation(campaign, enemy, 'loc_kanyou')
    champion = 'formation_tang_champions_first'
    op = activate_operation(campaign, 'operation_sector_validation', [champion, enemy], location='loc_kanyou')
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
