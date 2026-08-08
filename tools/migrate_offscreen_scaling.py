from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD_TIME = "245-BCE-12-04T07:22:48+08:00"
OLD_REVISION = 18
NEW_REVISION = 19


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def dump(rel, data, pretty=False):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    else:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    p.write_text(text, encoding="utf-8")


def remove(rel):
    p = ROOT / rel
    if p.exists():
        p.unlink()


def check(cond, msg):
    if not cond:
        raise SystemExit(msg)


def replace_once(rel, old, new):
    p = ROOT / rel
    text = p.read_text(encoding="utf-8")
    check(old in text, f"missing replacement anchor: {rel}: {old[:100]!r}")
    check(text.count(old) == 1, f"nonunique replacement anchor: {rel}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def remove_values(obj, forbidden):
    if isinstance(obj, list):
        out = []
        for x in obj:
            if isinstance(x, str) and x in forbidden:
                continue
            out.append(remove_values(x, forbidden))
        return out
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in forbidden:
                continue
            out[k] = remove_values(v, forbidden)
        return out
    return obj


def age_years(birth_date):
    m = re.fullmatch(r"(\d+)-BCE-(\d\d)-(\d\d)", birth_date or "")
    check(m is not None, f"bad BCE birth date: {birth_date}")
    by, bm, bd = map(int, m.groups())
    cy, cm, cd = 245, 12, 4
    age = by - cy
    if (cm, cd) < (bm, bd):
        age -= 1
    return age


def capability_band(value):
    value = int(value)
    if value >= 180:
        return "master"
    if value >= 150:
        return "expert"
    if value >= 120:
        return "experienced"
    if value >= 80:
        return "competent"
    return "basic"


def focused_skills(focus):
    head = (focus or "").split(";", 1)[0]
    return [x.strip() for x in head.split(",") if x.strip()]


# Persistence base guard.
meta = load("state/meta.json")
check(meta.get("revision") == OLD_REVISION, f"unexpected revision {meta.get('revision')}")
check(meta.get("time") == WORLD_TIME, f"unexpected world time {meta.get('time')}")

# ---------------------------------------------------------------------------
# 1. Register new structural contracts first.
# ---------------------------------------------------------------------------
latent_schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "count", "identities"],
    "properties": {
        "schema": {"const": "latent-identity-catalog"},
        "count": {"type": "integer", "minimum": 0},
        "identities": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "source_hint": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}
role_schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "owner_id", "owner_type", "roles", "runtime"],
    "properties": {
        "schema": {"const": "role-slot-registry"},
        "owner_id": {"type": "string"},
        "owner_type": {"const": "role_slot_registry"},
        "roles": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "required": ["institution_ref", "role", "status", "position_count"],
                "properties": {
                    "institution_ref": {"type": "string"},
                    "role": {"type": "string"},
                    "status": {"enum": ["occupied", "vacant", "selection_in_progress", "capacity_only"]},
                    "position_count": {"type": "integer", "minimum": 1},
                    "authority_summary": {"type": "string"},
                    "location_ref": {"type": "string"},
                    "source_population_ref": {"type": "string"},
                    "included_in_population": {"type": "boolean"},
                    "incumbent": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["representation", "age_years", "capability_bands", "health_availability", "service_development_credit", "retirement_status", "materialized_character_id", "settled_through"],
                        "properties": {
                            "representation": {"enum": ["anonymous_role_incumbent", "materialized_character"]},
                            "age_years": {"type": "integer", "minimum": 0},
                            "capability_bands": {
                                "type": "object",
                                "additionalProperties": {"enum": ["basic", "competent", "experienced", "expert", "master"]},
                            },
                            "health_availability": {"enum": ["fit", "limited", "unavailable", "dead"]},
                            "service_development_credit": {"type": "number", "minimum": 0},
                            "retirement_status": {"enum": ["active", "eligible", "retiring", "retired"]},
                            "materialized_character_id": {"type": ["string", "null"]},
                            "settled_through": {"type": "string"},
                        },
                    },
                },
            },
        },
        "runtime": {
            "type": "object",
            "additionalProperties": False,
            "required": ["last_settled_at"],
            "properties": {"last_settled_at": {"type": "string"}},
        },
    },
}
fort_schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "owner_id", "owner_type", "sites", "runtime"],
    "properties": {
        "schema": {"const": "strategic-fortification-registry"},
        "owner_id": {"type": "string"},
        "owner_type": {"const": "strategic_fortification_registry"},
        "sites": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "controller_scope", "role", "fortification_class", "materialization_state"],
                "properties": {
                    "name": {"type": "string"},
                    "controller_scope": {"type": "string"},
                    "role": {"type": "string"},
                    "fortification_class": {"type": "string"},
                    "materialization_state": {"enum": ["profile_only", "materialized"]},
                    "defense_state": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["wall_condition_band", "gate_condition_band", "breach_state", "artillery_refs", "garrison_refs", "supply_refs", "engineer_refs", "repair_backlog_band"],
                        "properties": {
                            "wall_condition_band": {"type": "string"},
                            "gate_condition_band": {"type": "string"},
                            "breach_state": {"type": "string"},
                            "artillery_refs": {"type": "array", "items": {"type": "string"}},
                            "garrison_refs": {"type": "array", "items": {"type": "string"}},
                            "supply_refs": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "food": {"type": "string"},
                                    "water": {"type": "string"},
                                    "ammunition": {"type": "string"},
                                    "repair_material": {"type": "string"},
                                },
                            },
                            "engineer_refs": {"type": "array", "items": {"type": "string"}},
                            "repair_backlog_band": {"type": "string"},
                        },
                    },
                },
                "allOf": [
                    {
                        "if": {"properties": {"materialization_state": {"const": "materialized"}}},
                        "then": {"required": ["defense_state"]},
                    }
                ],
            },
        },
        "runtime": {
            "type": "object",
            "additionalProperties": False,
            "required": ["last_settled_at"],
            "properties": {"last_settled_at": {"type": "string"}},
        },
    },
}

dump("schemas/latent-identity-catalog.schema.json", latent_schema, True)
dump("schemas/role-slot-registry.schema.json", role_schema, True)
dump("schemas/strategic-fortification-registry.schema.json", fort_schema, True)

