from __future__ import annotations

import json
import subprocess


def _commit_state_edit(campaign, *relative_paths: str) -> None:
    subprocess.run(['git','-C',str(campaign),'add',*relative_paths],check=True)
    subprocess.run(['git','-C',str(campaign),'commit','--quiet','-m','test: action-ready combat state'],check=True)


def test_stats_above_200_continue_to_improve_personal_and_formation_combat(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    from sword_runtime.cohort_personnel import seed_cohort_capability

    planner=RepositoryCommandPlanner(campaign)
    eq={
        'skill_name':'Sword',
        'weapon':{'handling':1.0,'recovery_class':'standard'},
        'burden':{'movement_factor':1.0,'recovery_factor':1.0},
    }
    controls_200={'awareness':200,'agility':200,'coordination':200,'composure':200,'weapon_skill':200}
    controls_300={'awareness':300,'agility':300,'coordination':300,'composure':300,'weapon_skill':300}
    person_200={'attributes':{'Agility':200,'Coordination':200,'Awareness':200,'Endurance':200},'skills':{'Sword':200,'Formation Fighting':200,'Athletics':200}}
    person_300={'attributes':{'Agility':300,'Coordination':300,'Awareness':300,'Endurance':300},'skills':{'Sword':300,'Formation Fighting':300,'Athletics':300}}
    t200=planner._personal_timing_profile(person_200,eq,controls_200,{})
    t300=planner._personal_timing_profile(person_300,eq,controls_300,{})
    assert t300['tempo'] > t200['tempo']
    assert t300['minimum_action_interval_seconds'] < t200['minimum_action_interval_seconds']
    assert planner._combat_melee_capability_factor(300,1.0) > planner._combat_melee_capability_factor(200,1.0)

    cohort={}
    seed_cohort_capability(
        cohort,
        attribute_means={'Agility':230},
        skill_means={'Sword':240},
        aptitude_means={'physical_learning':225},
        evidence_ref='test:uncapped-cohort',
    )
    # Compact cohorts persist uncapped means plus scalar spread. They no longer
    # store derived min/max maps as competing projection authority.
    assert cohort['attribute_means']['Agility'] > 200
    assert cohort['skill_means']['Sword'] > 200
    assert cohort['aptitude_means']['physical_learning'] > 200
    assert isinstance(cohort['attribute_sd'], (int, float))
    assert isinstance(cohort['skill_sd'], (int, float))
    assert 'attribute_max' not in cohort and 'skill_max' not in cohort and 'aptitude_max' not in cohort


def test_personal_combat_uses_independent_action_ready_timestamps(campaign):
    from conftest import execute, execute_internal

    opponent='char_test_action_ready_opponent'
    player_path=campaign/'state/player.json'
    player=json.loads(player_path.read_text())
    location=player['location']
    execute_internal(campaign,'person_materialize',{
        'state':'qin','person_ref':opponent,'name':'Slow Action Ready Opponent',
        'birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':location,
    })
    owners=json.loads((campaign/'state/index/owner-index.json').read_text())['owners']
    opponent_path=campaign/owners[opponent]
    player=json.loads(player_path.read_text())
    other=json.loads(opponent_path.read_text())

    player.setdefault('attributes',{}).update({
        'Agility':300,'Coordination':300,'Awareness':300,'Endurance':300,'Composure':300,'Strength':180,
    })
    player.setdefault('skills',{}).update({
        'Sword':300,'Athletics':280,'Formation Fighting':260,
    })
    other.setdefault('attributes',{}).update({
        'Agility':25,'Coordination':25,'Awareness':20,'Endurance':30,'Composure':25,'Strength':55,
    })
    other.setdefault('skills',{}).update({
        'Sword':25,'Polearms':25,'Athletics':20,'Formation Fighting':10,
    })
    player_path.write_text(json.dumps(player,ensure_ascii=False,indent=2)+'\n')
    opponent_path.write_text(json.dumps(other,ensure_ascii=False,indent=2)+'\n')
    _commit_state_edit(campaign,'state/player.json',owners[opponent])

    result=execute(campaign,'personal_combat',{
        'opponent_ref':opponent,'objective':'controlled spar','duration_minutes':5,
    }).receipt.result
    assert result['timing_model']['mode']=='continuous_action_ready'
    assert result['elapsed_seconds']==300
    assert result['elapsed_milliseconds']==300000

    actions=[row for row in result['causal_trace'] if row.get('kind') in {'attack','movement'}]
    assert len(actions)>=3
    for row in actions:
        assert isinstance(row.get('start_at_ms'),int)
        assert isinstance(row.get('recovery_complete_at_ms'),int)
        if row['kind']=='attack':
            assert isinstance(row.get('contact_at_ms'),int)
            assert row['start_at_ms'] <= row['contact_at_ms'] <= row['recovery_complete_at_ms']
        else:
            assert isinstance(row.get('complete_at_ms'),int)
            assert row['start_at_ms'] <= row['complete_at_ms'] <= row['recovery_complete_at_ms']

    # No actor is entitled to one alternating turn. With a deliberately huge
    # tempo mismatch, the fast actor must be able to resolve consecutive actions
    # before the slow actor becomes action-ready again.
    action_actors=[row['actor_ref'] for row in actions]
    assert any(a==b for a,b in zip(action_actors,action_actors[1:])), action_actors
