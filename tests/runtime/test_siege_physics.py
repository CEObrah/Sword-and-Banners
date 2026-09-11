import json
import subprocess
from pathlib import Path

import pytest

from conftest import execute_internal, prepare_field_formation


def _owner_path(campaign, ref):
    idx=json.load(open(Path(campaign)/'state/index/owner-index.json'))['owners']
    return Path(campaign)/idx[ref]


def _create_tang_siege_pair(campaign):
    qcmd='char_siege_physics_qin'; zcmd='char_siege_physics_zhao'
    qloc=json.load(open(Path(campaign)/'state/depots/qin.json'))['location_ref']
    zloc=json.load(open(Path(campaign)/'state/depots/zhao.json'))['location_ref']
    execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':qcmd,'name':'Tang siege physics defender','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':qloc})
    execute_internal(campaign,'person_materialize',{'state':'zhao','person_ref':zcmd,'name':'Tang siege physics attacker','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':zloc})
    execute_internal(campaign,'formation_create',{
        'state':'qin','formation_ref':'formation_siege_physics_qin','composition':{'line_infantry':1000},
        'personnel':1000,'commander_ref':qcmd,'location_ref':qloc,
    })
    execute_internal(campaign,'formation_create',{
        'state':'zhao','formation_ref':'formation_siege_physics_zhao','composition':{'line_infantry':1000},
        'personnel':1000,'commander_ref':zcmd,'location_ref':zloc,
    })
    # Disposable fixture-only construction lots give both sides an exact
    # physical source for engineering material. They are committed so runtime
    # transactions never operate over an untracked dirty fixture.
    for depot_name,units in [('qin',5000),('zhao',2000)]:
        path=Path(campaign)/f'state/depots/{depot_name}.json'; depot=json.load(open(path)); depot.setdefault('stocks',{})['construction_material_units']=units; path.write_text(json.dumps(depot,indent=2)+'\n')
    subprocess.run(['git','-C',str(campaign),'add','state/depots/qin.json','state/depots/zhao.json'],check=True)
    subprocess.run(['git','-C',str(campaign),'commit','--quiet','-m','seed disposable siege construction lots'],check=True)
    # Siege material is loaded at the exact depots before the formations move.
    execute_internal(campaign,'resupply',{'formation_ref':'formation_siege_physics_zhao','construction_material_units':1600})
    execute_internal(campaign,'resupply',{'formation_ref':'formation_siege_physics_qin','construction_material_units':5000})
    prepare_field_formation(campaign,'formation_siege_physics_qin','loc_tang_manor')
    prepare_field_formation(campaign,'formation_siege_physics_zhao','loc_tang_manor')
    execute_internal(campaign,'fortification_materialize',{
        'fortification_ref':'fort_tang_physics','location_ref':'loc_tang_manor',
        'garrison_formation_refs':['formation_siege_physics_qin'],'state':'qin','commander_ref':qcmd,
    })
    execute_internal(campaign,'siege_start',{
        'siege_ref':'siege_tang_physics','fortification_ref':'fort_tang_physics',
        'attacker_formation_refs':['formation_siege_physics_zhao'],
    })
    return 'formation_siege_physics_qin','formation_siege_physics_zhao'


def test_tang_gate_blocks_assault_and_ram_until_crossing_exists(campaign):
    _q,z=_create_tang_siege_pair(campaign)
    with pytest.raises(Exception,match='closed.*intact|closed gate|passable breach'):
        execute_internal(campaign,'siege_action',{'siege_ref':'siege_tang_physics','action':'assault','target':'gate','method':'auto'})
    execute_internal(campaign,'siege_action',{
        'siege_ref':'siege_tang_physics','action':'build_work','blueprint_ref':'siege_heavy_covered_ram',
        'quantity':1,'target':'gate','source_formation_ref':z,
    })
    with pytest.raises(Exception,match='cannot reach gate|unresolved moat'):
        execute_internal(campaign,'siege_action',{'siege_ref':'siege_tang_physics','action':'ram_gate','cycles':10})
    crossing=execute_internal(campaign,'siege_action',{
        'siege_ref':'siege_tang_physics','action':'build_work','blueprint_ref':'siege_trestle_bridge_20m',
        'quantity':1,'target':'gate','source_formation_ref':z,
    }).receipt.result
    assert float(crossing['work']['effective_length_m']) == 20.0
    ram=execute_internal(campaign,'siege_action',{'siege_ref':'siege_tang_physics','action':'ram_gate','cycles':30}).receipt.result
    assert ram['structural_result']['target']=='gate'
    fort=json.load(open(Path(campaign)/'state/fortifications/fort_tang_physics.json'))
    assert fort['physical_state']['gates']['main_gate']['structural_condition_percent'] < 100.0
    assert fort['physical_state']['gates']['main_gate']['breach_width_m'] >= 1.5
    assault=execute_internal(campaign,'siege_action',{'siege_ref':'siege_tang_physics','action':'assault','target':'gate','method':'breach'}).receipt.result
    assert assault['access']['access_class']=='gate_breach'
    assert assault['causal_trace'][0]['phase']=='fortification_access'
    assert json.load(open(Path(campaign)/'state/fortifications/fort_tang_physics.json'))['physical_state']['gates']['main_gate']['breach_width_m'] >= 1.5


