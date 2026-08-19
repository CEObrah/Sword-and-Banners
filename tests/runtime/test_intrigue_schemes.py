from __future__ import annotations
import copy, json
from pathlib import Path
from sword_runtime.production_planner import ProductionCampaignPlanner
from conftest import execute_production


def planner_for(root):
    p=ProductionCampaignPlanner(root); meta=p.read('state/meta.json'); p.PLAYER_ACTOR=str(meta['player_id']); return p


def test_scheme_budget_is_exact_escrow_and_cancel_refunds_unspent(campaign):
    wallet=Path(campaign)/'state/economy/player-wallet.json'
    before=json.loads(wallet.read_text())['silver']
    execute_production(campaign,'scheme_action',{
        'action':'start','scheme_ref':'scheme_test_budget','objective':'discrediting',
        'target_ref':'char_tang_zhu','agent_refs':['char_tang_wei'],'budget_silver':100,
    },request_id='scheme-budget-start')
    assert json.loads(wallet.read_text())['silver']==before-100
    execute_production(campaign,'scheme_action',{'action':'work','scheme_ref':'scheme_test_budget','hours':10},request_id='scheme-budget-work')
    row=json.loads((Path(campaign)/'state/politics/schemes/scheme_test_budget.json').read_text())
    assert row['disbursed_silver']==20 and row['remaining_budget_silver']==80
    execute_production(campaign,'scheme_action',{'action':'cancel','scheme_ref':'scheme_test_budget'},request_id='scheme-budget-cancel')
    row=json.loads((Path(campaign)/'state/politics/schemes/scheme_test_budget.json').read_text())
    assert row['remaining_budget_silver']==0 and row['refunded_silver']==80
    assert json.loads(wallet.read_text())['silver']==before-20


def test_progress_and_exposure_are_independent_tracks(campaign):
    execute_production(campaign,'scheme_action',{
        'action':'start','scheme_ref':'scheme_test_tracks','objective':'misinformation',
        'target_ref':'char_tang_zhu','agent_refs':['char_tang_wei'],'budget_silver':50,
    },request_id='scheme-tracks-start')
    before=json.loads((Path(campaign)/'state/politics/schemes/scheme_test_tracks.json').read_text())
    execute_production(campaign,'scheme_action',{'action':'work','scheme_ref':'scheme_test_tracks','hours':24},request_id='scheme-tracks-work')
    after=json.loads((Path(campaign)/'state/politics/schemes/scheme_test_tracks.json').read_text())
    assert after['completed_progress']>=before['completed_progress']
    assert after['exposure_progress']>=before['exposure_progress']
    assert 'last_progress_score' in after and 'last_exposure_score' in after
    assert after['last_step_components']['progress'] != after['last_step_components']['exposure']


def test_assassination_completion_creates_contact_not_automatic_death(campaign):
    p=planner_for(campaign); pp,person=p._exact_person('char_tang_zhu',active=False); alive_before=person.get('status','alive')
    row={'owner_id':'scheme_test_assassination','objective':'assassination','target_ref':'char_tang_zhu'}
    effect=p._scheme_terminal_effect(row,str(p._world_time()))
    _pp,after=p._exact_person('char_tang_zhu',active=False)
    assert effect['kind'] in {'physical_contact_opportunity','opportunity_created'}
    assert after.get('status','alive')==alive_before


def test_crossing_sabotage_mutates_exact_crossing_only(campaign):
    p=planner_for(campaign); path='state/geography/strategic-crossings.json'; before=copy.deepcopy(p.read(path)); route='route_chu_heartland_east'
    old=int(before['crossings'][route]['bridge_condition_percent'])
    row={'owner_id':'scheme_test_sabotage','objective':'sabotage','target_ref':route}
    effect=p._scheme_terminal_effect(row,str(p._world_time()))
    after=p.read(path)
    assert effect['kind']=='strategic_crossing_damage'
    assert int(after['crossings'][route]['bridge_condition_percent'])==max(0,old-25)
    for ref,data in before['crossings'].items():
        if ref!=route: assert after['crossings'][ref]==data
