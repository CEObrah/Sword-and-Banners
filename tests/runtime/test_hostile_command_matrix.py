import json
import pytest

from conftest import execute, execute_internal, meta
from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS
from sword_runtime.commands import CommandEnvelope
from sword_runtime.production_planner import ProductionCampaignPlanner


def test_every_semantic_command_has_a_fail_closed_hostile_case(campaign):
    """Every current public semantic command must fail closed on one hostile boundary case."""
    catalog = set(json.load(open(campaign/'game/data/mechanics/command-catalog.json'))['commands'])
    hostile_contract = json.load(open(campaign/'game/data/mechanics/command-hostile-contracts.json'))
    attacks = hostile_contract['commands']

    assert hostile_contract['schema'] == 'sword-hostile-command-contracts'
    assert set(attacks) == catalog
    assert {'unknown_field', 'wrong_actor', 'stale_revision', 'impossible_chronology', 'internal_preview'} <= set(hostile_contract['universal_attacks'])
    assert set(COMMAND_PAYLOAD_KEYS) == catalog

    baseline = meta(campaign)
    planner = ProductionCampaignPlanner(campaign)
    failures = {}
    for command_type in sorted(catalog):
        attack = attacks[command_type]['specific_attack']
        payload = attack['payload']
        command = CommandEnvelope(
            baseline['campaign_id'], f'hostile-matrix-{command_type}', baseline['player_id'],
            command_type, baseline['revision'], baseline['time'], payload, mode='gameplay',
        )
        try:
            planner.preview(command)
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
    planner = ProductionCampaignPlanner(campaign)
    for command_type in sorted(catalog):
        command = CommandEnvelope(
            baseline['campaign_id'], f'hostile-unknown-field-{command_type}', baseline['player_id'],
            command_type, baseline['revision'], baseline['time'],
            {'__unexpected_shadow_field__': True}, mode='gameplay',
        )
        with pytest.raises(ValueError, match='unsupported payload fields'):
            planner.preview(command)
        assert meta(campaign) == baseline, f'{command_type} mutated authoritative meta before unknown-field rejection'
