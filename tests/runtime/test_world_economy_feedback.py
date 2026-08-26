from __future__ import annotations

import copy


def planner_for(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    p = ProductionCampaignPlanner(campaign)
    p._reset()
    return p


def test_all_major_states_settle_regional_land_and_labor_into_real_stock(campaign):
    p = planner_for(campaign)
    at = str(p.read('state/meta.json')['time'])
    for state in ('qin','zhao','chu','wei','han','yan','qi'):
        before = copy.deepcopy(p.read(f'state/economy/private/{state}.json'))
        p._settle_private_production(state, 1, at)
        eco = p.read(f'state/economy/private/{state}.json')
        rt = eco['production_runtime']
        assert rt['last_food_close']['produced_grain_kg'] > 0
        assert rt['last_food_close']['grain_due_kg'] > 0
        assert rt['last_gross_output_value_silver'] > 0
        assert rt['last_taxable_output_value_silver'] > 0
        assert rt['last_taxable_output_value_silver'] < rt['last_gross_output_value_silver']
        assert eco['commodity_stock']['grain_kg'] >= 0
        assert eco['commodity_stock']['construction_material_units'] >= before['commodity_stock']['construction_material_units']
        # Baseline represented states have enough current productive land/labor to feed civilians.
        assert rt['last_food_close']['grain_shortfall_kg'] == 0


def test_unsold_output_is_stock_not_a_completed_cash_sale(campaign):
    p = planner_for(campaign)
    at = str(p.read('state/meta.json')['time'])
    before = p.read('state/economy/private/zhao.json')
    pending_cash_sales = sum(
        max(0, int(row.get('production_runtime', {}).get('realized_sales_since_last_close_silver', 0)))
        for row in before['local_regions']['regions'].values()
    )
    # The live checkpoint may already contain exact cash-paid procurement/contract
    # sales waiting for the next fiscal close. Those are legitimate realization
    # evidence. Fresh production itself must not mint a sale merely by entering
    # stock.
    p._settle_private_production('zhao', 1, at)
    eco = p.read('state/economy/private/zhao.json')
    rt = eco['production_runtime']
    assert rt['last_realized_sales_silver'] == pending_cash_sales
    assert rt['last_taxable_output_value_silver'] < rt['last_gross_output_value_silver']
    assert all(
        max(0, int(row.get('production_runtime', {}).get('realized_sales_since_last_close_silver', 0))) == 0
        for row in eco['local_regions']['regions'].values()
    )
    assert rt['last_realized_sales_silver'] == pending_cash_sales


def test_cash_paid_private_sale_becomes_next_close_realization_evidence(campaign):
    p = planner_for(campaign)
    at = str(p.read('state/meta.json')['time'])
    path, eco = p._private_economy('wei')
    _ref, region = p._local_economy_region('wei', eco, 'loc_dairyou')
    p._record_private_realized_sale(region, amount_silver=1234, at=at, kind='test_sale', resource='grain_kg', quantity=100)
    p._write_private_economy(path, eco)
    p._settle_private_production('wei', 1, at)
    after = p.read(path)
    local = after['local_regions']['regions']['loc_dairyou']['production_runtime']
    assert after['production_runtime']['last_realized_sales_silver'] >= 1234
    assert local.get('realized_sales_since_last_close_silver', 0) == 0


def test_grain_price_responds_to_conserved_stock_cover_and_shortfall(campaign):
    p = planner_for(campaign)
    _path, eco = p._private_economy('han')
    _ref, region = p._local_economy_region('han', eco, 'loc_han_capital')
    region.setdefault('production_runtime', {})['last_food_close'] = {
        'grain_due_kg': 1_000_000,
        'grain_shortfall_kg': 500_000,
    }
    region.setdefault('commodity_stock', {})['grain_kg'] = 100_000
    high, basis = p._regional_commodity_unit_price(region, 'grain_kg', 0.08)
    region['production_runtime']['last_food_close']['grain_shortfall_kg'] = 0
    region['commodity_stock']['grain_kg'] = 6_000_000
    low, low_basis = p._regional_commodity_unit_price(region, 'grain_kg', 0.08)
    assert high > 0.08
    assert low < high
    assert basis['scarcity_factor'] > low_basis['scarcity_factor']


def test_food_failure_blocks_new_regular_force_authorization(campaign):
    p = planner_for(campaign)
    state = copy.deepcopy(p.read('state/states/qin.json'))
    state['known_threats'] = {'test': {'severity': 100}}
    state['mobilization_readiness'] = 100
    path, eco = p._private_economy('qin')
    eco.setdefault('production_runtime', {})['last_food_close'] = {
        'grain_due_kg': 100_000,
        'grain_shortfall_kg': 25_000,
    }
    p._write_private_economy(path, eco)
    result = p._review_state_force_authorization_growth(
        state='qin', state_doc=state, at=str(p.read('state/meta.json')['time']), occurrences=1,
        monthly_expense_due=0,
    )
    assert result['changed'] is False
    assert result['reason'] == 'civilian_food_supply_below_force_growth_floor'
