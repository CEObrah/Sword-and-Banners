#!/usr/bin/env python3
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATTR_ORDER = ["Strength","Agility","Endurance","Toughness","Coordination","Awareness","Composure","Intelligence","Presence"]
SKILL_ORDER = ["Sword","Spear","Glaive","Axe","Mace","Staff","Dagger","Bow","Crossbow","Shield","Defense","Athletics","Mass Combat","Grappling","Unarmed","Riding","Formation Fighting","Survival","Stealth","Scouting","Navigation","Medicine","Engineering","Leadership","Formation Command","Tactics","Strategy","Logistics","Intelligence Operations","Training","Diplomacy","Law","Trade","Intrigue","Governance"]

def load_member(i):
    p = ROOT / f"state/person/wei/{i:03d}.json"
    return json.loads(p.read_text(encoding="utf-8"))

def moments(rows, key, order):
    means=[]; spreads=[]
    for axis in order:
        vals=[r["stats"][key][axis] for r in rows]
        mu=sum(vals)/len(vals)
        sigma=math.sqrt(sum((v-mu)**2 for v in vals)/len(vals))
        means.append(round(mu,4)); spreads.append(round(sigma,4))
    return means,spreads

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
    print("PERSONAL_TROOP_COMPRESSION_BLOCKED", errors[:50])
    sys.exit(1)
print("PERSONAL_TROOP_COMPRESSION_SAFE ordinary=100 exceptions=0")

for label,indexes in (("first",range(1,51)),("second",range(51,101)),("all",range(1,101))):
    rows=[all_rows[i-1] for i in indexes]
    health={}
    for r in rows:
        status=r.get("health",{}).get("status","unknown")
        health[status]=health.get(status,0)+1
    am,asig=moments(rows,"attributes",ATTR_ORDER)
    sm,ssig=moments(rows,"skills",SKILL_ORDER)
    print("PERSONAL_TROOP_AGG",json.dumps({"label":label,"count":len(rows),"attribute_values":am,"attribute_spread":asig,"skill_values":sm,"skill_spread":ssig,"health":health},separators=(",",":")))
