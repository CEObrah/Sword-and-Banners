from __future__ import annotations

import copy
import json

from conftest import execute_production_internal
from sword_runtime.sim.calendar import CampaignTime


def planner_for(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    return ProductionCampaignPlanner(campaign)


def _test_time(planner):
    return str(planner.read("state/runtime.json")["world_time"])


def test_all_state_capitals_have_exact_markets_and_scarcity_pricing(campaign):
    planner = planner_for(campaign)
    rules = planner.read('game/data/mechanics/civil-economy.json')
    owners = planner.read('state/index/owner-index.json')['owners']
    assert len(rules['capital_markets']) == 7
    for spec in rules['capital_markets'].values():
        assert spec['market_ref'] in owners
        market = planner.read(spec['path'])
        assert market['location_ref'] == spec['location_ref']
        assert market['normal_stock']
    market = copy.deepcopy(planner.read('state/markets/kanyou.json'))
    normal_price, _ = planner._market_unit_price(market, 'military_sword')
    market['stock']['military_sword'] = 5
    scarce_price, factors = planner._market_unit_price(market, 'military_sword')
    assert scarce_price > normal_price
    assert factors['scarcity'] > 1.0


def test_institution_project_reserves_silver_materials_and_labor(campaign):
    from types import SimpleNamespace
    planner = planner_for(campaign); planner._reset()
    ep, eco = planner._private_economy('qin')
    inst0 = planner.read(planner.owner_path('inst_qin_fortification_bureau'))
    _site_ref, region = planner._local_economy_region('qin', eco, str(inst0.get('location_ref', '')))
    for row in eco['local_regions']['regions'].values():
        row.setdefault('commodity_stock', {})['construction_material_units'] = 0
    region['commodity_stock']['construction_material_units'] = 1000
    planner._sync_local_economy_aggregate(eco); planner._write_private_economy(ep, eco)
    before_state = copy.deepcopy(planner.read('state/states/qin.json')); before_cash = int(eco['cash_silver'])
    meta = planner.read('state/meta.json'); command = SimpleNamespace(command_type='institution_project', digest='0123456789abcdef', semantic_digest='0123456789abcdef', actor_id='internal:sword-autonomy', expected_revision=int(meta['revision']), submitted_at=str(meta['time']))
    result = planner._start_funded_institution_project(command, {
        'institution_ref': 'inst_qin_fortification_bureau',
        'project_ref': 'project_causal_materials',
        'duration_hours': 24,
        'kind': 'construction',
        'magnitude': 2,
    })
    state = planner.read('state/states/qin.json'); after_eco = planner.read(ep); inst = planner.read(planner.owner_path('inst_qin_fortification_bureau'))
    project = next(x for x in inst['projects'] if x['project_ref'] == 'project_causal_materials')
    reserved = project['inputs_reserved']
    assert reserved['silver'] == 400
    assert reserved['construction_material_units'] == 40
    assert reserved['labor_hours'] == 24
    assert state['treasury_silver'] == before_state['treasury_silver'] - 400
    assert after_eco['cash_silver'] == before_cash + 400
    assert after_eco['commodity_stock']['construction_material_units'] == 960
    assert result['reserved_inputs']['material_source_ref'] == 'private_economy_qin'


def test_granary_procurement_moves_existing_grain_and_cash(campaign):
    planner = planner_for(campaign); planner._reset()
    ep, eco = planner._private_economy('qin')
    depot0 = planner.read('state/depots/qin.json'); depot_location = str(depot0.get('location_ref', ''))
    _site_ref, region = planner._local_economy_region('qin', eco, depot_location)
    for row in eco['local_regions']['regions'].values():
        row.setdefault('commodity_stock', {})['grain_kg'] = 0
    region['commodity_stock']['grain_kg'] = 1_000_000
    planner._sync_local_economy_aggregate(eco); planner._write_private_economy(ep, eco)
    before_depot = int(planner.read('state/depots/qin.json')['stocks']['grain_kg'])
    before_state = int(planner.read('state/states/qin.json')['treasury_silver'])
    before_private_cash = int(eco['cash_silver'])
    planner._autonomy_institution({'owner_ref':'inst_qin_granary_depot_office'}, 1, _test_time(planner))
    after_eco = planner.read(ep); after_depot = planner.read('state/depots/qin.json'); after_state = planner.read('state/states/qin.json')
    moved = int(after_depot['stocks']['grain_kg']) - before_depot
    assert moved > 0
    assert int(after_eco['commodity_stock']['grain_kg']) == 1_000_000 - moved
    spent = before_state - int(after_state['treasury_silver'])
    assert spent > 0
    assert int(after_eco['cash_silver']) == before_private_cash + spent


def test_faction_review_uses_distinct_saved_resources_and_actions(campaign):
    planner = planner_for(campaign); planner._reset()
    path = 'state/factions/faction_qin_noble_patrons.json'; before = copy.deepcopy(planner.read(path))
    before.setdefault('resources', {})['influence'] = max(16, int(before.get('resources', {}).get('influence', 0)))
    before['pressure'] = max(30, int(before.get('pressure', 0)))
    planner.put(path, before)
    planner._autonomy_faction({'owner_ref':'faction_qin_noble_patrons'}, 6, _test_time(planner))
    after = planner.read(path)
    assert after['goals'] != ['preserve influence', 'advance current interests']
    assert after['resources']['funds_silver'] < before['resources']['funds_silver']
    assert after['last_action']['action'] == 'patronage_lobbying'
    assert planner.read('state/states/qin.json')['political_pressure']['faction_qin_noble_patrons']['kind'] == 'patronage_lobbying'


def test_occupation_tracks_control_claim_administration_loyalty_and_resistance(campaign):
    planner = planner_for(campaign); planner._reset()
    planner._occupation_initialize('loc_gyou', 'state_qin', 'state_zhao', _test_time(planner), 'battle_example')
    site = planner.read('state/territory/control.json')['sites']['loc_gyou']
    gov = site['governance']
    assert gov['military_controller'] == 'state_qin'
    assert gov['status'] == 'military_occupation'
    assert 0 < gov['tax_compliance'] < 100
    assert gov['resistance'] > gov['civilian_loyalty']
    assert site['legal_claims']['state_zhao']['strength'] == 100
    assert site['legal_claims']['state_qin']['strength'] < 100


def test_interstate_config_expands_from_real_cross_state_routes(campaign):
    planner = planner_for(campaign); planner._reset()
    base = planner.read('game/data/world/autonomous-theaters.json')
    expanded = planner._interstate_theater_config(base)
    assert len(expanded['theaters']) >= len(base['theaters'])
    assert any(row.get('dynamic') for row in expanded['theaters'])



def test_state_institutions_publish_specialized_exact_reviews(campaign):
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    planner._autonomy_institution({'owner_ref':'inst_qin_military_bureau'}, 1, at)
    military = planner.read(planner.owner_path('inst_qin_military_bureau'))
    assert 'commander_vacancies' in military['military_review']
    assert planner.read('state/states/qin.json')['military_administration']['last_review'] == at

    planner._autonomy_institution({'owner_ref':'inst_qin_fortification_bureau'}, 1, at)
    fort = planner.read(planner.owner_path('inst_qin_fortification_bureau'))
    assert 'priorities' in fort['fortification_review']
    assert 'project_started_ref' in fort['fortification_review']
    assert 'rule' not in fort['fortification_review']

    planner._autonomy_institution({'owner_ref':'inst_qin_recruitment_office'}, 1, at)
    recruit = planner.read(planner.owner_path('inst_qin_recruitment_office'))
    assert recruit['recruitment_review']['office_capacity'] == recruit['capacity']
    assert recruit['recruitment_review']['force_shortage'] >= 0
    assert 'rule' not in recruit['recruitment_review']


def test_interstate_peace_creates_first_class_treaty_terms(campaign):
    planner = planner_for(campaign); planner._reset()
    path = planner.owner_path('interstate_warring_states')
    world = copy.deepcopy(planner.read(path))
    record = world['theaters']['qin_zhao_gyou']
    previous_treaty_ref = record.get('last_treaty_ref')
    record.update({
        'phase': 'peace_settlement',
        'cycle': 1,
        'attacker_state': 'qin',
        'defender_state': 'zhao',
        'battle_count': 2,
        'war_result': 'defender_holds',
        'started_at': _test_time(planner),
    })
    planner.put(path, world)
    host = copy.deepcopy(planner.read('state/runtime.json')['hosts']['host_interstate_wars'])
    at = str(host['next_due'])
    planner._autonomy_interstate(host, 1, at)
    settled = planner.read(path)['theaters']['qin_zhao_gyou']
    treaty_ref = settled.get('last_treaty_ref')
    assert treaty_ref
    assert treaty_ref != previous_treaty_ref
    treaties = planner.read('state/politics/treaties.json')['records']
    treaty = treaties[treaty_ref]
    assert treaty['kind'] == 'ceasefire_and_war_settlement'
    assert treaty['theater_ref'] == 'qin_zhao_gyou'
    assert treaty['terms']['ceasefire'] is True
    assert treaty['terms']['territorial_status']['legal_claim_resolution'] == 'not_implied_by_military_control'
    assert CampaignTime.parse(treaty['truce_until']) > CampaignTime.parse(treaty['signed_at'])
    qin = planner.read('state/states/qin.json')
    assert qin['diplomacy']['state_zhao']['treaty_ref'] == treaty['treaty_ref']


def test_occupation_tracks_displacement_disease_and_food_security_pressure(campaign):
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    planner._occupation_initialize('loc_gyou', 'state_qin', 'state_zhao', at, 'battle_example')
    before = copy.deepcopy(planner.read('state/territory/control.json')['sites']['loc_gyou']['governance'])
    assert before['displacement_pressure'] > 0
    assert before['disease_risk'] > 0
    assert 0 < before['food_security'] < 100
    planner._settle_occupation_administration('qin', 1, _test_time(planner))
    after = planner.read('state/territory/control.json')['sites']['loc_gyou']['governance']
    assert all(key in after for key in ('displacement_pressure', 'disease_risk', 'food_security'))


def test_autonomous_battle_losses_create_saved_state_war_burden(campaign):
    planner = planner_for(campaign); planner._reset()
    before = copy.deepcopy(planner.read('state/states/qin.json'))
    planner._autonomy_apply_battle_losses(
        'formation_qin_mobile_reserve',
        300,
        _test_time(planner),
        losing_side=True,
        opponent_state='zhao',
        seed_material='civil-war-burden-test',
    )
    after = planner.read('state/states/qin.json')
    assert after['war_burden']['casualties_total'] >= 300
    assert after['war_burden']['last_loss']['formation_ref'] == 'formation_qin_mobile_reserve'
    assert after['war_burden']['last_loss']['basis'] == 'conserved autonomous battle losses'
    assert after['internal_stability'] <= before.get('internal_stability', 50)


def test_generic_house_lineage_close_keeps_only_current_lineage_authority(campaign):
    planner = planner_for(campaign); planner._reset()
    ref = 'house_shou_bun_kun_household'
    planner._autonomy_house({'owner_ref': ref, 'recurrence_seconds': 7776000}, 1, _test_time(planner))
    house = planner.read(planner.owner_path(ref))
    runtime = house.get('lineage_runtime', {})
    assert 'branches' not in runtime
    assert 'reviews' not in runtime
    assert 'representation' not in runtime
    assert 'representation' not in house['lineage_cohort']
    assert 'population_backing' not in house['lineage_cohort']


def test_routine_trade_and_credit_do_not_require_named_merchant_registry(campaign):
    planner = planner_for(campaign); planner._reset()
    # Routine trade/credit is aggregate economic activity. Exact merchant Houses
    # materialize only when individually causal; there is no permanent registry
    # that duplicates private-economy cash ownership.
    import pytest
    with pytest.raises((FileNotFoundError, KeyError)):
        planner.read('state/economy/merchant-houses.json')
    owner_index = planner.read('state/index/owner-index.json').get('owners', {})
    assert 'faction_central_merchant_houses' not in owner_index
    for state in ('qin','zhao','chu','wei','han','yan','qi'):
        private = planner.read(f'state/economy/private/{state}.json')
        assert int(private.get('cash_silver', 0)) >= 0
        assert isinstance(private.get('local_economy', private.get('regions', {})), dict)


def test_house_tang_cash_close_is_transfer_based_and_outer_wall_is_unified_house_force(campaign):
    planner = planner_for(campaign); planner._reset()
    owner_index = planner.read('state/index/owner-index.json').get('owners', {})
    for retired in ('force_bastion_iron_wall','force_bastion_red_thunder','force_bastion_white_blade','force_bastion_stone_spear','force_sword_manor'):
        assert retired not in owner_index
    house_force = planner.read(planner.owner_path('force_house_tang'))
    assert int(house_force['headcount']) == 176060
    outer_wall = []
    for formation_ref, route in owner_index.items():
        if not formation_ref.startswith('formation_house_tang_outer_wall_'):
            continue
        row = planner.read(route)
        outer_wall.append(row)
    assert len(outer_wall) == 26
    assert sum(int(row['authorized_strength']) for row in outer_wall) == 110000
    assert all(row.get('owner_force_ref') == 'force_house_tang' for row in outer_wall)
    assert all(row.get('administrative_owner') == 'house_tang' for row in outer_wall)

    treasury_before = int(planner.read('state/treasury/treasury-house-tang.json')['silver'])
    private_before = int(planner.read('state/economy/private/qin.json')['cash_silver'])
    total_before = treasury_before + private_before
    planner._autonomy_house({'owner_ref':'house_tang', 'recurrence_seconds':7776000}, 1, _test_time(planner))
    treasury = planner.read('state/treasury/treasury-house-tang.json')
    private = planner.read('state/economy/private/qin.json')
    assert int(treasury['silver']) + int(private['cash_silver']) == total_before
    outer_wall_payroll = int(treasury['monthly_flow_components']['cash']['outer_wall_defense_payroll_expense_silver'])
    assert outer_wall_payroll > 0
    assert treasury['stable_monthly_flows']['revenue_silver'] < 3000000
    assert treasury['stable_monthly_flows']['expense_silver'] >= outer_wall_payroll

def test_state_monthly_expense_plan_scales_with_exact_force_headcount(campaign):
    planner = planner_for(campaign); planner._reset()
    revenue = sum(int(row['due_silver']) for row in planner._territorial_revenue_plan('qin', 1))
    before = planner._state_monthly_expense_plan('qin', revenue)
    force_path = 'state/forces/state-qin.json'
    force = copy.deepcopy(planner.read(force_path))
    force['headcount'] = int(force['headcount']) + 10000
    planner.put(force_path, force)
    after = planner._state_monthly_expense_plan('qin', revenue)
    assert after['military_headcount'] == before['military_headcount'] + 10000
    assert after['military_due_silver'] > before['military_due_silver']
    assert after['total_due_silver'] > before['total_due_silver']



def test_state_threat_can_be_bound_to_exact_information_and_operation_basis(campaign):
    execute_production_internal(campaign, 'information_create', {
        'information_ref': 'information_threat_basis_test',
        'claim': 'A Qin force is reported preparing for frontier action.',
        'knowers': ['char_riboku'],
        'confidence': '0.8',
        'provenance': 'scout report',
    }, request_id='civil-info-create')
    execute_production_internal(campaign, 'state_action', {
        'state': 'zhao',
        'action': 'record_threat',
        'source_state': 'qin',
        'severity': 70,
        'provenance': 'authorized staff assessment from exact report',
        'information_ref': 'information_threat_basis_test',
    }, request_id='civil-info-threat')
    planner = planner_for(campaign); planner._reset()
    zhao = planner.read('state/states/zhao.json')
    threat = zhao['known_threats']['qin']
    assert threat['information_ref'] == 'information_threat_basis_test'
    assert 'information_threat_basis_test' in zhao['known_information_refs']
    host = planner.read('state/runtime.json')['hosts']['host_state_zhao']
    fields = planner._operation_plan_fields(
        state='zhao', threat_ref='qin', threat_value=threat, selected=[],
        admin=int(zhao.get('administrative_capacity', 0)), host=host,
        at=str(planner.read('state/runtime.json')['world_time']),
    )
    assert fields['intelligence_basis']['exact_information_refs'] == ['information_threat_basis_test']


def test_infrastructure_project_completes_as_exact_physical_work_without_creating_population(campaign):
    from types import SimpleNamespace
    planner = planner_for(campaign); planner._reset()
    before_infra = copy.deepcopy(planner.read('state/infrastructure/settlements.json'))
    before_pop = int(planner.read('state/population/qin.json')['population_total'])
    before_kanyou = copy.deepcopy(before_infra['sites']['loc_kanyou'])
    meta = planner.read('state/meta.json')
    command = SimpleNamespace(command_type='institution_project', digest='physicalwell123456', semantic_digest='physicalwell123456', actor_id='internal:sword-autonomy', expected_revision=int(meta['revision']), submitted_at=str(meta['time']))
    result = planner._start_funded_institution_project(command, {
        'institution_ref': 'inst_qin_fortification_bureau',
        'project_ref': 'project_kanyou_public_wells',
        'duration_hours': 168,
        'kind': 'infrastructure',
        'magnitude': 1,
        'effect': {'infrastructure_blueprint_ref':'settlement_public_well_cluster','target_site_ref':'loc_kanyou'},
    })
    assert result['reserved_inputs']['construction_material_units'] == 990
    inst = copy.deepcopy(planner.read(planner.owner_path('inst_qin_fortification_bureau')))
    project = next(row for row in inst['projects'] if row['project_ref']=='project_kanyou_public_wells')
    assert project['physical_work_spec']['works_add']['public_wells'] == 6.0
    planner._resolve_funded_project(inst, project, project['completes_at'])
    planner.put(planner.owner_path('inst_qin_fortification_bureau'), inst)
    after = planner.read('state/infrastructure/settlements.json')['sites']['loc_kanyou']
    assert after['physical_support']['water_capacity_people'] == before_kanyou['physical_support']['water_capacity_people'] + 1000
    assert after['works']['public_wells'] == before_kanyou.get('works',{}).get('public_wells',0) + 6
    assert after['constructed_works']['project_kanyou_public_wells']['blueprint_ref'] == 'settlement_public_well_cluster'
    assert int(planner.read('state/population/qin.json')['population_total']) == before_pop


def test_physical_infrastructure_cost_is_derived_from_geometry_labor_and_transport(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.infrastructure_projects import infrastructure_work_spec, calculate_project_schedule
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    work = infrastructure_work_spec(planner.read, blueprint_ref='settlement_housing_courtyard_block', target_site_ref='loc_kanyou', quantity=1)
    assert 'pricing_model' not in work
    assert work['construction_material_units'] > 0
    assert work['material_equivalent_tonnes'] > 0
    assert work['labor_hours'] == sum(work['labor_hours_by_class'].values())
    assert work['silver_cost'] == int(__import__('math').ceil(sum(work['cash_cost_breakdown'].values())))
    assert work['support_capacity_add']['housing_capacity_people'] == 1000
    schedule = calculate_project_schedule(planner.read, work=work, available_workers=1000)
    assert schedule['construction_workers'] <= work['workfront_capacity_workers']
    assert schedule['duration_hours'] >= work['minimum_calendar_hours']
    # 220k labor-hours cannot be completed by ~1k workers as though they work 24h/day.
    assert schedule['labor_calendar_hours'] >= 600


def test_quarterly_state_settlement_review_selects_real_bottleneck_and_reserves_inputs(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.settlement_development import settle_state_settlement_development
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    infra = copy.deepcopy(planner.read('state/infrastructure/settlements.json'))
    site = infra['sites']['loc_kanyou']
    # Make water the only severe physical bottleneck without changing population.
    residents = planner.read('state/population/qin.json')['local_population']['sites']['loc_kanyou']['civilian_population']
    site['physical_support']['water_capacity_people'] = max(1, residents // 2)
    site['development_profile'] = {'review_month_accumulator': 2}
    planner.put('state/infrastructure/settlements.json', infra)
    treasury_before = planner.read('state/states/qin.json')['treasury_silver']
    local_before = planner.read('state/economy/private/qin.json')['local_regions']['regions']['loc_kanyou']['commodity_stock']['construction_material_units']
    result = settle_state_settlement_development(planner, state='qin', at=str(planner.read('state/runtime.json')['world_time']), occurrences=1)
    assert result['reviewed_sites'] >= 1
    after = planner.read('state/infrastructure/settlements.json')['sites']['loc_kanyou']
    assert result['started_project_refs']
    project_ref = result['started_project_refs'][0]
    project = after['development_projects'][project_ref]
    assert project['blueprint_ref'] == 'settlement_public_well_cluster'
    assert project['inputs_reserved']['silver'] > 0
    assert project['inputs_reserved']['construction_material_units'] > 0
    assert planner.read('state/states/qin.json')['treasury_silver'] < treasury_before
    local_after = planner.read('state/economy/private/qin.json')['local_regions']['regions']['loc_kanyou']['commodity_stock']['construction_material_units']
    assert local_after < local_before
    runtime = planner.read('state/runtime.json')
    assert any(h.get('kind') == 'settlement_development_project' and h.get('project_ref') == project['project_ref'] for h in runtime['hosts'].values())


def test_settlement_project_completion_uses_exact_due_host_and_changes_capacity(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.settlement_development import settle_state_settlement_development
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    infra = copy.deepcopy(planner.read('state/infrastructure/settlements.json'))
    site = infra['sites']['loc_kanyou']
    residents = planner.read('state/population/qin.json')['local_population']['sites']['loc_kanyou']['civilian_population']
    site['physical_support']['water_capacity_people'] = max(1, residents // 2)
    site['development_profile'] = {'review_month_accumulator': 2}
    before_water = site['physical_support']['water_capacity_people']
    planner.put('state/infrastructure/settlements.json', infra)
    settle_state_settlement_development(planner, state='qin', at=str(planner.read('state/runtime.json')['world_time']), occurrences=1)
    after_start = planner.read('state/infrastructure/settlements.json')['sites']['loc_kanyou']
    project = next(row for row in after_start['development_projects'].values() if row['status'] == 'active')
    host = next(h for h in planner.read('state/runtime.json')['hosts'].values() if h.get('project_ref') == project['project_ref'])
    planner._settle_development_project_for_test = None
    from sword_runtime.settlement_development import settle_development_project
    settled = settle_development_project(planner, host, project['completes_at'])
    assert settled is not None
    after = planner.read('state/infrastructure/settlements.json')['sites']['loc_kanyou']
    assert after['physical_support']['water_capacity_people'] > before_water
    assert after['development_projects'][project['project_ref']]['status'] == 'completed'


def test_private_production_consumes_compact_mobilization_strain_labor_factor(campaign, monkeypatch):
    import sword_runtime.civil_world as civil_world
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    monkeypatch.setattr(
        civil_world,
        'mobilization_strain_snapshot',
        lambda runtime, *, state, at=None: {
            'state': state, 'as_of': at, 'mobilization_strain_milli': 1000,
            'civil_labor_factor_milli': 750, 'rule_ref': 'game/data/mechanics/settlement.json',
        },
    )
    planner._settle_private_production('qin', 1, at)
    _path, eco = planner._private_economy('qin')
    factors = {
        int(row.get('production_runtime', {}).get('last_output', {}).get('mobilization_labor_factor_milli', 1000))
        for row in eco.get('local_regions', {}).get('regions', {}).values()
        if isinstance(row, dict)
    }
    assert factors == {750}
