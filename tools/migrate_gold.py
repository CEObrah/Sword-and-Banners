#!/usr/bin/env python3
from __future__ import annotations
import copy, json, re, shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'state'; GAME=ROOT/'game'; ARCH=ROOT/'archive'/'legacy-execution'
STATES=('qin','zhao','chu','wei','han','yan','qi')
STATE_NAMES={s:s.upper() if s!='qin' else 'Qin' for s in STATES}

def load(rel):
    return json.loads((ROOT/rel).read_text(encoding='utf-8'))
def dump(rel,obj):
    p=ROOT/rel; p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding='utf-8')
def move_to_archive(rel):
    src=ROOT/rel
    if not src.exists(): return
    dst=ARCH/rel
    dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists(): shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
    shutil.move(str(src),str(dst))

def parse_pairs(text):
    out={}
    if not isinstance(text,str): return out
    for part in text.split(';'):
        m=re.match(r'\s*([A-Za-z0-9_]+)\s+([0-9]+)\s*$',part)
        if m: out[m.group(1)]=int(m.group(2))
    return out

# ---------- static Gold catalogs ----------
world_dir=GAME/'data'/'world'; world_dir.mkdir(parents=True,exist_ok=True)

def loc(ref,name,state=None,functions=(),kind='place',fortified=False,flavor=False):
    return {'ref':ref,'name':name,'state':state,'kind':kind,'functions':list(functions),'fortified':bool(fortified),'flavor_only':bool(flavor)}

locations=[
 loc('loc_kanyou','Kanyou','qin',('politics','market','recruitment','supply','information'), 'capital',True),
 loc('loc_kankoku_pass','Kankoku Pass','qin',('movement','chokepoint','fortification','supply','battlefield'),'pass',True),
 loc('loc_bu_pass','Bu Pass','qin',('movement','chokepoint','fortification'),'pass',True),
 loc('loc_sai','Sai','qin',('movement','fortification','market'),'city',True),
 loc('loc_qin_eastern_depot','Qin Eastern Military Depot','qin',('supply','military','market'),'depot',False),
 loc('loc_qin_western_fort','Qin Western Regional Fort','qin',('fortification','military','supply'),'fort',True),
 loc('loc_kantan','Kantan','zhao',('politics','market','recruitment','supply'),'capital',True),
 loc('loc_gyou','Gyou','zhao',('market','fortification','supply','battlefield'),'city',True),
 loc('loc_zhao_border_fort','Zhao Southern Border Fort','zhao',('fortification','military','supply'),'fort',True),
 loc('loc_shintei','Shintei','chu',('politics','market','supply'),'capital',True),
 loc('loc_chu_north_fort','Chu Northern Fort','chu',('fortification','military','supply'),'fort',True),
 loc('loc_dairyou','Dairyou','wei',('politics','market','fortification','supply'),'capital',True),
 loc('loc_keiyou','Keiyou','wei',('fortification','market','battlefield'),'city',True),
 loc('loc_wei_west_fort','Wei Western Fort','wei',('fortification','military'),'fort',True),
 loc('loc_han_capital','Shintei of Han','han',('politics','market','supply'),'capital',True),
 loc('loc_han_frontier_fort','Han Frontier Fort','han',('fortification','military'),'fort',True),
 loc('loc_ji','Ji','yan',('politics','market','fortification'),'capital',True),
 loc('loc_yan_south_fort','Yan Southern Fort','yan',('fortification','military'),'fort',True),
 loc('loc_ei','Linzi','qi',('politics','market','fortification','trade'),'capital',True),
 loc('loc_qi_west_fort','Qi Western Fort','qi',('fortification','military'),'fort',True),
 loc('loc_tang_manor_inner_citadel_family_hall','Tang Manor Family Hall','qin',('house','scene'),'hall',False),
 loc('loc_tang_manor_training_ground','Sword Manor Training Ground','qin',('training','house'),'training_ground',False),
 loc('loc_tang_manor_market_gate','Tang Manor Market Gate','qin',('market','house'),'market',False),
 loc('loc_kanyou_officer_bureau','Kanyou Officer Intake Bureau','qin',('recruitment','politics'),'office',False),
]
# Add strategically useful regional nodes and pure scene/flavor places to reach 76.
for s in STATES:
    for i in range(1,5):
        locations.append(loc(f'loc_{s}_regional_{i:02d}',f'{STATE_NAMES[s]} Regional Seat {i}',s,('movement','taxation','recruitment','information'),'regional_seat', i==1))
