#!/usr/bin/env python3
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
errors=[]
def load(rel):
    p=ROOT/rel
    if not p.exists(): errors.append(f"missing:{rel}"); return {}
    return json.loads(p.read_text(encoding="utf-8"))
def err(x): errors.append(x)
for label,rel,uid,cmd in (("first","state/unit/tang-champions-first.json","unit_tang_wei_tang_champions_first","char_duan_jin"),("second","state/unit/tang-champions-second.json","unit_tang_wei_tang_champions_second","char_shen_rui")):
    u=load(rel); per=u.get("personnel",{}); pop=u.get("population_profile",{}); cap=u.get("capability",{})
    if u.get("id")!=uid or u.get("owner")!="char_tang_wei" or u.get("commander_id")!=cmd: err(f"{label}_identity_command")
    if u.get("troop_type")!="heavy_cavalry" or u.get("loadout_standard")!="loadout_house_guardian_cavalry": err(f"{label}_standard")
    if u.get("doctrine")!="doc.tang_wei.household_champions" or u.get("training")!="train.tang_wei.household_champions": err(f"{label}_program")
    if per.get("representation")!="aggregate" or per.get("count")!=50 or per.get("member_ids"): err(f"{label}_personnel")
    if per.get("condition",{}).get("healthy")!=50: err(f"{label}_condition")
    if sum(x.get("count",0) for x in per.get("source_claims",[]))!=50: err(f"{label}_source")
    if cap.get("sample_count")!=50 or len(cap.get("skills",{}).get("mean",[]))!=35: err(f"{label}_capability")
    if sum(pop.get("age_distribution",{}).values())!=50 or sum(pop.get("experience_distribution",{}).values())!=50: err(f"{label}_population")
    if u.get("issue_state",{}).get("mount_issue_state",{}).get("standard_mounts_present")!=50: err(f"{label}_mounts")
pf=load("state/pforce/wei.json")
if pf.get("permanent_units")!=["unit_tang_wei_tang_champions_first","unit_tang_wei_tang_champions_second"]: err("personal_force_units")
if set(pf.get("members",[]))!={"char_duan_jin","char_shen_rui"}: err("personal_force_named_members")
if any((ROOT/"state/person/wei").glob("*.json")): err("legacy_person_sheets")
if errors:
    print("TANG CHAMPIONS TEST FAILED")
    for e in errors: print("-",e)
    sys.exit(1)
print("TANG CHAMPIONS TEST OK")
print("two peer aggregate 50-rider Champion companies; exact commanders separate; no ordinary Champion person files")
