from __future__ import annotations
import copy


def test_jo_city_parcel_is_expandable_with_conserved_regional_land(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.land_development import expand_site_parcel, validate_land_registry, wall_expansion_work_spec
    planner = ProductionCampaignPlanner(campaign)
    land = copy.deepcopy(planner.read('state/development/land.json'))
    region = land['regions']['loc_jo_mountain_region']
    site = land['sites']['loc_jo_city']
    old_parcel = float(site['parcel_area_km2'])
    old_open = float(region['land_use_km2']['open_developable'])
    old_nested = float(region['nested_site_parcels_km2'])
    result = expand_site_parcel(land, site_ref='loc_jo_city', area_km2=5.0)
    assert result['parcel_area_km2'] == round(old_parcel + 5.0, 6)
    assert land['regions']['loc_jo_mountain_region']['land_use_km2']['open_developable'] == round(old_open - 5.0, 6)
    assert land['regions']['loc_jo_mountain_region']['nested_site_parcels_km2'] == round(old_nested + 5.0, 6)
    assert land['sites']['loc_jo_city']['external_land_use_km2']['open_developable'] >= 5.0
    assert validate_land_registry(land) == []
    # Once adjacent parcel land exists, the same universal wall physics can quote
    # an enclosure expansion rather than treating the seed parcel as a cap.
    planner.put('state/development/land.json', land)
    spec = wall_expansion_work_spec(planner.read, site_ref='loc_jo_city', add_area_km2=1.0)
    assert spec['add_area_km2'] == 1.0
    assert spec['geometry_change']['new_wall_construction_km'] > 0
    assert spec['silver_cost'] > 0


def test_private_house_grant_can_expand_existing_estate_without_free_land(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.land_development import grant_house_land, expand_site_parcel, validate_land_registry
    planner = ProductionCampaignPlanner(campaign)
    land = copy.deepcopy(planner.read('state/development/land.json'))
    region = land['regions']['loc_qin_regional_01']
    old_open = float(region['land_use_km2']['open_developable'])
    old_nested = float(region['nested_site_parcels_km2'])
    old_parcel = float(land['sites']['loc_tang_manor']['parcel_area_km2'])
    grant_house_land(
        land, house_ref='house_tang', region_ref='loc_qin_regional_01', area_km2=10.0,
        grant_ref='test_adjacent_tang_grant', adjacent_to_holding_ref='holding_house_tang_tang_manor',
    )
    assert land['regions']['loc_qin_regional_01']['land_use_km2']['open_developable'] == round(old_open - 10.0, 6)
    assert land['regions']['loc_qin_regional_01']['land_use_km2']['private_holdings'] == 10.0
    expand_site_parcel(land, site_ref='loc_tang_manor', area_km2=10.0)
    assert land['sites']['loc_tang_manor']['parcel_area_km2'] == round(old_parcel + 10.0, 6)
    assert land['regions']['loc_qin_regional_01']['nested_site_parcels_km2'] == round(old_nested + 10.0, 6)
    assert land['regions']['loc_qin_regional_01']['land_use_km2'].get('private_holdings', 0) == 0.0
    assert validate_land_registry(land) == []


def test_jo_frontiers_are_claimed_adjacent_regions_not_free_wilderness(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.land_development import adjacent_regions, strategic_region_frontiers
    planner = ProductionCampaignPlanner(campaign)
    neighbors = set(adjacent_regions(planner.read, 'loc_jo_mountain_region'))
    assert {'loc_chu_regional_02', 'loc_wei_regional_03', 'loc_zhao_regional_04'} <= neighbors
    jo_rows = [r for r in strategic_region_frontiers(planner.read) if 'loc_jo_mountain_region' in {r['region_a_ref'], r['region_b_ref']}]
    assert len(jo_rows) == 3
    assert all(r['unclaimed_gap_implied'] is False for r in jo_rows)


def test_tang_manor_6000_500_50_nested_land_capacity_and_commute_are_physical(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.land_development import (
        enclosure_chain, nested_site_children, productive_labor_access_factor,
        validate_land_registry,
    )
    planner = ProductionCampaignPlanner(campaign)
    land = planner.read('state/development/land.json')
    assert validate_land_registry(land) == []
    tang = land['sites']['loc_tang_manor']
    sword = land['sites']['loc_tang_inner_walls']
    inner = land['sites']['loc_tang_inner_citadel']
    assert tang['parcel_area_km2'] == tang['enclosed_area_km2'] == 6000
    assert sword['parcel_area_km2'] == sword['enclosed_area_km2'] == 500
    assert inner['parcel_area_km2'] == inner['enclosed_area_km2'] == 50
    assert nested_site_children(land, 'loc_tang_manor') == ['loc_tang_inner_walls']
    assert nested_site_children(land, 'loc_tang_manor', recursive=True) == ['loc_tang_inner_walls', 'loc_tang_inner_citadel']
    assert enclosure_chain(land, 'loc_tang_inner_citadel') == ['loc_tang_manor', 'loc_tang_inner_walls', 'loc_tang_inner_citadel']
    assert sum(tang['enclosed_land_use_km2'].values()) + sword['parcel_area_km2'] == 6000
    assert sum(sword['enclosed_land_use_km2'].values()) + inner['parcel_area_km2'] == 500
    assert sum(inner['enclosed_land_use_km2'].values()) == 50

    master = planner.read('game/data/world/tang-manor-master-plan.json')
    assert master['survey_geometry']['enclosed_area_km2'] == 6000
    infra = planner.read('state/infrastructure/settlements.json')
    sword_support = infra['sites']['loc_tang_inner_walls']
    inner_support = infra['sites']['loc_tang_inner_citadel']
    assert sword_support['physical_support']['housing_capacity_people'] == 2_500_000
    assert sword_support['military_support']['permanent_bed_capacity_people'] == 350_000
    assert sword_support['training_support']['simultaneous_trainee_capacity'] == 500_000
    assert inner_support['military_support']['permanent_bed_capacity_people'] == 50_000

    pop = planner.read('state/population/tang-manor.json')
    assert pop['population_total'] == sum(int(value) for value in pop['strata'].values())
    assert pop['population_total'] <= sword_support['physical_support']['housing_capacity_people']
    rules = planner.read('game/data/mechanics/land-development.json')
    access = productive_labor_access_factor(land, site_ref='loc_tang_manor', commuting_workers=159_400, rules=rules)
    assert access['factor'] == 1.0
    assert access['gate_capacity_workers_per_outbound_window'] == 162_000
    constrained = copy.deepcopy(land)
    constrained['sites']['loc_tang_inner_walls']['fortification']['gate_count'] = 6
    access2 = productive_labor_access_factor(constrained, site_ref='loc_tang_manor', commuting_workers=159_400, rules=rules)
    assert access2['factor'] < 1.0


def test_regional_productive_land_has_local_labor_access(campaign):
    from sword_runtime.land_development import productive_labor_access_factor
    import json
    land = json.loads((campaign / 'state/development/land.json').read_text())
    rules = json.loads((campaign / 'game/data/mechanics/land-development.json').read_text())
    access = productive_labor_access_factor(land, site_ref='loc_zhao_regional_01', commuting_workers=100000, rules=rules)
    assert access['factor'] == 1.0
    assert access['access_basis'] == 'regional_hinterland_local_residence'