for i in range(1,25):
    s=STATES[(i-1)%len(STATES)]
    locations.append(loc(f'loc_flavor_{i:02d}',f'{STATE_NAMES[s]} Local Venue {i}',s,('scene',),'scene_venue',False,True))
locations=locations[:76]

def route(ref,a,b,hours,modes=('foot','horse','formation')):
    return {'ref':ref,'a':a,'b':b,'hours':hours,'modes':list(modes)}
routes=[
 route('route_kanyou_kankoku','loc_kanyou','loc_kankoku_pass',24),
 route('route_kanyou_qin_east_depot','loc_kanyou','loc_qin_eastern_depot',18),
 route('route_kanyou_sai','loc_kanyou','loc_sai',20),
 route('route_kanyou_qin_west_fort','loc_kanyou','loc_qin_western_fort',26),
 route('route_gyou_kantan','loc_gyou','loc_kantan',20),
 route('route_009','loc_gyou','loc_qin_eastern_depot',42),
 route('route_keiyou_dairyou','loc_keiyou','loc_dairyou',18),
 route('route_kankoku_keiyou','loc_kankoku_pass','loc_keiyou',22),
 route('route_kantan_zhao_border','loc_kantan','loc_zhao_border_fort',24),
 route('route_dairyou_wei_west','loc_dairyou','loc_wei_west_fort',20),
]
strategic=[x['ref'] for x in locations if not x['flavor_only']]
idx=1
while len(routes)<54:
    a=strategic[idx%len(strategic)]; b=strategic[(idx+5)%len(strategic)]
    if a!=b and not any({r['a'],r['b']}=={a,b} for r in routes):
        routes.append(route(f'route_{len(routes)+1:03d}',a,b,12+(idx%36)))
    idx+=1

fort_refs=[x['ref'] for x in locations if x['fortified']][:19]
fort_profiles=[{'site_ref':r,'profile_id':f'fort_profile_{r[4:]}','defense_class':'major' if r in {'loc_kankoku_pass','loc_kanyou','loc_kantan'} else 'regional','materialization_required':True} for r in fort_refs]

dump('game/data/world/locations.json',{'schema':'sword-world-locations','locations':locations})
dump('game/data/world/routes.json',{'schema':'sword-world-routes','routes':routes})
dump('game/data/world/fortification-profiles.json',{'schema':'sword-fortification-profiles','profiles':fort_profiles})

noble_names=[
'House Tang','Ou Family','Mou Family','Ouki Household','Kanki Retinue House','Shou Bun Kun Household','Ri Ministerial House','Ryo Fui Household','Shou Hei Kun Household','Sai Taku House','Duke Hyou House','Heki Household','Ei Royal House','Seikyou Branch','Riboku Household','Prince Ka House','Kakukai Political House','Bananji Household','Shibashou House','Kisui House','Renpa Household','Go Military House','Gaimou Household','Reiou House','Earl Shi House','Karin House','Kouen House','Kanmei House','Shun Shin Kun House','Ordo House','Geki Shin House','Ou Ken Royal House','Qi Ministerial House','Han Royal House','Kan Pishi House','Sei Kai House','Yotanwa Mountain Court','Ryouyou Lord House','Wei Jian Household','Duan Jin Household','Shen Rui Household','Tou Household','Toujou Royal House']
assert len(noble_names)==43
nobles=[{'house_ref':'house_'+re.sub('[^a-z0-9]+','_',n.lower()).strip('_'),'name':n,'state':STATES[i%7],'representation':'exact_host' if i<10 else 'cold_catalog','functions':['politics','family','property','retainers']} for i,n in enumerate(noble_names)]
merchant_names=['Jade River','Bronze Crane','Western Grain','Kanyou Silk','Yellow Cart','North Horse','Red Seal','Three Roads','River Reed','White Lantern','Copper Scale','East Gate','Long Wagon','Black Ox','Spring Well','Southern Salt','Iron Reed','Blue Ledger','Golden Millet','Seven Bridges','Mountain Tea']
merchants=[{'merchant_house_ref':f'merchant_house_{i+1:02d}','name':name+' Merchant House','state':STATES[i%7],'representation':'aggregate_private_economy','functions':['trade','credit','transport']} for i,name in enumerate(merchant_names)]
lords=[]
for s in STATES:
    for i in range(1,4): lords.append({'office_ref':f'office_{s}_regional_lord_{i}','state':s,'title':f'{STATE_NAMES[s]} Regional Lord {i}','jurisdiction_ref':f'loc_{s}_regional_{i:02d}'})
