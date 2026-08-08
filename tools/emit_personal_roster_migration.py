#!/usr/bin/env python3
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLY = "--apply" in sys.argv
CHAMPION_UNITS = {
    "unit_tang_wei_tang_champions_first": ROOT / "state/unit/tang-champions-first.json",
    "unit_tang_wei_tang_champions_second": ROOT / "state/unit/tang-champions-second.json",
}
ATTR_ORDER = ["Strength","Agility","Endurance","Toughness","Coordination","Awareness","Composure","Intelligence","Presence"]
SKILL_ORDER = ["Sword","Spear","Glaive","Axe","Mace","Staff","Dagger","Bow","Crossbow","Shield","Defense","Athletics","Mass Combat","Grappling","Unarmed","Riding","Formation Fighting","Survival","Stealth","Scouting","Navigation","Medicine","Engineering","Leadership","Formation Command","Tactics","Strategy","Logistics","Intelligence Operations","Training","Diplomacy","Law","Trade","Intrigue","Governance"]
APT_ORDER = ["physical_learning","technical_learning","tactical_learning","academic_learning","social_learning"]
BASELINE_DEFAULTS = {
    "origin":"Warring States China",
    "birth_date_source":"simulation_assigned_stable_seed",
    "appearance_source":"simulation_assigned",
    "body_growth_profile_id":"human_height_to_18",
    "body_growth_end_age":18,
    "body_source":"simulation_assigned",
    "aptitude_source":"household_champion_selection",
    "role_profile_ref":"role.tang_champion",
    "personality_resolution":"compact",
    "personality_preferences":["clean readiness","well-kept horse and equipment","clear orders"],
    "personality_dislikes":["betrayal","careless risk to the assigned Tang principal"]
}

def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))

def write_json(rel, obj):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def append_section(rel, heading, text):
    p = ROOT / rel
    old = p.read_text(encoding="utf-8").rstrip()
    if heading not in old:
        p.write_text(old + "\n\n" + heading + "\n\n" + text.strip() + "\n", encoding="utf-8")

def moments(rows):
    n = len(rows)
    width = len(rows[0])
    mean = [sum(row[i] for row in rows) / n for i in range(width)]
    var = [sum((row[i] - mean[i]) ** 2 for row in rows) / n for i in range(width)]
    return [round(x, 6) for x in mean], [round(x, 6) for x in var]

