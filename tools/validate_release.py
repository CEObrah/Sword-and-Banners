#!/usr/bin/env python3
"""Current structural and conservation validator for Sword & Banners."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import validators

ROOT = Path(__file__).resolve().parents[1]
FAILURES: list[str] = []
CHECKS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"PASS {name}")
    else:
        FAILURES.append(name + (f": {detail}" if detail else ""))
        print(f"FAIL {name}" + (f" -- {detail}" if detail else ""))


def j(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def all_json(root: Path):
    for path in root.rglob("*.json"):
        if any(part in {".git", ".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        yield path


# Release shape: one current authority tree and no runtime-generated residue.
check("single_current_tree", not (ROOT / "archive").exists())
check("no_runtime_logs", not (ROOT / "log").exists())
check("owner_index_present", (ROOT / "state/index/owner-index.json").is_file())
check("relationship_authority_present", (ROOT / "state/relationships.json").is_file())
check("economy_authority_present", (ROOT / "game/data/mechanics/economy.json").is_file())
check("release_workflow_present", (ROOT / ".github/workflows/release.yml").is_file())

# Schema registry is complete for every schema-bearing object in active game/state JSON.
registry=j("game/schemas/registry.json")
schema_validators={}
for schema_id, filename in registry.items():
    document=j("game/schemas/"+filename)
    cls=validators.validator_for(document); cls.check_schema(document); schema_validators[schema_id]=cls(document)
unknown=[]; invalid=[]
for base in (ROOT/"game", ROOT/"state"):
    for path in all_json(base):
        value=json.loads(path.read_text(encoding="utf-8"))
        stack=[value]
        while stack:
            cur=stack.pop()
            if isinstance(cur,dict):
                sid=cur.get("schema")
                if isinstance(sid,str):
                    validator=schema_validators.get(sid)
                    if validator is None:
                        unknown.append((path.relative_to(ROOT).as_posix(),sid))
                    else:
                        errs=list(validator.iter_errors(cur))
                        if errs:
                            invalid.append((path.relative_to(ROOT).as_posix(),sid,errs[0].message))
                stack.extend(cur.values())
            elif isinstance(cur,list):
                stack.extend(cur)
check("all_active_schemas_registered", not unknown, str(unknown[:8]))
check("all_active_schema_objects_validate", not invalid, str(invalid[:5]))

# Mutable owner routing. Exact logical owners may live inside compact JSON shards
# and are addressed through JSON Pointer fragments. Validate both the base file
# and the pointed record so compact person-lite storage remains first-class.
def _owner_route_exists(route: object) -> bool:
    text = str(route)
    base, sep, fragment = text.partition("#")
    path = ROOT / base
    if not path.is_file():
        return False
    if not sep or not fragment:
        return True
    if not fragment.startswith("/"):
        return False
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        for raw in fragment[1:].split("/"):
            token = raw.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict):
                current = current[token]
            elif isinstance(current, list):
                current = current[int(token)]
            else:
                return False
        return True
    except (KeyError, IndexError, ValueError, TypeError, json.JSONDecodeError):
        return False

owner_index=j("state/index/owner-index.json")
owners=owner_index.get("owners",{})
broken=[(k,v) for k,v in owners.items() if not _owner_route_exists(v)]
missing=[]
for path in all_json(ROOT/"state"):
    value=json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value,dict):
        oid=value.get("owner_id")
        if isinstance(oid,str) and oid and oid not in owners:
            missing.append((oid,path.relative_to(ROOT).as_posix()))
check("owner_routes_exist", not broken, str(broken[:8]))
check("all_top_level_owner_ids_routed", not missing, str(missing[:8]))

# Command hierarchy is a zero-body routing layer. Every saved command-group
# file must be discoverable through the index, every direct formation may have
# only one primary parent, and exact commander/deputy references must resolve.
command_group_dir = ROOT / "state/cmd/command-groups"
command_group_index = j("state/cmd/command-groups/index.json")
saved_command_groups = {}
command_group_bad_people = []
command_group_formation_parents = {}
for path in sorted(command_group_dir.glob("cmdgrp*.json")):
    doc = json.loads(path.read_text(encoding="utf-8"))
    ref = doc.get("id")
    if not isinstance(ref, str) or not ref.startswith("cmdgrp."):
        continue
    saved_command_groups[ref] = path.relative_to(ROOT).as_posix()
    for key in ("commander_ref", "deputy_ref"):
        person_ref = doc.get(key)
        if isinstance(person_ref, str) and person_ref and person_ref not in owners:
            command_group_bad_people.append((ref, key, person_ref))
    for unit in doc.get("units", []):
        if not isinstance(unit, dict) or unit.get("kind") != "formation" or not isinstance(unit.get("ref"), str):
            continue
        formation_ref = unit["ref"]
        prior = command_group_formation_parents.get(formation_ref)
        if prior not in {None, ref}:
            command_group_formation_parents[formation_ref] = f"DUPLICATE:{prior}|{ref}"
        else:
            command_group_formation_parents[formation_ref] = ref
indexed_refs = set(command_group_index.get("refs", []))
indexed_formations = command_group_index.get("primary_formation_group", {})
command_group_index_errors = []
if indexed_refs != set(saved_command_groups):
    command_group_index_errors.append(("refs", sorted(set(saved_command_groups) - indexed_refs), sorted(indexed_refs - set(saved_command_groups))))
if int(command_group_index.get("count", -1)) != len(saved_command_groups):
    command_group_index_errors.append(("count", command_group_index.get("count"), len(saved_command_groups)))
for formation_ref, group_ref in command_group_formation_parents.items():
    if group_ref.startswith("DUPLICATE:") or indexed_formations.get(formation_ref) != group_ref:
        command_group_index_errors.append((formation_ref, indexed_formations.get(formation_ref), group_ref))
check("command_group_index_complete", not command_group_index_errors, str(command_group_index_errors[:8]))
check("command_group_exact_leaders_resolve", not command_group_bad_people, str(command_group_bad_people[:8]))

# Current transaction state and campaign chronology. Gameplay state carries one
# campaign revision only; mutable owners do not carry independent revision counters in the
# current gameplay tree. Protocol/schema identities live in their own authorities.
meta=j("state/meta.json")
check("campaign_revision_valid", isinstance(meta.get("revision"), int) and meta.get("revision") >= 0)
check("world_time_present", isinstance(meta.get("time"),str) and "BCE" in meta["time"])
state_versions=[]
state_revisions=[]
for path in all_json(ROOT/"state"):
    value=json.loads(path.read_text(encoding="utf-8"))
    stack=[((),value)]
    while stack:
        key_path,cur=stack.pop()
        if isinstance(cur,dict):
            for key,child in cur.items():
                child_path=key_path+(str(key),)
                if key == "version":
                    state_versions.append((path.relative_to(ROOT).as_posix(), ".".join(child_path)))
                if key == "revision":
                    state_revisions.append((path.relative_to(ROOT).as_posix(), ".".join(child_path)))
                stack.append((child_path,child))
        elif isinstance(cur,list):
            for idx,child in enumerate(cur):
                stack.append((key_path+(str(idx),),child))
check("state_gameplay_tree_has_no_version_fields", not state_versions, str(state_versions[:8]))
check("state_has_single_campaign_revision", state_revisions == [("state/meta.json", "revision")], str(state_revisions[:8]))

# A clean gameplay tree stores current semantic truth, not transaction/request ledgers
# or one-off release scaffolding. Normal post-reset receipts remain in the private
# transaction layer, never inside current campaign state.
state_request_ids=[]
state_receipt_refs=[]
state_release_scaffolding=[]
for path in all_json(ROOT/"state"):
    value=json.loads(path.read_text(encoding="utf-8"))
    stack=[((),value)]
    while stack:
        key_path,cur=stack.pop()
        if isinstance(cur,dict):
            for key,child in cur.items():
                child_path=key_path+(str(key),)
                if key == "request_id":
                    state_request_ids.append((path.relative_to(ROOT).as_posix(), ".".join(child_path)))
                if key in {"accounting_repairs", "stable_four_month_fixture", "standing_training_repair_provenance"} or key.endswith("_category_removed"):
                    state_release_scaffolding.append((path.relative_to(ROOT).as_posix(), ".".join(child_path)))
                stack.append((child_path,child))
        elif isinstance(cur,list):
            for idx,child in enumerate(cur):
                stack.append((key_path+(str(idx),),child))
        elif isinstance(cur,str) and (cur.startswith("tx.") or cur.startswith("receipt.")):
            state_receipt_refs.append((path.relative_to(ROOT).as_posix(), ".".join(key_path), cur))
check("state_has_no_request_id_scaffolding", not state_request_ids, str(state_request_ids[:8]))
check("state_has_no_historical_receipt_chains", not state_receipt_refs, str(state_receipt_refs[:8]))
check("state_has_no_release_scaffolding", not state_release_scaffolding, str(state_release_scaffolding[:8]))
check("no_state_migration_tree", not (ROOT/"state/migrations").exists())

invalidations=j("runtime/contracts/transaction-invalidations.json")
check("transaction_invalidation_registry_valid", isinstance(invalidations, dict))

# World-arc priority queues are current work, not historical ledgers. Every action
# ref is unique inside its exact owner, and every pending row must have a live
# scheduler host. Settled rows may remain as bounded semantic actor history.
runtime_state=j("state/runtime.json")
active_priority_refs={
    str(host.get("action_ref"))
    for host in runtime_state.get("hosts",{}).values()
    if isinstance(host,dict)
    and host.get("kind")=="world_arc_priority"
    and host.get("next_due") is not None
    and isinstance(host.get("action_ref"),str)
}
priority_duplicates=[]; orphan_pending=[]
for path in all_json(ROOT/"state"):
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        continue
    queues=[]
    if isinstance(value.get("world_arc_priorities"),list):
        queues.append(("world_arc_priorities",value["world_arc_priorities"]))
    runtime=value.get("runtime") if isinstance(value.get("runtime"),dict) else None
    if runtime and isinstance(runtime.get("autonomous_action_attempts"),list):
        queues.append(("runtime.autonomous_action_attempts",runtime["autonomous_action_attempts"]))
    for queue_name,rows in queues:
        seen=set()
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get("arc_ref"),str):
                continue
            action_ref=row.get("action_ref")
            if isinstance(action_ref,str):
                if action_ref in seen:
                    priority_duplicates.append((path.relative_to(ROOT).as_posix(),queue_name,action_ref))
                seen.add(action_ref)
                if row.get("status") in {"queued","attempted","queued_for_institutional_review"} and action_ref not in active_priority_refs:
                    orphan_pending.append((path.relative_to(ROOT).as_posix(),queue_name,action_ref,row.get("status")))
check("world_arc_priority_action_refs_unique", not priority_duplicates, str(priority_duplicates[:8]))
check("world_arc_pending_work_has_live_host", not orphan_pending, str(orphan_pending[:8]))

# Force/population conservation and theater liveness.
for state in ("qin","zhao","chu","wei","han","yan","qi"):
    pop=j(f"state/population/{state}.json")
    check(f"population_conserved:{state}", sum(int(v) for v in pop.get("strata",{}).values()) == int(pop.get("population_total",-1)))
    force=j(f"state/forces/state-{state}.json")
    available=sum(int(v) for v in force.get("available_by_role",{}).values())
    allocated=sum(int(v.get("personnel",0)) if isinstance(v,dict) else int(v) for v in force.get("allocated_to_formations",{}).values())
    assignments=force.get("materialized_assignments",{})
    internal_refs=set(assignments) if isinstance(assignments,dict) else set()
    materialized=sum(
        int(v.get("personnel",1)) if isinstance(v,dict) else int(v)
        for ref,v in force.get("materialized_people",{}).items() if ref not in internal_refs
    )
    check(f"force_conserved:{state}", available+allocated+materialized == int(force.get("headcount",-1)))
    mounts=j(f"state/mounts/{state}.json")
    check(f"mount_pool_conserved:{state}", sum(int(v) for v in mounts.get("types",{}).values()) == int(mounts.get("total",-1)))

for theater in j("game/data/world/autonomous-theaters.json").get("theaters",[]):
    refs=list(theater.get("formation_refs",{}).values())
    check(f"theater_formations_routed:{theater.get('theater_ref')}", all(ref in owners for ref in refs))


# Routed-world geography/conservation authority.
try:
    from validate_world_geography import validate as validate_world_geography
    geography_errors = validate_world_geography(ROOT)
except Exception as exc:
    geography_errors = [f"validator raised {type(exc).__name__}: {exc}"]
check("world_geography_authority_valid", not geography_errors, str(geography_errors[:8]))

try:
    from validate_mercenary_ecology import validate as validate_mercenary_ecology
    mercenary_errors = validate_mercenary_ecology(ROOT)
except Exception as exc:
    mercenary_errors = [f"validator raised {type(exc).__name__}: {exc}"]
check("mercenary_ecology_conserved", not mercenary_errors, str(mercenary_errors[:8]))

# Tang Champion and personal-retinue representation invariants.
champ=j("state/formations/tang-champions-first.json")
check("single_tang_champion_formation", champ.get("personnel")==500 and not (ROOT/"state/formations/tang-champions-second.json").exists())
check("champion_material_owner", champ.get("owner_force_ref")=="force_house_tang" and champ.get("administrative_owner")=="house_tang")
check("champion_assignment_authority", champ.get("command_authority")=="char_tang_wei" and champ.get("commander_ref")=="char_duan_jin" and champ.get("deputy_ref")=="char_shen_rui")
check("champion_tang_horses", champ.get("mounts")=={"horse_tang_heavy_war":500})
check("no_champion_individual_roster", not (ROOT/"state/personnel/house-tang-champions.json").exists())
pforce=j("state/pforce/wei.json")
check("champions_assigned_not_owned", "formation_tang_champions_first" in pforce.get("assigned_formations",[]) and not pforce.get("permanent_formations"))
policy_text = json.dumps(pforce.get("policy",{})).lower()
check("personal_recruits_cohort_first_policy", "cohort" in policy_text and "selective" in policy_text)
check("personal_recruit_campaign_runtime_present", (ROOT/"runtime/sword_runtime/recruitment_campaigns.py").is_file())

# Current House Tang / Sword Manor establishment invariants.
def _conserved_role(force: dict, role: str) -> int:
    total = int(force.get("available_by_role", {}).get(role, 0))
    for row in force.get("allocated_to_formations", {}).values():
        if not isinstance(row, dict):
            continue
        if row.get("role") == role:
            total += int(row.get("personnel", 0))
            continue
        composition = row.get("composition", {})
        if isinstance(composition, dict):
            total += int(composition.get(role, 0))
    establishment = force.get("officer_establishment", {})
    rank_commands = establishment.get("rank_commands", {}) if isinstance(establishment, dict) else {}
    row = rank_commands.get(role) if isinstance(rank_commands, dict) else None
    if not isinstance(row, dict) and isinstance(establishment, dict):
        row = establishment.get(role)
    refs = set()
    if isinstance(row, dict):
        for key in ("commanders_1000", "commanders_500"):
            refs.update(str(ref) for ref in row.get(key, []) if isinstance(ref, str))
    for person_ref, assignment in force.get("materialized_assignments", {}).items():
        if person_ref in refs and isinstance(assignment, dict) and assignment.get("role") == role and assignment.get("formation_ref"):
            refs.discard(person_ref)
    return total + len(refs)

house_force=j("state/forces/house-tang.json")
house_caps={"house_guard":18000,"guardian_cavalry":8000,"tang_champion":4000}
check("house_tang_establishment_conserved",
      house_force.get("headcount")==30000
      and house_force.get("authorized_strength")==sum(house_caps.values())
      and house_force.get("authorized_by_role")==house_caps
      and all(_conserved_role(house_force, role)==cap for role,cap in house_caps.items()))
sword_force=j("state/forces/sword-manor.json")
sword_counts={role:_conserved_role(sword_force, role) for role in ("trainee","junior_disciple","general_disciple","senior_disciple")}
check("sword_manor_physical_capacity_and_conservation",
      sword_force.get("headcount")==sum(sword_counts.values())==30060
      and sword_force.get("authorized_strength")==30060
      and sword_force.get("authorized_by_role")==sword_counts
      and sword_counts=={"trainee":20060,"junior_disciple":5000,"general_disciple":3500,"senior_disciple":1500}
      and isinstance(sword_force.get("capacity_policy"),dict)
      and sword_force.get("capacity_policy",{}).get("fixed_personnel_cap") is None)
check("wei_house_guard_3000_present", j("state/formations/tang-wei-house-guard.json").get("personnel")==3000)
bastion_expected={
    "bastion-iron-rampart.json":75000,
    "bastion-red-crane.json":16000,
    "bastion-white-lantern.json":10000,
    "bastion-deep-earth.json":9000,
}
bastion_total=sum(int(j("state/forces/"+path).get("headcount",0)) for path in bastion_expected)
check("house_tang_four_bastion_corps_110000",
      bastion_total==110000
      and all(int(j("state/forces/"+path).get("headcount",0))==heads for path,heads in bastion_expected.items()))
# Mixed formations own only fighting strength. Top commander/deputy remain separate exact people.
mixed_bastions=[]
for path in (ROOT/"state/formations").glob("bastion-*.json"):
    formation=json.loads(path.read_text(encoding="utf-8")); comp=formation.get("composition",{})
    mixed_bastions.append(isinstance(comp,dict) and len([v for v in comp.values() if int(v)>0])>=2 and sum(int(v) for v in comp.values())==int(formation.get("personnel",0)) and formation.get("command_structure",{}).get("unit_command",{}).get("external_to_fighting_establishment") is True)
check("bastion_mixed_role_and_external_top_command", len(mixed_bastions)==26 and all(mixed_bastions))

# Runtime safety/liveness markers.
engine=(ROOT/"runtime/sword_runtime/engine.py").read_text(encoding="utf-8")
check("no_unrepresentable_never_sentinel", "9999-BCE" not in engine)
rt=j("state/runtime.json")
check("zero_global_scan_metrics", all(int(rt.get("metrics",{}).get(k,0))==0 for k in ("global_person_scans","global_faction_scans","global_force_scans","global_house_scans")))
check("vitality_diagnostic_present", (ROOT/"runtime/sword_runtime/vitality.py").is_file() and "playability_vitality" in (ROOT/"runtime/sword_runtime/api/operations.py").read_text(encoding="utf-8"))

# Skill and routing essentials.
skill=ROOT/"plugins/sword-and-banners/skills/sword-and-banners-game-master"
check("skill_entrypoint_present", (skill/"SKILL.md").is_file())
check("skill_metadata_present", (skill/"agents/openai.yaml").is_file())
repo_map=j("runtime/contracts/repository-map.json")
check("machine_router_present", isinstance(repo_map, dict) and bool(repo_map))

if FAILURES:
    print(f"\nvalidate_release: FAIL ({len(FAILURES)}/{CHECKS})")
    for failure in FAILURES: print(" - "+failure)
    raise SystemExit(1)
print(f"\nvalidate_release: PASS ({CHECKS} checks)")