dump('game/data/world/noble-houses.json',{'schema':'sword-noble-house-catalog','houses':nobles})
dump('game/data/world/merchant-houses.json',{'schema':'sword-merchant-house-catalog','merchant_houses':merchants})
dump('game/data/world/regional-lords.json',{'schema':'sword-regional-lord-catalog','offices':lords})

# Canon is background gravity, not a predetermined future.
dump('game/data/history/canon-background.json',{
 'schema':'sword-canon-background','future_commitments':[],
 'completed_background':[{'year_bce':260,'event':'Warring States rivalry and Qin reform institutions already shape the campaign world.'},{'year_bce':246,'event':'Ei Sei has inherited the Qin throne while court factions remain politically consequential.'},{'year_bce':245,'event':'The campaign opens with Tang Wei and House Tang active in Qin during continuing interstate competition.'}],
 'conditional_future_pressures':[{'pressure_ref':'pressure_keiyou','label':'Qin-Wei conflict around Keiyou','condition':'only if military and political causes lawfully converge'},{'pressure_ref':'pressure_coalition','label':'Multi-state coalition pressure and Kankoku Pass','condition':'only if interstate hostility and alliances produce it'},{'pressure_ref':'pressure_gyou','label':'Qin-Zhao contest around Gyou','condition':'only if prior campaign history leaves the strategic conditions intact'}]
})

# Economy balance and service issue rules.
economy={
 'schema':'sword-economy-balance','currency':{'copper_per_silver':100},
 'wages':{'unskilled_monthly_silver':4.5,'professional_soldier_monthly_silver':7.0},
 'service_issue':{'standard_service_kit_is_state_issue':True,'includes':['primary service weapon','required basic armor','helmet/shield when role requires','campaign rations','formation ammunition']},
 'prices_silver':{'common_sword':11,'military_sword':23,'military_spear':7,'military_bow':20,'arrows_20':3,'padded_coat':12,'lamellar_cuirass':72,'helmet':21,'shield':10,'grain_kg':0.08,'fodder_kg':0.10,'riding_horse':110,'pack_animal':68,'two_axle_wagon':115},
 'retail_rule':'Exact buyer money and materially scarce stock; ordinary sellers settle into aggregate local/private-economy accounts, not individual merchant balance sheets.'
}
dump('game/data/mechanics/economy-gold.json',economy)

