#!/usr/bin/env python3
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; NOW="245-BCE-12-04T07:22:48+08:00"; CORE=["Leadership","Formation Command","Tactics","Strategy","Logistics","Mass Combat"]
def load(p): return json.loads((ROOT/p).read_text(encoding="utf-8"))
def save(p,o): q=ROOT/p; q.parent.mkdir(parents=True,exist_ok=True); q.write_text(json.dumps(o,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
def slug(s): return re.sub(r"[^a-z0-9]+","_",s.lower()).strip("_")
def band(v): return "basic" if v<80 else "competent" if v<100 else "experienced" if v<120 else "expert" if v<140 else "master"
def age(b):
 m=re.fullmatch(r"(\d+)-BCE-(\d{2})-(\d{2})",b or "");
 if not m: raise SystemExit("bad birth date:"+str(b))
 y,mo,d=map(int,m.groups()); a=y-245-((12,4)<(mo,d));
 if a<16: raise SystemExit("bad age:"+b)
 return a
def special(text):
 pairs=[("engineer",["Engineering"]),("intelligence",["Intelligence Operations","Intrigue"]),("scout",["Scouting","Navigation"]),("recon",["Scouting","Navigation"]),("supply",["Trade"]),("quartermaster",["Trade"]),("signal",["Training"]),("training",["Training"]),("medical",["Medicine"]),("liaison",["Diplomacy"]),("administr",["Governance","Law"])]
 out=[]; text=text.lower()
 for n,ss in pairs:
  if n in text:
   for s in ss:
    if s not in out: out.append(s)
 return out

def classify(paths):
 ids=set(paths); ppl={i:load(paths[i]) for i in ids}; why={i:[] for i in ids}
 for i,p in ppl.items():
  for r in p.get("relationships",[]):
   t=r.get("target_id")
   if t in ids: why[i].append("staff_peer_relationship"); why[t].append("referenced_by_staff_peer")
 for i,p in ppl.items():
  h=p.get("history",{}); s=h.get("service",[]); generic=len(s)==1 and "permanent named post" in s[0].lower() and "anonymous staff representation" in s[0].lower() and h.get("promotion",[])==[]
  if not generic: why[i].append("individual_service_history")
  he=p.get("health",{})
  if he.get("status")!="healthy" or he.get("fatigue")!=0: why[i].append("material_health_state")
  if p.get("narration_priority")!="role_until_relevant": why[i].append("individual_narration_priority")
  if p.get("mount") is not None: why[i].append("individual_mount")
  for k in ("inventory","injuries","wounds","knowledge","reputation","contracts","property","spouse","children"):
   if k in p: why[i].append(k)
  if len(p.get("relationships",[]))!=2 and not any(r.get("target_id") in ids for r in p.get("relationships",[])): why[i].append("non_generic_relationship_count")
 keep={i for i,v in why.items() if v}; return ppl,keep,ids-keep,why

meta=load("state/meta.json")
if meta.get("revision")!=21 or meta.get("time")!=NOW: raise SystemExit("unexpected maintenance base")
staffidx=load("state/index/owners/staff.json"); paths=dict(staffidx.get("owners",{}))
if len(paths)!=18: raise SystemExit(f"expected 18 staff, found {len(paths)}")
ppl,keep,compress,why=classify(paths)
if len(keep)!=2 or len(compress)!=16: raise SystemExit(f"unsafe partition keep={sorted(keep)} compress={sorted(compress)}")
print("staff_total=18 preserve_exact=2 compressible=16")
for i in sorted(paths): print("PRESERVE" if i in keep else "COMPRESS",i,sorted(set(why[i])) if why[i] else "generic_role_filler")
cmdidx=load("state/cmd/command-personnel.json"); cmdpaths=cmdidx["record_index"]
allowed={"state/index/owners/staff.json","state/cmd/command-personnel.json","state/cmd/army-registry.json","data/runtime/coverage-requirements.json","state/time/coverage/process_named_staff_quarterly.json"}; allowed.update(paths[i] for i in compress); allowed.update(cmdpaths[i] for i in compress)
for base in ("state","data","rules"):
 for p in (ROOT/base).rglob("*"):
  if not p.is_file() or p.suffix not in {".json",".md"}: continue
  rel=p.relative_to(ROOT).as_posix(); txt=p.read_text(encoding="utf-8"); hits=[i for i in compress if i in txt]
  if hits and rel not in allowed: raise SystemExit(f"compressible staff externally referenced:{rel}:{hits}")
roles={}; rolefor={}
for i in sorted(compress):
 p=ppl[i]; he=p.get("health",{})
 if p.get("schema")!="person-lite" or p.get("resolution")!="individual_lite" or p.get("rank")!="named_staff_officer" or he.get("status")!="healthy" or he.get("fatigue")!=0: raise SystemExit("unsafe person:"+i)
 c=load(cmdpaths[i]); x=c.get("command",{})
 if c.get("person_id")!=i or x.get("representation")!="individual_lite_named_person" or x.get("current_unit_ids",[])!=[] or x.get("current_army_id")!=p.get("owner") or x.get("role")!=p.get("role"): raise SystemExit("unsafe command:"+i)
 targets={r.get("target_id") for r in p.get("relationships",[])}; principals=[t for t in targets if isinstance(t,str) and t.startswith("char_")]
 if len(principals)!=1 or p.get("owner") not in targets: raise SystemExit("unsafe relationships:"+i)
 skills=p.get("stats",{}).get("skills",{}); sel=CORE+[s for s in special((p.get("role") or "")+" "+(x.get("specialty_hint") or "")) if s not in CORE]
 if any(s not in skills for s in sel): raise SystemExit("missing functional skill:"+i)
 rid=f"staff_role.{slug(x['current_army_id'].replace('army.',''))}.{slug(p['role'])}"
 if rid in roles: rid+=f".{slug(x.get('specialty_hint') or 'staff')}"
 if rid in roles: raise SystemExit("duplicate role:"+rid)
 roles[rid]={"command_owner_ref":x["current_army_id"],"principal_ref":principals[0],"role":p["role"],"specialty_hint":x.get("specialty_hint") or "general_staff","status":"occupied","position_count":1,"incumbent":{"representation":"anonymous_command_staff_incumbent","age_years":age(p.get("birth_date")),"capability_bands":{slug(s):band(skills[s]) for s in sel},"health_availability":"fit","service_development_credit":0.0,"retirement_status":"active","materialized_character_id":None,"settled_through":NOW}}; rolefor[i]=rid
save("state/cmd/staff-role-slots.json",{"schema":"command-staff-role-registry","owner_id":"command_staff_role_slots","owner_type":"command_staff_role_registry","policy":{"role_slot_is_not_character":True,"materialize_only_when_personal_identity_is_causal":True,"materialization_preserves_same_incumbent":True,"command_effect_requires_current_evidence":True,"vacancy_and_unavailability_are_mechanical":True},"roles":roles,"runtime":{"last_settled_at":NOW}})
army=load("state/cmd/army-registry.json"); seen=set()
for a in army.get("armies",[]):
 old=a.get("staff_person_ids",[]); seen.update(old); a["staff_person_ids"]=[i for i in old if i in keep]; a["staff_role_ids"]=[rolefor[i] for i in old if i in compress]; a["named_officer_accounting"]="Commander and materialized named officers/staff are separate people. Routine headquarters functions use staff_role_ids; neither representation creates anonymous unit manpower."
if seen!=set(paths): raise SystemExit("army staff coverage mismatch")
save("state/cmd/army-registry.json",army)
# register structure
reg=load("schemas/registry.json"); reg["command-staff-role-registry"]="command-staff-role-registry.schema.json"; save("schemas/registry.json",reg)
ti=load("data/runtime/template-index-shards/c.json"); ti.setdefault("templates",{})["command-staff-role-registry"]={"path":"data/runtime/templates/command-staff-role-registry.template.json","source_schema":"schemas/command-staff-role-registry.schema.json","scope":"mutable_state"}; save("data/runtime/template-index-shards/c.json",ti)
cc=load("data/runtime/system-contracts/command.json")
if "command-staff-role-registry" not in cc["owner_templates"]: cc["owner_templates"].append("command-staff-role-registry")
cc["read_first"]=["commander person","command-person record when exact named command status matters","command-staff role registry only when routine headquarters function/availability matters","one command group and only requested descendants","command mechanics"]
cc["write_order"]=["validate legal authority","update exact command-person assignment/status only when a materialized person's institutional fact changed","update routine command-staff role availability/development/succession without inventing hidden people","recompute direct personnel and direct command slots","write command-group hierarchy","update derived indexes","validate succession/delegation"]
cc["invariants"]=[v for v in cc["invariants"] if v!="Commander is a real person, never a one-person troop unit."]
for v in ("Commanders and materialized notable staff are real people, never one-person troop units.","Routine headquarters staff functions may remain anonymous role slots until individual agency becomes causal.","Command-staff role slots affect staff-and-signals only through current role capability, availability, communications and saved evidence; role count alone grants no bonus.","Materializing a staff incumbent preserves the same occupied role body and settled service history exactly once."):
 if v not in cc["invariants"]: cc["invariants"].append(v)
save("data/runtime/system-contracts/command.json",cc)
fc=load("data/runtime/system-contracts/forces_institutions.json"); fc["invariants"]=[v for v in fc["invariants"] if v!="Military commanders and command staff remain exact people under command authority rather than role-slot bonuses."]; mixed="Military commanders and notable/materialized staff remain people; routine headquarters staff functions may use command-staff role slots until individual agency becomes causal.";
if mixed not in fc["invariants"]: fc["invariants"].append(mixed)
save("data/runtime/system-contracts/forces_institutions.json",fc)
mech=load("data/mechanics/command.json"); mech["capacity_modifiers"]["staff_and_signals"]="Qualified exact/materialized staff or occupied command-staff role slots, messengers/signals/communications, command posts, maps and relay quality. Role slots contribute only from current capability and availability evidence; vacancy or incapacity can reduce support."; mech["effective_capacity"]["selection_rule"]="Choose each factor only from current saved evidence. For staff_and_signals, use exact/materialized staff and/or occupied command-staff role capability/availability together with actual communications resources and conditions; do not count slots as an automatic bonus. If evidence does not support a better category, use normal/adequate/familiar. Do not grant a bonus because a commander is important or named."; save("data/mechanics/command.json",mech)
rtp=ROOT/"RUNTIME.md"; rt=rtp.read_text(encoding="utf-8"); rt=rt.replace("Commanders and staff are people, never one-person units.","Commanders and notable/materialized staff are people, never one-person units. Routine headquarters staff functions may remain anonymous command-staff role slots until individual agency becomes causal."); rtp.write_text(rt,encoding="utf-8")
orgp=ROOT/"rules/org.md"; org=orgp.read_text(encoding="utf-8"); anchor="The commander of a command group remains a real combat-capable person."; add="Routine headquarters staff offices may be anonymous command-staff role slots when only institutional function, capability, availability and succession matter. The commander and any staff member whose personal agency/history becomes causal are materialized people. A role slot is never a hidden character, never a one-person unit, and never an automatic command bonus.\n\n";
if "Routine headquarters staff offices may be anonymous command-staff role slots" not in org:
 if anchor not in org: raise SystemExit("org command anchor missing")
 org=org.replace(anchor,add+anchor)
orgp.write_text(org,encoding="utf-8")
rm=load("data/runtime/repository-map.json"); rm["route_index"]["command_staff_role"]="military"; save("data/runtime/repository-map.json",rm)
mr=load("data/runtime/repository-routes/military.json"); mr["routes"]["command_staff_role"]={"r":["state/cmd/staff-role-slots.json","data/mechanics/command.json","rules/org.md"],"note":"Load only relevant role slots. Routine staff functions are not hidden people; notable/materialized staff remain named person owners."}; save("data/runtime/repository-routes/military.json",mr)
# delete only generic person owners/wrappers
for i in sorted(compress): (ROOT/paths[i]).unlink(); (ROOT/cmdpaths[i]).unlink(); del cmdpaths[i]
cmdidx["count"]=len(cmdpaths); cmdidx["rule"]="Command personnel index contains exact named commanders and materialized/notable command staff only. Routine headquarters staff roles live in state/cmd/staff-role-slots.json."; save("state/cmd/command-personnel.json",cmdidx)
staffidx["owners"]={i:paths[i] for i in sorted(keep)}; save("state/index/owners/staff.json",staffidx)
co=load("state/index/owners/command.json"); co["owners"]["command_staff_role_slots"]="state/cmd/staff-role-slots.json"; save("state/index/owners/command.json",co)
oi=load("state/index/owners.json"); oi["owner_count"]=sum(len(load(p).get("owners",{})) for p in oi["prefix_index"].values()); save("state/index/owners.json",oi)
# temporal liveness
cr=load("data/runtime/coverage-requirements.json"); cr["required_owner_ids"]=[x for x in cr["required_owner_ids"] if x not in compress]
for x in ["command_staff_role_slots",*sorted(keep)]:
 if x not in cr["required_owner_ids"]: cr["required_owner_ids"].append(x)
save("data/runtime/coverage-requirements.json",cr)
ec=load("state/time/coverage/process_external_state_ecosystem.json");
if "command_staff_role_slots" not in ec["owner_ids"]: ec["owner_ids"].append("command_staff_role_slots")
save("state/time/coverage/process_external_state_ecosystem.json",ec)
econ=load("state/reg/process-contracts/process_external_state_ecosystem.json")
for g in ("settle routine command-staff role aging, service-development credit, health availability, vacancy, retirement and succession from actual state/army conditions","wake/materialize an exact staff person only when personal agency, injury, capture, relationship, appointment or direct interaction becomes causal"):
 if g not in econ["goals"]: econ["goals"].append(g)
c="Command-staff role slots gain no free promotion or capability; development and succession require actual duties, resources, availability and lawful personnel sources."
if c not in econ["constraints"]: econ["constraints"].append(c)
save("state/reg/process-contracts/process_external_state_ecosystem.json",econ)
nc=load("state/time/coverage/process_named_character_life_monthly.json")
for i in sorted(keep):
 if i not in nc["owner_ids"]: nc["owner_ids"].append(i)
save("state/time/coverage/process_named_character_life_monthly.json",nc)
ncon=load("state/reg/process-contracts/process_named_character_life_monthly.json"); ncon["goals"]=["advance slow life-course, health, recovery and maintenance state for materialized named people (full or lite)","wake exact/lite person owners when injury, death, retirement, status or other material life thresholds occur"]; ncon["reconstruction_policy"]="Use each materialized named person owner plus only causal health, career, family, relationship and command authorities. Unknown outcomes remain unknown."; ncon["standing_orders"]=["preserve materialized named-person state deterministically","defer active goal execution to exact processes or the autonomous heartbeat"]; save("state/reg/process-contracts/process_named_character_life_monthly.json",ncon)
fr=load("state/time/frontier.json"); fr["processes"]=[p for p in fr["processes"] if p.get("id")!="process_named_staff_quarterly"]; save("state/time/frontier.json",fr)
pr=load("state/reg/registry-processes.json"); pr["processes"].pop("process_named_staff_quarterly",None); save("state/reg/registry-processes.json",pr)
pcr=load("state/reg/registry-process-contracts.json"); pcr["record_count"]-=1; save("state/reg/registry-process-contracts.json",pcr)
psi=load("state/process-state/index.json"); psi["entries"]=[e for e in psi["entries"] if e.get("process_id")!="process_named_staff_quarterly"]; save("state/process-state/index.json",psi)
for p in ("state/time/coverage/process_named_staff_quarterly.json","state/reg/process-contracts/process_named_staff_quarterly.json","state/process-state/process-named-staff-quarterly.json"): (ROOT/p).unlink()
# remove fixed roster-size validator snapshots
p=ROOT/"tools/audit.py"; s=p.read_text(encoding="utf-8"); old="_cmd_people=command_people()\nif len(_cmd_people)<40:err(f'command_personnel_count:{len(_cmd_people)}')"; new="_cmd_index=rj(ROOT/'state/cmd/command-personnel.json') or {}\n_cmd_people=command_people()\nif len(_cmd_people)!=_cmd_index.get('count'):err(f'command_personnel_count:{len(_cmd_people)}:{_cmd_index.get(\"count\")}')";
if old not in s: raise SystemExit("audit fixed-count assertion missing")
p.write_text(s.replace(old,new),encoding="utf-8")
p=ROOT/"tools/test_living_world.py"; s=p.read_text(encoding="utf-8"); old="if len(records)<40 or idx.get('count')!=len(records):fail('command_personnel_count')"; new="if not records or idx.get('count')!=len(records):fail('command_personnel_count')";
if old not in s: raise SystemExit("living-world fixed-count assertion missing")
p.write_text(s.replace(old,new),encoding="utf-8")
runner=ROOT/"tools/run_validators.py"; s=runner.read_text(encoding="utf-8"); needle='    "tools/test_household_military_networks.py",\n';
if '"tools/test_command_staff_roles.py"' not in s:
 if needle not in s: raise SystemExit("validator insertion point missing")
 s=s.replace(needle,needle+'    "tools/test_command_staff_roles.py",\n')
runner.write_text(s,encoding="utf-8")
meta["revision"]=22; save("state/meta.json",meta)
print(f"command staff migration staged preserve={len(keep)} routine_roles={len(roles)} command_people={len(cmdpaths)}")
