#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAT = json.load(open(ROOT / "data/mechanics/stat-orders.json"))["profiles"]["military_person"]
ATTRS = STAT["attribute_order"]
SKILLS = STAT["skill_order"]
APT = ["physical_learning", "technical_learning", "tactical_learning", "academic_learning", "social_learning"]
files = sorted((ROOT / "state/person/wei").glob("*.json"))
if len(files) != 100:
    raise SystemExit(f"expected 100 Wei ordinary person-lite files, found {len(files)}")

DEFAULTS = {
    "origin": "Warring States China",
    "birth_date_source": "simulation_assigned_stable_seed",
    "appearance_source": "simulation_assigned",
    "body_growth_profile_id": "human_height_to_18",
    "body_growth_end_age": 18,
    "body_source": "simulation_assigned",
    "aptitude_source": "household_champion_selection",
    "role_profile_ref": "role.tang_champion",
    "personality_resolution": "compact",
    "personality_preferences": ["clean readiness", "well-kept horse and equipment", "clear orders"],
    "personality_dislikes": ["betrayal", "careless risk to the assigned Tang principal"]
}

members = {}
first_ids = []
second_ids = []
for path in files:
    d = json.load(open(path))
    if d.get("schema") != "person-lite" or d.get("owner") != "char_tang_wei" or d.get("role") != "tang_champion":
        raise SystemExit(f"unexpected ordinary-person record {path}")
    if d.get("health") != {"status":"healthy","fatigue":0}:
        raise SystemExit(f"individual condition requires exception preservation: {d['id']}")
    hist = d.get("history", {})
    if any(hist.get(k) for k in ("service", "promotion")):
        raise SystemExit(f"individual history requires exception preservation: {d['id']}")
    body = d["body"]
    personality = d.get("personality") or {}
    checks = {
        "origin": d.get("origin"),
        "birth_date_source": d.get("birth_date_source"),
        "appearance_source": d.get("appearance_source"),
        "body_growth_profile_id": body.get("growth_profile_id"),
        "body_growth_end_age": body.get("growth_end_age"),
        "body_source": body.get("source"),
        "aptitude_source": d["aptitude"].get("source"),
        "role_profile_ref": d.get("role_profile_ref"),
        "personality_resolution": personality.get("resolution"),
        "personality_preferences": personality.get("preferences"),
        "personality_dislikes": personality.get("dislikes")
    }
    for key, value in checks.items():
        if value != DEFAULTS[key]:
            raise SystemExit(f"nondefault preserved identity field {d['id']} {key}={value!r}")
    if body.get("height_anchors") != []:
        raise SystemExit(f"nonempty height anchors require explicit preservation: {d['id']}")
    rid = d["id"]
    members[rid] = {
        "name": d["name"],
        "family_id": d.get("family_id"),
        "birth_date": d["birth_date"],
        "appearance": d.get("appearance"),
        "body": [body["adult_height_cm"], body["current_weight_kg"], body["frame"]],
        "attributes": [d["stats"]["attributes"][k] for k in ATTRS],
        "skills": [d["stats"]["skills"][k] for k in SKILLS],
        "aptitude": [d["aptitude"][k] for k in APT],
        "traits": personality.get("traits", [])
    }
    n = int(rid.split("m",1)[1])
    (first_ids if n <= 50 else second_ids).append(rid)

roster = {
    "schema": "personal-force-roster.v1",
    "id": "roster.tang_wei",
    "owner": "char_tang_wei",
    "stat_order_ref": "data/mechanics/stat-orders.json#military_person",
    "aptitude_order": APT,
    "next_sequence": 101,
    "preserved_baseline_defaults": DEFAULTS,
    "batches": {
        "tang_champions_first_founders": {
            "member_ids": first_ids,
            "source_ref": "state/org/unit-transactions.json#txn_tang_wei_tang_champions_form",
            "joined_at": "245-BCE-12-02T09:50:00+08:00"
        },
        "tang_champions_second_founders": {
            "member_ids": second_ids,
            "source_ref": "state/org/unit-transactions.json#txn_tang_wei_tang_champions_form",
            "joined_at": "245-BCE-12-02T09:50:00+08:00"
        }
    },
    "preserved_members": members,
    "exceptions": {}
}
print("PERSONAL_ROSTER_MIGRATION=" + json.dumps(roster, separators=(",",":"), sort_keys=False))

refs = []
for path in ROOT.rglob("*.json"):
    if "state/person/wei" in path.as_posix():
        continue
    text = path.read_text(encoding="utf-8")
    if "tw.m0" in text or "tw.m100" in text:
        refs.append(path.relative_to(ROOT).as_posix())
print("PERSONAL_ROSTER_REFERENCE_FILES=" + json.dumps(sorted(refs), separators=(",",":")))