formation_blueprints={
'qin':[('border_line',8000,'line_infantry','char_ouki','doc.house_tang_internal.standard','train.house_tang_internal.standard'),('mobile_reserve',5000,'cavalry','char_mou_bu','doc.house_tang_internal.heavy_cavalry','train.house_tang_internal.heavy_cavalry'),('siege_train',3000,'siege_engineering','char_shou_hei_kun',None,None)],
'zhao':[('border_line',7500,'line_infantry','char_riboku',None,None),('mobile_reserve',5000,'cavalry','char_bananji',None,None),('reconstitution',3500,'line_infantry','char_kochou',None,None)],
'chu':[('field_reserve',9000,'line_infantry','char_karin',None,None),('shock_reserve',5000,'cavalry','char_kanmei',None,None),('siege_train',3200,'siege_engineering','char_kouen',None,None)],
'wei':[('engineered_line',6500,'line_infantry','char_go_hou_mei',None,None),('mobile_reserve',4200,'cavalry','char_gai_mou',None,None),('reconstitution',2800,'line_infantry','char_rei_ou',None,None)],
'yan':[('frontier_army',5200,'line_infantry','char_ordo',None,None),('mobile_reserve',3200,'cavalry','char_geki_shin',None,None)],
'han':[('fortress_reserve',4200,'line_infantry','char_sei_kai',None,None),('mobile_screen',2200,'cavalry',None,None,None)],
'qi':[('coastal_reserve',4200,'line_infantry','char_ou_ken',None,None),('mobile_guard',2400,'cavalry',None,None,None)],
}
dump('game/data/mil/autonomy-blueprints.json',{'schema':'sword-autonomy-blueprints','states':{s:[{'key':a,'personnel':b,'role':c,'commander_ref':d,'doctrine_ref':e,'training_ref':f} for a,b,c,d,e,f in v] for s,v in formation_blueprints.items()}})

# ---------- migrate current mutable authorities ----------
macro=load('state/polity/external-state-macros.json')
flows=load('state/polity/external-state-flows.json')
pops=load('state/pop/external-civil-population.json')
depots=load('state/market/regional-depots.json')
mounts=load('state/res/external-mount-pools.json')
flow_by={r['record_id']:r.get('facts',{}) for r in flows['records'] if r.get('record_id') in STATES}
macro_by={r['record_id'].removeprefix('state_').removesuffix('_macro'):r.get('facts',{}) for r in macro['records'] if str(r.get('record_id','')).startswith('state_')}
pop_by={r['record_id'].removeprefix('civil_pool_'):r.get('facts',{}) for r in pops['records'] if str(r.get('record_id','')).startswith('civil_pool_')}
depot_by={r['record_id'].removeprefix('state_depot_'):r.get('facts',{}) for r in depots['records'] if str(r.get('record_id','')).startswith('state_depot_')}
mount_by={r['record_id'].removeprefix('mount_pool_'):r.get('facts',{}) for r in mounts['records'] if str(r.get('record_id','')).startswith('mount_pool_')}

for d in ('forces','formations','population','states','depots','mounts','houses','institutions','factions','economy/private','markets','operations','information','sieges','fortifications','history/events','territory'):
    (STATE/d).mkdir(parents=True,exist_ok=True)

# State force ownership preserves original role pools and aggregate capability references.
for s in STATES:
    fp=load(f'state/force-pool/{s}.json')
    roles={}
    for p in fp.get('troop_pools',[]):
        role=p.get('role'); count=int(p.get('count',0))
        if role and role!='command_personnel': roles[role]=roles.get(role,0)+count
    force={
      'schema':'sword-force','owner_id':f'force_state_{s}','owner_type':'force','administrative_owner':f'state_{s}','kind':'state_force','headcount':int(fp['headcount']),
      'available_by_role':roles,'allocated_to_formations':{},'materialized_people':{},'source_legacy_ref':f'archive/legacy-execution/state/force-pool/{s}.json'
    }
    dump(f'state/forces/state-{s}.json',force)

# House Tang has separate permanent owners. Keep Champions inside conserved private headcount.
house_guard=load('state/force/house-guards.json'); house_cav=load('state/force/house-guardian-cavalry.json'); manor=load('state/force/sword-manor-personnel.json')
def guess_count(obj):
    for key in ('count','personnel','headcount'):
        v=obj.get(key)
        if isinstance(v,int): return v
    total=0
    for rec in obj.get('records',[]):
        f=rec.get('facts',{})
        for k in ('count','personnel','headcount'):
            if isinstance(f.get(k),int): total+=f[k]
    return total
