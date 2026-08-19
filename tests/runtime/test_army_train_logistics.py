from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import execute_production_internal, meta


def _read(root, path):
    return json.loads((Path(root)/path).read_text())


def _owner(root, ref):
    idx=_read(root,'state/index/owner-index.json')['owners']
    return _read(root,idx[ref])


def _materialize(root, ref, name):
    execute_production_internal(root,'person_materialize',{
        'state':'qin','person_ref':ref,'name':name,'birth_date':'270-BCE-01-01',
        'role':'command_personnel','source_location_ref':'loc_qin_eastern_depot','representation':'exact'
    })


def _formation(root, ref, commander, n=1000):
    execute_production_internal(root,'formation_create',{
        'state':'qin','formation_ref':ref,'role':'line_infantry','personnel':n,
        'location_ref':'loc_qin_eastern_depot','commander_ref':commander
    })
    execute_production_internal(root,'resupply',{'formation_ref':ref,'food_kg':n*30,'fodder_kg':0,'war_arrows':n*4})
    execute_production_internal(root,'formation_mobilize',{'formation_ref':ref})


def _army(root):
    _materialize(root,'char_train_army','Train Army Commander')
    _materialize(root,'char_train_one','Train Unit One')
    _materialize(root,'char_train_two','Train Unit Two')
    _formation(root,'formation_train_one','char_train_one')
    _formation(root,'formation_train_two','char_train_two')
    group='cmdgrp.train.test_army'
    execute_production_internal(root,'command_group_action',{'action':'create','command_group_ref':group,'commander_ref':'char_train_army','display_name':'Train Test Army'})
    for f in ('formation_train_one','formation_train_two'):
        execute_production_internal(root,'command_group_action',{'action':'attach_formation','command_group_ref':group,'formation_ref':f})
    return group


def test_recursive_army_allocates_exact_cart_teams_and_persists_one_camp_owner(campaign):
    group=_army(campaign)
    before=int(_read(campaign,'state/depots/qin.json')['stocks']['carts'])
    result=execute_production_internal(campaign,'command_group_action',{'action':'move_army','command_group_ref':group,'location_ref':'loc_kanyou'},request_id='train-move-one').receipt.result
    train_ref=result['army_train_ref']; required=int(result['required_wagon_equivalents'])
    assert required > 0
    after=int(_read(campaign,'state/depots/qin.json')['stocks']['carts'])
    assert after == before-required

    train=_owner(campaign,train_ref)
    assert train['command_group_ref']==group
    assert train['location_ref']=='loc_kanyou'
    assert train['cart_count']==required
    assert train['serviceable_cart_count']==required
    assert train['cargo_custody_refs']==['formation_train_one#logistics','formation_train_two#logistics']
    assert set(train['camp']['sectors'])=={'headquarters','baggage_park','animal_lines','kitchens','sanitation','medical','picket_line'}
    assert train['camp']['temporary_depot']['authority'] is False
    assert train['camp']['temporary_depot']['cargo_custody_refs']==train['cargo_custody_refs']
    assert train['geography']['owns_local_population'] is False
    index=_read(campaign,'state/logistics/army-trains/index.json')
    assert index['trains'][train_ref]==_read(campaign,'state/index/owner-index.json')['owners'][train_ref]


def test_cart_damage_is_persistent_and_repair_does_not_create_new_carts(campaign):
    group=_army(campaign)
    result=execute_production_internal(campaign,'command_group_action',{'action':'move_army','command_group_ref':group,'location_ref':'loc_kanyou'},request_id='train-move-damage').receipt.result
    train_ref=result['army_train_ref']; required=result['required_wagon_equivalents']
    execute_production_internal(campaign,'army_train_action',{'army_train_ref':train_ref,'action':'damage_carts','quantity':3},request_id='train-damage')
    damaged=_owner(campaign,train_ref)
    assert damaged['cart_count']==required
    assert damaged['serviceable_cart_count']==required-3
    assert damaged['damaged_cart_count']==3
    execute_production_internal(campaign,'army_train_action',{'army_train_ref':train_ref,'action':'repair_carts','quantity':2},request_id='train-repair')
    repaired=_owner(campaign,train_ref)
    assert repaired['cart_count']==required
    assert repaired['serviceable_cart_count']==required-1
    assert repaired['damaged_cart_count']==1
    execute_production_internal(campaign,'army_train_action',{'army_train_ref':train_ref,'action':'destroy_carts','quantity':1},request_id='train-destroy')
    destroyed=_owner(campaign,train_ref)
    assert destroyed['cart_count']==required-1
    assert destroyed['destroyed_cart_count']==1


