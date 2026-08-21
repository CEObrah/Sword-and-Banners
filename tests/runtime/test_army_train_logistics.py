from __future__ import annotations

import copy
import subprocess
from pathlib import Path

from conftest import execute_production_internal


def _owner(root: Path, ref: str):
    import json
    idx=json.loads((root/'state/index/owner-index.json').read_text())['owners']
    return json.loads((root/idx[ref]).read_text())


def _add_test_formation(root: Path, ref: str='formation_transport_test'):
    import json
    idxp=root/'state/index/owner-index.json'; idx=json.loads(idxp.read_text())
    fp=root/f'state/formations/{ref}.json'
    f={
      'schema':'sword-formation','owner_id':ref,'formation_ref':ref,'name':'Transport Test Formation',
      'owner_force_ref':'force_state_qin','administrative_owner':'state_qin','command_authority':'state_qin','personnel':1000,
      'location_ref':'loc_kanyou','status':'mobilized','mobilized':True,'composition':{'line_infantry':1000},'mounts':{},
      'logistics':{'food_kg':100000,'fodder_kg':0,'war_arrows':0,'war_bolts':0},
      'supply_depot_ref':'state_depot_qin'
    }
    fp.write_text(json.dumps(f,indent=2)+'\n'); idx['owners'][ref]=f'state/formations/{ref}.json'; idxp.write_text(json.dumps(idx,indent=2)+'\n')
    subprocess.run(['git','-C',str(root),'add','-A'],check=True)
    subprocess.run(['git','-C',str(root),'commit','--quiet','-m',f'add {ref}'],check=True)
    return ref


def test_standalone_movement_uses_compact_aggregate_transport(campaign):
    ref=_add_test_formation(campaign)
    depot0=copy.deepcopy(_owner(campaign,'state_depot_qin'))
    result=execute_production_internal(campaign,'formation_move',{'formation_ref':ref,'destination_ref':'loc_qin_eastern_depot'},request_id='transport-move').receipt.result
    train=_owner(campaign,result['army_train_ref']); required=int(result['required_wagon_equivalents'])
    assert train['transport_capacity_equivalents'] >= required
    assert train['transport_condition']==1.0
    assert train['baggage_burden_equivalents']==required
    assert train['cargo_custody_refs']==[f'{ref}#logistics']
    assert 'cart_source_ledger' not in train
    assert 'serviceable_cart_count' not in train
    assert 'damaged_cart_count' not in train
    assert 'duty_allocation_requirements' not in train
    assert set(train['camp']).issuperset({'required_area_m2','cargo_custody_refs'})
    depot1=_owner(campaign,'state_depot_qin')
    assert int(depot0['stocks']['carts'])-int(depot1['stocks']['carts'])==train['transport_capacity_equivalents']


def test_transport_damage_is_one_condition_factor_not_cart_ledger(campaign):
    ref=_add_test_formation(campaign,'formation_transport_damage')
    result=execute_production_internal(campaign,'formation_move',{'formation_ref':ref,'destination_ref':'loc_qin_eastern_depot'},request_id='transport-damage-move').receipt.result
    train_ref=result['army_train_ref']; before=_owner(campaign,train_ref)
    execute_production_internal(campaign,'army_train_action',{'army_train_ref':train_ref,'action':'damage_transport','quantity':1},request_id='transport-damage')
    damaged=_owner(campaign,train_ref)
    assert damaged['transport_condition'] < before['transport_condition']
    assert damaged['transport_capacity_equivalents']==before['transport_capacity_equivalents']
    execute_production_internal(campaign,'army_train_action',{'army_train_ref':train_ref,'action':'repair_transport','quantity':1},request_id='transport-repair')
    repaired=_owner(campaign,train_ref)
    assert repaired['transport_condition'] >= damaged['transport_condition']
    execute_production_internal(campaign,'army_train_action',{'army_train_ref':train_ref,'action':'destroy_transport','quantity':1},request_id='transport-destroy')
    destroyed=_owner(campaign,train_ref)
    assert destroyed['transport_capacity_equivalents']==max(0,repaired['transport_capacity_equivalents']-1)
    assert 'destroyed_cart_count' not in destroyed


def test_transport_delay_and_corridor_do_not_create_supply(campaign):
    ref=_add_test_formation(campaign,'formation_transport_corridor')
    result=execute_production_internal(campaign,'formation_move',{'formation_ref':ref,'destination_ref':'loc_qin_eastern_depot'},request_id='transport-corridor-move').receipt.result
    train_ref=result['army_train_ref']; formation0=copy.deepcopy(_owner(campaign,ref))
    execute_production_internal(campaign,'army_train_action',{'army_train_ref':train_ref,'action':'delay_baggage','hours':4},request_id='transport-delay')
    assert _owner(campaign,train_ref)['status']=='delayed'
    execute_production_internal(campaign,'army_train_action',{'army_train_ref':train_ref,'action':'clear_delay'},request_id='transport-clear')
    assert _owner(campaign,ref)['logistics']==formation0['logistics']