# Conservative known force totals; exact old files remain archived evidence.
tang_force={'schema':'sword-force','owner_id':'force_house_tang','owner_type':'force','administrative_owner':'house_tang','kind':'house_force','headcount':1400,'available_by_role':{'house_guard':800,'heavy_cavalry':500},'allocated_to_formations':{'formation_tang_champions_first':50,'formation_tang_champions_second':50},'materialized_people':{}}
dump('state/forces/house-tang.json',tang_force)
dump('state/forces/sword-manor.json',{'schema':'sword-force','owner_id':'institution_sword_manor','owner_type':'force','administrative_owner':'house_tang','kind':'institution_cohort','headcount':1600,'available_by_role':{'trainee':600,'junior_disciple':450,'general_disciple':350,'senior_disciple':150,'officer':50},'allocated_to_formations':{},'materialized_people':{}})

# Champions: authoritative exact formations. Identity is aggregate except named commanders.
for suffix,commander in (('first','char_duan_jin'),('second','char_shen_rui')):
    old=load(f'state/unit/tang-champions-{suffix}.json')
    form={
      'schema':'sword-formation','formation_ref':f'formation_tang_champions_{suffix}','name':old.get('name'),
      'owner_force_ref':'force_house_tang','administrative_owner':'char_tang_wei','command_authority':'char_tang_wei','commander_ref':commander,
      'personnel':50,'composition':{'heavy_cavalry':50},'location_ref':'loc_tang_manor_inner_citadel_family_hall','doctrine_ref':'doc.tang_wei.household_champions','training_ref':'train.tang_wei.household_champions',
      'readiness':88,'morale':92,'cohesion':94,'fatigue':0,'equipment_completeness':'1.0','experience':'veteran','status':'ready','mobilized':False,
      'logistics':{'food_kg':0,'fodder_kg':0,'war_arrows':1800},'mounts':{'horse_war_heavy':50},
      'doctrine_behavior':{'primary_success_condition':'Tang Wei returns alive','principal_ref':'char_tang_wei','extraction_priority':100,'casualty_tolerance':'low_when_extraction_possible','offensive_use':'only_when_required_by_protection_or_order'}
    }
    dump(f'state/formations/tang-champions-{suffix}.json',form)

# State population, treasury, depots, mounts.
for s in STATES:
    pd=copy.deepcopy(pop_by[s]); dist=copy.deepcopy(pd['population_distribution'])
    # private household troops are a distinct population class and come out of household/service.
    private=0
    if s in {'qin','zhao','chu','wei'}:
        private={'qin':2360,'zhao':620,'chu':820,'wei':360}.get(s,0)
        if private and dist['household_and_service']>=private:
            dist['household_and_service']-=private; dist['private_household_military']=private
    dump(f'state/population/{s}.json',{'schema':'sword-population','owner_id':f'population_{s}','state':s,'population_total':int(pd['population_total']),'strata':dist,'demography':{'birth_rate_per_thousand':'25.0','death_rate_per_thousand':'17.0','last_close':'245-BCE-12-04T07:22:48+08:00','closes':0}})
    m=macro_by[s]; f=flow_by[s]
    dump(f'state/states/{s}.json',{'schema':'sword-state','owner_id':f'state_{s}','state':s,'treasury_silver':int(m['treasury_units'])*100000,'administrative_capacity':m['administrative_capacity'],'internal_stability':m['internal_stability'],'mobilization_readiness':m['mobilization_readiness'],'normal_monthly_revenue_silver':f['monthly_realized_revenue_silver'],'normal_monthly_expense_silver':f['monthly_normal_expense_silver'],'strategic_goals':['protect core territory','maintain military readiness'],'known_threats':{},'diplomacy':{},'territorial_control':[],'last_review':'245-BCE-12-04T07:22:48+08:00'})
    df=depot_by[s]
    dump(f'state/depots/{s}.json',{'schema':'sword-depot','owner_id':f'state_depot_{s}','state':s,'stocks':df,'location_ref':f'loc_{s}_regional_01' if s!='qin' else 'loc_qin_eastern_depot'})
    mf=mount_by[s]
    health=parse_pairs(mf.get('health_distribution')); types=parse_pairs(mf.get('type_distribution'))
    dump(f'state/mounts/{s}.json',{'schema':'sword-mount-pool','owner_id':f'mount_pool_{s}','state':s,'total':int(mf['total_serviceable_mounts']),'health':health,'types':types,'allocated_to_formations':{}})
    dump(f'state/economy/private/{s}.json',{'schema':'sword-private-economy','owner_id':f'private_economy_{s}','state':s,'cash_silver':1000000,'retail_sink_source':True})