def test_baggage_delay_blocks_next_army_march_until_time_causally_passes(campaign):
    group=_army(campaign)
    result=execute_production_internal(campaign,'command_group_action',{'action':'move_army','command_group_ref':group,'location_ref':'loc_kanyou'},request_id='train-move-delay').receipt.result
    train_ref=result['army_train_ref']
    execute_production_internal(campaign,'army_train_action',{'army_train_ref':train_ref,'action':'delay_baggage','hours':6},request_id='train-delay')
    with pytest.raises(ValueError,match='baggage train is delayed'):
        execute_production_internal(campaign,'command_group_action',{'action':'move_army','command_group_ref':group,'location_ref':'loc_qin_eastern_depot'},request_id='train-move-too-soon')
    execute_production_internal(campaign,'advance_time',{'hours':6},request_id='train-wait-delay')
    execute_production_internal(campaign,'command_group_action',{'action':'move_army','command_group_ref':group,'location_ref':'loc_qin_eastern_depot'},request_id='train-move-after-delay')
    train=_owner(campaign,train_ref)
    assert train['location_ref']=='loc_qin_eastern_depot'
    assert len(train['movement_history'])==2


def test_relief_corridor_is_connected_from_current_camp_and_does_not_create_supply(campaign):
    group=_army(campaign)
    result=execute_production_internal(campaign,'command_group_action',{'action':'move_army','command_group_ref':group,'location_ref':'loc_kanyou'},request_id='train-move-corridor').receipt.result
    train_ref=result['army_train_ref']
    before={ref:dict(_owner(campaign,ref)['logistics']) for ref in ('formation_train_one','formation_train_two')}
    execute_production_internal(campaign,'army_train_action',{'army_train_ref':train_ref,'action':'set_relief_corridor','route_refs':['route_kanyou_qin_east_depot']},request_id='train-corridor')
    train=_owner(campaign,train_ref)
    assert train['relief_corridor_route_refs']==['route_kanyou_qin_east_depot']
    after={ref:dict(_owner(campaign,ref)['logistics']) for ref in ('formation_train_one','formation_train_two')}
    assert before==after


def test_standalone_formation_move_materializes_one_exact_train_and_conserves_depot_carts(campaign):
    _materialize(campaign,'char_standalone_train','Standalone Train Commander')
    _formation(campaign,'formation_standalone_train','char_standalone_train',n=1200)
    before=int(_read(campaign,'state/depots/qin.json')['stocks']['carts'])
    result=execute_production_internal(
        campaign,'formation_move',
        {'formation_ref':'formation_standalone_train','destination_ref':'loc_kanyou'},
        request_id='standalone-train-move',
    ).receipt.result
    train_ref=result['army_train_ref']
    required=int(result['required_wagon_equivalents'])
    assert required > 0
    after=int(_read(campaign,'state/depots/qin.json')['stocks']['carts'])
    assert after == before-required
    train=_owner(campaign,train_ref)
    assert train['movement_owner_kind']=='standalone_formation'
    assert train['movement_owner_ref']=='formation_standalone_train'
    assert train['standalone_formation_ref']=='formation_standalone_train'
    assert 'command_group_ref' not in train
    assert train['location_ref']=='loc_kanyou'
    assert train['cart_count']==required
    assert train['serviceable_cart_count']==required
    assert train['cargo_custody_refs']==['formation_standalone_train#logistics']
    assert train['camp']['sectors']['headquarters']['formation_ref']=='formation_standalone_train'
    assert train['camp']['temporary_depot']['cargo_custody_refs']==train['cargo_custody_refs']
    duties=train['duty_allocation_requirements']
    assert duties['cart_drivers']==required
    assert duties['baggage_guards']>0


def test_standalone_train_damage_and_delay_follow_same_conserved_train_owner(campaign):
    _materialize(campaign,'char_standalone_train_delay','Standalone Delay Commander')
    _formation(campaign,'formation_standalone_train_delay','char_standalone_train_delay',n=1200)
    result=execute_production_internal(
        campaign,'formation_move',
        {'formation_ref':'formation_standalone_train_delay','destination_ref':'loc_kanyou'},
        request_id='standalone-train-first-move',
    ).receipt.result
    train_ref=result['army_train_ref']
    required=int(result['required_wagon_equivalents'])
    execute_production_internal(campaign,'army_train_action',{'army_train_ref':train_ref,'action':'damage_carts','quantity':1},request_id='standalone-train-damage')
    damaged=_owner(campaign,train_ref)
    assert damaged['cart_count']==required
    assert damaged['damaged_cart_count']==1
    execute_production_internal(campaign,'army_train_action',{'army_train_ref':train_ref,'action':'delay_baggage','hours':4},request_id='standalone-train-delay')
    with pytest.raises(ValueError,match='formation baggage train is delayed'):
        execute_production_internal(
            campaign,'formation_move',
            {'formation_ref':'formation_standalone_train_delay','destination_ref':'loc_qin_eastern_depot'},
            request_id='standalone-train-too-soon',
        )
