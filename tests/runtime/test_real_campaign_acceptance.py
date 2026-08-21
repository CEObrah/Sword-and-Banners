import json
import subprocess
from conftest import execute, execute_internal, execute_production, meta, prepare_field_formation, activate_operation

def test_personal_gameplay_and_exact_retail(campaign):
    start_wallet=json.load(open(campaign/'state/economy/player-wallet.json'))['silver']
    start_private_cash=json.load(open(campaign/'state/economy/private/qin.json'))['cash_silver']
    execute(campaign,'scene_consequence',{'summary':'Wei accepts a Qin officer briefing.'})
    execute(campaign,'individual_training',{'focus':'Formation Command','hours':4})
    execute(campaign,'health_injury',{'injury':'training bruise','severity':'minor'})
    execute(campaign,'health_recovery',{'hours':24})
    execute(campaign,'relationship_change',{'target_ref':'char_lin_zhen','kind':'trust','delta':2})
    execute(campaign,'travel',{'destination_ref':'loc_kanyou'})
    execute(campaign,'market_purchase',{'item_key':'common_sword','quantity':1})
    wallet=json.load(open(campaign/'state/economy/player-wallet.json')); market=json.load(open(campaign/'state/markets/kanyou.json')); private=json.load(open(campaign/'state/economy/private/qin.json'))
    assert wallet['silver']==start_wallet-11
    assert market['stock']['common_sword']==59
    assert private['cash_silver']==start_private_cash+11
    execute(campaign,'travel',{'destination_ref':'loc_kankoku_pass'})
    assert json.load(open(campaign/'state/player.json'))['location']=='loc_kankoku_pass'

def test_hidden_information_boundary(campaign):
    execute_internal(campaign,'information_create',{'information_ref':'info_secret_accept','claim':'Zhao covert agent observed','confidence':'0.8','knowers':['char_shen_rui']})
    claim=json.load(open(campaign/'state/information/info_secret_accept.json')); assert 'char_tang_wei' not in claim['knowers']
    execute_internal(campaign,'information_deliver',{'information_ref':'info_secret_accept','source_ref':'char_shen_rui','target_ref':'char_tang_wei'})
    claim=json.load(open(campaign/'state/information/info_secret_accept.json')); assert 'char_tang_wei' in claim['knowers']

def test_sword_manor_and_champions(campaign):
    before=json.load(open(campaign/'state/forces/sword-manor.json'))
    execute(campaign,'cohort_training',{'cohort_ref':'junior_disciple','hours':6})
    after=json.load(open(campaign/'state/forces/sword-manor.json')); assert after['cohort_training_hours']>=6
    first=json.load(open(campaign/'state/formations/tang-champions-first.json'))
    assert first['personnel']==500
    assert first['composition']=={'tang_champion':500}
    assert first['owner_force_ref']=='force_house_tang'
    assert first['command_authority']=='char_tang_wei'
    assert first['commander_ref']=='char_duan_jin' and first['deputy_ref']=='char_shen_rui'
    assert first['mounts']=={'horse':500}

def test_army_lifecycle_and_population_conservation(campaign):
    before=json.load(open(campaign/'state/population/qin.json'))
    execute_internal(campaign,'recruitment',{'state':'qin','personnel':500,'source_stratum':'agricultural','role':'line_infantry'})
    execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':'char_accept_qin_commander','name':'Acceptance Qin Commander','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':'loc_qin_eastern_depot'})
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':'formation_accept_qin','role':'line_infantry','personnel':2000,'location_ref':'loc_qin_eastern_depot','commander_ref':'char_accept_qin_commander'})
    execute_internal(campaign,'formation_train',{'formation_ref':'formation_accept_qin','hours':8})
    # Reconstitution must draw replacements while the formation is physically at its reserve source.
    execute_internal(campaign,'formation_reconstitute',{'formation_ref':'formation_accept_qin','target_personnel':2100})
    execute_internal(campaign,'resupply',{'formation_ref':'formation_accept_qin','food_kg':30000,'war_arrows':10000})
    execute_internal(campaign,'formation_mobilize',{'formation_ref':'formation_accept_qin'})
    execute_internal(campaign,'formation_move',{'formation_ref':'formation_accept_qin','destination_ref':'loc_kanyou'})
    execute_internal(campaign,'formation_split',{'formation_ref':'formation_accept_qin','new_formation_ref':'formation_accept_qin_b','personnel':400})
    execute_internal(campaign,'formation_merge',{'formation_refs':['formation_accept_qin','formation_accept_qin_b']})
    execute_internal(campaign,'formation_demobilize',{'formation_ref':'formation_accept_qin'})
    pop=json.load(open(campaign/'state/population/qin.json')); force=json.load(open(campaign/'state/forces/state-qin.json'))
    assert pop['population_total']==sum(pop['strata'].values())
    assignments=force.get('materialized_assignments',{})
    assigned={str(ref) for ref in assignments}
    unassigned_materialized=sum((v.get('personnel',1) if isinstance(v,dict) else v) for ref,v in force.get('materialized_people',{}).items() if str(ref) not in assigned)
    external_allocated=sum(max(0,int(count)) for roles in force.get('external_personnel_allocations',{}).values() if isinstance(roles,dict) for count in roles.values())
    assert force['headcount']==sum(force['available_by_role'].values())+sum((v['personnel'] if isinstance(v,dict) else v) for v in force['allocated_to_formations'].values())+external_allocated+unassigned_materialized
    assert pop['strata']['active_military']==before['strata']['active_military']+500

