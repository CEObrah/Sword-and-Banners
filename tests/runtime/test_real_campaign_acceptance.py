import json
from conftest import execute, execute_internal, meta, prepare_field_formation, activate_operation

def test_personal_gameplay_and_exact_retail(campaign):
    start_wallet=json.load(open(campaign/'state/economy/player-wallet.json'))['silver']
    execute(campaign,'scene_consequence',{'summary':'Wei accepts a Qin officer briefing.'})
    execute(campaign,'individual_training',{'focus':'Formation Command','hours':4})
    execute(campaign,'health_injury',{'injury':'training bruise','fatigue':5})
    execute(campaign,'health_recovery',{'health':'healthy','fatigue_recovery':6})
    execute(campaign,'relationship_change',{'target_ref':'char_ouki','kind':'trust','delta':2})
    execute(campaign,'travel',{'destination_ref':'loc_kanyou'})
    execute(campaign,'market_purchase',{'item_key':'common_sword','quantity':1})
    wallet=json.load(open(campaign/'state/economy/player-wallet.json')); market=json.load(open(campaign/'state/markets/kanyou.json')); private=json.load(open(campaign/'state/economy/private/qin.json'))
    assert wallet['silver']==start_wallet-11
    assert market['stock']['common_sword']==59
    assert private['cash_silver']==1000011
    execute(campaign,'travel',{'destination_ref':'loc_kankoku_pass'})
    assert json.load(open(campaign/'state/player.json'))['location']=='loc_kankoku_pass'

def test_hidden_information_boundary(campaign):
    execute_internal(campaign,'information_create',{'information_ref':'info_secret_accept','claim':'Zhao covert agent observed','confidence':'0.8','knowers':['char_riboku']})
    claim=json.load(open(campaign/'state/information/info_secret_accept.json')); assert 'char_tang_wei' not in claim['knowers']
    execute_internal(campaign,'information_deliver',{'information_ref':'info_secret_accept','target_ref':'char_tang_wei'})
    claim=json.load(open(campaign/'state/information/info_secret_accept.json')); assert 'char_tang_wei' in claim['knowers']

def test_sword_manor_and_champions(campaign):
    before=json.load(open(campaign/'state/forces/sword-manor.json'))
    execute(campaign,'cohort_training',{'cohort_ref':'junior_disciple','hours':6})
    after=json.load(open(campaign/'state/forces/sword-manor.json')); assert after['cohort_training_hours']>=6
    first=json.load(open(campaign/'state/formations/tang-champions-first.json')); second=json.load(open(campaign/'state/formations/tang-champions-second.json'))
    assert first['personnel']==50 and second['personnel']==50
    assert first['doctrine_behavior']['primary_success_condition']=='Tang Wei returns alive'
    execute(campaign,'formation_mobilize',{'formation_ref':'formation_tang_champions_first'})
    mobilized=json.load(open(campaign/'state/formations/tang-champions-first.json')); assert mobilized['mobilized'] is True

def test_army_lifecycle_and_population_conservation(campaign):
    before=json.load(open(campaign/'state/population/qin.json'))
    execute_internal(campaign,'recruitment',{'state':'qin','personnel':500,'source_stratum':'agricultural','role':'line_infantry'})
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':'formation_accept_qin','role':'line_infantry','personnel':2000,'location_ref':'loc_qin_eastern_depot','commander_ref':'char_heki'})
    execute_internal(campaign,'formation_train',{'formation_ref':'formation_accept_qin','hours':8})
    execute_internal(campaign,'resupply',{'formation_ref':'formation_accept_qin','food_kg':30000,'war_arrows':10000})
    execute_internal(campaign,'formation_mobilize',{'formation_ref':'formation_accept_qin'})
    execute_internal(campaign,'formation_move',{'formation_ref':'formation_accept_qin','destination_ref':'loc_kanyou'})
    execute_internal(campaign,'formation_split',{'formation_ref':'formation_accept_qin','new_formation_ref':'formation_accept_qin_b','personnel':400})
    execute_internal(campaign,'formation_merge',{'formation_refs':['formation_accept_qin','formation_accept_qin_b']})
    execute_internal(campaign,'formation_reconstitute',{'formation_ref':'formation_accept_qin','target_personnel':2100})
    execute_internal(campaign,'formation_demobilize',{'formation_ref':'formation_accept_qin'})
    pop=json.load(open(campaign/'state/population/qin.json')); force=json.load(open(campaign/'state/forces/state-qin.json'))
    assert pop['population_total']==sum(pop['strata'].values())
    assert force['headcount']==sum(force['available_by_role'].values())+sum((v['personnel'] if isinstance(v,dict) else v) for v in force['allocated_to_formations'].values())+sum((v.get('personnel',1) if isinstance(v,dict) else v) for v in force['materialized_people'].values())
    assert pop['strata']['active_military']==before['strata']['active_military']+500

