from __future__ import annotations

import copy
import json
import pytest


def test_house_tang_ammunition_procurement_is_silver_backed(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    force = copy.deepcopy(planner.read('state/forces/house-tang.json'))
    depot = copy.deepcopy(planner.read('state/depots/house-tang.json'))
    treasury = copy.deepcopy(planner.read('state/treasury/treasury-house-tang.json'))
    depot['stocks']['war_arrows'] = 0
    depot['stocks']['war_bolts'] = 0
    treasury['silver'] = 100_000
    planner.put('state/depots/house-tang.json', depot)
    planner.put('state/treasury/treasury-house-tang.json', treasury)

    result = planner._fc_procure_ammunition(
        force,
        depot_path='state/depots/house-tang.json',
        treasury_path='state/treasury/treasury-house-tang.json',
        treasury_field='silver',
        occurrences=1,
        at=str(planner._world_time()),
        owner_ref='house_tang',
    )
    after_depot = planner.read('state/depots/house-tang.json')
    after_treasury = planner.read('state/treasury/treasury-house-tang.json')
    assert result['war_arrows'] > 0
    assert result['war_bolts'] == 0
    assert result['silver_spent'] > 0
    assert after_depot['stocks']['war_arrows'] == result['war_arrows']
    assert after_treasury['silver'] == 100_000 - result['silver_spent']


def test_ammunition_procurement_cannot_mint_without_treasury(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    force = copy.deepcopy(planner.read('state/forces/house-tang.json'))
    depot = copy.deepcopy(planner.read('state/depots/house-tang.json'))
    treasury = copy.deepcopy(planner.read('state/treasury/treasury-house-tang.json'))
    depot['stocks']['war_arrows'] = 0
    depot['stocks']['war_bolts'] = 0
    treasury['silver'] = 0
    planner.put('state/depots/house-tang.json', depot)
    planner.put('state/treasury/treasury-house-tang.json', treasury)

    result = planner._fc_procure_ammunition(
        force,
        depot_path='state/depots/house-tang.json',
        treasury_path='state/treasury/treasury-house-tang.json',
        treasury_field='silver',
        occurrences=1,
        at=str(planner._world_time()),
        owner_ref='house_tang',
    )
    after = planner.read('state/depots/house-tang.json')
    assert result == {'war_arrows': 0, 'war_bolts': 0, 'silver_spent': 0}
    assert after['stocks']['war_arrows'] == 0
    assert after['stocks']['war_bolts'] == 0


def test_autonomous_state_recruitment_creates_real_cohort_and_conserves_population(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    force_path = 'state/forces/state-qin.json'
    pop_path = 'state/population/qin.json'
    force = copy.deepcopy(planner.read(force_path))
    population = copy.deepcopy(planner.read(pop_path))
    before_headcount = int(force['headcount'])
    before_agricultural = int(population['strata']['agricultural'])
    before_active = int(population['strata']['active_military'])
    before_ids = set(force.get('cohort_ledger', {}).get('cohorts', {}))
    force['authorized_strength'] = before_headcount + 100
    planner.put(force_path, force)
    at = str(planner._world_time())
    planner._autonomy_state({'owner_ref': 'state_qin', 'recurrence_seconds': 30 * 86400}, 1, at)

    after_force = planner.read(force_path)
    after_pop = planner.read(pop_path)
    new_ids = set(after_force['cohort_ledger']['cohorts']) - before_ids
    recruited_delta = int(after_force['headcount']) - before_headcount
    # The monthly state review may lawfully expand establishment and perform
    # replacement/recruitment work beyond the artificial +100 vacancy injected
    # above.  Conservation, not a historical snapshot count, is the invariant.
    assert recruited_delta > 0
    assert int(after_force['headcount']) <= int(after_force['authorized_strength'])
    assert before_agricultural - int(after_pop['strata']['agricultural']) == recruited_delta
    assert int(after_pop['strata']['active_military']) - before_active == recruited_delta
    assert new_ids
    recruited = [after_force['cohort_ledger']['cohorts'][cid] for cid in new_ids if after_force['cohort_ledger']['cohorts'][cid].get('origin', {}).get('provenance_ref') == f'autonomy_state:{at}']
    assert recruited
    assert sum(
        sum(int(v) for v in c.get('reserve_by_location', {}).values())
        + sum(int(v) for v in c.get('allocated_by_formation', {}).values())
        + sum(int(v) for v in c.get('allocated_external_by_formation', {}).values())
        for c in recruited
    ) == recruited_delta
    assert all(c['origin']['population_ref'] == 'population_qin' for c in recruited)
    assert all(c['origin']['background_profile'] == 'agricultural_laborer' for c in recruited)


def test_autonomous_formation_creation_draws_bolts_from_depot(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    # Add one test-only crossbow blueprint to the disposable campaign. The
    # production state review must draw its first carried load from the exact
    # depot rather than creating bolts inside the formation.
    blueprints = copy.deepcopy(planner.read('game/data/mil/autonomy-blueprints.json'))
    blueprints['states']['qin'] = [{
        'key': 'test_crossbow_line',
        'personnel': 200,
        'role': 'missile_crossbow',
        'commander_ref': None,
        'doctrine_ref': None,
        'training_ref': None,
    }]
    planner.put('game/data/mil/autonomy-blueprints.json', blueprints)
    depot = copy.deepcopy(planner.read('state/depots/qin.json'))
    depot['stocks']['war_bolts'] = 1_000_000
    before = int(depot['stocks']['war_bolts'])
    planner.put('state/depots/qin.json', depot)
    at = str(planner._world_time())
    planner._autonomy_state({'owner_ref': 'state_qin', 'recurrence_seconds': 30 * 86400}, 1, at)

    ref = 'formation_qin_test_crossbow_line'
    idx = planner.read('state/index/owner-index.json')['owners']
    assert ref in idx
    formation = planner.read(idx[ref])
    depot_after = planner.read('state/depots/qin.json')
    bolts = int(formation.get('logistics', {}).get('war_bolts', 0))
    assert bolts == 200 * 30
    procured = int(depot_after['stocks']['war_bolts']) - (before - bolts)
    assert procured >= 0
    assert 'procurement_history' not in depot_after
    assert int(formation.get('logistics', {}).get('war_arrows', 0)) == 0


def test_recruitment_backgrounds_are_canonical_bounded_and_selection_is_not_training(campaign):
    import copy
    from sword_runtime.cohort_personnel import apply_selection_profile, record_recruitment_cohort

    registry = json.loads((campaign / 'game/data/mil/recruitment-cohort-profiles.json').read_text(encoding='utf-8'))
    profiles = registry['background_profiles']
    expected = {
        'agricultural_laborer', 'artisan', 'boatman_fisher', 'civilian_common',
        'clerk_scribe', 'former_soldier', 'guard_watchman', 'herder',
        'household_service', 'hunter', 'merchant_caravan', 'miner',
        'mounted_household', 'urban_laborer',
    }
    assert expected <= set(profiles)

    for ref in sorted(expected):
        profile = profiles[ref]
        for mean_key, sd_key, min_key, max_key in (
            ('attribute_means', 'attribute_sd', 'attribute_min', 'attribute_max'),
            ('skill_means', 'skill_sd', 'skill_min', 'skill_max'),
            ('aptitude_means', 'aptitude_sd', 'aptitude_min', 'aptitude_max'),
        ):
            means = profile[mean_key]
            assert means, f'{ref} must define {mean_key}'
            assert set(means) <= set(profile[sd_key])
            assert set(means) <= set(profile[min_key])
            assert set(means) <= set(profile[max_key])
            for metric, mean in means.items():
                assert float(profile[min_key][metric]) <= float(mean) <= float(profile[max_key][metric])
                assert float(profile[sd_key][metric]) >= 0

    hunter = profiles['hunter']
    farmer = profiles['agricultural_laborer']
    assert hunter['skill_means']['Bow'] > farmer['skill_means']['Bow']
    assert hunter['attribute_means']['Awareness'] > farmer['attribute_means']['Awareness']
    assert hunter['skill_means']['Survival'] > farmer['skill_means']['Survival']
    assert hunter['skill_means']['Formation Fighting'] < farmer['skill_means']['Formation Fighting']

    selected = copy.deepcopy(farmer)
    before = copy.deepcopy(selected)
    selection = registry['selection_profiles']['wei_physical_trial']
    retain = apply_selection_profile(selected, selection, retain_fraction=0.25)
    assert retain == 0.25
    assert selected['attribute_means']['Endurance'] > before['attribute_means']['Endurance']
    assert selected['skill_means']['Athletics'] > before['skill_means']['Athletics']
    assert selected.get('verified_training_hours_per_person', 0) == before.get('verified_training_hours_per_person', 0)
    assert selected.get('verified_role_exposure_hours_per_person', 0) == before.get('verified_role_exposure_hours_per_person', 0)

    # An explicit unknown occupational background must fail rather than let the
    # caller/ChatGPT invent intake statistics.
    force = {'headcount': 1, 'available_by_role': {'line_infantry': 1}, 'available_by_location': {'loc_test': {'line_infantry': 1}}}
    with pytest.raises(ValueError, match='unknown recruitment background profile'):
        record_recruitment_cohort(
            force,
            role='line_infantry', count=1, location_ref='loc_test',
            source_population_ref='population_qin', source_stratum='agricultural',
            recruited_at='245-BCE-01-01T00:00:00+08:00', profile_registry=registry,
            background_profile='chatgpt_invented_super_hunter', validate=False,
        )


def test_state_force_authorization_growth_creates_shortage_then_real_recruitment_fills_it(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    state_path = 'state/states/qin.json'
    force_path = 'state/forces/state-qin.json'
    pop_path = 'state/population/qin.json'
    state = copy.deepcopy(planner.read(state_path))
    force = copy.deepcopy(planner.read(force_path))
    population = copy.deepcopy(planner.read(pop_path))
    before_authorized = int(force['authorized_strength'])
    before_headcount = int(force['headcount'])
    before_agricultural = int(population['strata']['agricultural'])
    before_active = int(population['strata']['active_military'])
    at = str(planner._world_time())

    state['mobilization_readiness'] = 70
    state.setdefault('known_threats', {})['test_material_frontier_pressure'] = {
        'kind': 'frontier_incident',
        'severity': 85,
        'source_ref': 'state_zhao',
        'location_ref': 'loc_gyou',
        'observed_at': at,
    }
    planner.put(state_path, state)
    planner._autonomy_state({'owner_ref': 'state_qin', 'recurrence_seconds': 30 * 86400}, 1, at)

    after_force = planner.read(force_path)
    after_pop = planner.read(pop_path)
    growth = int(after_force['authorized_strength']) - before_authorized
    recruited = int(after_force['headcount']) - before_headcount
    assert growth >= 500
    assert growth % 500 == 0
    assert recruited == growth
    assert int(after_pop['strata']['agricultural']) == before_agricultural - recruited
    assert int(after_pop['strata']['active_military']) == before_active + recruited

    history = planner.read('state/history/events/index.json')
    events = [row for row in history.get('events', []) if row.get('kind') == 'state_force_authorization_growth' and row.get('state_ref') == 'state_qin']
    assert events
    assert events[-1]['authorized_growth_personnel'] == growth
    assert events[-1]['authorized_strength_before'] == before_authorized
    assert events[-1]['authorized_strength_after'] == before_authorized + growth


def test_state_force_authorization_does_not_grow_from_routine_peace(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    force_before = copy.deepcopy(planner.read('state/forces/state-qi.json'))
    state = copy.deepcopy(planner.read('state/states/qi.json'))
    state['known_threats'] = {}
    state['war_intents'] = []
    state['mobilization_readiness'] = 80
    planner.put('state/states/qi.json', state)
    at = str(planner._world_time())
    result = planner._review_state_force_authorization_growth(
        state='qi', state_doc=state, at=at, occurrences=1,
        monthly_expense_due=int(state.get('normal_monthly_expense_silver', 0)),
    )
    force_after = planner.read('state/forces/state-qi.json')
    assert result['changed'] is False
    assert result['reason'] == 'insufficient_current_pressure_or_readiness'
    assert int(force_after['authorized_strength']) == int(force_before['authorized_strength'])


def test_state_force_authorization_growth_respects_population_ceiling(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    state = copy.deepcopy(planner.read('state/states/han.json'))
    force = copy.deepcopy(planner.read('state/forces/state-han.json'))
    population = planner.read('state/population/han.json')
    at = str(planner._world_time())
    ceiling = int(int(population['population_total']) * 0.10)
    force['authorized_strength'] = ceiling
    planner.put('state/forces/state-han.json', force)
    state['mobilization_readiness'] = 100
    state['known_threats'] = {'test': {'severity': 100, 'observed_at': at}}
    result = planner._review_state_force_authorization_growth(
        state='han', state_doc=state, at=at, occurrences=1,
        monthly_expense_due=int(state.get('normal_monthly_expense_silver', 0)),
    )
    assert result['changed'] is False
    assert result['reason'] == 'active_military_population_ceiling'
    assert int(planner.read('state/forces/state-han.json')['authorized_strength']) == ceiling
