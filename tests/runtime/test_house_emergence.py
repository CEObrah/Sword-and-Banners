from __future__ import annotations

import copy
from sword_runtime.house_emergence import form_house_from_existing_person
from sword_runtime.production_planner import ProductionCampaignPlanner


def _totals(planner):
    land=planner.read('state/development/land.json')
    return {
        'qin_population': int(planner.read('state/population/qin.json')['population_total']),
        'qin_force': int(planner.read('state/forces/state-qin.json')['headcount']),
        'qin_treasury': int(planner.read('state/states/qin.json')['treasury_silver']),
        'land_regions': sum(float(r['area_km2']) for r in land['regions'].values()),
    }


def test_house_emergence_reclassifies_existing_person_without_assets(campaign):
    p=ProductionCampaignPlanner(campaign)
    person_ref='char_shin'
    person_path=p.owner_path(person_ref)
    person=copy.deepcopy(p.read(person_path))
    person.pop('house_ref',None)
    p.put(person_path,person)
    hist=copy.deepcopy(p.read('state/history/events/index.json'))
    evidence='test.house_emergence.evidence'
    hist.setdefault('events',[]).append({'event_id':evidence,'kind':'career_merit','at':'244-BCE-08-18T00:00:00+08:00','person_ref':person_ref,'merit':100})
    p.put('state/history/events/index.json',hist)
    before=_totals(p)
    result=form_house_from_existing_person(p,founder_ref=person_ref,state='qin',at='244-BCE-08-18T00:00:00+08:00',evidence_ref=evidence,house_ref='house_shin_test')
    assert result['created'] is True
    house=p.read('state/houses/house_shin_test.json')
    assert house['leader_ref']==person_ref
    assert house['lineage_cohort']['adults']==1
    assert house['nobility']['grade']=='unranked_house'
    assert house['treasury_silver']==0
    assert 'military_force_ref' not in house
    assert 'holding_ref' not in house
    assert p.read(person_path)['house_ref']=='house_shin_test'
    assert p.read('state/index/owner-index.json')['owners']['house_shin_test']=='state/houses/house_shin_test.json'
    assert _totals(p)==before
