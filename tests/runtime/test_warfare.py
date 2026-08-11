import json,time
from conftest import execute, execute_internal, prepare_field_formation, activate_operation

def create_pair(campaign,tag,n,battlefield='loc_kankoku_pass'):
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':f'formation_qin_{tag}','role':'line_infantry','personnel':n,'commander_ref':'char_ouki'})
    execute_internal(campaign,'formation_create',{'state':'zhao','formation_ref':f'formation_zhao_{tag}','role':'line_infantry','personnel':n,'commander_ref':'char_riboku'})
    a,d=f'formation_qin_{tag}',f'formation_zhao_{tag}'
    prepare_field_formation(campaign,a,battlefield); prepare_field_formation(campaign,d,battlefield)
    op=activate_operation(campaign,f'operation_{tag}',[a,d],battlefield)
    return a,d,op

def create_local_scale_pair(campaign,tag,n):
    """Exercise battle scaling without re-benchmarking strategic travel.

    Causal movement is covered separately by hardening and acceptance tests.
    Both benchmark formations are lawfully raised, supplied, mobilized, and
    admitted to one saved operation at Qin's military depot.
    """
    a=f'formation_qin_{tag}_a'; d=f'formation_qin_{tag}_b'
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':a,'role':'line_infantry','personnel':n,'commander_ref':'char_ouki'})
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':d,'role':'line_infantry','personnel':n,'commander_ref':'char_ousen'})
    for ref in (a,d):
        execute_internal(campaign,'resupply',{'formation_ref':ref,'food_kg':n,'war_arrows':0})
        execute_internal(campaign,'formation_mobilize',{'formation_ref':ref})
    op=activate_operation(campaign,f'operation_{tag}',[a,d],'loc_qin_eastern_depot')
    return a,d,op

def test_personal_duel(campaign):
    x=execute(campaign,'personal_combat',{'opponent_ref':'char_shen_rui','objective':'controlled spar','duration_minutes':30}); assert x.receipt.result['scale']=='exact_personal'

def test_warfare_scale_ladder(campaign):
    for tag,n in [('skirmish',25),('hundreds',300),('thousands',5000),('major',50000)]:
        a,d,op=create_local_scale_pair(campaign,tag,n); x=execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':[a],'defender_formation_refs':[d],'operation_ref':op,'objective':'field engagement'}); assert x.receipt.result['represented_personnel']==n*2; assert x.receipt.result['planning_reads']<=25; assert x.receipt.result['writes']<=24

def test_200k_battle_is_bounded(campaign):
    a,d,op=create_local_scale_pair(campaign,'huge',100000); start=time.perf_counter(); x=execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':[a],'defender_formation_refs':[d],'operation_ref':op,'objective':'major operation'}); duration=time.perf_counter()-start; r=x.receipt.result
    assert r['represented_personnel']==200000
    assert r['planning_reads']<=25
    assert r['writes']<=24
    assert duration<3.0
    assert not any((campaign/'state').rglob('soldier-*.json'))

def test_full_siege_lifecycle(campaign):
    q,z,_=create_pair(campaign,'siege',4000)
    execute_internal(campaign,'fortification_materialize',{'fortification_ref':'fort_kankoku_accept','location_ref':'loc_kankoku_pass','garrison_formation_refs':[q],'food_kg':20000,'state':'qin','commander_ref':'char_ouki'})
    execute_internal(campaign,'siege_start',{'siege_ref':'siege_kankoku_accept','fortification_ref':'fort_kankoku_accept','attacker_formation_refs':[z]})
    execute_internal(campaign,'siege_action',{'siege_ref':'siege_kankoku_accept','action':'blockade','days':1})
    execute_internal(campaign,'siege_action',{'siege_ref':'siege_kankoku_accept','action':'repair','points':3})
    execute_internal(campaign,'siege_action',{'siege_ref':'siege_kankoku_accept','action':'assault'})
    execute_internal(campaign,'siege_action',{'siege_ref':'siege_kankoku_accept','action':'withdraw'})
    execute_internal(campaign,'siege_action',{'siege_ref':'siege_kankoku_accept','action':'settle'})
    sg=json.load(open(campaign/'state/sieges/siege_kankoku_accept.json')); fort=json.load(open(campaign/'state/fortifications/fort_kankoku_accept.json'))
    assert sg['status']=='settled'; assert fort['food_kg']<20000; assert fort['integrity']<100

def test_fortified_territory_requires_siege_evidence(campaign):
    import pytest
    with pytest.raises(Exception): execute_internal(campaign,'territorial_consequence',{'location_ref':'loc_kankoku_pass','controller':'state_zhao'})
