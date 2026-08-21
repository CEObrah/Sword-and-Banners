import copy
import json

from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _sum_population_strata(pop):
    return sum(int(v) for v in pop.get('strata', {}).values())


def test_bastion_pipeline_reserves_real_civilians_and_does_not_create_active_troops(campaign):
    planner = ProductionCampaignPlanner(campaign)
    at = json.load(open(campaign / 'state/meta.json'))['time']
    before_pop = copy.deepcopy(planner.read('state/population/qin.json'))
    before_force = copy.deepcopy(planner.read('state/forces/bastion-iron-wall.json'))

    result = planner._settle_bastion_personnel(at)
    after_pop = planner.read('state/population/qin.json')
    after_force = planner.read('state/forces/bastion-iron-wall.json')

    assert result['corps']['iron_wall']['started_training'] > 0
    assert after_force['headcount'] == before_force['headcount'] == 75000
    assert int(after_pop['strata']['recruitment_candidates_reserved']) > 0
    assert _sum_population_strata(after_pop) == _sum_population_strata(before_pop)
    local = after_pop['local_population']['sites']['loc_tang_manor']
    assert local['candidates_reserved'] == int(after_pop['strata']['recruitment_candidates_reserved'])
    cohort = after_force['personnel_pipeline']['cohorts'][0]
    assert cohort['status'] == 'training'
    assert CampaignTime.parse(cohort['qualifies_at']) > CampaignTime.parse(at)


def test_qualified_bastion_candidates_only_enter_a_real_vacancy(campaign):
    planner = ProductionCampaignPlanner(campaign)
    at = json.load(open(campaign / 'state/meta.json'))['time']
    planner._settle_bastion_personnel(at)

    force_path = 'state/forces/bastion-iron-wall.json'
    force = copy.deepcopy(planner.read(force_path))
    cohort = force['personnel_pipeline']['cohorts'][0]
    cohort['qualifies_at'] = at
    # Authorize a vacancy exactly equal to the conserved qualified cohort.
    # The pipeline may satisfy it, but must never invent bodies beyond the cohort.
    qualified = int(cohort['remaining_candidates'])
    assert qualified > 0
    force['authorized_strength'] = int(force['headcount']) + qualified
    force['authorized_by_role']['bastion_heavy_infantry'] = int(force['authorized_by_role']['bastion_heavy_infantry']) + qualified
    planner.put(force_path, force)

    pop_before = copy.deepcopy(planner.read('state/population/qin.json'))
    planner._settle_bastion_personnel(at)
    pop_after = planner.read('state/population/qin.json')
    force_after = planner.read(force_path)

    assert force_after['headcount'] == int(force['headcount']) + qualified
    assert force_after['authorized_strength'] == force_after['headcount']
    latest = force_after['personnel_pipeline']['history'][-1]
    assert latest['admitted_active'] == qualified
    # Ten qualified people leave candidate reserve for active service. The
    # personnel office may immediately reserve a replacement training class,
    # so the net reserved count can remain stable while the active transfer is
    # still exactly conserved.
    assert int(pop_after['strata']['recruitment_candidates_reserved']) == int(pop_before['strata']['recruitment_candidates_reserved']) - qualified + int(latest['started_training'])
    assert int(pop_after['strata']['private_household_military']) == int(pop_before['strata']['private_household_military']) + qualified
    assert _sum_population_strata(pop_after) == _sum_population_strata(pop_before)
