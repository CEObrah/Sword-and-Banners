from __future__ import annotations

import copy

from sword_runtime.engine import CommandEnvelope
from sword_runtime.production_planner import ProductionCampaignPlanner


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read('state/meta.json'))
    planner.PLAYER_ACTOR = str(meta['player_id'])
    planner._reset()
    return planner


def test_outside_bastion_applicant_relocates_before_selection(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    wei0 = copy.deepcopy(planner.read('state/population/wei.json'))
    qin0 = copy.deepcopy(planner.read('state/population/qin.json'))
    tang0 = copy.deepcopy(planner.read('state/population/tang-manor.json'))
    source_site = 'loc_dairyou'
    source0 = int(wei0['local_population']['sites'][source_site]['civilian_population'])

    move = planner._bastion_relocate_outside_applicants(
        'deep_earth', source_state='wei', source_site_ref=source_site, applicant_count=24, at=at,
    )
    assert move['relocated_applicants'] == 24
    cohort = planner.read('state/mobility/population-transit.json')['cohorts'][move['migration_ref']]
    assert cohort['status'] == 'in_transit'
    assert cohort['bastion_application']['corps'] == 'deep_earth'
    assert int(planner.read('state/population/wei.json')['population_total']) == int(wei0['population_total'])
    assert int(planner.read('state/population/qin.json')['population_total']) == int(qin0['population_total'])
    assert int(planner.read('state/population/tang-manor.json')['population_total']) == int(tang0['population_total'])
    assert int(planner.read('state/population/wei.json')['local_population']['sites'][source_site]['civilian_population']) == source0 - 24

    planner._settle_population_mobility_arrival({'cohort_ref': move['migration_ref']}, str(move['arrives_at']))
    wei1 = planner.read('state/population/wei.json')
    qin1 = planner.read('state/population/qin.json')
    tang1 = planner.read('state/population/tang-manor.json')
    assert int(wei1['population_total']) == int(wei0['population_total']) - 24
    assert int(qin1['population_total']) == int(qin0['population_total']) + 24
    assert int(tang1['population_total']) == int(tang0['population_total']) + 24
    app = tang1['bastion_outside_applications']['deep_earth']
    assert app['available_applicants'] == 24
    assert app['arrival_history'][-1]['migration_ref'] == move['migration_ref']


def test_house_action_accepts_applicants_but_does_not_create_bastion_bodies(campaign) -> None:
    planner = _planner(campaign)
    meta = planner.read('state/meta.json')
    force0 = int(planner.read('state/forces/bastion-red-crane.json')['headcount'])
    cmd = CommandEnvelope(
        campaign_id=str(meta['campaign_id']), command_type='house_action', actor_id=planner.PLAYER_ACTOR,
        payload={
            'house_ref':'house_tang', 'action':'accept_bastion_applicants',
            'corps_key':'red_crane', 'source_state':'han',
            'source_site_ref':'loc_nanyou', 'applicant_count':12,
        }, expected_revision=int(meta['revision']), submitted_at=str(meta['time']), request_id='outside-bastion-applicants-test',
    )
    planner._authorize_command(cmd, cmd.payload)
    planner._validate_command_semantics(cmd, cmd.payload)
    result = planner._dispatch(cmd, cmd.payload)
    assert result['action'] == 'accept_bastion_applicants'
    assert result['relocated_applicants'] == 12
    assert int(planner.read('state/forces/bastion-red-crane.json')['headcount']) == force0


def test_arrived_outside_applicants_can_be_considered_without_guaranteed_selection(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    move = planner._bastion_relocate_outside_applicants(
        'white_lantern', source_state='qin', source_site_ref='loc_kanyou', applicant_count=20, at=at,
    )
    planner._settle_population_mobility_arrival({'cohort_ref': move['migration_ref']}, str(move['arrives_at']))
    force_path='state/forces/bastion-white-lantern.json'
    force=copy.deepcopy(planner.read(force_path))
    # Create one real vacancy so the pipeline has a reason to train candidates.
    force['headcount'] -= 1
    force['available_by_role']['bastion_signal'] = max(0, int(force['available_by_role'].get('bastion_signal', 0)) - 1)
    planner.put(force_path, force)
    force=copy.deepcopy(planner.read(force_path))
    started=planner._bastion_start_pipeline('white_lantern', force, at)
    assert started > 0
    row=force['personnel_pipeline']['cohorts'][-1]
    assert row['outside_applicants_considered'] > 0
    assert row['outside_applicant_arrival_refs'] == [move['migration_ref']]
    # Starting training does not fill the active-service vacancy immediately.
    assert int(force['headcount']) == int(planner.read(force_path)['headcount'])
