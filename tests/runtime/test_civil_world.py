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
    inst0 = planner.read('state/institutions/inst_qin_fortification_bureau.json')
    _site_ref, region = planner._local_economy_region('qin', eco, str(inst0.get('location_ref', '')))
    for row in eco['local_regions']['regions'].values():
        row.setdefault('commodity_stock', {})['construction_material_units'] = 0
    region['commodity_stock']['construction_material_units'] = 1000
    planner._sync_local_economy_aggregate(eco); planner._write_private_economy(ep, eco)
    before_state = copy.deepcopy(planner.read('state/states/qin.json')); before_cash = int(eco['cash_silver'])
    meta = planner.read('state/meta.json'); command = SimpleNamespace(command_type='institution_project', digest='0123456789abcdef', actor_id='internal:sword-autonomy', expected_revision=int(meta['revision']), submitted_at=str(meta['time']))
    result = planner._start_funded_institution_project(command, {
        'institution_ref': 'inst_qin_fortification_bureau',
        'project_ref': 'project_causal_materials',
        'duration_hours': 24,
        'kind': 'construction',
        'magnitude': 2,
    })
    state = planner.read('state/states/qin.json'); after_eco = planner.read(ep); inst = planner.read('state/institutions/inst_qin_fortification_bureau.json')
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
    path = 'state/factions/faction_qin_ryofui_network.json'; before = copy.deepcopy(planner.read(path))
    before.setdefault('resources', {})['influence'] = max(16, int(before.get('resources', {}).get('influence', 0)))
    before['pressure'] = max(30, int(before.get('pressure', 0)))
    planner.put(path, before)
    planner._autonomy_faction({'owner_ref':'faction_qin_ryofui_network'}, 6, _test_time(planner))
    after = planner.read(path)
    assert after['goals'] != ['preserve influence', 'advance current interests']
    assert after['resources']['funds_silver'] < before['resources']['funds_silver']
    assert after['commitments'][-1]['action'] == 'patronage_lobbying'
    assert planner.read('state/states/qin.json')['political_pressure']['faction_qin_ryofui_network']['kind'] == 'patronage_lobbying'


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


def test_nonstate_faction_actions_touch_real_linked_owners(campaign):
    planner = planner_for(campaign); planner._reset()
    qin_path = 'state/states/qin.json'; qin = copy.deepcopy(planner.read(qin_path)); qin['known_threats']['broker_test'] = {'severity': 70, 'kind': 'border'}; planner.put(qin_path, qin)
    planner._autonomy_faction({'owner_ref':'faction_mercenary_brokers'}, 6, _test_time(planner))
    broker = planner.read('state/factions/faction_mercenary_brokers.json')
    assert broker['commitments'][-1]['action'] == 'broker_contracts'
    assert broker['commitments'][-1]['effect']['status'] in {'offer_created', 'no_available_affordable_company'}
    if broker['commitments'][-1]['effect']['status'] == 'offer_created':
        company_ref = broker['commitments'][-1]['effect']['company_ref']
        company = planner.read(planner.owner_path(company_ref))
        assert any(c.get('broker_ref') == 'faction_mercenary_brokers' for c in company['contracts'])

    market_path = 'state/markets/kanyou.json'; market = copy.deepcopy(planner.read(market_path)); market['insecurity_hoarding_factor'] = 1.4; planner.put(market_path, market)
    planner._autonomy_faction({'owner_ref':'faction_river_transport_leagues'}, 6, _test_time(planner))
    river = planner.read('state/factions/faction_river_transport_leagues.json')
    assert river['commitments'][-1]['effect']['status'] == 'route_reliability_improved'
    touched = planner.read(planner.owner_path(river['commitments'][-1]['effect']['market_ref']))
    assert touched['insecurity_hoarding_factor'] < 1.4

    planner._autonomy_faction({'owner_ref':'faction_martial_school_networks'}, 6, _test_time(planner))
    school = planner.read('state/factions/faction_martial_school_networks.json')
    assert school['resources']['available_instruction_slots'] > 0
    assert 'no skill gain' in school['commitments'][-1]['effect']['rule']

    planner._autonomy_faction({'owner_ref':'faction_yotanwa_confederation'}, 6, _test_time(planner))
    yotanwa = planner.read('state/factions/faction_yotanwa_confederation.json')
    assert yotanwa['resources']['muster_readiness'] > 0
    assert 'does not create troops' in yotanwa['commitments'][-1]['effect']['rule']


