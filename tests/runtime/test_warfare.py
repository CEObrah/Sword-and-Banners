import json,time,subprocess
from pathlib import Path
from conftest import execute, execute_internal, prepare_field_formation, activate_operation


def stage_qin_line_reserve(campaign, count, location="loc_qin_eastern_depot"):
    """Relocate already-conserved Qin line reserve for synthetic scale tests.

    This changes only geographic disposition inside the disposable fixture. It
    preserves force totals, cohort provenance, and issued-equipment totals.
    """
    path=Path(campaign)/"state/forces/state-qin.json"
    force=json.load(open(path))
    target=force.setdefault("available_by_location",{}).setdefault(location,{})
    need=max(0,int(count)-int(target.get("line_infantry",0)))
    if need:
        remaining=need
        cohorts=force.get("cohort_ledger",{}).get("cohorts",{})
        for cohort in cohorts.values():
            if remaining<=0: break
            if not isinstance(cohort,dict) or cohort.get("role")!="line_infantry": continue
            reserve=cohort.setdefault("reserve_by_location",{})
            for source in sorted(list(reserve)):
                if remaining<=0: break
                if source==location: continue
                take=min(remaining,max(0,int(reserve.get(source,0))))
                if not take: continue
                reserve[source]=int(reserve[source])-take
                if reserve[source]==0: reserve.pop(source,None)
                reserve[location]=int(reserve.get(location,0))+take
                remaining-=take
        if remaining:
            raise AssertionError("fixture lacks conserved Qin line reserve")
        # Rebuild only the line-infantry geographic projection from exact cohort reserve.
        by_loc={}
        for cohort in cohorts.values():
            if not isinstance(cohort,dict) or cohort.get("role")!="line_infantry": continue
            for loc,n in cohort.get("reserve_by_location",{}).items():
                by_loc[loc]=by_loc.get(loc,0)+int(n)
        for loc,pool in force.setdefault("available_by_location",{}).items():
            if isinstance(pool,dict): pool["line_infantry"]=int(by_loc.get(loc,0))
        for loc,n in by_loc.items():
            force["available_by_location"].setdefault(loc,{})["line_infantry"]=int(n)

    equip_target=force.setdefault("available_equipment_by_location",{}).setdefault(location,{})
    # formation_create intentionally issues a new formation at 80% equipment by
    # default when no explicit issue is requested. The scale benchmark therefore
    # stages only that lawful issue requirement instead of inventing enough spare
    # equipment to give 200,000 synthetic troops a 100% issue.
    required_equipment=int((int(count)*8 + 9)//10)
    equip_need=max(0,required_equipment-int(equip_target.get("line_infantry",0)))
    for source in sorted(force["available_equipment_by_location"]):
        if equip_need<=0: break
        if source==location: continue
        pool=force["available_equipment_by_location"][source]
        if not isinstance(pool,dict): continue
        take=min(equip_need,max(0,int(pool.get("line_infantry",0))))
        if not take: continue
        pool["line_infantry"]=int(pool.get("line_infantry",0))-take
        equip_target["line_infantry"]=int(equip_target.get("line_infantry",0))+take
        equip_need-=take
    if equip_need:
        raise AssertionError("fixture lacks conserved Qin line equipment")
    path.write_text(json.dumps(force,indent=2)+"\n")
    subprocess.run(["git","-C",str(campaign),"add",path.relative_to(campaign).as_posix()],check=True)
    dirty=subprocess.run(["git","-C",str(campaign),"diff","--cached","--quiet"]).returncode != 0
    if dirty:
        subprocess.run(["git","-C",str(campaign),"commit","--quiet","-m","Stage conserved warfare benchmark reserve"],check=True)

def _consolidate_qin_line_infantry(campaign):
    """Move only disposable Qin reserve geography to the benchmark depot.

    This preserves total force/cohort conservation while giving scale tests one
    explicit local muster site. Existing allocated formations are untouched.
    """
    path=campaign/'state/forces/state-qin.json'
    force=json.load(open(path))
    target='loc_qin_eastern_depot'
    reserve_total=int(force['available_by_role']['line_infantry'])
    for pool in force.get('available_by_location',{}).values():
        if isinstance(pool,dict): pool['line_infantry']=0
    force.setdefault('available_by_location',{}).setdefault(target,{})['line_infantry']=reserve_total
    for cohort in force.get('cohort_ledger',{}).get('cohorts',{}).values():
        if not isinstance(cohort,dict) or cohort.get('role')!='line_infantry': continue
        reserve=sum(max(0,int(v)) for v in cohort.get('reserve_by_location',{}).values())
        cohort['reserve_by_location']={target:reserve} if reserve else {}
    path.write_text(json.dumps(force,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    subprocess.run(['git','-C',str(campaign),'add','state/forces/state-qin.json'],check=True)
    dirty=subprocess.run(['git','-C',str(campaign),'diff','--cached','--quiet']).returncode != 0
    if dirty:
        subprocess.run(['git','-C',str(campaign),'commit','--quiet','-m','test consolidate Qin line reserve'],check=True)


def create_pair(campaign,tag,n,battlefield='loc_kankoku_pass',food_per_person=7):
    qcmd=f'char_warfare_{tag}_qin'; zcmd=f'char_warfare_{tag}_zhao'
    qloc='loc_qin_eastern_depot'; zloc=json.load(open(Path(campaign)/'state/depots/zhao.json'))['location_ref']
    execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':qcmd,'name':f'Qin {tag} commander','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':qloc})
    execute_internal(campaign,'person_materialize',{'state':'zhao','person_ref':zcmd,'name':f'Zhao {tag} commander','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':zloc})
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':f'formation_qin_{tag}','role':'line_infantry','personnel':n,'commander_ref':qcmd,'location_ref':qloc})
    zhao_payload={'state':'zhao','formation_ref':f'formation_zhao_{tag}','role':'line_infantry','personnel':n,'commander_ref':zcmd,'location_ref':zloc}
    if tag=='siege':
        # The exact Kankoku lifecycle fixture includes a small conserved engineer
        # element so registered crossings and ladders can be built lawfully.
        zhao_payload.pop('role',None)
        zhao_payload['composition']={'line_infantry':n-100,'siege_engineering':100}
    execute_internal(campaign,'formation_create',zhao_payload)
    a,d=f'formation_qin_{tag}',f'formation_zhao_{tag}'
    prepare_field_formation(campaign,a,battlefield,food_per_person=food_per_person); prepare_field_formation(campaign,d,battlefield,food_per_person=food_per_person)
    op=activate_operation(campaign,f'operation_{tag}',[a,d],battlefield)
    return a,d,op

def create_local_scale_pair(campaign,tag,n):
    """Exercise battle scaling with conserved reserve staged at a real depot."""
    location='loc_qin_eastern_depot'
    stage_qin_line_reserve(campaign,2*n,location)
    a=f'formation_qin_{tag}_a'; d=f'formation_qin_{tag}_b'
    acmd=f'char_warfare_{tag}_a'; dcmd=f'char_warfare_{tag}_b'
    execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':acmd,'name':f'Qin {tag} A commander','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':location})
    execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':dcmd,'name':f'Qin {tag} B commander','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':location})
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':a,'role':'line_infantry','personnel':n,'commander_ref':acmd,'location_ref':location})
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':d,'role':'line_infantry','personnel':n,'commander_ref':dcmd,'location_ref':location})
    for ref in (a,d):
        execute_internal(campaign,'resupply',{'formation_ref':ref,'food_kg':n,'war_arrows':0})
        execute_internal(campaign,'formation_mobilize',{'formation_ref':ref})
    op=activate_operation(campaign,f'operation_{tag}',[a,d],location)
    return a,d,op

def test_personal_duel(campaign):
    opponent='char_warfare_personal_duel_opponent'
    location=json.load(open(campaign/'state/player.json'))['location']
    execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':opponent,'name':'Warfare Test Sparring Opponent','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':location})
    x=execute(campaign,'personal_combat',{'opponent_ref':opponent,'objective':'controlled spar','duration_minutes':30}); assert x.receipt.result['scale']=='exact_personal'

def test_warfare_scale_ladder(campaign):
    for tag,n in [('skirmish',25),('hundreds',300),('thousands',5000),('major',50000)]:
        a,d,op=create_local_scale_pair(campaign,tag,n); x=execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':[a],'defender_formation_refs':[d],'operation_ref':op,'objective':'field engagement'}); assert x.receipt.result['represented_personnel']==n*2; assert x.receipt.result['planning_reads']<=48; assert x.receipt.result['writes']<=24

def test_200k_battle_is_bounded(campaign):
    a,d,op=create_local_scale_pair(campaign,'huge',100000); start=time.perf_counter(); x=execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':[a],'defender_formation_refs':[d],'operation_ref':op,'objective':'major operation'}); duration=time.perf_counter()-start; r=x.receipt.result
    assert r['represented_personnel']==200000
    assert r['planning_reads']<=48
    assert r['writes']<=24
    assert duration<3.0
    assert not any((campaign/'state').rglob('soldier-*.json'))

def test_full_siege_lifecycle(campaign):
    q,z,_=create_pair(campaign,'siege',4000,food_per_person=20)
    execute_internal(campaign,'fortification_materialize',{'fortification_ref':'fort_kankoku_accept','location_ref':'loc_kankoku_pass','garrison_formation_refs':[q],'food_kg':20000,'state':'qin','commander_ref':'char_warfare_siege_qin'})
    execute_internal(campaign,'siege_start',{'siege_ref':'siege_kankoku_accept','fortification_ref':'fort_kankoku_accept','attacker_formation_refs':[z]})
    execute_internal(campaign,'siege_action',{'siege_ref':'siege_kankoku_accept','action':'blockade','days':1})
    # Exact Kankoku geometry forbids a direct assault through the closed gate
    # or across the 28 m rock-cut ditch. This disposable fixture stages real
    # carried engineering material, builds a 30 m load-bearing causeway, then
    # builds a registered 24 m ladder that safely reaches the 22 m wall.
    owner_index=json.load(open(campaign/'state/index/owner-index.json'))['owners']
    zpath=campaign/owner_index[z]
    zdoc=json.load(open(zpath))
    zdoc.setdefault('logistics',{})['timber_tonnes']=54
    zdoc['logistics']['construction_material_units']=55
    zpath.write_text(json.dumps(zdoc,indent=2)+'\n')
    subprocess.run(['git','-C',str(campaign),'add',str(zpath.relative_to(campaign))],check=True)
    if subprocess.run(['git','-C',str(campaign),'diff','--cached','--quiet']).returncode != 0:
        subprocess.run(['git','-C',str(campaign),'commit','--quiet','-m','stage siege fixture engineering material'],check=True)
    execute_internal(campaign,'siege_action',{'siege_ref':'siege_kankoku_accept','action':'build_work','source_formation_ref':z,'blueprint_ref':'siege_timber_earth_causeway_10m','target':'wall','quantity':3})
    execute_internal(campaign,'siege_action',{'siege_ref':'siege_kankoku_accept','action':'build_work','source_formation_ref':z,'blueprint_ref':'siege_ladder_24m','target':'wall','quantity':1})
    execute_internal(campaign,'siege_action',{'siege_ref':'siege_kankoku_accept','action':'assault','target':'wall','method':'ladder'})
    execute_internal(campaign,'siege_action',{'siege_ref':'siege_kankoku_accept','action':'withdraw'})
    execute_internal(campaign,'siege_action',{'siege_ref':'siege_kankoku_accept','action':'settle'})
    sg=json.load(open(campaign/'state/sieges/siege_kankoku_accept.json')); fort=json.load(open(campaign/'state/fortifications/fort_kankoku_accept.json'))
    assert sg['status']=='settled'; assert fort['food_kg']<20000
    # Troop casualties do not magically damage exact Kankoku masonry. The
    # grapnel route creates infantry access only and does not create a breach.
    assert fort['integrity']==100

def test_fortified_territory_requires_siege_evidence(campaign):
    import pytest
    with pytest.raises(Exception): execute_internal(campaign,'territorial_consequence',{'location_ref':'loc_kankoku_pass','controller':'state_zhao'})