def test_state_house_institution_autonomy(campaign):
    from sword_runtime.sim.calendar import CampaignTime
    m=meta(campaign); target=str(CampaignTime.parse(m['time']).add_years(3)); execute(campaign,'advance_time',{'target_time':target},request_id='autonomy-three')
    idx=json.load(open(campaign/'state/index/owner-index-gold.json'))['owners']; assert 'formation_qin_border_line' in idx
    qin=json.load(open(campaign/'state/states/qin.json')); assert qin['last_review']==target
    inst=json.load(open(campaign/'state/institutions/inst_qin_recruitment_office.json')); assert inst['last_review']==target
    house=json.load(open(campaign/'state/houses/house_tang.json')); assert house['last_review']==target; assert house['projects']
    treasury=json.load(open(campaign/'state/treasury/treasury-house-tang.json')); assert treasury['runtime']['completed_monthly_closes']>0

def test_operation_family_pay_and_internal_repair(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    execute(campaign,'operation_create',{'operation_ref':'operation_accept','objective':'logistics_review','formation_refs':[],'location_ref':'loc_kanyou'})
    execute(campaign,'operation_transition',{'operation_ref':'operation_accept','status':'succeeded'})
    execute(campaign,'family_event',{'house_ref':'house_tang','kind':'marriage','person_ref':'char_tang_kai'})
    before=json.load(open(campaign/'state/economy/player-wallet.json'))['silver']; execute_internal(campaign,'enlisted_service_pay',{'state':'qin','amount_silver':7}); after=json.load(open(campaign/'state/economy/player-wallet.json'))['silver']; assert after==before+7
    execute(campaign,'repair',{'path':'state/houses/house_tang.json','changes':{'threat_level':'0.2'},'reason':'confirmed test repair'},actor=RepositoryCommandPlanner.INTERNAL_ACTOR,mode='maintenance')
    history=json.load(open(campaign/'state/history/events/index.json')); assert any(x['kind']=='explicit_repair' for x in history['events'])


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
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':'formation_repl_qin','role':'line_infantry','personnel':4000,'commander_ref':'char_heki'})
    execute_internal(campaign,'formation_create',{'state':'zhao','formation_ref':'formation_repl_zhao','role':'line_infantry','personnel':4000,'commander_ref':'char_riboku'})
    prepare_field_formation(campaign,'formation_repl_qin'); prepare_field_formation(campaign,'formation_repl_zhao'); op=activate_operation(campaign,'operation_replacement_accept',['formation_repl_qin','formation_repl_zhao'])
    execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':['formation_repl_qin'],'defender_formation_refs':['formation_repl_zhao'],'operation_ref':op,'objective':'replacement acceptance battle'})
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
    assert qstate2['treasury_silver'] == qstate0['treasury_silver'] + (qstate0['normal_monthly_revenue_silver']-qstate0['normal_monthly_expense_silver']) - recruited*12
    assert qpop2['population_total'] == sum(qpop2['strata'].values())


def test_private_household_battle_losses_reconcile_population(campaign):
    before=json.load(open(campaign/'state/population/qin.json'))
    house_force_before=json.load(open(campaign/'state/forces/house-tang.json'))
    execute_internal(campaign,'formation_create',{'state':'zhao','formation_ref':'formation_house_opponent','role':'line_infantry','personnel':5000,'commander_ref':'char_riboku'})
    prepare_field_formation(campaign,'formation_tang_champions_first'); prepare_field_formation(campaign,'formation_house_opponent'); op=activate_operation(campaign,'operation_house_opponent',['formation_tang_champions_first','formation_house_opponent'])
    execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':['formation_tang_champions_first'],'defender_formation_refs':['formation_house_opponent'],'operation_ref':op,'objective':'principal extraction under attack'})
    after=json.load(open(campaign/'state/population/qin.json'))
    house_force_after=json.load(open(campaign/'state/forces/house-tang.json'))
    loss=house_force_before['headcount']-house_force_after['headcount']
    assert loss > 0
    assert after['strata']['private_household_military'] == before['strata']['private_household_military']-loss
    assert after['population_total'] == before['population_total']-loss
    assert after['population_total'] == sum(after['strata'].values())
