#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PRESERVED={"staff.chu.karin.chu_yan","staff.chu.karin.lan_qi"}
def load(rel): return json.loads((ROOT/rel).read_text(encoding="utf-8"))
def fail(msg): raise SystemExit(msg)
reg=load("state/cmd/staff-role-slots.json"); roles=reg.get("roles",{})
if reg.get("schema")!="command-staff-role-registry" or len(roles)!=16: fail("command_staff_registry")
for rid,r in roles.items():
    inc=r.get("incumbent",{})
    if not rid.startswith("staff_role.") or inc.get("representation")!="anonymous_command_staff_incumbent": fail("command_staff_role:"+rid)
    if {"name","personality","biography","background","relationships","inventory","body","stats","skills","attributes","appearance"}.intersection(r)|{"name","personality","biography","background","relationships","inventory","body","stats","skills","attributes","appearance"}.intersection(inc): fail("hidden_staff_character:"+rid)
    if r.get("position_count")!=1 or not r.get("command_owner_ref") or not r.get("principal_ref"): fail("command_staff_shape:"+rid)
staff=load("state/index/owners/staff.json").get("owners",{})
if set(staff)!=PRESERVED: fail("preserved_staff:"+repr(sorted(staff)))
cmd=load("state/cmd/command-personnel.json"); staff_people={x for x in cmd.get("record_index",{}) if x.startswith("staff.")}
if staff_people!=PRESERVED or cmd.get("count")!=len(cmd.get("record_index",{})): fail("command_staff_people")
role_refs=[]; person_refs=[]
for army in load("state/cmd/army-registry.json").get("armies",[]):
    for rid in army.get("staff_role_ids",[]):
        role_refs.append(rid)
        if rid not in roles or roles[rid].get("command_owner_ref")!=army.get("id"): fail("army_role:"+rid)
    person_refs.extend(army.get("staff_person_ids",[]))
if set(role_refs)!=set(roles) or len(role_refs)!=len(set(role_refs)): fail("army_role_coverage")
if set(person_refs)!=PRESERVED or len(person_refs)!=2: fail("army_exact_staff_coverage")
coverage=set(load("data/runtime/coverage-requirements.json").get("required_owner_ids",[]))
if "command_staff_role_slots" not in coverage or not PRESERVED.issubset(coverage) or ({x for x in coverage if x.startswith("staff.")}-PRESERVED): fail("staff_required_coverage")
if "command_staff_role_slots" not in set(load("state/time/coverage/process_external_state_ecosystem.json").get("owner_ids",[])): fail("staff_role_liveness")
if not PRESERVED.issubset(set(load("state/time/coverage/process_named_character_life_monthly.json").get("owner_ids",[]))): fail("notable_staff_liveness")
if any(p.get("id")=="process_named_staff_quarterly" for p in load("state/time/frontier.json").get("processes",[])): fail("legacy_staff_process")
for rel in ("state/time/coverage/process_named_staff_quarterly.json","state/reg/process-contracts/process_named_staff_quarterly.json","state/process-state/process-named-staff-quarterly.json"):
    if (ROOT/rel).exists(): fail("legacy_staff_file:"+rel)
print("COMMAND STAFF ROLE TEST OK")
print("routine_roles=16 preserved_named_staff=2 separate_staff_process=0")