def guard_preflight():
    person_files = sorted((ROOT / "state/person/wei").glob("*.json"))
    if len(person_files) != 100:
        raise SystemExit(f"expected exactly 100 legacy Wei Champion person files, found {len(person_files)}")
    expected = {f"tw.m{i:03d}" for i in range(1, 101)}
    found = set()
    for p in person_files:
        d = json.loads(p.read_text(encoding="utf-8"))
        found.add(d.get("id"))
        if d.get("schema") != "person-lite" or d.get("owner") != "char_tang_wei" or d.get("role") != "tang_champion":
            raise SystemExit(f"unexpected legacy person record: {p}")
        if d.get("health") != {"status":"healthy","fatigue":0}:
            raise SystemExit(f"individual condition requires separate migration handling: {d.get('id')}")
        hist = d.get("history", {})
        if any(hist.get(k) for k in ("service", "promotion")):
            raise SystemExit(f"individual history requires separate migration handling: {d.get('id')}")
    if found != expected:
        raise SystemExit("legacy Wei Champion ID set is incomplete or unexpected")
    unexpected_units = []
    for p in sorted((ROOT / "state/unit").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        per = d.get("personnel", {})
        if d.get("id") not in CHAMPION_UNITS and (per.get("representation") != "aggregate" or per.get("member_ids")):
            unexpected_units.append(str(p.relative_to(ROOT)))
    if unexpected_units:
        raise SystemExit("non-Champion units require explicit migration review before aggregate-only tightening: " + ", ".join(unexpected_units))
    return person_files

person_files = guard_preflight()
if not APPLY:
    print("PERSONNEL CONSOLIDATION PREFLIGHT OK")
    print("legacy_person_files=100; no non-Champion unit depends on named member arrays")
    raise SystemExit(0)

meta = load("state/meta.json")
baseline_at = meta["time"]
people = {}
first_ids, second_ids = [], []
for p in person_files:
    d = json.loads(p.read_text(encoding="utf-8"))
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
    for k, v in checks.items():
        if v != BASELINE_DEFAULTS[k]:
            raise SystemExit(f"nondefault legacy identity field requires explicit preservation: {d['id']} {k}={v!r}")
    if body.get("height_anchors") != []:
        raise SystemExit(f"nonempty height anchors require explicit preservation: {d['id']}")
    rid = d["id"]
    people[rid] = {
        "name": d["name"],
        "family_id": d.get("family_id"),
        "birth_date": d["birth_date"],
        "appearance": d.get("appearance"),
        "body": [body["adult_height_cm"], body["current_weight_kg"], body["frame"]],
        "attributes": [d["stats"]["attributes"][k] for k in ATTR_ORDER],
        "skills": [d["stats"]["skills"][k] for k in SKILL_ORDER],
        "aptitude": [d["aptitude"][k] for k in APT_ORDER],
        "traits": personality.get("traits", [])
    }
    number = int(rid.split("m", 1)[1])
    (first_ids if number <= 50 else second_ids).append(rid)

# ---- Structural authority first. ----
unit_schema = load("schemas/unit-v1.schema.json")
unit_schema["required"] = [x for x in unit_schema["required"] if x != "capability_ref"]
if "capability" not in unit_schema["required"]:
    unit_schema["required"].append("capability")
pper = unit_schema["properties"]["personnel"]
pper["required"] = ["representation", "count", "source_claims"]
pper["properties"]["representation"] = {"const":"aggregate"}
pper["properties"]["member_ids"] = {"type":"array","maxItems":0}
pper["properties"]["source_claims"] = {
    "type":"array",
    "minItems":1,
    "items":{
        "type":"object",
        "required":["source_ref","count","transaction_ref","claim_kind"],
        "properties":{
            "source_ref":{"type":"string","minLength":1},
            "count":{"type":"integer","minimum":1},
            "transaction_ref":{"type":"string","minLength":1},
            "claim_kind":{"type":"string","minLength":1},
            "service_model":{"type":"string"},
            "generation_schema":{"type":"string"}
        },
        "additionalProperties":False
    }
}
unit_schema["properties"].pop("capability_ref", None)
unit_schema["properties"]["capability"] = {
    "type":"object",
    "required":["representation","as_of","stat_order_ref","sample_count","attributes","skills","aptitudes"],
    "properties":{
        "representation":{"const":"aggregate_moments"},
        "as_of":{"type":"string"},
        "stat_order_ref":{"type":"string"},
        "sample_count":{"type":"integer","minimum":1},
        "attributes":{"type":"object","required":["mean","variance"],"properties":{"mean":{"type":"array","minItems":9,"maxItems":9,"items":{"type":"number"}},"variance":{"type":"array","minItems":9,"maxItems":9,"items":{"type":"number","minimum":0}}},"additionalProperties":False},
        "skills":{"type":"object","required":["mean","variance"],"properties":{"mean":{"type":"array","minItems":35,"maxItems":35,"items":{"type":"number"}},"variance":{"type":"array","minItems":35,"maxItems":35,"items":{"type":"number","minimum":0}}},"additionalProperties":False},
        "aptitudes":{"type":"object","required":["order","mean","variance"],"properties":{"order":{"type":"array","minItems":5,"maxItems":5,"items":{"type":"string"}},"mean":{"type":"array","minItems":5,"maxItems":5,"items":{"type":"number"}},"variance":{"type":"array","minItems":5,"maxItems":5,"items":{"type":"number","minimum":0}}},"additionalProperties":False},
        "tail_source_ref":{"type":["string","null"]}
    },
    "additionalProperties":False
}
write_json("schemas/unit-v1.schema.json", unit_schema)

ut = load("data/runtime/templates/unit.v1.template.json")
root = ut["object_contracts"][""]
for key in ("capability_ref",):
    if key in root["allowed_keys"]: root["allowed_keys"].remove(key)
    if key in root["canonical_order"]: root["canonical_order"].remove(key)
if "capability" not in root["allowed_keys"]: root["allowed_keys"].append("capability")
if "capability" not in root["canonical_order"]:
    insert_at = root["canonical_order"].index("location") if "location" in root["canonical_order"] else len(root["canonical_order"])
    root["canonical_order"].insert(insert_at, "capability")
if "capability" not in ut["required_top_level_keys"]: ut["required_top_level_keys"].append("capability")
ut["object_contracts"]["/personnel/source_claims/*"] = {"mode":"closed","allowed_keys":["source_ref","count","transaction_ref","claim_kind","service_model","generation_schema"],"canonical_order":["source_ref","count","transaction_ref","claim_kind","service_model","generation_schema"]}
ut["object_contracts"]["/capability"] = {"mode":"closed","allowed_keys":["representation","as_of","stat_order_ref","sample_count","attributes","skills","aptitudes","tail_source_ref"],"canonical_order":["representation","as_of","stat_order_ref","sample_count","attributes","skills","aptitudes","tail_source_ref"]}
for section in ("attributes","skills"):
    ut["object_contracts"][f"/capability/{section}"] = {"mode":"closed","allowed_keys":["mean","variance"],"canonical_order":["mean","variance"]}
ut["object_contracts"]["/capability/aptitudes"] = {"mode":"closed","allowed_keys":["order","mean","variance"],"canonical_order":["order","mean","variance"]}
ut["type_contracts"].pop("/capability_ref", None)
ut["type_contracts"].update({
    "/personnel/source_claims/*":["object"],
    "/personnel/source_claims/*/source_ref":["string"],
    "/personnel/source_claims/*/count":["integer"],
    "/personnel/source_claims/*/transaction_ref":["string"],
    "/personnel/source_claims/*/claim_kind":["string"],
    "/personnel/source_claims/*/service_model":["string"],
    "/personnel/source_claims/*/generation_schema":["string"],
    "/capability":["object"],
    "/capability/representation":["string"],
    "/capability/as_of":["string"],
    "/capability/stat_order_ref":["string"],
    "/capability/sample_count":["integer"],
    "/capability/attributes":["object"],
    "/capability/attributes/mean":["array"],
    "/capability/attributes/mean/*":["number"],
    "/capability/attributes/variance":["array"],
    "/capability/attributes/variance/*":["number"],
    "/capability/skills":["object"],
    "/capability/skills/mean":["array"],
    "/capability/skills/mean/*":["number"],
    "/capability/skills/variance":["array"],
    "/capability/skills/variance/*":["number"],
    "/capability/aptitudes":["object"],
    "/capability/aptitudes/order":["array"],
    "/capability/aptitudes/order/*":["string"],
    "/capability/aptitudes/mean":["array"],
    "/capability/aptitudes/mean/*":["number"],
    "/capability/aptitudes/variance":["array"],
    "/capability/aptitudes/variance/*":["number"],
    "/capability/tail_source_ref":["null","string"]
})
ut["array_contracts"]["/personnel/source_claims"] = {"item_types":["object"]}
for path in ("/capability/attributes/mean","/capability/attributes/variance","/capability/skills/mean","/capability/skills/variance","/capability/aptitudes/mean","/capability/aptitudes/variance"):
    ut["array_contracts"][path] = {"item_types":["number"]}
ut["array_contracts"]["/capability/aptitudes/order"] = {"item_types":["string"]}
write_json("data/runtime/templates/unit.v1.template.json", ut)

pf_template = load("data/runtime/templates/personal_force.template.json")
pfroot = pf_template["object_contracts"][""]
if "legacy_roster_ref" not in pfroot["allowed_keys"]: pfroot["allowed_keys"].append("legacy_roster_ref")
if "legacy_roster_ref" not in pfroot["canonical_order"]: pfroot["canonical_order"].append("legacy_roster_ref")
pol = pf_template["object_contracts"]["/policy"]
pol["allowed_keys"] = ["ordinary_personnel_representation","standout_materialization_policy","player_controls_permanent_unit_names_roles_doctrine_loadouts_commanders"]
pol["canonical_order"] = list(pol["allowed_keys"])
pf_template["type_contracts"].pop("/policy/all_personal_troops_individual_lite_or_exact", None)
pf_template["type_contracts"]["/legacy_roster_ref"] = ["string"]
pf_template["type_contracts"]["/policy/ordinary_personnel_representation"] = ["string"]
pf_template["type_contracts"]["/policy/standout_materialization_policy"] = ["string"]
write_json("data/runtime/templates/personal_force.template.json", pf_template)

roster_schema = {
    "$schema":"https://json-schema.org/draft/2020-12/schema",
    "title":"Cold preserved baseline roster for already-established personal-force identities",
    "type":"object",
    "required":["schema","id","owner","baseline_at","stat_order_ref","aptitude_order","next_materialized_sequence","preserved_baseline_defaults","batches","preserved_members","exceptions"],
    "properties":{
        "schema":{"const":"personal-force-roster.v1"},"id":{"type":"string"},"owner":{"type":"string"},"baseline_at":{"type":"string"},"stat_order_ref":{"type":"string"},
        "aptitude_order":{"type":"array","items":{"type":"string"}},"next_materialized_sequence":{"type":"integer","minimum":1},
        "preserved_baseline_defaults":{"type":"object","properties":{
            "origin":{"type":"string"},"birth_date_source":{"type":"string"},"appearance_source":{"type":"string"},"body_growth_profile_id":{"type":"string"},"body_growth_end_age":{"type":"integer"},"body_source":{"type":"string"},"aptitude_source":{"type":"string"},"role_profile_ref":{"type":"string"},"personality_resolution":{"type":"string"},"personality_preferences":{"type":"array","items":{"type":"string"}},"personality_dislikes":{"type":"array","items":{"type":"string"}}
        },"additionalProperties":False},
        "batches":{"type":"object","additionalProperties":{"type":"object","required":["member_ids","source_ref","joined_at"],"properties":{"member_ids":{"type":"array","items":{"type":"string"},"uniqueItems":True},"source_ref":{"type":"string"},"joined_at":{"type":"string"}},"additionalProperties":False}},
        "preserved_members":{"type":"object","additionalProperties":{"type":"object","required":["name","family_id","birth_date","appearance","body","attributes","skills","aptitude","traits"],"properties":{"name":{"type":"string"},"family_id":{"type":["string","null"]},"birth_date":{"type":"string"},"appearance":{"type":"integer"},"body":{"type":"array","minItems":3,"maxItems":3,"prefixItems":[{"type":"number"},{"type":"number"},{"type":"string"}]},"attributes":{"type":"array","minItems":9,"maxItems":9,"items":{"type":"number"}},"skills":{"type":"array","minItems":35,"maxItems":35,"items":{"type":"number"}},"aptitude":{"type":"array","minItems":5,"maxItems":5,"items":{"type":"number"}},"traits":{"type":"array","items":{"type":"string"}}},"additionalProperties":False}},
        "exceptions":{"type":"object","additionalProperties":{"type":"object","required":["status","event_ref"],"properties":{"status":{"type":"string"},"event_ref":{"type":"string"},"notes":{"type":"array","items":{"type":"string"}}},"additionalProperties":False}}
    },"additionalProperties":False
}
write_json("schemas/personal-force-roster-v1.schema.json", roster_schema)
roster_template = {
    "schema":"file-template.v1","template_id":"template.personal-force-roster.v1","target_schema":"personal-force-roster.v1","source_schema":"schemas/personal-force-roster-v1.schema.json","scope":"mutable_state","current_directories":["state/pforce"],"unknown_key_policy":"reject",
    "required_top_level_keys":["schema","id","owner","baseline_at","stat_order_ref","aptitude_order","next_materialized_sequence","preserved_baseline_defaults","batches","preserved_members","exceptions"],
    "object_contracts":{
        "":{"mode":"closed","allowed_keys":["schema","id","owner","baseline_at","stat_order_ref","aptitude_order","next_materialized_sequence","preserved_baseline_defaults","batches","preserved_members","exceptions"],"canonical_order":["schema","id","owner","baseline_at","stat_order_ref","aptitude_order","next_materialized_sequence","preserved_baseline_defaults","batches","preserved_members","exceptions"]},
        "/preserved_baseline_defaults":{"mode":"closed","allowed_keys":list(BASELINE_DEFAULTS.keys()),"canonical_order":list(BASELINE_DEFAULTS.keys())},
        "/batches":{"mode":"open_map"},"/batches/*":{"mode":"closed","allowed_keys":["member_ids","source_ref","joined_at"],"canonical_order":["member_ids","source_ref","joined_at"]},
        "/preserved_members":{"mode":"open_map"},"/preserved_members/*":{"mode":"closed","allowed_keys":["name","family_id","birth_date","appearance","body","attributes","skills","aptitude","traits"],"canonical_order":["name","family_id","birth_date","appearance","body","attributes","skills","aptitude","traits"]},
        "/exceptions":{"mode":"open_map"},"/exceptions/*":{"mode":"closed","allowed_keys":["status","event_ref","notes"],"canonical_order":["status","event_ref","notes"]}
    },
    "type_contracts":{
        "":["object"],"/schema":["string"],"/id":["string"],"/owner":["string"],"/baseline_at":["string"],"/stat_order_ref":["string"],"/aptitude_order":["array"],"/aptitude_order/*":["string"],"/next_materialized_sequence":["integer"],"/preserved_baseline_defaults":["object"],
        "/batches":["object"],"/batches/*":["object"],"/batches/*/member_ids":["array"],"/batches/*/member_ids/*":["string"],"/batches/*/source_ref":["string"],"/batches/*/joined_at":["string"],
        "/preserved_members":["object"],"/preserved_members/*":["object"],"/preserved_members/*/name":["string"],"/preserved_members/*/family_id":["null","string"],"/preserved_members/*/birth_date":["string"],"/preserved_members/*/appearance":["integer"],"/preserved_members/*/body":["array"],"/preserved_members/*/body/*":["number","string"],"/preserved_members/*/attributes":["array"],"/preserved_members/*/attributes/*":["number"],"/preserved_members/*/skills":["array"],"/preserved_members/*/skills/*":["number"],"/preserved_members/*/aptitude":["array"],"/preserved_members/*/aptitude/*":["number"],"/preserved_members/*/traits":["array"],"/preserved_members/*/traits/*":["string"],
        "/exceptions":["object"],"/exceptions/*":["object"],"/exceptions/*/status":["string"],"/exceptions/*/event_ref":["string"],"/exceptions/*/notes":["array"],"/exceptions/*/notes/*":["string"]
    },
    "array_contracts":{
        "/aptitude_order":{"item_types":["string"]},"/batches/*/member_ids":{"item_types":["string"]},"/preserved_members/*/body":{"item_types":["number","string"]},"/preserved_members/*/attributes":{"item_types":["number"]},"/preserved_members/*/skills":{"item_types":["number"]},"/preserved_members/*/aptitude":{"item_types":["number"]},"/preserved_members/*/traits":{"item_types":["string"]},"/exceptions/*/notes":{"item_types":["string"]}
    },
    "writing_rules":["This owner preserves already-established cold identity baselines only; it is not a roster-generation requirement for future aggregate recruits.","Ordinary recruitment never creates preserved_members entries. Add a new exact/lite person only through a separate lawful materialization transaction.","Current unit state, location, training, fatigue, doctrine and shared experience remain with the unit owner; do not duplicate them here."]
}
for key, value in BASELINE_DEFAULTS.items():
    roster_template["type_contracts"][f"/preserved_baseline_defaults/{key}"] = ["integer"] if isinstance(value, int) else (["array"] if isinstance(value, list) else ["string"])
    if isinstance(value, list):
        roster_template["type_contracts"][f"/preserved_baseline_defaults/{key}/*"] = ["string"]
        roster_template["array_contracts"][f"/preserved_baseline_defaults/{key}"] = {"item_types":["string"]}
write_json("data/runtime/templates/personal-force-roster.v1.template.json", roster_template)
pidx = load("data/runtime/template-index-shards/p.json")
pidx["templates"]["personal-force-roster.v1"] = {"path":"data/runtime/templates/personal-force-roster.v1.template.json","source_schema":"schemas/personal-force-roster-v1.schema.json","scope":"mutable_state"}
write_json("data/runtime/template-index-shards/p.json", pidx)

fit = load("data/runtime/system-contracts/forces_institutions.json")
if "state/pforce/" not in fit["authority_paths"]: fit["authority_paths"].append("state/pforce/")
for sid in ("personal_force","personal-force-roster.v1"):
    if sid not in fit["owner_templates"]: fit["owner_templates"].append(sid)
fit["read_first"] = ["owning force/institution/personal-force owner","one causal source population, force pool, or home establishment","only causal unit records","cold legacy personal roster only when an established identity must be reconstructed"]
fit["write_order"] = ["validate recruitment/transfer authority and exact source stratum or pool","conserve and deduct people, horses, equipment and resources from the source aggregate","update destination force/unit aggregate without creating ordinary person owners","materialize a standout or notable individual only through a separate evidence-backed transaction","rebuild routing indexes"]
fit["invariants"] = ["Strategic manpower pools cannot fight until organized into units.","Mass recruitment is aggregate transfer only and never creates one person record per recruit.","Every recruited batch has conserved source provenance; missing source depletion fails closed.","Tang Wei personal-force recruitment is aggregate by default; only a small evidence-backed standout subset may be materialized separately.","Narrative materialization elsewhere is a separate causal event, never a side effect of recruitment.","Returning assigned units preserves losses/history."]
write_json("data/runtime/system-contracts/forces_institutions.json", fit)

units_contract = load("data/runtime/system-contracts/units.json")
units_contract["authority_paths"] = [p for p in units_contract["authority_paths"] if p != "state/unit-capability/"]
units_contract["owner_templates"] = [x for x in units_contract["owner_templates"] if x != "unit-capability.v1"]
units_contract["read_first"] = ["exact materialized unit when present","inline unit capability only when combat/training capability matters","home establishment or force pool only when source/reconstitution matters"]
units_contract["write_order"] = ["validate ownership/authority and conserved personnel source claims","apply split/merge/refit/training/casualty transaction to the single authoritative unit owner","update inline multidimensional capability and shared development state with the unit","conserve manpower/equipment/injury/history","rebuild unit index and derived battle kernels"]
units_contract["invariants"] = ["One unit is one troop type.","One durable standard loadout per unit.","Ordinary unit personnel are aggregate; complete member-name arrays are forbidden.","Unit source-claim counts equal current unit headcount.","Full multidimensional unit capability is intrinsic unit state; battle kernels are derived caches.","Partial durable differences require a split first.","Aggregate unit math remains the large-battle representation; never expand ordinary troops into thousands of people."]
write_json("data/runtime/system-contracts/units.json", units_contract)

pt = load("data/runtime/templates/personnel-policy.template.json")
facts_contract = pt["object_contracts"]["/records/*/facts"]
new_fact_keys = ["Mass recruitment representation","Recruitment source conservation","Tang Wei personal-force recruitment","Narrative materialization boundary"]
for key in new_fact_keys:
    if key not in facts_contract["allowed_keys"]: facts_contract["allowed_keys"].append(key)
    if key not in facts_contract["canonical_order"]: facts_contract["canonical_order"].append(key)
    pt["type_contracts"][f"/records/*/facts/{key}"] = ["string"]
write_json("data/runtime/templates/personnel-policy.template.json", pt)
policy = load("state/person-reg/personnel-policy.json")
facts = policy["records"][0]["facts"]
facts["Mass recruitment representation"] = "Mass forces, countries, mercenary companies, House Tang, Sword Manor, institutions and other ordinary recruitment transfer aggregate headcount only; recruitment itself creates no person owner."
facts["Recruitment source conservation"] = "Every recruited batch identifies and deducts an exact source owner stratum or pool and conserves people; missing source or depletion evidence fails closed. Source strata live inside the owner that controls those people rather than becoming one file per occupation or village."
facts["Tang Wei personal-force recruitment"] = "Tang Wei personal-force recruitment is aggregate by default. A small number of proven standouts may become person-lite only through a separate evidence-backed selection and materialization transaction after recruitment."
facts["Narrative materialization boundary"] = "A specific enemy officer or notable NPC may later become an individual when causally required, but that is a separate materialization event and never a side effect of mass recruitment."
write_json("state/person-reg/personnel-policy.json", policy)

append_section("rules/characters.md", "## Recruitment representation boundary", "Ordinary recruitment is an aggregate whole-person transfer from an exact source population stratum, force pool, institution, household, settlement, state, mercenary source, or other lawful aggregate owner. The recruitment transaction deducts the source and adds the destination count; it does not create a person owner for each recruit. Population strata such as agricultural workers, hunters/foresters, urban labor, veterans, or similar categories exist inside the owner that actually controls those people when such a distinction is causally supported; do not create one state file per stratum.\n\nTang Wei's personal force follows the same aggregate default. Its policy may select a small number of proven standouts for person-lite only after evidence-backed selection and a separate materialization transaction. Recruitment itself never performs that materialization.\n\nA specific enemy officer, notable NPC, recurring contact, specialist, casualty, award recipient, captured person, or other causally important individual may be materialized later under the ordinary exact/lite triggers. That later event deducts or identifies one real body exactly once and is not retroactively treated as part of recruitment. Already-established cold identity baselines may be retained compactly for reconstruction, but current shared unit development and condition remain unit-owned.")
append_section("rules/personal-force.md", "## Aggregate recruitment and standouts", "Personal ownership does not imply one persistent file per soldier. Tang Wei's ordinary personal-force recruits enter lawful homogeneous units or accounting pools as aggregate headcount with conserved source claims. No complete recruit name list is generated.\n\nIf later evidence identifies a genuinely exceptional or narratively persistent member, a separate selection/materialization transaction may peel that one real survivor out into person-lite, deducting or excluding the body from aggregate resolution exactly once and importing settled unit history without free capability. This exception is intentionally sparse.")
append_section("rules/org.md", "## Recruitment source conservation", "Recruitment into a unit, force pool, institution, mercenary company, household force, state force, or training establishment is a conserved aggregate transfer. Each batch records an exact source reference, count, transaction reference, and claim kind; the source owner loses the same real people before the destination may use them. Source strata are nested data of their controlling owner rather than separate files unless the settlement or population itself becomes independently causal.\n\nRecruitment never creates ordinary person owners. Later materialization of a commander, standout, specialist, notable enemy, recurring NPC, casualty, prisoner, award recipient, or other persistent individual is a separate causal transaction governed by the character materialization rules.")

# ---- Migrate existing canonical Tang Champion state under the new structure. ----
roster = {
    "schema":"personal-force-roster.v1","id":"roster.tang_wei.legacy_champions","owner":"char_tang_wei","baseline_at":baseline_at,
    "stat_order_ref":"data/mechanics/stat-orders.json#military_person","aptitude_order":APT_ORDER,"next_materialized_sequence":101,
    "preserved_baseline_defaults":BASELINE_DEFAULTS,
    "batches":{
        "tang_champions_first_founders":{"member_ids":first_ids,"source_ref":"state/org/unit-transactions.json#txn_tang_wei_tang_champions_form","joined_at":"245-BCE-12-02T09:50:00+08:00"},
        "tang_champions_second_founders":{"member_ids":second_ids,"source_ref":"state/org/unit-transactions.json#txn_tang_wei_tang_champions_form","joined_at":"245-BCE-12-02T09:50:00+08:00"}
    },
    "preserved_members":people,"exceptions":{}
}
write_json("state/pforce/wei-legacy-roster.json", roster)

for uid, ids, source_claim in (
    ("unit_tang_wei_tang_champions_first", first_ids, {"source_ref":"state/org/unit-transactions.json#txn_tang_wei_tang_champions_form","count":50,"transaction_ref":"state/org/unit-transactions.json#txn_tang_wei_tang_champions_form","claim_kind":"legacy_personal_retinue_reorganization","service_model":"army_model_household_retainer","generation_schema":"preserved_named_baseline"}),
    ("unit_tang_wei_tang_champions_second", second_ids, {"source_ref":"state/force/house-guardian-cavalry.json#pool_house_guardian_cavalry","count":50,"transaction_ref":"state/org/unit-transactions.json#txn_tang_wei_tang_champions_form","claim_kind":"historical_accounting_correction","service_model":"army_model_household_retainer","generation_schema":"preserved_named_baseline"})
):
    path = CHAMPION_UNITS[uid]
    u = json.loads(path.read_text(encoding="utf-8"))
    arows = [people[x]["attributes"] for x in ids]
    srows = [people[x]["skills"] for x in ids]
    prows = [people[x]["aptitude"] for x in ids]
    am, av = moments(arows); sm, sv = moments(srows); pm, pv = moments(prows)
    u["personnel"] = {"representation":"aggregate","count":50,"source_claims":[source_claim],"condition":{"healthy":50}}
    u.pop("capability_ref", None)
    batch = "tang_champions_first_founders" if uid.endswith("first") else "tang_champions_second_founders"
    u["capability"] = {"representation":"aggregate_moments","as_of":baseline_at,"stat_order_ref":"data/mechanics/stat-orders.json#military_person","sample_count":50,"attributes":{"mean":am,"variance":av},"skills":{"mean":sm,"variance":sv},"aptitudes":{"order":APT_ORDER,"mean":pm,"variance":pv},"tail_source_ref":f"state/pforce/wei-legacy-roster.json#batches/{batch}"}
    u.setdefault("lineage", {})["legacy_identity_roster_ref"] = "state/pforce/wei-legacy-roster.json"
    path.write_text(json.dumps(u, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

pf = load("state/pforce/wei.json")
pf["members"] = ["char_duan_jin","char_shen_rui"]
pf["unassigned_members"] = []
pf["legacy_roster_ref"] = "state/pforce/wei-legacy-roster.json"
pf["policy"] = {"ordinary_personnel_representation":"aggregate_units_default","standout_materialization_policy":"small_evidence_backed_person_lite_only_via_separate_materialization_transaction","player_controls_permanent_unit_names_roles_doctrine_loadouts_commanders":True}
write_json("state/pforce/wei.json", pf)

for p in person_files:
    p.unlink()
idx = load("state/index/owners/tw.json")
idx["owners"] = {}
write_json("state/index/owners/tw.json", idx)
coverage = load("data/runtime/coverage-requirements.json")
if isinstance(coverage.get("required_owner_ids"), list):
    coverage["required_owner_ids"] = [x for x in coverage["required_owner_ids"] if not (isinstance(x,str) and x.startswith("tw.m"))]
write_json("data/runtime/coverage-requirements.json", coverage)

# Permanent regression tests for the new representation contract.
recruitment_test = r'''#!/usr/bin/env python3
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
if "separate_materialization_transaction" not in pf.get("policy",{}).get("standout_materialization_policy",""): err("wei_standout_boundary")
if set(pf.get("members",[]))!={"char_duan_jin","char_shen_rui"}: err("wei_members_not_exact_only")
if any((ROOT/"state/person/wei").glob("*.json")): err("legacy_person_file_present")
roster=load("state/pforce/wei-legacy-roster.json")
if len(roster.get("preserved_members",{}))!=100: err("legacy_roster_count")
for rel in sorted((ROOT/"state/unit").glob("*.json")):
    u=json.loads(rel.read_text(encoding="utf-8")); per=u.get("personnel",{})
    if per.get("representation")!="aggregate": err(f"nonaggregate_unit:{u.get('id')}")
    if per.get("member_ids"): err(f"unit_member_list:{u.get('id')}")
    claims=per.get("source_claims",[])
    if sum(x.get("count",0) for x in claims)!=per.get("count"): err(f"source_claim_conservation:{u.get('id')}")
    for x in claims:
        for k in ("source_ref","count","transaction_ref","claim_kind"):
            if not x.get(k): err(f"source_claim_field:{u.get('id')}:{k}")
    cap=u.get("capability",{})
    if cap.get("sample_count")!=per.get("count"): err(f"capability_count:{u.get('id')}")
    if len(cap.get("attributes",{}).get("mean",[]))!=9 or len(cap.get("attributes",{}).get("variance",[]))!=9: err(f"attribute_distribution:{u.get('id')}")
    if len(cap.get("skills",{}).get("mean",[]))!=35 or len(cap.get("skills",{}).get("variance",[]))!=35: err(f"skill_distribution:{u.get('id')}")
    if len(cap.get("aptitudes",{}).get("mean",[]))!=5 or len(cap.get("aptitudes",{}).get("variance",[]))!=5: err(f"aptitude_distribution:{u.get('id')}")
if errors:
    print("RECRUITMENT REPRESENTATION TEST FAILED")
    for e in errors: print("-",e)
    sys.exit(1)
print("RECRUITMENT REPRESENTATION TEST OK")
print("mass recruitment aggregate-only; source claims conserved; Wei standout and narrative materialization are separate events")
'''
(ROOT/"tools/test_recruitment_representation.py").write_text(recruitment_test, encoding="utf-8")

tang_test = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
errors=[]
def load(rel):
    p=ROOT/rel
    if not p.exists(): errors.append(f"missing:{rel}"); return {}
    return json.loads(p.read_text(encoding="utf-8"))
def err(x): errors.append(x)
first=load("state/unit/tang-champions-first.json"); second=load("state/unit/tang-champions-second.json")
for label,u,uid,cmd in (("first",first,"unit_tang_wei_tang_champions_first","char_duan_jin"),("second",second,"unit_tang_wei_tang_champions_second","char_shen_rui")):
    if u.get("id")!=uid: err(f"{label}_id")
    if u.get("owner")!="char_tang_wei" or u.get("troop_type")!="heavy_cavalry": err(f"{label}_owner_type")
    if u.get("commander_id")!=cmd: err(f"{label}_commander")
    if u.get("doctrine")!="doc.tang_wei.household_champions" or u.get("training")!="train.tang_wei.household_champions": err(f"{label}_doctrine_training")
    if u.get("loadout_standard")!="loadout_house_guardian_cavalry": err(f"{label}_loadout")
    per=u.get("personnel",{})
    if per.get("representation")!="aggregate" or per.get("count")!=50 or per.get("member_ids"): err(f"{label}_personnel")
    if per.get("condition",{}).get("healthy")!=50: err(f"{label}_condition")
    if sum(x.get("count",0) for x in per.get("source_claims",[]))!=50: err(f"{label}_source_claims")
    cap=u.get("capability",{})
    if cap.get("sample_count")!=50 or cap.get("representation")!="aggregate_moments": err(f"{label}_capability")
    if u.get("issue_state",{}).get("mount_issue_state",{}).get("standard_mounts_present")!=50: err(f"{label}_mounts")
pf=load("state/pforce/wei.json")
if pf.get("owner")!="char_tang_wei": err("personal_force_owner")
if pf.get("permanent_units")!=["unit_tang_wei_tang_champions_first","unit_tang_wei_tang_champions_second"]: err("personal_force_units")
if set(pf.get("members",[]))!={"char_duan_jin","char_shen_rui"}: err("personal_force_exact_members")
roster=load("state/pforce/wei-legacy-roster.json")
expected={f"tw.m{i:03d}" for i in range(1,101)}
if set(roster.get("preserved_members",{}))!=expected: err("legacy_identity_set")
if set(roster.get("batches",{}).get("tang_champions_first_founders",{}).get("member_ids",[]))!={f"tw.m{i:03d}" for i in range(1,51)}: err("first_legacy_batch")
if set(roster.get("batches",{}).get("tang_champions_second_founders",{}).get("member_ids",[]))!={f"tw.m{i:03d}" for i in range(51,101)}: err("second_legacy_batch")
if any((ROOT/"state/person/wei").glob("*.json")): err("legacy_live_person_sheets")
parent=load("state/cmd/command-groups/cmdgrp.tang_wei.personal_force.json"); duan=load("state/cmd/command-groups/cmdgrp.duan_jin.tang_champions_first.json"); shen=load("state/cmd/command-groups/cmdgrp.shen_rui.tang_champions_second.json")
if set(parent.get("subordinate_command_group_refs",[]))!={"cmdgrp.duan_jin.tang_champions_first","cmdgrp.shen_rui.tang_champions_second"}: err("parent_peer_groups")
for label,g,cmd,uid in (("duan",duan,"char_duan_jin","unit_tang_wei_tang_champions_first"),("shen",shen,"char_shen_rui","unit_tang_wei_tang_champions_second")):
    if g.get("commander_ref")!=cmd or g.get("direct_unit_refs")!=[uid] or g.get("parent_command_group_ref")!="cmdgrp.tang_wei.personal_force": err(f"{label}_command_group")
hgc=load("state/force/house-guardian-cavalry.json")
if hgc.get("aggregate_personnel_count")!=250 or hgc.get("headcount")!=251: err("house_guardian_cavalry_accounting")
kai=load("state/char/tang-kai.json"); kcmd=load("state/cmd/command-personnel/char_tang_kai.json")
if kcmd.get("command",{}).get("current_unit_ids")!=[] or kcmd.get("command",{}).get("current_army_id") is not None: err("kai_has_assigned_troops")
if "no independent" not in kai.get("authority","").lower(): err("kai_independent_authority_not_blocked")
idx=load("state/index/units.json").get("units",{})
if idx!={"unit_tang_wei_tang_champions_first":"state/unit/tang-champions-first.json","unit_tang_wei_tang_champions_second":"state/unit/tang-champions-second.json"}: err("unit_index")
if errors:
    print("TANG CHAMPIONS TEST FAILED")
    for e in errors: print("-",e)
    sys.exit(1)
print("TANG CHAMPIONS TEST OK")
print("two peer aggregate 50-person Tang Champion companies; exact commanders separate; 100 legacy identities cold-preserved in one roster")
'''
(ROOT/"tools/test_tang_champions.py").write_text(tang_test, encoding="utf-8")

rv = (ROOT/"tools/run_validators.py").read_text(encoding="utf-8")
rv = rv.replace('    "tools/emit_personal_roster_migration.py",\n', '    "tools/test_recruitment_representation.py",\n')
(ROOT/"tools/run_validators.py").write_text(rv, encoding="utf-8")

# Ensure no unexpected live JSON references still depend on the retired ordinary-person owners.
allowed_tw_ref_files = {"state/pforce/wei-legacy-roster.json","state/org/unit-transactions.json"}
unexpected_refs=[]
for p in (ROOT/"state").rglob("*.json"):
    rel=p.relative_to(ROOT).as_posix()
    if rel in allowed_tw_ref_files: continue
    text=p.read_text(encoding="utf-8")
    if "tw.m0" in text or "tw.m100" in text:
        unexpected_refs.append(rel)
if unexpected_refs:
    raise SystemExit("unexpected live tw.m references remain after migration: " + ", ".join(sorted(unexpected_refs)))

# Restore the normal read-only audit workflow in the generated commit and remove this one-shot tool.
(ROOT/".github/workflows/audit.yml").write_text("name: audit\non: [push, pull_request]\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install jsonschema\n      - name: Run full validator stack\n        run: python tools/run_validators.py\n", encoding="utf-8")
Path(__file__).unlink()
print("PERSONNEL CONSOLIDATION APPLIED")
print("100 ordinary live person sheets -> two aggregate unit owners + one cold legacy baseline roster; future recruitment creates zero person records by default")
