from __future__ import annotations

import copy

from sword_runtime.house_lineage import materialize_house_lineage_member, settle_state_house_lineages
from sword_runtime.production_planner import ProductionCampaignPlanner


def _planner(campaign):
    p=ProductionCampaignPlanner(campaign); p._reset(); return p


def test_all_aggregate_house_lineages_are_population_backed(campaign):
    p=_planner(campaign)
    idx=p.read('state/index/house-lineage-index.json')
    for state,routes in idx['by_state'].items():
        parent=p.read(f'state/population/{state}.json')
        total=0
        for path in routes.values():
            house=p.read(path); cohort=house['lineage_cohort']
            assert cohort['population_ref']==f'population_{state}'
            assert 'representation' not in cohort
            assert 'population_backing' not in cohort
            total += int(cohort['children'])+int(cohort['adults'])+int(cohort['elders'])
        assert total <= int(parent['population_total'])


def test_house_demography_only_classifies_parent_births_and_deaths(campaign):
    p=_planner(campaign)
    before={path:copy.deepcopy(p.read(path)['lineage_cohort']) for path in p.read('state/index/house-lineage-index.json')['by_state']['qin'].values()}
    result=settle_state_house_lineages(p,state='qin',at='243-BCE-09-09T20:22:48+08:00',years=1,parent_births=25_000,parent_deaths=15_000)
    assert result['births'] <= 25_000
    assert result['deaths'] <= 15_000
    assert result['births'] >= 0 and result['deaths'] >= 0
    # One annual settlement cannot reproduce the old 120-day explosive arithmetic.
    for path,old in before.items():
        new=p.read(path)['lineage_cohort']
        old_total=sum(int(old.get(k,0)) for k in ('children','adults','elders'))
        new_total=sum(int(new.get(k,0)) for k in ('children','adults','elders'))
        assert new_total <= old_total + max(2, int(old.get('aggregate_marriages',0)))


def test_stale_house_lineage_state_route_cannot_spend_another_states_demography(campaign):
    p=_planner(campaign)
    foreign_ref='house_karin_house'
    foreign_path=p.owner_path(foreign_ref)
    before=copy.deepcopy(p.read(foreign_path))
    assert before['state']=='chu'

    idx=copy.deepcopy(p.read('state/index/house-lineage-index.json'))
    idx['by_state']['qin'][foreign_ref]=foreign_path
    p.put('state/index/house-lineage-index.json',idx)

    settle_state_house_lineages(
        p,state='qin',at='243-BCE-09-09T20:22:48+08:00',years=1,
        parent_births=1_000_000,parent_deaths=1_000_000,
    )
    assert p.read(foreign_path)==before


def test_materialization_consumes_one_anonymous_lineage_slot(campaign):
    p=_planner(campaign)
    ref='house_mou_family'
    house0=copy.deepcopy(p.read(p.owner_path(ref)))
    total0=sum(int(house0['lineage_cohort'][k]) for k in ('children','adults','elders'))
    pop0=int(p.read('state/population/qin.json')['population_total'])
    result=materialize_house_lineage_member(p,house_ref=ref,person_ref='char_mou_test_descendant',name='Mou Test Descendant',age_band='children',at=str(p._world_time()))
    assert result['population_delta']==0 and result['house_headcount_delta']==0
    house1=p.read(p.owner_path(ref))
    total1=sum(int(house1['lineage_cohort'][k]) for k in ('children','adults','elders'))
    assert total1==total0
    assert int(p.read('state/population/qin.json')['population_total'])==pop0
    assert 'char_mou_test_descendant' in house1['lineage_cohort']['exact_member_refs']


def test_missing_house_lineage_cache_route_is_repaired_from_exact_house_owner(campaign):
    p = _planner(campaign)
    house_ref = 'house_mou_family'
    house_path = p.owner_path(house_ref)
    idx = copy.deepcopy(p.read('state/index/house-lineage-index.json'))
    idx['by_state']['qin'].pop(house_ref, None)
    p.put('state/index/house-lineage-index.json', idx)

    settle_state_house_lineages(
        p, state='qin', at='243-BCE-09-09T20:22:48+08:00', years=1,
        parent_births=0, parent_deaths=0,
    )

    repaired = p.read('state/index/house-lineage-index.json')
    assert repaired['by_state']['qin'][house_ref] == house_path