latent_template = {
    "schema": "file-template.v1",
    "template_id": "template.latent-identity-catalog",
    "target_schema": "latent-identity-catalog",
    "source_schema": "schemas/latent-identity-catalog.schema.json",
    "scope": "static_data",
    "current_directories": ["data/people"],
    "unknown_key_policy": "reject",
    "required_top_level_keys": ["count", "identities", "schema"],
    "object_contracts": {
        "": {"mode": "closed", "allowed_keys": ["schema", "count", "identities"], "canonical_order": ["schema", "count", "identities"]},
        "/identities": {"mode": "open_map"},
        "/identities/*": {"mode": "closed", "allowed_keys": ["name", "source_hint"], "canonical_order": ["name", "source_hint"]},
    },
    "type_contracts": {"/schema": ["string"], "/count": ["integer"], "/identities": ["object"], "/identities/*": ["object"], "/identities/*/name": ["string"], "/identities/*/source_hint": ["string"], "": ["object"]},
    "array_contracts": {},
    "writing_rules": ["Catalog entries own canonical source names only.", "A catalog entry is not a current body, office, location, capability, relationship, inventory, knowledge state, or personal clock.", "Current existence must be established from live world authority before materialization."],
}
role_template = {
    "schema": "file-template.v1",
    "template_id": "template.role-slot-registry",
    "target_schema": "role-slot-registry",
    "source_schema": "schemas/role-slot-registry.schema.json",
    "scope": "mutable_state",
    "current_directories": ["state/app"],
    "unknown_key_policy": "reject",
    "required_top_level_keys": ["owner_id", "owner_type", "roles", "runtime", "schema"],
    "object_contracts": {
        "": {"mode": "closed", "allowed_keys": ["schema", "owner_id", "owner_type", "roles", "runtime"], "canonical_order": ["schema", "owner_id", "owner_type", "roles", "runtime"]},
        "/roles": {"mode": "open_map"},
        "/roles/*": {"mode": "closed", "allowed_keys": ["institution_ref", "role", "status", "position_count", "authority_summary", "location_ref", "source_population_ref", "included_in_population", "incumbent"], "canonical_order": ["institution_ref", "role", "status", "position_count", "authority_summary", "location_ref", "source_population_ref", "included_in_population", "incumbent"]},
        "/roles/*/incumbent": {"mode": "closed", "allowed_keys": ["representation", "age_years", "capability_bands", "health_availability", "service_development_credit", "retirement_status", "materialized_character_id", "settled_through"], "canonical_order": ["representation", "age_years", "capability_bands", "health_availability", "service_development_credit", "retirement_status", "materialized_character_id", "settled_through"]},
        "/roles/*/incumbent/capability_bands": {"mode": "open_map"},
        "/runtime": {"mode": "closed", "allowed_keys": ["last_settled_at"], "canonical_order": ["last_settled_at"]},
    },
    "type_contracts": {"/schema": ["string"], "/owner_id": ["string"], "/owner_type": ["string"], "/roles": ["object"], "/roles/*": ["object"], "/roles/*/institution_ref": ["string"], "/roles/*/role": ["string"], "/roles/*/status": ["string"], "/roles/*/position_count": ["integer"], "/roles/*/authority_summary": ["string"], "/roles/*/location_ref": ["string"], "/roles/*/source_population_ref": ["string"], "/roles/*/included_in_population": ["boolean"], "/roles/*/incumbent": ["object"], "/roles/*/incumbent/representation": ["string"], "/roles/*/incumbent/age_years": ["integer"], "/roles/*/incumbent/capability_bands": ["object"], "/roles/*/incumbent/capability_bands/*": ["string"], "/roles/*/incumbent/health_availability": ["string"], "/roles/*/incumbent/service_development_credit": ["number"], "/roles/*/incumbent/retirement_status": ["string"], "/roles/*/incumbent/materialized_character_id": ["null", "string"], "/roles/*/incumbent/settled_through": ["string"], "/runtime": ["object"], "/runtime/last_settled_at": ["string"], "": ["object"]},
    "array_contracts": {},
    "writing_rules": ["Role slots own institutional continuity only.", "Anonymous incumbents never carry a secret name, personality, biography, private inventory, relationship graph, or exact personal skill sheet.", "When an exact individual becomes causally necessary, materialize one real person and bind the slot without creating another body."],
}
fort_template = {
    "schema": "file-template.v1",
    "template_id": "template.strategic-fortification-registry",
    "target_schema": "strategic-fortification-registry",
    "source_schema": "schemas/strategic-fortification-registry.schema.json",
    "scope": "mutable_state",
    "current_directories": ["state/geo"],
    "unknown_key_policy": "reject",
    "required_top_level_keys": ["owner_id", "owner_type", "runtime", "schema", "sites"],
    "object_contracts": {
        "": {"mode": "closed", "allowed_keys": ["schema", "owner_id", "owner_type", "sites", "runtime"], "canonical_order": ["schema", "owner_id", "owner_type", "sites", "runtime"]},
        "/sites": {"mode": "open_map"},
        "/sites/*": {"mode": "closed", "allowed_keys": ["name", "controller_scope", "role", "fortification_class", "materialization_state", "defense_state"], "canonical_order": ["name", "controller_scope", "role", "fortification_class", "materialization_state", "defense_state"]},
        "/sites/*/defense_state": {"mode": "closed", "allowed_keys": ["wall_condition_band", "gate_condition_band", "breach_state", "artillery_refs", "garrison_refs", "supply_refs", "engineer_refs", "repair_backlog_band"], "canonical_order": ["wall_condition_band", "gate_condition_band", "breach_state", "artillery_refs", "garrison_refs", "supply_refs", "engineer_refs", "repair_backlog_band"]},
        "/sites/*/defense_state/supply_refs": {"mode": "closed", "allowed_keys": ["food", "water", "ammunition", "repair_material"], "canonical_order": ["food", "water", "ammunition", "repair_material"]},
        "/runtime": {"mode": "closed", "allowed_keys": ["last_settled_at"], "canonical_order": ["last_settled_at"]},
    },
    "type_contracts": {"/schema": ["string"], "/owner_id": ["string"], "/owner_type": ["string"], "/sites": ["object"], "/sites/*": ["object"], "/sites/*/name": ["string"], "/sites/*/controller_scope": ["string"], "/sites/*/role": ["string"], "/sites/*/fortification_class": ["string"], "/sites/*/materialization_state": ["string"], "/sites/*/defense_state": ["object"], "/sites/*/defense_state/wall_condition_band": ["string"], "/sites/*/defense_state/gate_condition_band": ["string"], "/sites/*/defense_state/breach_state": ["string"], "/sites/*/defense_state/artillery_refs": ["array"], "/sites/*/defense_state/artillery_refs/*": ["string"], "/sites/*/defense_state/garrison_refs": ["array"], "/sites/*/defense_state/garrison_refs/*": ["string"], "/sites/*/defense_state/supply_refs": ["object"], "/sites/*/defense_state/supply_refs/food": ["string"], "/sites/*/defense_state/supply_refs/water": ["string"], "/sites/*/defense_state/supply_refs/ammunition": ["string"], "/sites/*/defense_state/supply_refs/repair_material": ["string"], "/sites/*/defense_state/engineer_refs": ["array"], "/sites/*/defense_state/engineer_refs/*": ["string"], "/sites/*/defense_state/repair_backlog_band": ["string"], "/runtime": ["object"], "/runtime/last_settled_at": ["string"], "": ["object"]},
    "array_contracts": {"/sites/*/defense_state/artillery_refs": {"item_types": ["string"]}, "/sites/*/defense_state/garrison_refs": {"item_types": ["string"]}, "/sites/*/defense_state/engineer_refs": {"item_types": ["string"]}},
    "writing_rules": ["Profile-only sites contain no invented wall dimensions, garrison numbers, artillery counts, stores, ammunition, water, or repair stock.", "Before an exact siege, assault, blockade, breach, or repair resolution, materialize defense_state from lawful controller resources and current geography.", "Player and NPC fortifications use the same materialization and conservation requirements."],
}