# Exact player wallet and Kanyou retail stock.
dump('state/economy/player-wallet.json',{'schema':'sword-wallet','owner_id':'wallet_char_tang_wei','person_ref':'char_tang_wei','silver':200,'copper':0})
dump('state/markets/kanyou.json',{'schema':'sword-market','owner_id':'market_kanyou','location_ref':'loc_kanyou','private_economy_ref':'private_economy_qin','stock':{'common_sword':60,'military_sword':25,'military_spear':120,'military_bow':50,'arrows_20':400,'padded_coat':80,'lamellar_cuirass':35,'helmet':60,'shield':60},'prices_ref':'game/data/mechanics/economy-gold.json'})

# House hosts. Tang is exact; other high-salience households remain compact aggregates.
hot_house_specs=[
 ('house_tang','qin','char_tang_zhu',0),('house_ou_family','qin','char_ousen',320),('house_mou_family','qin','char_mou_gou',280),('house_ouki_household','qin','char_ouki',520),('house_kanki_retinue_house','qin','char_kanki',760),('house_riboku_household','zhao','char_riboku',620),('house_go_military_house','wei','char_go_hou_mei',360),('house_karin_house','chu','char_karin',820),('house_shou_bun_kun_household','qin','char_shou_bun_kun',180),('house_tou_household','qin','char_tou',220)]
for href,s,leader,troops in hot_house_specs:
    dump(f'state/houses/{href}.json',{'schema':'sword-house','owner_id':href,'house_ref':href,'state':s,'leader_ref':leader,**({'treasury_ref':'treasury_house_tang'} if href=='house_tang' else {'treasury_silver':150000+troops*20}),'military_force_ref':'force_house_tang' if href=='house_tang' else (f'force_{href}' if troops else None),'goals':['preserve household','improve standing'],'projects':[],'threat_level':'0.1','lineage_cohort':{'adults':14 if href!='house_tang' else 4,'children':5 if href!='house_tang' else 0,'elders':2,'marriages':4,'last_close':'245-BCE-12-04T07:22:48+08:00'},'last_review':'245-BCE-12-04T07:22:48+08:00'})
    if href!='house_tang' and troops:
        role='household_retainer'
        dump(f'state/forces/{href}.json',{'schema':'sword-force','owner_id':f'force_{href}','owner_type':'force','administrative_owner':href,'kind':'house_force','headcount':troops,'available_by_role':{role:0},'allocated_to_formations':{f'formation_{href}_guard':troops},'materialized_people':{}})
        dump(f'state/formations/{href}-guard.json',{'schema':'sword-formation','formation_ref':f'formation_{href}_guard','name':href.replace('_',' ').title()+' Guard','owner_force_ref':f'force_{href}','administrative_owner':href,'command_authority':leader,'commander_ref':leader,'personnel':troops,'composition':{role:troops},'location_ref':f'loc_{s}_regional_01','doctrine_ref':'household_guard','training_ref':'household_retainer','readiness':72,'morale':78,'cohesion':74,'fatigue':0,'equipment_completeness':'0.85','experience':'trained','status':'ready','mobilized':False,'logistics':{'food_kg':0,'fodder_kg':0,'war_arrows':0},'mounts':{},'doctrine_behavior':{'primary_success_condition':'protect household principal and assets','extraction_priority':80}})

# 42 state institutions, 6 per state.
inst_types=[('military_bureau','Military Bureau'),('recruitment_office','Recruitment Office'),('granary_depot_office','Granary and Depot Office'),('horse_administration','Horse Administration'),('fortification_bureau','Fortification Bureau'),('regional_administration','Regional Administration')]
for s in STATES:
    for kind,label in inst_types:
        cap={'military_bureau':80,'recruitment_office':12000,'granary_depot_office':85,'horse_administration':75,'fortification_bureau':70,'regional_administration':78}[kind]
        dump(f'state/institutions/inst_{s}_{kind}.json',{'schema':'sword-institution','owner_id':f'inst_{s}_{kind}','state':s,'kind':kind,'name':f'{STATE_NAMES[s]} {label}','capacity':cap,'staffing':'aggregate','resources':{},'policy':'maintain lawful state function','projects':[],'backlog':0,'last_review':'245-BCE-12-04T07:22:48+08:00'})

