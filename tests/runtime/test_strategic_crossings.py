from __future__ import annotations

import json

from sword_runtime.geography import route_is_usable
from sword_runtime.operational_logistics import formation_movement_profile, route_operational_profile
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.strategic_crossings import crossing_operational_profile

from conftest import execute_production_internal


def _route(planner, ref):
    return next(r for r in planner.read('game/data/world/routes.json')['routes'] if r['ref'] == ref)


def test_four_strategic_river_crossings_have_exact_cold_blueprints_and_one_mutable_owner(campaign):
    planner=ProductionCampaignPlanner(campaign); planner._reset()
    routes=planner.read('game/data/world/routes.json')['routes']
    water=[r for r in routes if isinstance(r.get('water_crossing'),dict)]
    assert {r['ref'] for r in water} == {
        'route_chu_heartland_east','route_zhao_west_retsubi','route_retsubi_gyou','route_chu_east_ei'
    }
    state=planner.read('state/geography/strategic-crossings.json')
    assert state['authority'] is True
    assert state['geography']['owns_local_population'] is False
    assert set(state['crossings']) == {r['ref'] for r in water}
    assert _route(planner,'route_chu_heartland_east')['water_crossing']['river_width_m'] == 210.0
    assert _route(planner,'route_zhao_west_retsubi')['water_crossing']['bridge_span_m'] == 96.0
    assert _route(planner,'route_retsubi_gyou')['water_crossing']['ferry_boats'] == 14
    assert _route(planner,'route_chu_east_ei')['water_crossing']['crossing_type'] == 'capital_approach_bridge_with_ferry_support'


def test_bridge_damage_reduces_real_route_throughput_without_capping_army_size(campaign):
    planner=ProductionCampaignPlanner(campaign); planner._reset()
    ref='route_zhao_west_retsubi'; route=_route(planner,ref)
    baseline=route_operational_profile(planner.read,[ref])
    crossing0=crossing_operational_profile(planner.read,route)
    assert baseline['daily_troop_throughput'] < route['physical_geometry']['daily_troop_throughput']
    assert crossing0['bridge_condition_percent'] == 100.0

    execute_production_internal(campaign,'strategic_crossing_action',{'route_ref':ref,'action':'damage_bridge','amount':60},request_id='crossing-damage-bridge')
    planner=ProductionCampaignPlanner(campaign); planner._reset(); route=_route(planner,ref)
    damaged=route_operational_profile(planner.read,[ref])
    crossing1=crossing_operational_profile(planner.read,route)
    assert crossing1['bridge_condition_percent'] == 40.0
    assert 0 < damaged['daily_troop_throughput'] < baseline['daily_troop_throughput']
    assert 0 < damaged['daily_wagon_throughput'] < baseline['daily_wagon_throughput']

    owners=planner.read('state/index/owner-index.json')['owners']
    formation=planner.read(owners['formation_zhao_retsubi_garrison']) if 'formation_zhao_retsubi_garrison' in owners else planner.read(next(path for ref2,path in owners.items() if ref2.startswith('formation_')))
    move_route={'route_refs':[ref],'duration_hours':8}
    profile=formation_movement_profile(planner.read,formation,move_route)
    assert profile['personnel'] == int(formation['personnel'])
    assert profile['column_clearance_hours'] > 0
    assert profile['rule'].startswith('Route throughput never caps army size')


def test_destroyed_bridge_and_ferries_close_crossing_until_physical_alternative_exists(campaign):
    ref='route_zhao_west_retsubi'
    execute_production_internal(campaign,'strategic_crossing_action',{'route_ref':ref,'action':'damage_bridge','amount':100},request_id='crossing-destroy-bridge')
    execute_production_internal(campaign,'strategic_crossing_action',{'route_ref':ref,'action':'damage_ferries','quantity':10},request_id='crossing-destroy-ferries')
    planner=ProductionCampaignPlanner(campaign); planner._reset(); route=_route(planner,ref)
    profile=crossing_operational_profile(planner.read,route)
    assert profile['daily_troop_throughput'] == 0
    assert profile['daily_wagon_throughput'] == 0
    assert route_is_usable(planner.read,route) is False

    execute_production_internal(campaign,'strategic_crossing_action',{'route_ref':ref,'action':'set_water_stage','water_stage':'low'},request_id='crossing-low-water')
    execute_production_internal(campaign,'strategic_crossing_action',{'route_ref':ref,'action':'open_ford'},request_id='crossing-open-ford')
    planner=ProductionCampaignPlanner(campaign); planner._reset(); route=_route(planner,ref)
    reopened=crossing_operational_profile(planner.read,route)
    assert reopened['ford_open'] is True
    assert reopened['daily_troop_throughput'] > 0
    assert reopened['daily_wagon_throughput'] > 0
    assert route_is_usable(planner.read,route) is True


def test_flood_closes_ferries_but_does_not_magically_destroy_bridge(campaign):
    ref='route_retsubi_gyou'
    execute_production_internal(campaign,'strategic_crossing_action',{'route_ref':ref,'action':'set_water_stage','water_stage':'flood'},request_id='crossing-flood')
    planner=ProductionCampaignPlanner(campaign); planner._reset(); route=_route(planner,ref)
    profile=crossing_operational_profile(planner.read,route)
    assert profile['water_stage'] == 'flood'
    assert profile['bridge_condition_percent'] == 100.0
    assert profile['serviceable_ferry_boats'] == 14
    assert profile['available_methods'] == ['bridge']
    assert profile['daily_troop_throughput'] > 0
