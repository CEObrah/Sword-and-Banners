#!/usr/bin/env python3
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
errors=[]
def load(rel): return json.loads((ROOT/rel).read_text(encoding="utf-8"))
def err(x): errors.append(x)
policy=load("state/person-reg/personnel-policy.json")
facts=policy["records"][0]["facts"]
for k in ("Mass recruitment representation","Recruitment source conservation","Tang Wei personal-force recruitment","Narrative materialization boundary"):
    if not facts.get(k): err(f"missing_policy:{k}")
pf=load("state/pforce/wei.json")
if pf.get("policy",{}).get("ordinary_personnel_representation")!="aggregate_units_default": err("wei_not_aggregate_default")
if set(pf.get("members",[]))!={"char_duan_jin","char_shen_rui"}: err("wei_members_not_exact_only")
if any((ROOT/"state/person/wei").glob("*.json")): err("ordinary_wei_person_file_present")
for rel in sorted((ROOT/"state/unit").glob("*.json")):
    u=json.loads(rel.read_text(encoding="utf-8")); per=u.get("personnel",{})
    if per.get("representation")!="aggregate": err(f"nonaggregate_unit:{u.get('id')}")
    if per.get("member_ids"): err(f"unit_member_list:{u.get('id')}")
    claims=per.get("source_claims",[])
    if sum(x.get("count",0) for x in claims)!=per.get("count"): err(f"source_claim_conservation:{u.get('id')}")
    cap=u.get("capability",{}); pop=u.get("population_profile",{})
    if cap.get("sample_count")!=per.get("count"): err(f"capability_count:{u.get('id')}")
    if sum(pop.get("age_distribution",{}).values())!=per.get("count"): err(f"age_distribution:{u.get('id')}")
    if sum(pop.get("body_distribution",{}).get("frame_distribution",{}).values())!=per.get("count"): err(f"frame_distribution:{u.get('id')}")
    if sum(pop.get("experience_distribution",{}).values())!=per.get("count"): err(f"experience_distribution:{u.get('id')}")
    if sum(pop.get("qualification_distribution",{}).values())!=per.get("count"): err(f"qualification_distribution:{u.get('id')}")
if errors:
    print("RECRUITMENT REPRESENTATION TEST FAILED")
    for e in errors: print("-",e)
    sys.exit(1)
print("RECRUITMENT REPRESENTATION TEST OK")
print("ordinary recruitment aggregate-only; source claims conserved; unit development inputs remain aggregate and live")
