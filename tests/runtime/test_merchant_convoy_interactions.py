from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _planner(root: Path):
    p=ProductionCampaignPlanner(root); p.PLAYER_ACTOR='char_tang_wei'; p._reset(); return p


def _install_formation(p, ref, personnel, location='loc_gyou'):
    path=f'state/formations/{ref}.json'
    row={'schema':'sword-formation','formation_ref':ref,'owner_id':ref,'name':ref,'personnel':personnel,'composition':{'line_infantry':personnel},'location_ref':location,'owner_force_ref':'force_state_qin','administrative_owner':'state_qin','command_authority':'char_tang_wei','readiness':80,'mobilized':True,'logistics':{},'mounts':{}}
    p.put(path,row); p._register_owner(ref,path); return ref


def _install_convoy(p):
    at=str(p._world_time()); ref='merchant_convoy_test_interaction'; path='state/economy/convoys/test-interaction.json'
    convoy={'schema':'sword-merchant-convoy','owner_id':ref,'merchant_house_ref':'merchant_house_lu','source_market_ref':'market_qin_kanyou','destination_market_ref':'market_zhao_gyou','source_state':'qin','destination_state':'zhao','cargo':{'grain_kg':100},'purchase_cost_silver':100,'status':'in_transit','departed_at':at,'arrives_at':str(CampaignTime.parse(at).add_hours(24)),'route_refs':[],'route_path':['loc_gyou'],'wagon_equivalents':4,'escort_formation_refs':[],'security_incidents':[],'delay_history':[],'current_location_ref':'loc_gyou'}
    p.put(path,convoy); p._register_owner(ref,path); idx=copy.deepcopy(p.read('state/economy/merchant-convoys.json')); idx.setdefault('convoys',{})[ref]=path; idx.setdefault('active_refs',[]).append(ref); p.put('state/economy/merchant-convoys.json',idx); return ref,path


def _cmd(p, actor='char_tang_wei'):
    m=p.read('state/meta.json'); return SimpleNamespace(actor_id=actor,expected_revision=int(m['revision']),command_type='merchant_convoy_action',request_id='convoy-test')


def test_convoy_escort_is_exact_existing_formation_and_interception_moves_cargo(campaign):
    p=_planner(campaign); escort=_install_formation(p,'formation_test_convoy_escort',500); attacker=_install_formation(p,'formation_test_convoy_attacker',3000); ref,path=_install_convoy(p)
    p._merchant_convoy_interaction(_cmd(p),{'action':'assign_escort','convoy_ref':ref,'formation_ref':escort})
    convoy=p.read(path); assert convoy['escort_formation_refs']==[escort]
    before=sum(int(v) for v in convoy['cargo'].values())
    p._merchant_convoy_interaction(_cmd(p),{'action':'interdict','convoy_ref':ref,'formation_ref':attacker})
    convoy=p.read(path); captured=p.read(f'state/formations/{attacker}.json').get('captured_cargo',{})
    after=sum(int(v) for v in convoy.get('cargo',{}).values()); seized=sum(int(v) for v in captured.values())
    assert seized>0 and after+seized==before
    assert convoy['security_incidents'][-1]['kind']=='interception' and convoy['security_incidents'][-1]['attacker_wins'] is True


def test_convoy_delay_is_internal_and_preserves_cargo(campaign):
    p=_planner(campaign); ref,path=_install_convoy(p); before=copy.deepcopy(p.read(path)); old=CampaignTime.parse(before['arrives_at'])
    p._merchant_convoy_interaction(_cmd(p,actor=p.INTERNAL_ACTOR),{'action':'delay','convoy_ref':ref,'hours':7})
    after=p.read(path); assert old.seconds_until(CampaignTime.parse(after['arrives_at']))==7*3600; assert after['cargo']==before['cargo']


def test_assigned_escort_moves_on_convoy_chronology_and_consumes_its_own_supply(campaign):
    p=_planner(campaign)
    escort=_install_formation(p,'formation_test_convoy_moving_escort',600,location='loc_gyou')
    fp=f'state/formations/{escort}.json'; f=copy.deepcopy(p.read(fp)); f['logistics']={'food_kg':5000,'fodder_kg':0}; p.put(fp,f)
    ref,path=_install_convoy(p)
    convoy=copy.deepcopy(p.read(path))
    convoy['route_path']=['loc_gyou','loc_zhao_regional_01']
    convoy['route_edge_hours']=[24]
    convoy['arrives_at']=str(CampaignTime.parse(convoy['departed_at']).add_hours(24))
    p.put(path,convoy)
    p._merchant_convoy_interaction(_cmd(p),{'action':'assign_escort','convoy_ref':ref,'formation_ref':escort})
    food_before=int(p.read(fp)['logistics']['food_kg'])
    future=str(CampaignTime.parse(str(p._world_time())).add_hours(24))
    convoy=copy.deepcopy(p.read(path)); p._sync_convoy_escorts(convoy,future); p.put(path,convoy)
    moved=p.read(fp)
    assert moved['location_ref']=='loc_zhao_regional_01'
    assert int(moved['logistics']['food_kg']) < food_before
    assert moved['convoy_escort_assignment']['convoy_ref']==ref
    assert convoy['escort_state'][escort]['last_location_ref']=='loc_zhao_regional_01'
