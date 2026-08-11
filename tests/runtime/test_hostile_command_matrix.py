import json
import pytest

from conftest import execute, execute_internal, meta
from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS


def test_every_semantic_command_has_a_fail_closed_hostile_case(campaign):
    """Every public semantic command must fail closed on one hostile boundary case.

    This is intentionally a coverage matrix, not a substitute for the deeper causal
    tests.  It prevents new commands from entering the Gold surface with no hostile
    admission test at all.
    """
    champion = 'formation_tang_champions_first'
    cases = {
        'advance_time': {'hours': 0},
        'battle_resolve': {'attacker_formation_refs': [], 'defender_formation_refs': [champion]},
        'career_event': {'person_ref': 'char_does_not_exist', 'kind': 'merit', 'merit': 1},
        'cohort_training': {'hours': 0},
        'command_assign': {'formation_ref': champion, 'commander_ref': 'char_does_not_exist'},
        'command_transfer': {'formation_ref': champion, 'commander_ref': 'char_does_not_exist'},
        'economy_transfer': {'state': 'qin', 'direction': 'player_to_state', 'amount_silver': 0},
        'enlisted_service_pay': {'state': 'qin', 'amount_silver': 0},
        'equipment_consume': {'item_key': 'item_does_not_exist', 'quantity': 1},
        'equipment_drop': {'item_key': 'item_does_not_exist', 'quantity': 1},
        'equipment_equip': {'item_key': 'item_does_not_exist', 'quantity': 1},
        'equipment_issue': {'item_key': 'item_does_not_exist', 'quantity': 1, 'target_ref': 'char_shen_rui'},
        'equipment_loot': {'item_key': 'item_does_not_exist', 'quantity': 1},
        'equipment_return': {'item_key': 'item_does_not_exist', 'quantity': 1, 'target_ref': 'char_shen_rui'},
        'equipment_transfer': {'item_key': 'item_does_not_exist', 'quantity': 1, 'target_ref': 'char_shen_rui'},
        'equipment_unequip': {'item_key': 'item_does_not_exist', 'quantity': 1},
        'family_event': {'house_ref': 'house_tang', 'kind': 'proposal', 'person_ref': 'char_tang_wei', 'partner_ref': 'char_does_not_exist'},
        'force_assignment': {'formation_ref': champion, 'commander_ref': 'char_does_not_exist'},
        'formation_assign': {'formation_ref': champion, 'commander_ref': 'char_does_not_exist'},
        'formation_create': {'state': 'qin', 'formation_ref': 'formation_hostile', 'role': 'line_infantry', 'personnel': 0},
        'formation_demobilize': {'formation_ref': 'formation_does_not_exist'},
        'formation_dissolve': {'formation_ref': 'formation_does_not_exist'},
        'formation_doctrine_set': {'formation_ref': champion, 'doctrine_ref': 'doc.does_not_exist', 'doctrine_behavior': {}},
        'formation_merge': {'formation_refs': []},
        'formation_mobilize': {'formation_ref': 'formation_does_not_exist'},
        'formation_move': {'formation_ref': champion, 'destination_ref': 'loc_does_not_exist'},
        'formation_reconstitute': {'formation_ref': champion, 'target_personnel': 0},
        'formation_split': {'formation_ref': champion, 'personnel': 0, 'new_formation_ref': 'formation_hostile_split'},
        'formation_train': {'formation_ref': champion, 'hours': 0},
        'formation_training_set': {'formation_ref': champion, 'training_ref': 'train.does_not_exist'},
        'fortification_materialize': {'fortification_ref': 'fort_hostile', 'location_ref': 'loc_does_not_exist', 'garrison_formation_refs': [champion]},
        'health_injury': {'severity': 'fatal'},
        'health_recovery': {'hours': 0},
        'house_action': {'house_ref': 'house_tang', 'action': 'teleport_estate'},
        'individual_training': {'focus': 'Formation Command', 'hours': 0},
        'information_create': {'information_ref': 'info_hostile', 'claim': 'ghost report', 'knowers': ['char_does_not_exist']},
        'information_deliver': {'information_ref': 'info_does_not_exist', 'target_ref': 'char_does_not_exist'},
        'institution_project': {'institution_ref': 'inst_qin_fortification_bureau', 'project_ref': 'project_hostile', 'duration_hours': 0},
        'market_purchase': {'item_key': 'common_sword', 'quantity': 0},
        'market_sell': {'item_key': 'common_sword', 'quantity': 0},
        'mercenary_contract': {'mercenary_ref': 'merc.major.01', 'action': 'offer', 'amount_silver': 0, 'term_days': 90},
        'operation_create': {'operation_ref': 'operation_hostile', 'formation_refs': [], 'location_ref': 'loc_kankoku_pass'},
        'operation_transition': {'operation_ref': 'operation_does_not_exist', 'status': 'active'},
        'person_materialize': {'state': 'qin', 'person_ref': 'char_tang_wei'},
        'personal_combat': {'opponent_ref': 'char_does_not_exist', 'duration_minutes': 30},
        'population_transfer': {'state': 'qin', 'personnel': 0, 'source_stratum': 'agricultural', 'destination_stratum': 'active_military'},
        'project_resolve': {'institution_ref': 'inst_qin_fortification_bureau', 'project_ref': 'project_does_not_exist'},
        'recruitment': {'state': 'qin', 'personnel': 0, 'source_stratum': 'agricultural', 'role': 'line_infantry'},
        'relationship_change': {'target_ref': 'char_does_not_exist', 'kind': 'trust', 'delta': 1},
        'repair': {'path': 'state/player.json', 'changes': {}},
        'reputation_event': {'subject_ref': 'char_does_not_exist', 'audience_ref': 'char_shen_rui', 'delta': 1},
        'resupply': {'formation_ref': champion, 'food_kg': 0, 'fodder_kg': 0, 'war_arrows': 0},
        'scene_consequence': {'summary': ''},
        'siege_action': {'siege_ref': 'siege_does_not_exist', 'action': 'blockade', 'days': 0},
        'siege_start': {'siege_ref': 'siege_hostile', 'fortification_ref': 'fort_does_not_exist', 'attacker_formation_refs': []},
        'state_action': {'state': 'atlantis', 'action': 'strategic_goal', 'goal': 'impossible'},
        'territorial_consequence': {'location_ref': 'loc_kanyou', 'controller': 'house_tang'},
        'travel': {'destination_ref': 'loc_does_not_exist', 'mode': 'foot'},
    }

    catalog = set(json.load(open(campaign/'game/data/mechanics/command-catalog.json'))['commands'])
    hostile_contract = json.load(open(campaign/'game/data/mechanics/command-hostile-contracts.json'))
    assert hostile_contract['schema'] == 'sword-hostile-command-contracts.v1'
    assert set(hostile_contract['commands']) == catalog
    assert {'unknown_field', 'wrong_actor', 'stale_revision', 'impossible_chronology', 'internal_preview'} <= set(hostile_contract['universal_attacks'])
    assert set(COMMAND_PAYLOAD_KEYS) == catalog
    assert set(cases) == catalog, f'matrix drift: missing={sorted(catalog-set(cases))}, extra={sorted(set(cases)-catalog)}'

    baseline = meta(campaign)
    failures = {}
    for command_type, payload in cases.items():
        try:
            execute(campaign, command_type, payload, request_id=f'hostile-matrix-{command_type}')
        except (ValueError, PermissionError) as exc:
            failures[command_type] = type(exc).__name__
        else:
            pytest.fail(f'{command_type} accepted hostile payload: {payload!r}')
        assert meta(campaign) == baseline, f'{command_type} mutated authoritative meta before rejection'

    assert set(failures) == catalog


def test_every_semantic_command_rejects_unknown_payload_fields(campaign):
    """No production command may silently accept caller fields outside its contract."""
    catalog = set(json.load(open(campaign/'game/data/mechanics/command-catalog.json'))['commands'])
    assert set(COMMAND_PAYLOAD_KEYS) == catalog
    baseline = meta(campaign)
    for command_type in sorted(catalog):
        with pytest.raises(ValueError, match='unsupported payload fields'):
            if command_type == 'repair':
                execute_internal(
                    campaign,
                    command_type,
                    {'__unexpected_shadow_field__': True},
                    mode='maintenance',
                    request_id=f'hostile-unknown-field-{command_type}',
                )
            else:
                execute(
                    campaign,
                    command_type,
                    {'__unexpected_shadow_field__': True},
                    request_id=f'hostile-unknown-field-{command_type}',
                )
        assert meta(campaign) == baseline, f'{command_type} mutated authoritative meta before unknown-field rejection'
