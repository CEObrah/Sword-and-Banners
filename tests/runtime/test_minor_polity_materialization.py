from __future__ import annotations

import copy


def planner_for(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    p = ProductionCampaignPlanner(campaign)
    p._reset()
    return p


def test_living_minor_polities_have_conserved_population_force_mounts_and_land(campaign):
    p = planner_for(campaign)
    specs = {
        'yotanwa_confederation': ('polity_yotanwa_confederation','force_yotanwa_confederation','loc_yotanwa_mountain_confederation'),
        'quanrong': ('polity_quanrong','force_quanrong','loc_quanrong_highlands'),
        'northern_steppe': ('polity_northern_steppe','force_northern_steppe','loc_northern_steppe_confederation'),
    }
    land = p.read('state/development/land.json')
    for key,(polity_ref,force_ref,region_ref) in specs.items():
        pop = p.read(f'state/population/{key}.json')
        force = p.read(p.owner_path(force_ref))
        mounts = p.read(f'state/mounts/{key}.json')
        polity = p.read(p.owner_path(polity_ref))
        assert sum(int(v) for v in pop['strata'].values()) == int(pop['population_total'])
        assert int(force['headcount']) == int(pop['strata']['active_military'])
        assert sum(int(v) for v in mounts['types'].values()) == int(mounts['total'])
        assert region_ref in land['regions']
        assert polity['economy_state_key'] == key


def test_minor_polity_monthly_close_uses_real_land_output_and_universal_tax(campaign):
    p = planner_for(campaign)
    at = str(p.read('state/meta.json')['time'])
    treasury_path = p.owner_path('treasury_yotanwa_confederation')
    before_treasury = copy.deepcopy(p.read(treasury_path))
    p._settle_minor_polity('polity_yotanwa_confederation', 1, at)
    eco = p.read('state/economy/private/yotanwa_confederation.json')
    polity = p.read(p.owner_path('polity_yotanwa_confederation'))
    after_treasury = p.read(treasury_path)
    rt = eco['production_runtime']
    assert rt['last_food_close']['produced_grain_kg'] > 0
    assert rt['last_gross_output_value_silver'] > 0
    assert polity['civil_finance']['universal_tax_rate'] == 0.1
    assert polity['civil_finance']['food_settled_by_private_production'] is True
    before_balance = int(before_treasury.get('silver', before_treasury.get('treasury_silver', 0)))
    after_balance = int(after_treasury.get('silver', after_treasury.get('treasury_silver', 0)))
    assert after_balance >= before_balance


def test_minor_polity_world_arc_preparation_spends_its_own_treasury_into_its_own_economy(campaign):
    p = planner_for(campaign)
    at = str(p.read('state/meta.json')['time'])
    tp = p.owner_path('treasury_northern_steppe')
    before_t = copy.deepcopy(p.read(tp))
    before_e = copy.deepcopy(p.read('state/economy/private/northern_steppe.json'))
    result = p._world_arc_polity_action('polity_northern_steppe','state_zhao','secure frontier leverage',at,'arc_test_steppe')
    assert result['status'] == 'work_queued'
    after_t = p.read(tp); after_e = p.read('state/economy/private/northern_steppe.json')
    before_balance = int(before_t.get('silver', before_t.get('treasury_silver', 0)))
    after_balance = int(after_t.get('silver', after_t.get('treasury_silver', 0)))
    assert after_balance < before_balance
    assert int(after_e['cash_silver']) > int(before_e['cash_silver'])
    assert result['preparation_evidence']['payee_ref'] == 'private_economy_northern_steppe'
