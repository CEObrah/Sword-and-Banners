#!/usr/bin/env python3
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATTR_ORDER = ["Strength","Agility","Endurance","Toughness","Coordination","Awareness","Composure","Intelligence","Presence"]
SKILL_ORDER = ["Sword","Spear","Glaive","Axe","Mace","Staff","Dagger","Bow","Crossbow","Shield","Defense","Athletics","Mass Combat","Grappling","Unarmed","Riding","Formation Fighting","Survival","Stealth","Scouting","Navigation","Medicine","Engineering","Leadership","Formation Command","Tactics","Strategy","Logistics","Intelligence Operations","Training","Diplomacy","Law","Trade","Intrigue","Governance"]

def load_member(i):
    p = ROOT / f"state/person/wei/{i:03d}.json"
    return json.loads(p.read_text(encoding="utf-8"))

def moments(rows, key, order):
    means=[]
    spreads=[]
    for axis in order:
        vals=[r["stats"][key][axis] for r in rows]
        mu=sum(vals)/len(vals)
        sigma=math.sqrt(sum((v-mu)**2 for v in vals)/len(vals))
        means.append(round(mu,4))
        spreads.append(round(sigma,4))
    return means,spreads

for label,indexes in (("first",range(1,51)),("second",range(51,101)),("all",range(1,101))):
    rows=[load_member(i) for i in indexes]
    health={}
    for r in rows:
        status=r.get("health",{}).get("status","unknown")
        health[status]=health.get(status,0)+1
    am,asig=moments(rows,"attributes",ATTR_ORDER)
    sm,ssig=moments(rows,"skills",SKILL_ORDER)
    print("PERSONAL_TROOP_AGG",json.dumps({
        "label":label,"count":len(rows),
        "attribute_values":am,"attribute_spread":asig,
        "skill_values":sm,"skill_spread":ssig,
        "health":health,
    },separators=(",",":")))
