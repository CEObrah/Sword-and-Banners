from __future__ import annotations
import copy


def test_bastion_long_service_retirement_returns_real_bodies_to_civilian_veterans(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner=ProductionCampaignPlanner(campaign)
    force_path='state/forces/bastion-iron-rampart.json'
    force=copy.deepcopy(planner.read(force_path))
    cohort=next(iter(force['cohort_ledger']['cohorts'].values()))
    cohort['service_months_mean']=240.1
    before_head=int(force['headcount'])
    before_qin=copy.deepcopy(planner.read('state/population/qin.json'))
    before_tang=copy.deepcopy(planner.read('state/population/tang-manor.json'))
    planner.put(force_path,force)
    force=copy.deepcopy(planner.read(force_path))
    retired=planner._bastion_retirements('iron_rampart',force,planner.read('state/meta.json')['time'])
    assert retired>0
    planner.put(force_path,force)
    after_force=planner.read(force_path)
    after_qin=planner.read('state/population/qin.json')
    after_tang=planner.read('state/population/tang-manor.json')
    assert int(after_force['headcount'])==before_head-retired
    assert int(after_qin['population_total'])==int(before_qin['population_total'])
    assert int(after_qin['strata']['private_household_military'])==int(before_qin['strata']['private_household_military'])-retired
    assert int(after_qin['strata']['retired_military_veterans'])==int(before_qin['strata'].get('retired_military_veterans',0))+retired
    assert int(after_tang['population_total'])==int(before_tang['population_total'])+retired
    assert int(after_tang['strata']['veterans_and_retired_service'])==retired
