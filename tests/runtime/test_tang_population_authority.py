from __future__ import annotations

import copy

from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.tang_population import resident_support_capacity, sync_tang_private_population


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def test_tang_estate_uses_nested_sword_manor_resident_capacity(campaign):
    planner = _planner(campaign)
    sites = planner.read('state/infrastructure/settlements.json')['sites']
    ref, capacity = resident_support_capacity(sites, 'loc_tang_manor', 0)
    assert ref == 'loc_tang_inner_walls'
    assert capacity == int(sites['loc_tang_inner_walls']['effective_resident_support_capacity_people'])
    assert capacity >= 2_500_000


def test_tang_detail_is_projection_of_qin_local_civilians(campaign):
    planner = _planner(campaign)
    qin = planner.read('state/population/qin.json')
    tang = planner.read('state/population/tang-manor.json')
    parent = qin['local_population']['sites']['loc_tang_manor']['civilian_population']
    assert parent == tang['population_total'] == sum(tang['strata'].values()) == 719000
    assert tang['demography']['authority'] == 'parent_population_only'
    assert 'birth_rate_per_thousand' not in tang['demography']
    assert 'death_rate_per_thousand' not in tang['demography']


def test_tang_projection_reconciles_after_parent_local_change(campaign):
    planner = _planner(campaign)
    qin = copy.deepcopy(planner.read('state/population/qin.json'))
    row = qin['local_population']['sites']['loc_tang_manor']
    row['civilian_strata']['agricultural'] -= 3
    row['civilian_population'] -= 3
    planner.put('state/population/qin.json', qin)
    sync_tang_private_population(planner, at=str(planner._world_time()), reason='test', evidence_ref='test')
    tang = planner.read('state/population/tang-manor.json')
    assert tang['population_total'] == row['civilian_population']
    assert sum(tang['strata'].values()) == row['civilian_population']


def test_rebaselined_tang_population_has_no_repair_receipt_or_duplicate_host(campaign):
    planner = _planner(campaign)
    mobility = planner.read('state/mobility/population-transit.json')
    assert mobility['cohorts'] == {}
    assert 'settled_receipts' not in mobility
    assert 'last_correction' not in mobility
    assert 'population_owner_paths' not in mobility
    tang = planner.read('state/population/tang-manor.json')
    assert 'last_population_mobility' not in tang
    assert 'last_parent_sync' not in tang
    runtime = planner.read('state/runtime.json')
    assert 'host_population_tang_manor' not in runtime['hosts']
    assert not any(row.get('target_host') == 'host_population_tang_manor' for row in runtime['events'])