def test_state_institutions_publish_specialized_exact_reviews(campaign):
    planner = planner_for(campaign); planner._reset()
    at = _test_time(planner)
    planner._autonomy_institution({'owner_ref':'inst_qin_military_bureau'}, 1, at)
    military = planner.read('state/institutions/inst_qin_military_bureau.json')
    assert 'commander_vacancies' in military['military_review']
    assert planner.read('state/states/qin.json')['military_administration']['last_review'] == at

    planner._autonomy_institution({'owner_ref':'inst_qin_fortification_bureau'}, 1, at)
    fort = planner.read('state/institutions/inst_qin_fortification_bureau.json')
    assert 'funded local-material' in fort['fortification_review']['rule']

    planner._autonomy_institution({'owner_ref':'inst_qin_recruitment_office'}, 1, at)
    recruit = planner.read('state/institutions/inst_qin_recruitment_office.json')
    assert recruit['recruitment_review']['office_capacity'] == recruit['capacity']
    assert 'does not create recruits' in recruit['recruitment_review']['rule']


def test_interstate_peace_creates_first_class_treaty_terms(campaign):
    planner = planner_for(campaign); planner._reset()
    path = planner.owner_path('interstate_warring_states')
    world = copy.deepcopy(planner.read(path))
    record = world['theaters']['qin_zhao_gyou']
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
    treaties = planner.read('state/politics/treaties.json')['records']
    assert treaties
    treaty = next(iter(treaties.values()))
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


def test_generic_house_lineage_close_keeps_aggregate_branch_provenance(campaign):
    planner = planner_for(campaign); planner._reset()
    ref = 'house_shou_bun_kun_household'
    planner._autonomy_house({'owner_ref': ref, 'recurrence_seconds': 7776000}, 1, _test_time(planner))
    house = planner.read(planner.owner_path(ref))
    runtime = house['lineage_runtime']
    assert runtime['representation'].startswith('aggregate household branches')
    assert runtime['branches']['household_core']['adults'] == house['lineage_cohort']['adults']
    assert runtime['reviews'][-1]['basis'].startswith('aggregate lineage close')


def test_merchant_houses_extend_and_recover_conserved_private_credit(campaign):
    planner = planner_for(campaign); planner._reset()
    registry_before = copy.deepcopy(planner.read('state/economy/merchant-houses.json'))
    private_paths = [f'state/economy/private/{state}.json' for state in ('qin','zhao','chu','wei','han','yan','qi')]
    private_before = {path: int(planner.read(path)['cash_silver']) for path in private_paths}
    liquid_before = sum(int(row['capital_silver']) for row in registry_before['houses'].values())
    planner._autonomy_faction({'owner_ref':'faction_central_merchant_houses'}, 6, _test_time(planner))
    faction = planner.read('state/factions/faction_central_merchant_houses.json')
    effect = faction['commitments'][-1]['effect']
    assert effect['status'] == 'credit_extended'
    registry_after = planner.read('state/economy/merchant-houses.json')
    liquid_after = sum(int(row['capital_silver']) for row in registry_after['houses'].values())
    target_path = f"state/economy/private/{effect['state']}.json"
    assert liquid_before - liquid_after == effect['principal_silver']
    assert int(planner.read(target_path)['cash_silver']) - private_before[target_path] == effect['principal_silver']
    planner._settle_merchant_credit(effect['state'], 1, '244-BCE-01-31T00:00:00+08:00')
    repaid_registry = planner.read('state/economy/merchant-houses.json')
    lender = repaid_registry['houses'][effect['merchant_house_ref']]
    loan = next(row for row in lender['loans'] if row['loan_ref'] == effect['loan_ref'])
    assert loan['repaid_silver'] > 0
    assert loan['outstanding_silver'] < loan['principal_silver']


def test_house_tang_cash_close_is_transfer_based_and_bastions_are_permanent_house_forces(campaign):
    planner = planner_for(campaign); planner._reset()
    bastion_refs = [
        'force_bastion_iron_rampart', 'force_bastion_red_crane',
        'force_bastion_white_lantern', 'force_bastion_deep_earth',
    ]
    bastions = [planner.read(planner.owner_path(ref)) for ref in bastion_refs]
    assert sum(int(row['headcount']) for row in bastions) == 110000
    assert all(row.get('administrative_owner') == 'house_tang' for row in bastions)
    assert all(row.get('kind') == 'house_military_institution' for row in bastions)
    assert all(not row.get('contract_ref') for row in bastions)

    treasury_before = int(planner.read('state/treasury/treasury-house-tang.json')['silver'])
    private_before = int(planner.read('state/economy/private/qin.json')['cash_silver'])
    total_before = treasury_before + private_before
    planner._autonomy_house({'owner_ref':'house_tang', 'recurrence_seconds':7776000}, 1, _test_time(planner))
    treasury = planner.read('state/treasury/treasury-house-tang.json')
    private = planner.read('state/economy/private/qin.json')
    assert int(treasury['silver']) + int(private['cash_silver']) == total_before
    finance = treasury['civil_finance']
    assert finance['cash_close_rule'].startswith('all realized revenue')
    assert finance['bastion_payroll_due_silver'] == treasury['monthly_flow_components']['cash']['bastion_corps_payroll_expense_silver'] * int(finance['months'])
    assert finance['bastion_payroll_due_silver'] > 0
    assert finance['monthly_fiscal_plan']['civilian_population'] == 725000
    assert treasury['stable_monthly_flows']['revenue_silver'] < 3000000
    assert treasury['stable_monthly_flows']['expense_silver'] < treasury['stable_monthly_flows']['revenue_silver']