dump("data/runtime/templates/latent-identity-catalog.template.json", latent_template)
dump("data/runtime/templates/role-slot-registry.template.json", role_template)
dump("data/runtime/templates/strategic-fortification-registry.template.json", fort_template)

registry = load("schemas/registry.json")
old_schema_keys = ["character-identity-shard.v1", "character-roster-index.v1", "identity-life-course-registry", "appointment-registry"]
old_schema_files = []
for key in old_schema_keys:
    if key in registry:
        old_schema_files.append(registry.pop(key))
registry["latent-identity-catalog"] = "latent-identity-catalog.schema.json"
registry["role-slot-registry"] = "role-slot-registry.schema.json"
registry["strategic-fortification-registry"] = "strategic-fortification-registry.schema.json"
dump("schemas/registry.json", registry)

# Template index maintenance.
for shard, keys in {
    "c": ["character-identity-shard.v1", "character-roster-index.v1"],
    "i": ["identity-life-course-registry"],
    "a": ["appointment-registry"],
}.items():
    rel = f"data/runtime/template-index-shards/{shard}.json"
    d = load(rel)
    for key in keys:
        d.get("templates", {}).pop(key, None)
    dump(rel, d)
for shard, key, path, schema_path, scope in [
    ("l", "latent-identity-catalog", "data/runtime/templates/latent-identity-catalog.template.json", "schemas/latent-identity-catalog.schema.json", "static_data"),
    ("r", "role-slot-registry", "data/runtime/templates/role-slot-registry.template.json", "schemas/role-slot-registry.schema.json", "mutable_state"),
    ("s", "strategic-fortification-registry", "data/runtime/templates/strategic-fortification-registry.template.json", "schemas/strategic-fortification-registry.schema.json", "mutable_state"),
]:
    rel = f"data/runtime/template-index-shards/{shard}.json"
    d = load(rel)
    d.setdefault("templates", {})[key] = {"path": path, "source_schema": schema_path, "scope": scope}
    dump(rel, d)

# Remove obsolete registered template/schema files after replacements are registered.
for rel in [
    "data/runtime/templates/character-identity-shard.v1.template.json",
    "data/runtime/templates/character-roster-index.v1.template.json",
    "data/runtime/templates/identity-life-course-registry.template.json",
    "data/runtime/templates/appointment-registry.template.json",
]:
    remove(rel)
for filename in old_schema_files:
    remove("schemas/" + filename)

