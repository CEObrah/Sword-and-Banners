#!/usr/bin/env python3
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATTR_ORDER = ["Strength","Agility","Endurance","Toughness","Coordination","Awareness","Composure","Intelligence","Presence"]
SKILL_ORDER = ["Sword","Spear","Glaive","Axe","Mace","Staff","Dagger","Bow","Crossbow","Shield","Defense","Athletics","Mass Combat","Grappling","Unarmed","Riding","Formation Fighting","Survival","Stealth","Scouting","Navigation","Medicine","Engineering","Leadership","Formation Command","Tactics","Strategy","Logistics","Intelligence Operations","Training","Diplomacy","Law","Trade","Intrigue","Governance"]
APT_ORDER = ["physical_learning","technical_learning","tactical_learning","academic_learning","social_learning"]

def load_member(i):
    p = ROOT / f"state/person/wei/{i:03d}.json"
    return json.loads(p.read_text(encoding="utf-8"))

def moments_values(vals):
    mu=sum(vals)/len(vals)
    sigma=math.sqrt(sum((v-mu)**2 for v in vals)/len(vals))
    return round(mu,4),round(sigma,4)

def moments(rows, key, order):
    means=[]; spreads=[]
    for axis in order:
        vals=[r["stats"][key][axis] for r in rows]
        mu,sigma=moments_values(vals)
        means.append(mu); spreads.append(sigma)
    return means,spreads

def age_on_245_12_04(birth):
    year=int(birth.split("-BCE-")[0])
    md=birth.split("-BCE-")[1]
    month,day=map(int,md.split("-"))
    age=year-245
    if (month,day)>(12,4): age-=1
    return age

errors=[]
all_rows=[load_member(i) for i in range(1,101)]
for i,r in enumerate(all_rows,1):
    if r.get("id") != f"tw.m{i:03d}": errors.append(f"id:{i}")
    if r.get("resolution") != "individual_lite": errors.append(f"resolution:{i}")
    if r.get("rank") != "tang_champion" or r.get("role") != "tang_champion": errors.append(f"role:{i}")
    if r.get("health",{}).get("status") != "healthy" or r.get("health",{}).get("fatigue",0) != 0: errors.append(f"health:{i}")
    hist=r.get("history",{})
    if hist.get("service") or hist.get("promotion"): errors.append(f"history:{i}")
    if r.get("relationships"): errors.append(f"relationships:{i}")
    if r.get("unit") not in (None,""): errors.append(f"unit_override:{i}")
if errors:
    print("PERSONAL_TROOP_COMPRESSION_BLOCKED", errors[:50]); sys.exit(1)
print("PERSONAL_TROOP_COMPRESSION_SAFE ordinary=100 exceptions=0")

for label,indexes in (("first",range(1,51)),("second",range(51,101)),("all",range(1,101))):
    rows=[all_rows[i-1] for i in indexes]
    health={}
    for r in rows:
        status=r.get("health",{}).get("status","unknown"); health[status]=health.get(status,0)+1
    am,asig=moments(rows,"attributes",ATTR_ORDER); sm,ssig=moments(rows,"skills",SKILL_ORDER)
    apt_means=[]; apt_spreads=[]
    for axis in APT_ORDER:
        mu,sigma=moments_values([r["aptitude"][axis] for r in rows]); apt_means.append(mu); apt_spreads.append(sigma)
    ages=[age_on_245_12_04(r["birth_date"]) for r in rows]
    age_counts={str(a):ages.count(a) for a in sorted(set(ages))}
    hm,hs=moments_values([r["body"]["adult_height_cm"] for r in rows])
    wm,ws=moments_values([r["body"]["current_weight_kg"] for r in rows])
    print("PERSONAL_TROOP_AGG",json.dumps({"label":label,"count":len(rows),"attribute_values":am,"attribute_spread":asig,"skill_values":sm,"skill_spread":ssig,"aptitude_order":APT_ORDER,"aptitude_values":apt_means,"aptitude_spread":apt_spreads,"age_distribution":age_counts,"adult_height_cm_mean":hm,"adult_height_cm_spread":hs,"current_weight_kg_mean":wm,"current_weight_kg_spread":ws,"health":health},separators=(",",":")))