def test_state_house_institution_autonomy(campaign):
    from sword_runtime.sim.calendar import CampaignTime
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner=ProductionCampaignPlanner(campaign); planner._reset()
    qin_before=json.load(open(campaign/'state/states/qin.json'))['last_review']
    house_before=json.load(open(campaign/'state/houses/house_tang.json'))['last_review']
    inst_before=planner.read(planner.owner_path('inst_qin_recruitment_office'))['last_review']
    m=meta(campaign); target=str(CampaignTime.parse(m['time']).add_days(75))
    execute_production(campaign,'advance_time',{'target_time':target},request_id='autonomy-window')
    idx=json.load(open(campaign/'state/index/owner-index.json'))['owners']; assert all(f'formation_qin_wei_unit_{i:02d}' in idx for i in range(1,5))
    qin=json.load(open(campaign/'state/states/qin.json')); assert CampaignTime.parse(qin['last_review']) > CampaignTime.parse(qin_before)
    planner=ProductionCampaignPlanner(campaign); planner._reset(); inst=planner.read(planner.owner_path('inst_qin_recruitment_office')); assert CampaignTime.parse(inst['last_review']) > CampaignTime.parse(inst_before)
    house=json.load(open(campaign/'state/houses/house_tang.json')); assert CampaignTime.parse(house['last_review']) > CampaignTime.parse(house_before); assert house.get('autonomous_reviews')

def test_operation_and_pay(campaign):
    champion_location=json.load(open(campaign/'state/formations/tang-champions-first.json'))['location_ref']
    execute(campaign,'operation_create',{'operation_ref':'operation_accept','objective':'formation readiness review','formation_refs':['formation_tang_champions_first'],'location_ref':champion_location})
    execute(campaign,'operation_transition',{'operation_ref':'operation_accept','status':'mobilizing'})
    execute(campaign,'operation_transition',{'operation_ref':'operation_accept','status':'active'})
    execute(campaign,'operation_transition',{'operation_ref':'operation_accept','status':'completed'})
    operation_index=json.load(open(campaign/'state/operations/index.json'))
    owner_index=json.load(open(campaign/'state/index/owner-index.json'))['owners']
    assert 'operation_accept' not in operation_index['operations']
    assert owner_index['operation_accept']
    assert json.load(open(campaign/owner_index['operation_accept']))['status']=='completed'
    before=json.load(open(campaign/'state/economy/player-wallet.json'))['silver']; execute_internal(campaign,'enlisted_service_pay',{'state':'qin','amount_silver':7}); after=json.load(open(campaign/'state/economy/player-wallet.json'))['silver']; assert after==before+7


def test_state_reacts_to_known_enemy_action(campaign):
    from sword_runtime.sim.calendar import CampaignTime
    execute_internal(campaign,'state_action',{'state':'zhao','action':'enemy_action','source_state':'qin','severity':80,'provenance':'border report'})
    m=meta(campaign); target=str(CampaignTime.parse(m['time']).add_days(40)); execute(campaign,'advance_time',{'target_time':target},request_id='zhao-react')
    zhao=json.load(open(campaign/'state/states/zhao.json')); assert zhao['autonomous_posture']=='fortify_and_reinforce'
    op=json.load(open(campaign/'state/operations/operation_auto_zhao_border_response.json')); assert op['autonomous'] is True and op['status']=='active'
    f=json.load(open(campaign/'state/formations/zhao-border-line.json')); assert f['mobilized'] is True