def test_state_tax_capacity_scales_with_real_local_population_without_growth_cap(campaign):
    planner = planner_for(campaign); planner._reset()
    before = {row['location_ref']: row for row in planner._territorial_revenue_plan('qin', 1)}
    pop_path = 'state/population/qin.json'
    pop = copy.deepcopy(planner.read(pop_path))
    target = pop['local_population']['sites']['loc_bu_pass']
    source = pop['local_population']['sites']['loc_kanyou']
    moved = 100000
    assert int(source['civilian_strata']['agricultural']) >= moved
    target['civilian_strata']['agricultural'] = int(target['civilian_strata']['agricultural']) + moved
    source['civilian_strata']['agricultural'] = int(source['civilian_strata']['agricultural']) - moved
    planner._sync_local_population_row(target); planner._sync_local_population_row(source)
    planner.put(pop_path, pop)
    after = {row['location_ref']: row for row in planner._territorial_revenue_plan('qin', 1)}
    assert after['loc_bu_pass']['local_population_factor'] > 1.25
    assert after['loc_bu_pass']['due_silver'] > before['loc_bu_pass']['due_silver'] * 1.25
    # Repartitioning the same civilians changes location dues but does not create a new national tax base.
    assert abs(sum(r['due_silver'] for r in after.values()) - sum(r['due_silver'] for r in before.values())) <= 2


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


def test_house_tang_fiscal_plan_scales_with_civilians_and_bastion_strength(campaign):
    planner = planner_for(campaign); planner._reset()
    before = planner._house_tang_monthly_fiscal_plan()
    pop_path = 'state/population/tang-manor.json'
    pop = copy.deepcopy(planner.read(pop_path)); pop['population_total'] = int(pop['population_total']) + 1000; planner.put(pop_path, pop)
    after_population = planner._house_tang_monthly_fiscal_plan()
    assert after_population['revenue_silver'] - before['revenue_silver'] == 2800
    force_path = planner.owner_path('force_bastion_iron_rampart')
    force = copy.deepcopy(planner.read(force_path)); force['headcount'] = int(force['headcount']) - 1000; planner.put(force_path, force)
    after_force = planner._house_tang_monthly_fiscal_plan()
    assert after_force['bastion_corps_payroll_expense_silver'] < after_population['bastion_corps_payroll_expense_silver']


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
    command = SimpleNamespace(command_type='institution_project', digest='physicalwell123456', actor_id='internal:sword-autonomy', expected_revision=int(meta['revision']), submitted_at=str(meta['time']))
    result = planner._start_funded_institution_project(command, {
        'institution_ref': 'inst_qin_fortification_bureau',
        'project_ref': 'project_kanyou_public_wells',
        'duration_hours': 168,
        'kind': 'infrastructure',
        'magnitude': 1,
        'effect': {'infrastructure_blueprint_ref':'settlement_public_well_cluster','target_site_ref':'loc_kanyou'},
    })
    assert result['reserved_inputs']['construction_material_units'] == 1000
    inst = copy.deepcopy(planner.read('state/institutions/inst_qin_fortification_bureau.json'))
    project = next(row for row in inst['projects'] if row['project_ref']=='project_kanyou_public_wells')
    assert project['physical_work_spec']['works_add']['public_wells'] == 6.0
    planner._resolve_funded_project(inst, project, project['completes_at'])
    planner.put('state/institutions/inst_qin_fortification_bureau.json', inst)
    after = planner.read('state/infrastructure/settlements.json')['sites']['loc_kanyou']
    assert after['physical_support']['water_capacity_people'] == before_kanyou['physical_support']['water_capacity_people'] + 1000
    assert after['works']['public_wells'] == before_kanyou.get('works',{}).get('public_wells',0) + 6
    assert after['constructed_works']['project_kanyou_public_wells']['blueprint_ref'] == 'settlement_public_well_cluster'
    assert int(planner.read('state/population/qin.json')['population_total']) == before_pop