# 15 faction agendas sourced from old living-faction labels where possible.
old_factions=list((STATE/'reg'/'living-factions').glob('*.json'))
for i in range(15):
    if i<len(old_factions):
        src=json.loads(old_factions[i].read_text()); fid=src.get('owner_id') or src.get('id') or old_factions[i].stem; name=src.get('name') or src.get('label') or old_factions[i].stem.replace('-',' ').title()
    else:
        fid=f'faction_gold_{i+1:02d}'; name=f'Political Faction {i+1}'
    safe=re.sub('[^a-z0-9_]+','_',str(fid).lower()).strip('_')
    dump(f'state/factions/{safe}.json',{'schema':'sword-faction-agenda','owner_id':safe,'name':name,'goals':['preserve influence','advance current interests'],'relationships':{},'knowledge':[],'resources':{},'commitments':[],'pressure':0,'last_review':'245-BCE-12-04T07:22:48+08:00'})

# Territory control is exact at strategic sites. Fortified control cannot change via generic territory command without siege evidence.
control={x['ref']:{'controller':f"state_{x['state']}" if x.get('state') else None,'fortified':x['fortified']} for x in locations if x.get('state') and not x['flavor_only']}
dump('state/territory/control.json',{'schema':'sword-territory-control','owner_id':'territory_control','sites':control})

# Runtime scheduler: 82 cold causal hosts, one due event each. No directory scans are needed to discover them.
hosts={}; events=[]
def add_host(hid,kind,owner_ref,days):
    due='245-BCE-12-%02dT07:22:48+08:00' % min(28,4+min(days,24)) if days<25 else '244-BCE-%02d-04T07:22:48+08:00' % (1 if days<60 else 3 if days<120 else 6 if days<300 else 12)
    # scheduler uses direct integer recurrence seconds; the first due date only seeds the queue.
    hosts[hid]={'kind':kind,'owner_ref':owner_ref,'resolved_through':'245-BCE-12-04T07:22:48+08:00','safe_through':'245-BCE-12-04T07:22:48+08:00','next_due':due,'recurrence_seconds':days*86400,'quiet_run_count':0}
    events.append({'event_id':f'event_{hid}_review','target_host':hid,'kind':f'{kind}_review','due_at':due,'priority':100})
for s in STATES: add_host(f'host_state_{s}','state',f'state_{s}',30)
for p in sorted((STATE/'factions').glob('*.json')): add_host('host_'+p.stem,'faction',json.loads(p.read_text())['owner_id'],90)
for p in sorted((STATE/'institutions').glob('*.json')): add_host('host_'+p.stem,'institution',json.loads(p.read_text())['owner_id'],60)
for p in sorted((STATE/'houses').glob('*.json')): add_host('host_'+p.stem,'house',json.loads(p.read_text())['owner_id'],120)
for s in STATES: add_host(f'host_population_{s}','population',f'population_{s}',365)
add_host('host_sword_manor','institution','institution_sword_manor',90)
assert len(hosts)==82, len(hosts)
dump('state/runtime.json',{'schema':'sword-runtime-state','owner_id':'runtime','world_time':'245-BCE-12-04T07:22:48+08:00','hosts':hosts,'events':sorted(events,key=lambda e:(e['due_at'],e['priority'],e['event_id'])),'metrics':{'global_person_scans':0,'global_faction_scans':0,'global_force_scans':0,'global_house_scans':0,'planning_reads':0,'writes':0,'hosts_woken':0,'events_processed':0}})

# Meta points at the only active temporal frontier.
meta=load('state/meta.json'); meta['temporal_frontier']='state/runtime.json'; dump('state/meta.json',meta)
player=load('state/player.json')
if isinstance(player.get('activity_contract'),dict): player['activity_contract']['clock_owner']='state/runtime.json#host_sword_manor'
player.setdefault('runtime',{})['last_settled_at']=meta['time']; dump('state/player.json',player)

