from __future__ import annotations

import copy
from sword_runtime.court_rewards import open_reward_review, settle_reward_package
from sword_runtime.production_planner import ProductionCampaignPlanner


def test_reward_review_does_not_grant_anything_until_decision(campaign):
    p=ProductionCampaignPlanner(campaign)
    evidence='test.reward.evidence'
    hist=copy.deepcopy(p.read('state/history/events/index.json'))
    hist.setdefault('events',[]).append({'event_id':evidence,'kind':'career_merit','at':'244-BCE-08-18T00:00:00+08:00','person_ref':'char_ryo_fui','merit':50})
    p.put('state/history/events/index.json',hist)
    state_before=copy.deepcopy(p.read('state/states/qin.json'))
    house_before=copy.deepcopy(p.read('state/houses/house_ryo_fui_household.json'))
    land_before=copy.deepcopy(p.read('state/development/land.json'))
    result=open_reward_review(p,state='qin',subject_ref='char_ryo_fui',evidence_ref=evidence,at='244-BCE-08-18T00:00:00+08:00',review_ref='reward_review.test')
    assert result['created'] is True
    assert p.read('state/states/qin.json')==state_before
    assert p.read('state/houses/house_ryo_fui_household.json')==house_before
    assert p.read('state/development/land.json')==land_before


def test_reward_package_conserves_silver_and_land_and_office_is_offer(campaign):
    p=ProductionCampaignPlanner(campaign)
    evidence='test.reward.package.evidence'
    hist=copy.deepcopy(p.read('state/history/events/index.json'))
    hist.setdefault('events',[]).append({'event_id':evidence,'kind':'career_merit','at':'244-BCE-08-18T00:00:00+08:00','person_ref':'char_ryo_fui','merit':100})
    p.put('state/history/events/index.json',hist)
    open_reward_review(p,state='qin',subject_ref='char_ryo_fui',evidence_ref=evidence,at='244-BCE-08-18T00:00:00+08:00',review_ref='reward_review.package')
    state0=copy.deepcopy(p.read('state/states/qin.json'))
    house0=copy.deepcopy(p.read('state/houses/house_ryo_fui_household.json'))
    land0=copy.deepcopy(p.read('state/development/land.json'))
    result=settle_reward_package(p,review_ref='reward_review.package',grantor_ref='char_ei_sei',at='244-BCE-08-18T01:00:00+08:00',silver_silver=1000,nobility_target_grade='minor_noble_house',land_region_ref='loc_qin_regional_02',land_km2=1.0,office_offer='Regional Supply Commissioner')
    state1=p.read('state/states/qin.json'); house1=p.read('state/houses/house_ryo_fui_household.json'); land1=p.read('state/development/land.json')
    assert int(state0['treasury_silver'])-int(state1['treasury_silver'])==1000
    assert int(house1['treasury_silver'])-int(house0['treasury_silver'])==1000
    assert house1['nobility']['grade']=='minor_noble_house'
    assert float(land0['regions']['loc_qin_regional_02']['land_use_km2']['open_developable'])-float(land1['regions']['loc_qin_regional_02']['land_use_km2']['open_developable'])==1.0
    assert float(land1['regions']['loc_qin_regional_02']['land_use_km2']['private_holdings'])-float(land0['regions']['loc_qin_regional_02']['land_use_km2'].get('private_holdings',0.0))==1.0
    assert any(g['kind']=='office_offer' and g['status']=='pending_acceptance' for g in result['grants'])
    assert 'Regional Supply Commissioner' not in str(p.read(p.owner_path('char_ryo_fui')).get('career_state',{}).get('office_or_command',''))