def test_state_replacement_recruiting_is_bounded_and_conserved(campaign):
    from sword_runtime.sim.calendar import CampaignTime
    qforce0=json.load(open(campaign/'state/forces/state-qin.json'))
    qpop0=json.load(open(campaign/'state/population/qin.json'))
    qstate0=json.load(open(campaign/'state/states/qin.json'))
    qcmd='char_accept_replacement_qin_commander'; zcmd='char_accept_replacement_zhao_commander'
    execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':qcmd,'name':'Replacement Qin Commander','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':'loc_qin_eastern_depot'})
    execute_internal(campaign,'person_materialize',{'state':'zhao','person_ref':zcmd,'name':'Replacement Zhao Commander','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':'loc_zhao_regional_01'})
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':'formation_repl_qin','role':'line_infantry','personnel':4000,'location_ref':'loc_qin_eastern_depot','commander_ref':qcmd})
    defender_ref='formation_repl_zhao'
    execute_internal(campaign,'formation_create',{'state':'zhao','formation_ref':defender_ref,'role':'line_infantry','personnel':4000,'location_ref':'loc_zhao_regional_01','commander_ref':zcmd})
    prepare_field_formation(campaign,'formation_repl_qin'); prepare_field_formation(campaign,defender_ref); op=activate_operation(campaign,'operation_replacement_accept',['formation_repl_qin',defender_ref])
    execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':['formation_repl_qin'],'defender_formation_refs':[defender_ref],'operation_ref':op,'objective':'replacement acceptance battle'})
    qforce1=json.load(open(campaign/'state/forces/state-qin.json'))
    qpop1=json.load(open(campaign/'state/population/qin.json'))
    assert qforce1['headcount'] < qforce0['authorized_strength']
    assert qpop1['population_total'] == sum(qpop1['strata'].values())
    shortage=qforce0['authorized_strength']-qforce1['headcount']
    m=meta(campaign); target=str(CampaignTime.parse(m['time']).add_days(40)); execute(campaign,'advance_time',{'target_time':target},request_id='replacement-close')
    qforce2=json.load(open(campaign/'state/forces/state-qin.json'))
    qpop2=json.load(open(campaign/'state/population/qin.json'))
    qstate2=json.load(open(campaign/'state/states/qin.json'))
    recruited=qforce2['headcount']-qforce1['headcount']
    assert 0 < recruited <= shortage
    assert qpop2['strata']['agricultural'] == qpop1['strata']['agricultural']-recruited
    assert qpop2['strata']['active_military'] == qpop1['strata']['active_military']+recruited
    monthly_net=qstate0['normal_monthly_revenue_silver']-qstate0['normal_monthly_expense_silver']
    operating_delta=qstate2['treasury_silver']-qstate0['treasury_silver']+recruited*12
    assert operating_delta > 0 and operating_delta % monthly_net == 0
    assert 1 <= operating_delta // monthly_net <= 2
    assert qpop2['population_total'] == sum(qpop2['strata'].values())


def test_private_household_battle_losses_reconcile_population(campaign):
    before=json.load(open(campaign/'state/population/qin.json'))
    house_force_before=json.load(open(campaign/'state/forces/house-tang.json'))
    opponent_cmd='char_accept_house_battle_qin_commander'
    execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':opponent_cmd,'name':'House Battle Qin Commander','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':'loc_qin_eastern_depot'})
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':'formation_house_opponent','role':'line_infantry','personnel':5000,'location_ref':'loc_qin_eastern_depot','commander_ref':opponent_cmd})
    execute_internal(campaign,'resupply',{'formation_ref':'formation_house_opponent','food_kg':40000,'war_arrows':20000})
    execute_internal(campaign,'formation_mobilize',{'formation_ref':'formation_house_opponent'})
    # This regression isolates casualty/population reconciliation. Keep the disposable
    # opponent at the Champions' actual current location rather than hard-coding a
    # campaign-phase location that may lawfully change in later baselines.
    champion_path=campaign/'state/formations/tang-champions-first.json'
    champion=json.load(open(champion_path)); logistics=dict(champion['logistics']); logistics['food_kg']=500; logistics['fodder_kg']=400; champion['logistics']=logistics
    champion_path.write_text(json.dumps(champion,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    subprocess.run(['git','-C',str(campaign),'add',str(champion_path.relative_to(campaign))],check=True)
    subprocess.run(['git','-C',str(campaign),'commit','--quiet','-m','test: casualty reconciliation fixture'],check=True)
    qin_force_before_battle=json.load(open(campaign/'state/forces/state-qin.json'))
    battle_location=json.load(open(champion_path))['location_ref']
    assert json.load(open(campaign/'state/formations/house-opponent.json'))['location_ref'] == battle_location
    op=activate_operation(campaign,'operation_house_opponent',['formation_tang_champions_first','formation_house_opponent'],location=battle_location)
    execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':['formation_tang_champions_first'],'defender_formation_refs':['formation_house_opponent'],'operation_ref':op,'objective':'principal extraction under attack'})
    after=json.load(open(campaign/'state/population/qin.json'))
    house_force_after=json.load(open(campaign/'state/forces/house-tang.json'))
    loss=house_force_before['headcount']-house_force_after['headcount']
    assert loss > 0
    assert after['strata']['private_household_military'] == before['strata']['private_household_military']-loss
    qin_force_after=json.load(open(campaign/'state/forces/state-qin.json'))
    qin_loss=qin_force_before_battle['headcount']-qin_force_after['headcount']
    assert after['population_total'] == before['population_total']-loss-qin_loss
    assert after['population_total'] == sum(after['strata'].values())