def test_tang_wall_rejects_short_ladders_and_grapnel_never_grants_ram_access(campaign):
    _q,z=_create_tang_siege_pair(campaign)
    # Build enough exact crossing work to cover the current wall-sector approach.
    for _ in range(4):
        execute_internal(campaign,'siege_action',{
            'siege_ref':'siege_tang_physics','action':'build_work','blueprint_ref':'siege_trestle_bridge_20m',
            'quantity':1,'target':'wall','source_formation_ref':z,
        })
    execute_internal(campaign,'siege_action',{
        'siege_ref':'siege_tang_physics','action':'build_work','blueprint_ref':'siege_ladder_16m',
        'quantity':1,'target':'wall','source_formation_ref':z,
    })
    with pytest.raises(Exception,match='ladder.*reach|wall height'):
        execute_internal(campaign,'siege_action',{'siege_ref':'siege_tang_physics','action':'assault','target':'wall','method':'ladder'})

    # The registered 30 m grapnel can reach the current wall directly after a swim,
    # but remains infantry-only access and does not solve the gate for a ram.
    execute_internal(campaign,'siege_action',{
        'siege_ref':'siege_tang_physics','action':'build_work','blueprint_ref':'siege_hook_rope_30m',
        'quantity':1,'target':'wall','source_formation_ref':z,
    })
    result=execute_internal(campaign,'siege_action',{'siege_ref':'siege_tang_physics','action':'assault','target':'wall','method':'swim_grapnel'}).receipt.result
    assert result['access']['access_class']=='swim_grapnel_escalade'
    assert result['access']['wheeled_engine_access'] is False


def test_structural_repair_consumes_engineers_material_and_time(campaign):
    q,z=_create_tang_siege_pair(campaign)
    execute_internal(campaign,'siege_action',{
        'siege_ref':'siege_tang_physics','action':'build_work','blueprint_ref':'siege_heavy_covered_ram',
        'quantity':1,'target':'gate','source_formation_ref':z,
    })
    execute_internal(campaign,'siege_action',{
        'siege_ref':'siege_tang_physics','action':'build_work','blueprint_ref':'siege_trestle_bridge_20m',
        'quantity':1,'target':'gate','source_formation_ref':z,
    })
    execute_internal(campaign,'siege_action',{'siege_ref':'siege_tang_physics','action':'ram_gate','cycles':12})
    qpath=_owner_path(campaign,q)
    before=json.load(open(Path(campaign)/'state/fortifications/fort_tang_physics.json'))['physical_state']['gates']['main_gate']['structural_condition_percent']
    repaired=execute_internal(campaign,'siege_action',{'siege_ref':'siege_tang_physics','action':'repair','target':'gate','hours':12,'source_formation_ref':q}).receipt.result
    after=json.load(open(Path(campaign)/'state/fortifications/fort_tang_physics.json'))['physical_state']['gates']['main_gate']['structural_condition_percent']
    assert after>before
    assert repaired['construction_material_units_consumed']>0
    remaining=json.load(open(qpath))['logistics']['construction_material_units']
    assert remaining == 5000-repaired['construction_material_units_consumed']


def test_nested_tang_fortifications_are_exact_and_route_to_their_own_perimeters(campaign):
    from sword_runtime.geography import enclosing_fortification_site
    from sword_runtime.siege_physics import initial_physical_state, required_crossing_length

    root=Path(campaign)
    def read(rel):
        return json.load(open(root/rel))

    master=read('game/data/world/tang-manor-master-plan.json')
    inner_walls=master['inner_walls']; inner=master['inner_citadel']
    assert inner_walls['plan_length_m']*inner_walls['plan_width_m']/1_000_000 == inner_walls['area_km2']
    assert 2*(inner_walls['plan_length_m']+inner_walls['plan_width_m'])/1000 == inner_walls['constructed_wall_centerline_perimeter_km']
    assert inner_walls['tower_station_interval_m']*inner_walls['tower_count']/1000 == inner_walls['constructed_wall_centerline_perimeter_km']
    assert inner['plan_length_m']*inner['plan_width_m']/1_000_000 == inner['area_km2']
    assert 2*(inner['plan_length_m']+inner['plan_width_m'])/1000 == inner['constructed_wall_centerline_perimeter_km']
    assert inner['tower_station_interval_m']*inner['tower_count']/1000 == inner['constructed_wall_centerline_perimeter_km']

    assert enclosing_fortification_site(read,'loc_tang_inner_walls_outer_gate') == 'loc_tang_inner_walls'
    assert enclosing_fortification_site(read,'loc_tang_manor_training_ground') == 'loc_tang_inner_walls'
    assert enclosing_fortification_site(read,'loc_tang_inner_citadel_gate') == 'loc_tang_inner_citadel'
    assert enclosing_fortification_site(read,'loc_tang_manor_inner_citadel_family_hall') == 'loc_tang_inner_citadel'

    profiles=read('game/data/world/fortification-profiles.json')['profiles']
    by_site={p['site_ref']:p for p in profiles}
    inner_walls_fort={'profile':by_site['loc_tang_inner_walls'],'physical_state':initial_physical_state(by_site['loc_tang_inner_walls'])}
    inner_fort={'profile':by_site['loc_tang_inner_citadel'],'physical_state':initial_physical_state(by_site['loc_tang_inner_citadel'])}
    assert inner_walls_fort['physical_state']['model']=='exact_perimeter'
    assert inner_walls_fort['physical_state']['perimeter']['wall_height_m']==26.0
    assert required_crossing_length(inner_walls_fort,'gate')==18.0
    assert required_crossing_length(inner_walls_fort,'wall')==45.0
    assert inner_fort['physical_state']['perimeter']['wall_height_m']==30.0
    assert required_crossing_length(inner_fort,'gate')==16.0
    assert required_crossing_length(inner_fort,'wall')==35.0
