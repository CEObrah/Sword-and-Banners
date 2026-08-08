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
    rid = d["id"]
    entry = {
        "identity_state": "preserved_named_baseline",
        "name": d["name"],
        "family_id": d.get("family_id"),
        "origin": d.get("origin"),
        "birth_date": d["birth_date"],
        "birth_date_source": d.get("birth_date_source"),
        "appearance": d.get("appearance"),
        "appearance_source": d.get("appearance_source"),
        "body_baseline": d["body"],
        "attribute_values": [d["stats"]["attributes"][k] for k in ATTRS],
        "skill_values": [d["stats"]["skills"][k] for k in SKILLS],
        "aptitude_values": [d["aptitude"][k] for k in APT],
        "aptitude_source": d["aptitude"].get("source"),
        "personality": d.get("personality"),
        "role_profile_ref": d.get("role_profile_ref")
    }
    members[rid] = entry
    n = int(rid.split("m",1)[1])
    (first_ids if n <= 50 else second_ids).append(rid)

roster = {
    "schema": "personal-force-roster.v1",
    "id": "roster.tang_wei",
    "owner": "char_tang_wei",
    "stat_order_ref": "data/mechanics/stat-orders.json#military_person",
    "aptitude_order": APT,
    "next_sequence": 101,
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
    "members": members,
    "exceptions": {}
}
print("PERSONAL_ROSTER_MIGRATION=" + json.dumps(roster, separators=(",",":"), sort_keys=False))