# Empty exact lifecycle registries.
dump('state/operations/index.json',{'schema':'sword-operation-index','owner_id':'operations','operations':{}})
dump('state/information/index.json',{'schema':'sword-information-index','owner_id':'information_index','claims':{}})
dump('state/sieges/index.json',{'schema':'sword-siege-index','owner_id':'sieges','sieges':{}})
dump('state/fortifications/index.json',{'schema':'sword-fortification-index','owner_id':'fortifications','fortifications':{}})
dump('state/history/events/index.json',{'schema':'sword-history-index','owner_id':'semantic_history','events':[]})

# Direct owner index. Cold/static catalogs are not mutable owners.
index={}
for base in ('forces','formations','population','states','depots','mounts','houses','institutions','factions','economy','markets','operations','information','sieges','fortifications','territory'):
    for p in (STATE/base).rglob('*.json'):
        d=json.loads(p.read_text()); oid=d.get('owner_id') or d.get('formation_ref')
        if isinstance(oid,str):
            if oid in index: raise RuntimeError(f'duplicate owner {oid}')
            index[oid]=str(p.relative_to(ROOT))
for p in [STATE/'player.json']+list((STATE/'char').glob('*.json')):
    d=json.loads(p.read_text()); oid=d.get('owner_id')
    if oid: index[oid]=str(p.relative_to(ROOT))
index['runtime']='state/runtime.json'
# Gold forces remember their lawful establishment ceiling for autonomous replacement.
for _force_path in sorted((ROOT/'state/forces').glob('*.json')):
    _force=json.loads(_force_path.read_text())
    _force['authorized_strength']=_force['headcount']
    _force_path.write_text(json.dumps(_force,indent=2,sort_keys=True)+'\n')

index['treasury_house_tang']='state/treasury/treasury-house-tang.json'
dump('state/index/owner-index-gold.json',{'schema':'sword-owner-index','owner_id':'owner_index_gold','owners':dict(sorted(index.items()))})

# Archive superseded mutable/execution authorities after deriving the new owners.
for rel in ['state/process-state','state/unit','state/force-pool','state/force','state/polity','state/pop','state/market','state/geo','state/inst','state/res','state/event/living-world-events.json']:
    move_to_archive(rel)
# Retire direct-edit runtime routers/templates. These remain reference-only evidence.
move_to_archive('game/data/runtime')

# Clean retired runtime field names in active mutable state where they are easy and material.
for p in STATE.rglob('*.json'):
    try: d=json.loads(p.read_text())
    except Exception: continue
    changed=False
    def clean(x):
        nonlocal_changed=[False]
        if isinstance(x,dict):
            for k in list(x):
                if k in {'monthly_process','settlement_process_id'}:
                    x.pop(k); nonlocal_changed[0]=True
                else:
                    if clean(x[k]): nonlocal_changed[0]=True
        elif isinstance(x,list):
            for v in x:
                if clean(v): nonlocal_changed[0]=True
        return nonlocal_changed[0]
    changed=clean(d)
    if changed: p.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True)+"\n")

# Current causal-world rule, no release-history language.
(GAME/'rules'/'process.md').write_text('''# Causal world settlement\n\nThe world is represented by bounded causal hosts. A host sleeps until its next scheduled boundary, a material outward consequence reaches it, or a player action directly touches it.\n\nLong time advances settle only hosts that are due. Recurring quiet intervals may be compacted arithmetically. Ordinary production paths never scan every person, faction, House, force, or formation to prove that nothing happened.\n\nAutonomous actors use the same semantic commands and conservation rules as player actions. Routine choices are deterministic; strategic choices are scored from current goals, knowledge, resources, authority, threats, doctrine, and commitments. Hidden actions remain hidden until information is lawfully delivered.\n''',encoding='utf-8')

print(f'Gold migration complete: hosts={len(hosts)} owners={len(index)} locations={len(locations)} routes={len(routes)} houses={len(nobles)} institutions={len(list((STATE/"institutions").glob("*.json")))}')