# ---------------------------------------------------------------------------
# 2. Convert the 306 mutable deferred-name records into one static name catalog.
# ---------------------------------------------------------------------------
identities = {}
for p in sorted((ROOT / "state/char-roster/shards").glob("*.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    for cid, rec in d.get("identities", {}).items():
        check(cid not in identities, f"duplicate latent identity {cid}")
        out = {"name": rec["name"]}
        hint = (rec.get("routing_hints") or {}).get("state_or_affiliation_hint")
        if hint:
            out["source_hint"] = hint
        identities[cid] = out
check(len(identities) == 306, f"latent identity count changed before migration: {len(identities)}")
dump("data/people/latent-identities.json", {"schema": "latent-identity-catalog", "count": len(identities), "identities": dict(sorted(identities.items()))})

for p in sorted((ROOT / "state/char-roster/shards").glob("*.json")):
    p.unlink()
remove("state/char-roster/index.json")
try:
    (ROOT / "state/char-roster/shards").rmdir()
    (ROOT / "state/char-roster").rmdir()
except OSError:
    pass

# The roster-specific mutable life-course owner is redundant once source names stop asserting bodies.
remove("state/life/identity-life-course.json")
try:
    (ROOT / "state/life").rmdir()
except OSError:
    pass

# ---------------------------------------------------------------------------
# 3. Migrate routine House Tang civilian people into anonymous institutional role slots.
# ---------------------------------------------------------------------------
full_roles = {
    "char_gu_wen": ("state/char/gu-wen.json", "role.house_tang.warehouse_granary_chief"),
    "char_han_qiao": ("state/char/han-qiao.json", "role.house_tang.forge_master"),
    "char_lu_zhen": ("state/char/lu-zhen.json", "role.house_tang.chief_administrator"),
    "char_ma_xun": ("state/char/ma-xun.json", "role.house_tang.stable_remount_master"),
    "char_tian_yu": ("state/char/tian-yu.json", "role.house_tang.agricultural_director"),
    "char_lin_mei": ("state/char/lin-mei.json", "role.house_tang.chief_physician"),
}
lite_roles = {
    "staff.tang.chen_yu": ("state/person/staff/staff-tang-chen_yu.json", "role.house_tang.estate_accountant"),
    "staff.tang.gao_fen": ("state/person/staff/staff-tang-gao_fen.json", "role.house_tang.armorer"),
    "staff.tang.he_mei": ("state/person/staff/staff-tang-he_mei.json", "role.house_tang.senior_scribe"),
    "staff.tang.liu_fang": ("state/person/staff/staff-tang-liu_fang.json", "role.house_tang.intelligence_contact_manager"),
    "staff.tang.luo_min": ("state/person/staff/staff-tang-luo_min.json", "role.house_tang.physician_assistant"),
    "staff.tang.sun_qiao": ("state/person/staff/staff-tang-sun_qiao.json", "role.house_tang.caravan_broker"),
    "staff.tang.xie_an": ("state/person/staff/staff-tang-xie_an.json", "role.house_tang.works_planner"),
    "staff.tang.zhang_ren": ("state/person/staff/staff-tang-zhang_ren.json", "role.house_tang.stable_deputy"),
}

training = load("state/prog/tang-named-staff-training.json")
training_focus = {}
for rec in training.get("records", []):
    facts = rec.get("facts") or {}
    sid = facts.get("subject_id")
    if sid:
        training_focus[sid] = facts.get("focus", "")
check(set(lite_roles) == set(training_focus), "Tang named-staff training registry no longer matches the eight intended civilian specialists")

roles = {}
for cid, (path, role_id) in full_roles.items():
    d = load(path)
    check(d.get("owner_id") == cid, f"character owner mismatch {cid}")
    focus = focused_skills((d.get("activity_contract") or {}).get("focus"))
    skills = d.get("skills") or {}
    bands = {s.lower().replace(" ", "_"): capability_band(skills[s]) for s in focus if s in skills}
    check(bands, f"no functional skill bands for {cid}")
    roles[role_id] = {
        "institution_ref": "institution_house_tang",
        "role": d.get("role") or role_id.rsplit(".", 1)[-1].replace("_", " "),
        "status": "occupied",
        "position_count": 1,
        "authority_summary": d.get("authority", "Delegated institutional authority only."),
        "location_ref": d.get("current_location"),
        "source_population_ref": "population_tang_manor",
        "included_in_population": True,
        "incumbent": {
            "representation": "anonymous_role_incumbent",
            "age_years": age_years(d.get("birth_date")),
            "capability_bands": bands,
            "health_availability": "fit" if d.get("health_status") == "healthy" else "limited",
            "service_development_credit": float((d.get("development_state") or {}).get("training_credit", 0.0)) + float((d.get("development_state") or {}).get("maintenance_credit", 0.0)),
            "retirement_status": "active",
            "materialized_character_id": None,
            "settled_through": WORLD_TIME,
        },
    }

for pid, (path, role_id) in lite_roles.items():
    d = load(path)
    check(d.get("id") == pid, f"person-lite id mismatch {pid}")
    focus = focused_skills(training_focus[pid])
    skills = ((d.get("stats") or {}).get("skills") or {})
    bands = {s.lower().replace(" ", "_"): capability_band(skills[s]) for s in focus if s in skills}
    check(bands, f"no functional skill bands for {pid}")
    health = (d.get("health") or {}).get("status")
    roles[role_id] = {
        "institution_ref": "institution_house_tang",
        "role": d.get("role") or role_id.rsplit(".", 1)[-1].replace("_", " "),
        "status": "occupied",
        "position_count": 1,
        "authority_summary": "Routine delegated authority within this House Tang specialty; no independent strategic commitment.",
        "source_population_ref": "population_tang_manor",
        "included_in_population": True,
        "incumbent": {
            "representation": "anonymous_role_incumbent",
            "age_years": age_years(d.get("birth_date")),
            "capability_bands": bands,
            "health_availability": "fit" if health == "healthy" else "limited",
            "service_development_credit": 0.0,
            "retirement_status": "active",
            "materialized_character_id": None,
            "settled_through": WORLD_TIME,
        },
    }

# Preserve capacity facts from the obsolete appointments owner without fabricating incumbents.
roles["role.sword_manor.escort_captain"] = {
    "institution_ref": "institution_sword_manor",
    "role": "escort captain",
    "status": "capacity_only",
    "position_count": 20,
    "authority_summary": "Defined escort-command capacity; an incumbent must be lawfully assigned before the position can exercise authority.",
}
roles["role.sword_manor.senior_instructor"] = {
    "institution_ref": "institution_sword_manor",
    "role": "senior instructor",
    "status": "capacity_only",
    "position_count": 10,
    "authority_summary": "Defined senior-instructor capacity; only lawfully assigned and available instructors contribute instruction.",
}

role_owner = {"schema": "role-slot-registry", "owner_id": "institution_role_slots", "owner_type": "role_slot_registry", "roles": dict(sorted(roles.items())), "runtime": {"last_settled_at": WORLD_TIME}}
dump("state/app/role-slots.json", role_owner, True)
remove("state/app/appointments-and-command.json")
remove("state/prog/tang-named-staff-training.json")
for _, (path, _) in full_roles.items():
    remove(path)
for _, (path, _) in lite_roles.items():
    remove(path)

# ---------------------------------------------------------------------------
# 4. Strategic-fortification parity without invented precision.
# ---------------------------------------------------------------------------
fort_owner = {
    "schema": "strategic-fortification-registry",
    "owner_id": "world_fortifications",
    "owner_type": "strategic_fortification_registry",
    "sites": {
        "loc_kanyou": {"name": "Kanyou", "controller_scope": "Qin", "role": "capital", "fortification_class": "fortified_capital", "materialization_state": "profile_only"},
        "loc_kankoku_pass": {"name": "Kankoku Pass", "controller_scope": "Qin", "role": "strategic fortified pass", "fortification_class": "major_fortified_pass", "materialization_state": "profile_only"},
        "loc_gyou": {"name": "Gyou", "controller_scope": "Zhao", "role": "major fortress city", "fortification_class": "major_fortress_city", "materialization_state": "profile_only"},
    },
    "runtime": {"last_settled_at": WORLD_TIME},
}
dump("state/geo/strategic-fortifications.json", fort_owner, True)
geo = load("state/geo/world-geography.json")
existing = {r.get("record_id") for r in geo.get("records", [])}
if "loc_kankoku_pass" not in existing:
    geo["records"].append({"facts": {"name": "Kankoku Pass", "role": "major fortified pass", "state": "Qin"}, "label": "loc_kankoku_pass", "record_id": "loc_kankoku_pass"})
if "loc_gyou" not in existing:
    geo["records"].append({"facts": {"name": "Gyou", "role": "major fortress city", "state": "Zhao"}, "label": "loc_gyou", "record_id": "loc_gyou"})
dump("state/geo/world-geography.json", geo, True)

# ---------------------------------------------------------------------------
# 5. Update system contracts and routing.
# ---------------------------------------------------------------------------
chars = load("data/runtime/system-contracts/characters.json")
chars["authority_paths"] = [x for x in chars.get("authority_paths", []) if x != "state/char-roster/"]
if "data/people/latent-identities.json" not in chars["authority_paths"]:
    chars["authority_paths"].append("data/people/latent-identities.json")
chars["owner_templates"] = [x for x in chars.get("owner_templates", []) if x not in {"character-identity-shard.v1", "character-roster-index.v1"}]
chars["read_first"] = [
    "exact/lite owner when a current named person is materialized",
    "static latent identity catalog only when a source-canon name is causally relevant; catalog presence alone never asserts current existence",
    "for a behavior-light exact owner in sustained interaction, one routed behavior support profile only when needed",
]
chars["invariants"] = [
    "A static identity-catalog entry is a source name, not a current body or personal clock.",
    "Current named people use exact or individual-lite owners; ordinary populations remain aggregate.",
    "Materialization from a source identity first proves current existence and one conserved source person/slot.",
    "No future achievements, ranks, offices, equipment, relationships, knowledge, or capability are back-projected.",
]
dump("data/runtime/system-contracts/characters.json", chars)

fi = load("data/runtime/system-contracts/forces_institutions.json")
if "state/app/" not in fi["authority_paths"]:
    fi["authority_paths"].append("state/app/")
if "role-slot-registry" not in fi["owner_templates"]:
    fi["owner_templates"].append("role-slot-registry")
fi["write_order"].extend([
    "settle anonymous institutional role slots through the owning institution/process without creating secret person sheets",
    "materialize a role incumbent as a named person only when exact personal agency becomes causal, conserving the same body exactly once",
])
fi["invariants"].extend([
    "Routine civilian offices may use anonymous role slots; role slots own function, availability and coarse capability only.",
    "Role slots never store secret names, personality, biography, relationships, private inventory or an exact personal skill sheet.",
    "Military commanders and command staff remain exact people under command authority rather than role-slot bonuses.",
])
dump("data/runtime/system-contracts/forces_institutions.json", fi)

geo_contract = load("data/runtime/system-contracts/geography_movement.json")
if "strategic-fortification-registry" not in geo_contract["owner_templates"]:
    geo_contract["owner_templates"].append("strategic-fortification-registry")
geo_contract["read_first"].append("strategic fortification entry when siege, assault, blockade, breach, garrison supply or repair is causal")
geo_contract["write_order"].append("before exact siege resolution, materialize required fortification, garrison, artillery, supply, water, ammunition, engineering and repair state from lawful owners")
geo_contract["invariants"].extend([
    "Profile-only strategic sites grant no hidden defensive numbers.",
    "Exact siege resolution requires materialized defense state; missing values fail closed rather than defaulting favorably for any side.",
    "Player and NPC fortifications use the same materialization and conservation rules.",
])
dump("data/runtime/system-contracts/geography_movement.json", geo_contract)

repo_map = load("data/runtime/repository-map.json")
repo_map.get("route_index", {}).pop("character_identity_roster", None)
repo_map["route_index"]["latent_identity_catalog"] = "people"
dump("data/runtime/repository-map.json", repo_map)

people_route = load("data/runtime/repository-routes/people.json")
people_route["routes"].pop("character_identity_roster", None)
people_route["routes"]["latent_identity_catalog"] = {"r": ["data/people/latent-identities.json"], "note": "Source-canon name lookup only. An entry does not assert a current body, office, location, capability or clock; prove current existence before materialization."}
dump("data/runtime/repository-routes/people.json", people_route)

mil_route = load("data/runtime/repository-routes/military.json")
mil_route["routes"]["siege"] = {"domain": "siege", "r": ["state/geo/strategic-fortifications.json"], "note": "Load the causal site entry. Profile-only sites must be materially resolved from lawful owners before exact siege, assault, blockade, breach or repair outcomes."}
dump("data/runtime/repository-routes/military.json", mil_route)

# Directory map: remove directories intentionally eliminated.
dirmap = load("data/runtime/directory-map.json")
for key in ["state/char-roster", "state/life"]:
    dirmap.get("dirs", {}).pop(key, None)
dump("data/runtime/directory-map.json", dirmap)

# ---------------------------------------------------------------------------
# 6. Current-state reference cleanup and conservation.
# ---------------------------------------------------------------------------
removed_people = set(full_roles) | set(lite_roles)
removed_owners = removed_people | {"tang_named_staff_training", "identity_life_course", "appointments_and_command"}

# Owner-index shards are derived. Remove old owners, add new owners, then recompute count/prefix map.
owner_dir = ROOT / "state/index/owners"
shards = {}
for p in owner_dir.glob("*.json"):
    d = json.loads(p.read_text(encoding="utf-8"))
    owners = d.get("owners", {})
    for oid in list(owners):
        if oid in removed_owners:
            owners.pop(oid, None)
    shards[p.name] = d
# Remove empty legacy prefix shards after the deletions.
for name in list(shards):
    if not shards[name].get("owners"):
        (owner_dir / name).unlink()
        shards.pop(name)
# Add role and fortification owners to semantic existing prefixes.
inst = shards.get("institution.json")
check(inst is not None, "institution owner-index shard missing")
inst.setdefault("owners", {})["institution_role_slots"] = "state/app/role-slots.json"
world = shards.get("world.json")
check(world is not None, "world owner-index shard missing")
world.setdefault("owners", {})["world_fortifications"] = "state/geo/strategic-fortifications.json"
for name, d in shards.items():
    dump("state/index/owners/" + name, d)
idx = load("state/index/owners.json")
idx["prefix_index"] = {d["prefix"]: "state/index/owners/" + name for name, d in sorted(shards.items())}
idx["owner_count"] = sum(len(d.get("owners", {})) for d in shards.values())
dump("state/index/owners.json", idx)
check(idx["owner_count"] == 229, f"unexpected owner count after compression: {idx['owner_count']}")

# Remove person IDs from derived coverage/config lists.
for base in [ROOT / "state/time/coverage", ROOT / "data/runtime"]:
    if not base.exists():
        continue
    for p in base.rglob("*.json"):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("data/runtime/templates/"):
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        new = remove_values(d, removed_owners)
        if new != d:
            dump(rel, new)

# Population keeps the same bodies; only the representation of department leadership changes.
pop = load("state/pop/population-tang-manor.json")
text = json.dumps(pop, ensure_ascii=False)
text = text.replace("under Lin Mei's professional medical authority when assigned", "under the occupied Chief Physician role's professional medical authority when assigned")
pop = json.loads(text)
dump("state/pop/population-tang-manor.json", pop)

# Chief Physician instruction now resolves through the institutional role slot.
contracts = load("state/train/training-contracts.json")
for rec in contracts.get("records", []):
    facts = rec.get("facts") or {}
    if facts.get("owner") == "support_sword_manor_medical_camp":
        io = facts.get("instruction_owner")
        if isinstance(io, str):
            facts["instruction_owner"] = io.replace("char_lin_mei", "institution_role_slots#role.house_tang.chief_physician").replace("Lin Mei", "the occupied Chief Physician role")
dump("state/train/training-contracts.json", contracts)

# Merchant network does not need a secret named broker as leader.
merchant = load("state/reg/living-factions/faction-tang-merchant-partners.json")
merchant["faction"]["leadership_ids"] = []
merchant["faction"]["leadership_model"] = "merchant_partner_network coordinated through the occupied House Tang caravan-broker role when available"
dump("state/reg/living-factions/faction-tang-merchant-partners.json", merchant)

# Life-course process remains, but it now settles only real represented people/roles rather than a name catalog.
lifec = load("state/reg/process-contracts/process_canon_life_course_aggregate.json")
lifec["goals"] = ["review births, deaths, aging, family lifecycle, guardianship, succession, and materially represented person/role continuity"]
lifec["standing_orders"] = ["static identity-catalog entries have no body or clock", "settle only current people, family claims, and role incumbents supported by live owners"]
dump("state/reg/process-contracts/process_canon_life_course_aggregate.json", lifec)
life_state = load("state/process-state/process-canon-life-course-aggregate.json")
if isinstance(life_state.get("plan_state"), dict):
    life_state["plan_state"]["current_plan"] = "review births, deaths, aging, succession, and materially represented person/role continuity"
dump("state/process-state/process-canon-life-course-aggregate.json", life_state)

# Replace stale representation label on exact profiles. This is a retrieval state, not a gameplay-history version.
for p in (ROOT / "state/char").glob("*.json"):
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("runtime_status") == "cold_profile_definition":
        d["runtime_status"] = "deferred_exact_profile"
        dump(p.relative_to(ROOT).as_posix(), d, True)

# ---------------------------------------------------------------------------
# 7. Rules/runtime: current semantics only.
# ---------------------------------------------------------------------------
replace_once(
    "RUNTIME.md",
    "Deferred-detail canonical identities are routed representations, not frozen people. Materialize exact/lite state only when causal from current-date/source evidence, settled history, and registered rules. Never back-project future achievements or create free bodies, gear, offices, relationships, information, or capability.",
    "Static identity-catalog entries are source names only and create no current body or personal clock. Current people develop through exact/lite owners, aggregate populations, units, institutions, or anonymous role slots. Materialize a named person only after current existence and one conserved source person/slot are proven; never back-project future achievements or create free bodies, gear, offices, relationships, information, or capability."
)
replace_once(
    "RUNTIME.md",
    "During play, if a real repository/runtime/narration defect becomes apparent, surface one concise `OOC:` note describing the issue and a suggested fix when useful. Do not interrupt ordinary scenes with speculative maintenance commentary, and never persist OOC suggestions as campaign state unless explicitly requested.",
    "During play, diagnose real repository/runtime/narration defects when they become apparent. A behavior-preserving, structurally safe repair covered by the player's standing maintenance authorization may be applied through the normal isolated-branch, validation, stale-base and readback workflow without separate confirmation; mention a concise `OOC:` note only when useful. Standing maintenance authority never permits changing campaign facts, player agency, balance, irreversible content design, or a materially ambiguous design choice. Those remain proposals until explicitly authorized. Maintenance does not advance world time or turn OOC discussion into campaign state."
)

# Repository cookbook route row.
p = ROOT / "REPOSITORY_MAP.md"
t = p.read_text(encoding="utf-8")
t = t.replace("| Deferred-detail canon identity | `state/char-roster/index.json` -> one authoritative initial shard | materialize only when causally active |", "| Source-canon identity name | `data/people/latent-identities.json` | name/source lookup only; prove a current body before materialization |")
p.write_text(t, encoding="utf-8")

# Rewrite the deferred-identity portion of world.md in one bounded block.
p = ROOT / "rules/world.md"
t = p.read_text(encoding="utf-8")
start = t.index("## Deferred-detail canonical identities")
end = t.index("## Vacancy sequence", start)
new_block = '''## Source identities and current people\n\n`data/people/latent-identities.json` is a static source-name catalog. A catalog entry does not assert that the named person currently exists, occupies an office, has a location, owns equipment, knows anything, or receives development. It therefore has no personal clock.\n\nCurrent people are represented only when the world requires them: exact characters, individual-lite people, anonymous role-slot incumbents, or aggregate population/unit members. An anonymous role-slot incumbent ages, develops, becomes unavailable, retires, dies, or triggers succession only through the owning institution/process. The slot stores functional continuity, not a secret biography.\n\nA source-canon name may bind to a current person only after current existence, source population/unit/role, age or life stage when needed, and one conserved body are established from live authority. Materialization imports only supported source history and creates no free capability, office, equipment, knowledge, relationship, achievement or survival.\n\n## Development parity\n\nEvery current person develops through real activity. Exact/lite people use their registered activity/process coverage. Aggregate people inherit only the development, health exposure and career movement earned by their population, unit, institution or role process. Representation compression never grants an advantage.\n\n## Scheduler rule\n\nStatic identity-catalog names have no scheduler entries. Anonymous role-slot incumbents settle with their owning institution/process. Exact personal clocks exist only when exact personal causality requires them.\n\n'''
t = t[:start] + new_block + t[end:]
t = t.replace("Every full capability-profile identity, active exact external actor, and deferred-detail routed identity retains one canonical display name. Whenever the identity is legitimately referenced, reported, encountered, or materialized, narration uses that canonical name. Deferred-detail representation suppresses irrelevant loading, not the name.", "Every materialized named person retains one canonical display name. A static source-catalog name is used only after the identity is lawfully bound to a current person; catalog presence alone never creates that person.")
p.write_text(t, encoding="utf-8")

# Character rules: replace representation-specific sections while keeping materialization mechanics.
p = ROOT / "rules/characters.md"
t = p.read_text(encoding="utf-8")
t = t.replace("The human kernel supports compact settlement for deferred-detail routed identities and aggregate populations.", "The human kernel supports compact settlement for anonymous role-slot incumbents and aggregate populations.")
t = t.replace("A deferred-detail profile is not expanded merely for storage or audit display.", "A static source-identity catalog entry has no capability profile to expand.")
t = t.replace("Canonical deferred-detail routed identities retain their canonical name at every representation depth.", "A source-canon name is preserved once it is lawfully bound to a current person.")
t = t.replace("Generated anonymous people receive a personal name only when lawful materialization creates a persistent individual; canonical routed identities retain their canonical name.", "Generated anonymous people receive a personal name only when lawful materialization creates a persistent individual; a source-canon name may be bound only after current existence is proven.")
start = t.index("## Runtime tiers")
end = t.index("## Ordinary-person naming", start)
new = '''## Runtime tiers\n\n- Full exact character: complete independently simulated narrative/mechanical actor with exact body, capability, knowledge, relationships, goals and activity when causally required.\n- Individual-lite person: persistent named individual with exact body/capability/equipment/service state and compact narrative state.\n- Anonymous role-slot incumbent: one real current institutional occupant represented only by age/availability, coarse functional capability, service-development credit and succession state; it owns no secret name or private character sheet.\n- Aggregate person: ordinary population/manpower member represented only through a population, institution or unit owner.\n- Source identity catalog entry: static canonical name/source hint only; it is not a current person representation.\n\n## Separation of source names and runtime state\n\nA source identity catalog never asserts current location, health, inventory, office, travel, knowledge, capability or existence. Exact/lite runtime facts require a current person owner. Role slots own only institutional continuity and must materialize an incumbent before exact personal agency, combat, relationships, private inventory, or individual opposed checks are resolved.\n\n## Identity activation\n\nA source-canon identity cannot act merely because its name exists in the catalog. Activation first proves current existence and resolves a lawful source population/unit/role, age or life stage when causal, location, health, authority, equipment, knowledge and current purpose. Materialization then creates one exact/lite owner and conserves the same real body exactly once. Missing inputs fail closed.\n\n## Context routing\n\nStartup loads no source identity catalog or external profile collection. Known materialized IDs use direct owners. A source-name lookup loads only `data/people/latent-identities.json`, then the one causal source owner if activation is required. Large scenes use deterministic sector, formation, authority or owner batches sized to available context. Batch size may change; semantic coverage may not.\n\n## Anti-bloat invariants\n\n- no complete name lists for anonymous populations or units;\n- no campaign-original exact quota filler;\n- no generic random state, age, role, office, location, health, equipment, knowledge, goal or elite skill;\n- static source identities have no personal periodic clocks or mutable profile seeds;\n- anonymous role slots carry no secret name, personality, biography, private inventory, relationship graph or exact personal skill sheet;\n- no profile definition is treated as a living runtime body without current-existence evidence.\n\n'''
t = t[:start] + new + t[end:]
t = t.replace("Every full capability-profile identity, active exact external actor, and deferred-detail routed named identity retains one canonical display name. Whenever the identity is legitimately referenced, reported, encountered, or materialized, narration uses that canonical name. Deferred-detail representation suppresses irrelevant loading, not the name.", "Every materialized named person retains one canonical display name. A source-canon catalog name is used only after the identity is lawfully bound to a current person.")
t = t.replace("A deferred-detail full capability profile is a capability definition, not an automatic 245 BCE body state. On activation, reconstruct age-stage, affiliation, office, health, equipment, location, knowledge, relationships, and current capability through the source unit and explicit initial evidence. Future achievements, future ranks, and later-series peak values cannot be imported as initial facts.", "A source-canon catalog entry is not an automatic 245 BCE body state. On activation, reconstruct only state supported by the current source owner and explicit initial evidence. Future achievements, future ranks and later-series peak values cannot be imported as initial facts.")
t = t.replace("This module creates a recurring exact canonical actor or a full-sheet person from a real unit or routed identity.", "This module creates a recurring exact canonical actor or a full-sheet person from a real unit, population, role incumbent, or source identity whose current existence has been proven.")
t = t.replace("Failure at any step leaves the identity deferred-detail/routed and produces no acting exact character.", "Failure at any step produces no acting exact character and leaves the source identity unbound or the anonymous source person unmaterialized.")
p.write_text(t, encoding="utf-8")

p = ROOT / "rules/character-runtime.md"
t = p.read_text(encoding="utf-8")
start = t.index("## Deferred-detail routed identities")
t = t[:start] + '''## Source identity catalog\n\nA static source identity is a canonical name/source hint, not a current actor. Do not load or simulate it during ordinary interaction. If the name becomes causally relevant and no current person owner exists, use `rules/characters.md` to prove current existence and materialize from one lawful source person/role without importing future achievements or later-series state.\n'''
p.write_text(t, encoding="utf-8")

p = ROOT / "rules/states.md"
t = p.read_text(encoding="utf-8")
t = t.replace("Deferred-detail named identities do not create scheduler load.", "Static source-identity names create no scheduler load. Current anonymous role incumbents settle through their institution/state process rather than private character clocks.")
t = t.replace("A deferred-detail routed named identity does not create an additional body merely because it has a roster record. When materialization maps that identity to an aggregate source unit/population slot, deduct exactly one source person at activation and import the source owner accumulated development and health history exactly once. If the identity already has an independently counted exact/lite body owner, never deduct another body.", "A static source-canon name creates no body. When current evidence binds that identity to an aggregate source unit, population or role slot, materialization conserves exactly one real source person and imports supported accumulated development and health history once. An already materialized exact/lite person is never deducted again.")
t = t.replace("A routed identity cannot materialize until one real source personnel claim is resolved.", "A source identity cannot materialize until one real current source-person claim is resolved.")
p.write_text(t, encoding="utf-8")

# Doctrine rule: state the current rule without release-history comparison.
p = ROOT / "rules/doctrine.md"
t = p.read_text(encoding="utf-8")
t = t.replace("A doctrine record represents a current durable military standard under a stable semantic doctrine ID. Doctrine records carry doctrine facts, not release numbers. A materially different durable standard uses a meaningful semantic doctrine ID; never append a software-style version suffix merely because doctrine changed.", "A doctrine record represents one current durable military standard under a stable semantic doctrine ID. A materially different durable standard uses a distinct meaningful semantic doctrine ID.")
p.write_text(t, encoding="utf-8")

# Siege parity rule.
p = ROOT / "rules/siege.md"
t = p.read_text(encoding="utf-8")
append = '''\n## Strategic-site materialization\n\nEvery consequential fortified location uses `state/geo/strategic-fortifications.json`. A profile-only site establishes only its strategic class and controller scope. It grants no hidden wall dimensions, garrison strength, artillery, stores, ammunition, water, engineer capacity or repair stock.\n\nBefore resolving an exact siege, assault, blockade, breach, starvation clock, artillery exchange or repair action, materialize the causal site's defense state from current geography plus conserved controller forces, inventories, supply sources and engineering capacity. If required state cannot be lawfully resolved, the exact siege outcome fails closed.\n\nTang Manor, state capitals, passes, fortress cities and NPC strongholds use the same requirements. Representation compression may reduce detail only while no exact outcome depends on that detail; it never improves defense, supply, survival or repair.\n'''
if "## Strategic-site materialization" not in t:
    t = t.rstrip() + "\n" + append
p.write_text(t, encoding="utf-8")

# ---------------------------------------------------------------------------
# 8. Validator/router maintenance.
# ---------------------------------------------------------------------------
# Game detection must not depend on an obsolete directory existing.
for rel in ["tools/test_semantics.py", "tools/test_routing.py"]:
    p = ROOT / rel
    t = p.read_text(encoding="utf-8")
    t = t.replace("GAME='sword' if (R/'state/char-roster').exists() else 'shinobi'", "GAME='sword' if (json.loads((R/'state/meta.json').read_text(encoding='utf-8')).get('game')=='sword_and_banners' else 'shinobi'")
    p.write_text(t, encoding="utf-8")

# Replace roster-specific audit blocks with static-catalog checks.
p = ROOT / "tools/audit.py"
t = p.read_text(encoding="utf-8")
start = t.index("# Canonical deferred-detail identity roster:")
end = t.index("# Troop pools are accounting objects", start)
new = '''# Static source-identity catalog owns names only and creates no current bodies.\n_cat=rj(ROOT/'data/people/latent-identities.json') or {}\nif _cat.get('schema')!='latent-identity-catalog':err('latent_identity_catalog_missing')\n_ids=_cat.get('identities',{})\nif len(_ids)!=int(_cat.get('count',-1)):err(f'latent_identity_catalog_count:{len(_ids)}:{_cat.get("count")}')\nfor _cid,_x in _ids.items():\n if not isinstance(_x,dict) or not _x.get('name'):err(f'latent_identity_name_missing:{_cid}')\n if set(_x)-{'name','source_hint'}:err(f'latent_identity_runtime_bloat:{_cid}:{sorted(set(_x)-{"name","source_hint"})}')\nif (ROOT/'state/char-roster').exists():err('mutable_character_roster_reintroduced')\n\n'''
t = t[:start] + new + t[end:]
start = t.index("# Canonical identity life-course route remains")
end = t.index("# Command-person direct records", start)
t = t[:start] + "# Source-name catalogs have no life-course owner; only current people/roles receive process coverage.\nif (ROOT/'state/life/identity-life-course.json').exists():err('obsolete_identity_life_course_owner_present')\n\n" + t[end:]
p.write_text(t, encoding="utf-8")

# Unit-model test no longer owns character-catalog validation.
p = ROOT / "tools/test_unit_model.py"
t = p.read_text(encoding="utf-8")
start = t.index("    roster=rj('state/char-roster/index.json')")
end = t.index("if errs:", start)
t = t[:start] + "    if (R/'state/char-roster').exists():err('mutable_character_roster_present')\n    if not (R/'data/people/latent-identities.json').exists():err('latent_identity_catalog_missing')\n" + t[end:]
p.write_text(t, encoding="utf-8")

# Dedicated invariant test for the new scalable representation.
oos_test = '''from pathlib import Path\nimport json,sys\nR=Path(__file__).resolve().parents[1]\nerrs=[]\ndef fail(x): errs.append(x)\ndef rj(rel): return json.loads((R/rel).read_text(encoding="utf-8"))\ncat=rj("data/people/latent-identities.json")\nif cat.get("schema")!="latent-identity-catalog": fail("catalog_schema")\nids=cat.get("identities",{})\nif len(ids)!=cat.get("count"): fail("catalog_count")\nif (R/"state/char-roster").exists(): fail("mutable_roster_present")\nfor cid,rec in ids.items():\n    if set(rec)-{"name","source_hint"}: fail("catalog_runtime_bloat:"+cid)\n    if not rec.get("name"): fail("catalog_name:"+cid)\nroles=rj("state/app/role-slots.json")\nif roles.get("schema")!="role-slot-registry": fail("role_schema")\nrequired={"role.house_tang.warehouse_granary_chief","role.house_tang.forge_master","role.house_tang.chief_administrator","role.house_tang.stable_remount_master","role.house_tang.agricultural_director","role.house_tang.chief_physician","role.house_tang.estate_accountant","role.house_tang.armorer","role.house_tang.senior_scribe","role.house_tang.intelligence_contact_manager","role.house_tang.physician_assistant","role.house_tang.caravan_broker","role.house_tang.works_planner","role.house_tang.stable_deputy","role.sword_manor.escort_captain","role.sword_manor.senior_instructor"}\nif set(roles.get("roles",{}))!=required: fail("role_set")\nfor rid,slot in roles.get("roles",{}).items():\n    inc=slot.get("incumbent")\n    if inc:\n        raw=json.dumps(inc).lower()\n        for bad in ("name","personality","biography","relationship","inventory","birth_date","skills"):\n            if bad in inc: fail(f"role_secret_person_state:{rid}:{bad}")\n        if inc.get("representation")=="anonymous_role_incumbent" and inc.get("materialized_character_id") is not None: fail("anonymous_role_bound:"+rid)\nold=["state/char/gu-wen.json","state/char/han-qiao.json","state/char/lu-zhen.json","state/char/ma-xun.json","state/char/tian-yu.json","state/char/lin-mei.json","state/person/staff/staff-tang-chen_yu.json","state/person/staff/staff-tang-gao_fen.json","state/person/staff/staff-tang-he_mei.json","state/person/staff/staff-tang-liu_fang.json","state/person/staff/staff-tang-luo_min.json","state/person/staff/staff-tang-sun_qiao.json","state/person/staff/staff-tang-xie_an.json","state/person/staff/staff-tang-zhang_ren.json","state/prog/tang-named-staff-training.json","state/life/identity-life-course.json"]\nfor rel in old:\n    if (R/rel).exists(): fail("obsolete_owner:"+rel)\nfor p in (R/"state/char").glob("*.json"):\n    if rj(p.relative_to(R).as_posix()).get("runtime_status")=="cold_profile_definition": fail("cold_runtime_status:"+p.name)\nfort=rj("state/geo/strategic-fortifications.json")\nif fort.get("schema")!="strategic-fortification-registry": fail("fort_schema")\nfor loc in ("loc_kanyou","loc_kankoku_pass","loc_gyou"):\n    s=fort.get("sites",{}).get(loc)\n    if not s or s.get("materialization_state")!="profile_only": fail("fort_profile:"+loc)\n    if "defense_state" in (s or {}): fail("invented_fort_detail:"+loc)\nif "materialize" not in (R/"rules/siege.md").read_text(encoding="utf-8").lower(): fail("siege_materialization_rule")\nif errs:\n    print("OFFSCREEN SCALING TEST FAILED")\n    for e in errs: print("-",e)\n    sys.exit(1)\nprint("OFFSCREEN SCALING TEST OK")\nprint(f"source_names={len(ids)} live_role_slots={sum(1 for s in roles['roles'].values() if s.get('status')=='occupied')} capacity_role_groups={sum(1 for s in roles['roles'].values() if s.get('status')=='capacity_only')} strategic_profiles={len(fort['sites'])}")\n'''
(ROOT / "tools/test_offscreen_scaling.py").write_text(oos_test, encoding="utf-8")
runv = ROOT / "tools/run_validators.py"
t = runv.read_text(encoding="utf-8")
anchor = '    "tools/test_population_sources.py",\n'
check(anchor in t, "validator-list anchor missing")
t = t.replace(anchor, anchor + '    "tools/test_offscreen_scaling.py",\n')
runv.write_text(t, encoding="utf-8")

# Drop stale 'cold structural contract' wording from templates without changing contracts.
for p in (ROOT / "data/runtime/templates").glob("*.json"):
    text = p.read_text(encoding="utf-8")
    if "cold structural contract" in text:
        p.write_text(text.replace("cold structural contract", "registered structural contract"), encoding="utf-8")

# ---------------------------------------------------------------------------
# 9. Meta revision changes once; world time does not move.
# ---------------------------------------------------------------------------
meta["revision"] = NEW_REVISION
dump("state/meta.json", meta)

# ---------------------------------------------------------------------------
# 10. Validate final candidate state, then remove one-shot maintenance helpers.
# ---------------------------------------------------------------------------
subprocess.run(["python", "tools/run_validators.py"], cwd=ROOT, check=True)

# Ensure the intended compression happened.
check(not (ROOT / "state/char-roster").exists(), "roster directory still exists")
check(len(list((ROOT / "state/person/staff").glob("*.json"))) == 18, "military staff count is not 18 after civilian-role compression")
check(len(list((ROOT / "state/char").glob("*.json"))) == 73, "full NPC character count is not 73 after role compression")
check(load("state/meta.json")["time"] == WORLD_TIME, "maintenance advanced world time")
check(load("state/meta.json")["revision"] == NEW_REVISION, "maintenance revision mismatch")

# Remove temporary audit/migration helpers and restore normal read-only CI.
for rel in ["tools/audit_offscreen_scaling.py", "tools/audit_roster_refs.py", "tools/migrate_offscreen_scaling.py"]:
    remove(rel)
(ROOT / ".github/workflows/audit.yml").write_text("""name: audit\non: [push, pull_request]\njobs:\n  audit:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n      - run: pip install jsonschema\n      - name: Run full validator stack\n        run: python tools/run_validators.py\n""", encoding="utf-8")

subprocess.run(["python", "tools/run_validators.py"], cwd=ROOT, check=True)

# Net-diff hygiene: temporary helpers must not survive.
status = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True)
check("audit_offscreen_scaling.py" not in status and "audit_roster_refs.py" not in status and "migrate_offscreen_scaling.py" not in status, "temporary helper survived net diff")

subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=ROOT, check=True)
subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=ROOT, check=True)
subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
subprocess.run(["git", "commit", "-m", "Scale latent people and institutional roles"], cwd=ROOT, check=True)
subprocess.run(["git", "push", "origin", "HEAD:maintenance/active-rule-dedup-r18"], cwd=ROOT, check=True)
print("MIGRATION_COMMITTED_AND_PUSHED")
