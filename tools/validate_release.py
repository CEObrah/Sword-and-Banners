#!/usr/bin/env python3
"""Current structural and conservation validator for Sword & Banners."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import validators

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.progression_integrity import exact_activity_shortfall
from sword_runtime.training_rates import resolved_activity_regimen, verified_activity_hours_per_cycle
from sword_runtime.officer_cadre import _target_billets
from sword_runtime.scheduler_frontier import RECONCILE_HOST_ID, RECONCILE_EVENT_ID, runtime_route_integrity

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
check("local_release_gate_present", all((ROOT / path).is_file() for path in ("tools/quick_check.py", "tools/test_changed.py", "tools/run_release_suite.py")))
check("no_github_actions_dependency", not (ROOT / ".github/workflows").exists())

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

def _read_owner_route(route: object):
    text = str(route)
    base, sep, fragment = text.partition("#")
    current = json.loads((ROOT / base).read_text(encoding="utf-8"))
    if not sep or not fragment:
        return current
    for raw in fragment[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        current = current[token] if isinstance(current, dict) else current[int(token)]
    return current

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

# Named-person progression integrity after deterministic-training migration.
command_personnel = j("state/cmd/command-personnel.json").get("record_index", {})
rt_for_progression = j("state/runtime.json")
life_host_refs = {
    str(host.get("owner_ref"))
    for host in rt_for_progression.get("hosts", {}).values()
    if isinstance(host, dict) and host.get("kind") == "person"
}
activity_route_refs = {
    str(ref)
    for host in rt_for_progression.get("hosts", {}).values()
    if isinstance(host, dict) and host.get("kind") == "person_activity"
    for ref in host.get("routed_person_refs", [])
    if isinstance(ref, str)
}
missing_command_life = []
missing_command_activity = []
for person_ref, route in sorted(command_personnel.items() if isinstance(command_personnel, dict) else []):
    if person_ref == "char_tang_wei" or not str(route).startswith("state/char/"):
        continue
    try:
        person = _read_owner_route(route)
    except Exception:
        continue
    if not isinstance(person, dict) or person.get("schema") != "sab_character":
        continue
    if str(person.get("life_status", person.get("status", "active"))).lower() in {"dead", "deceased"}:
        continue
    if person_ref not in life_host_refs:
        missing_command_life.append(person_ref)
    contract = person.get("activity_contract", {})
    activity = person.get("autonomous_activity_state", {})
    if (
        isinstance(contract, dict)
        and contract.get("autonomous_enabled") is not False
        and str(contract.get("mode", "")) != "age_appropriate_household_training"
        and isinstance(activity, dict)
        and float(activity.get("verified_hours_per_cycle", 0.0) or 0.0) > 0
        and person_ref not in activity_route_refs
    ):
        missing_command_activity.append(person_ref)
check("exact_command_life_hosts_complete", not missing_command_life, str(missing_command_life[:12]))
check("exact_command_activity_routes_complete", not missing_command_activity, str(missing_command_activity[:12]))
all_active_exact_missing_life = []
for person_ref, route in sorted(owners.items()):
    if not str(route).startswith("state/char/"):
        continue
    try:
        person = _read_owner_route(route)
    except Exception:
        continue
    if not isinstance(person, dict) or person.get("schema") != "sab_character":
        continue
    if str(person.get("life_status", person.get("status", "active"))).lower() in {"dead", "deceased"}:
        continue
    if person_ref not in life_host_refs:
        all_active_exact_missing_life.append(person_ref)
check("all_active_exact_life_hosts_complete", not all_active_exact_missing_life, str(all_active_exact_missing_life[:12]))

progression_shortfalls = []
cohort_provenance_missing = []
tracking_baseline_missing = []
all_person_routes = dict(owners)
if isinstance(command_personnel, dict):
    all_person_routes.update(command_personnel)
for person_ref, route in sorted(all_person_routes.items()):
    try:
        person = _read_owner_route(route)
    except Exception:
        continue
    if not isinstance(person, dict) or person.get("schema") not in {"sab_character", "person-lite"}:
        continue
    source_cohort_ref = str(person.get("source_cohort_ref", "") or "")
    if source_cohort_ref:
        ds = person.get("development_state", {})
        baseline = ds.get("inherited_training_baseline") if isinstance(ds, dict) else None
        if not isinstance(baseline, dict) or baseline.get("source_cohort_ref") != source_cohort_ref:
            cohort_provenance_missing.append(person_ref)
    if person.get("schema") != "sab_character" or person_ref == "char_tang_wei":
        continue
    activity = person.get("autonomous_activity_state", {})
    ds = person.get("development_state", {})
    if person_ref in command_personnel and isinstance(activity, dict) and isinstance(ds, dict):
        if (
            int(activity.get("completed_cycles", 0) or 0) == 0
            and int(ds.get("settled_training_hours", 0) or 0) == 0
            and not isinstance(ds.get("inherited_training_baseline"), dict)
            and not isinstance(ds.get("progression_tracking_baseline"), dict)
        ):
            tracking_baseline_missing.append(person_ref)
    if not isinstance(activity, dict) or not isinstance(ds, dict):
        continue
    contract = person.get("activity_contract", {})
    if not isinstance(contract, dict) or str(contract.get("mode", "")) == "age_appropriate_household_training":
        continue
    proof = exact_activity_shortfall(person, contract, j("game/data/mil/recruitment-cohort-profiles.json"))
    if int(proof.get("shortfall_hours", 0) or 0) > 0:
        progression_shortfalls.append((person_ref, proof.get("expected_hours"), proof.get("verified_deliberate_training_hours")))
check("no_proven_exact_progression_shortfalls", not progression_shortfalls, str(progression_shortfalls[:12]))
check("materialized_person_training_provenance_complete", not cohort_provenance_missing, str(cohort_provenance_missing[:12]))
check("zero_cycle_exact_command_baselines_explicit", not tracking_baseline_missing, str(tracking_baseline_missing[:12]))

# Every persistent fighting formation must obey the same-echelon command law.
# Commander/deputy own the formation's top echelon; active internal 1,000/500/100
# billets must be strictly smaller. Earned rank may survive in cadre reserve.
from sword_runtime.unit_establishment import authorized_strength_for, formation_class_for
from sword_runtime.warfare_depth import build_formation_command_structure

command_rules = j("game/data/mechanics/warfare-organization.json")
same_echelon_internal_violations = []
for formation_path in sorted((ROOT / "state/formations").glob("*.json")):
    formation = json.loads(formation_path.read_text(encoding="utf-8"))
    current = max(0, int(formation.get("personnel", 0) or 0))
    klass = formation_class_for(formation, personnel=current, explicit=formation.get("formation_class"))
    authorized = authorized_strength_for(formation, personnel=current, formation_class=klass)
    projection = build_formation_command_structure(formation, command_rules)
    for row in projection.get("internal_hierarchy", []):
        if int(row.get("count", 0) or 0) > 0 and int(row.get("scale", 0) or 0) >= authorized:
            same_echelon_internal_violations.append((formation.get("formation_ref"), "projected", row.get("scale"), authorized))
    active = formation.get("command_structure", {}).get("officer_cadre", {}).get("active_billets", {})
    if isinstance(active, dict):
        for rank, count in active.items():
            if int(count or 0) <= 0:
                continue
            try:
                scale = int(str(rank).split("_", 1)[0])
            except ValueError:
                continue
            if scale >= authorized:
                same_echelon_internal_violations.append((formation.get("formation_ref"), "active", rank, authorized))
check("no_same_echelon_internal_command_billets", not same_echelon_internal_violations, str(same_echelon_internal_violations[:12]))

# Training-regimen fairness and canonical-cache integrity. Every active/enrolled
# professional regimen has exactly the same deliberate clock: 48h per seven days,
# expressed as 205.714286h per 30-day activity cycle. Faction, rank, prestige and
# canon importance may change curriculum/quality/role exposure, never clock time.
training_profiles = j("game/data/mil/recruitment-cohort-profiles.json")
regimens = training_profiles.get("training_regimens", {}) if isinstance(training_profiles, dict) else {}
regular = regimens.get("regular_army", {}) if isinstance(regimens, dict) else {}
reserve = regimens.get("reserve_maintenance", {}) if isinstance(regimens, dict) else {}
universal_target = round(48.0 * 30.0 / 7.0, 6)
active_regimen_refs = {
    "regular_army", "household_professional", "house_tang_max_sustainable",
    "professional_officer", "elite_command", "elite_martial",
    "intensive_martial_aspirant", "strategist_academy", "martial_aspirant",
    "strategic_apprentice", "statecraft_intensive", "elite_professional",
}
universal_regimen_mismatches = []
for regimen_ref in sorted(active_regimen_refs):
    row = regimens.get(regimen_ref, {}) if isinstance(regimens, dict) else {}
    hours = float(row.get("deliberate_hours_per_30d", 0.0) or 0.0) if isinstance(row, dict) else 0.0
    if abs(hours - universal_target) > 1e-6:
        universal_regimen_mismatches.append((regimen_ref, hours, universal_target))
check("universal_active_training_clock_48h_week", not universal_regimen_mismatches, str(universal_regimen_mismatches))
universal_schedule_detail_mismatches = []
for regimen_ref in sorted(active_regimen_refs):
    row = regimens.get(regimen_ref, {}) if isinstance(regimens, dict) else {}
    per7 = float(row.get("deliberate_hours_per_7d", 0.0) or 0.0) if isinstance(row, dict) else 0.0
    exposure = float(row.get("role_exposure_hours_per_30d", 0.0) or 0.0) if isinstance(row, dict) else 0.0
    if abs(per7 - 48.0) > 1e-6 or abs(exposure - 96.0) > 1e-6:
        universal_schedule_detail_mismatches.append((regimen_ref, per7, exposure))
check("universal_active_training_schedule_details_match", not universal_schedule_detail_mismatches, str(universal_schedule_detail_mismatches))
check(
    "reserve_training_below_active_professional_clock",
    float(regular.get("deliberate_hours_per_30d", 0.0) or 0.0) == universal_target
    and float(reserve.get("deliberate_hours_per_30d", 0.0) or 0.0) < universal_target,
)
training_mechanics = j("game/data/mechanics/training.json")
instructor_rules = training_mechanics.get("instructor", {}) if isinstance(training_mechanics, dict) else {}
time_budget_rules = training_mechanics.get("time_budget", {}) if isinstance(training_mechanics, dict) else {}
check(
    "mass_training_uses_hierarchy_without_unit_cap",
    isinstance(instructor_rules, dict)
    and bool(instructor_rules.get("hierarchical_propagation"))
    and "lead_units_per_7d_max" not in instructor_rules
    and "lead_oversight_hours_per_unit_per_7d" not in instructor_rules
    and "ordinary_spans" not in instructor_rules
    and "capacity_formula" not in instructor_rules
    and "mass_senior_oversight_fraction" not in instructor_rules,
)
check(
    "training_time_budget_matches_universal_clock",
    float(time_budget_rules.get("deliberate_training_hours_per_7d_normal_max", 0.0) or 0.0) == 48.0,
)
player_training = j("state/player.json").get("activity_contract", {})
check(
    "tang_wei_uses_universal_48h_week_clock",
    isinstance(player_training, dict)
    and float(player_training.get("verified_hours_per_7d", 0.0) or 0.0) == 48.0,
)
activity_cache_mismatches = []
for person_ref, route in sorted(all_person_routes.items()):
    if not str(route).startswith("state/char/"):
        continue
    try:
        person = _read_owner_route(route)
    except Exception:
        continue
    contract = person.get("activity_contract") if isinstance(person, dict) else None
    activity = person.get("autonomous_activity_state") if isinstance(person, dict) else None
    if not isinstance(contract, dict) or not isinstance(activity, dict) or str(contract.get("mode", "")) == "age_appropriate_household_training":
        continue
    cadence = max(1, int(activity.get("cadence_seconds", 30 * 86400) or 30 * 86400))
    canonical = verified_activity_hours_per_cycle(person, contract, training_profiles, cadence)
    cached = float(activity.get("verified_hours_per_cycle", 0.0) or 0.0)
    if abs(float(canonical) - cached) > 1e-6:
        activity_cache_mismatches.append((person_ref, cached, canonical, resolved_activity_regimen(person, contract, training_profiles)[0]))
check("exact_activity_rate_cache_matches_canonical_regimen", not activity_cache_mismatches, str(activity_cache_mismatches[:12]))

# The proof-based universal-clock migration must be present. It catches up only
# proven completed-cycle shortfalls and never reduces previously higher Tang history.
training_repair = j("state/meta.json").get("last_universal_training_repair", {})
check(
    "universal_training_catchup_migration_recorded",
    isinstance(training_repair, dict)
    and training_repair.get("migration_ref") == "universal_active_48h_week_v1"
    and int(training_repair.get("exact_people_caught_up", 0) or 0) == 55
    and int(training_repair.get("exact_hours_caught_up", 0) or 0) == 25496
    and int(training_repair.get("aggregate_cohorts_caught_up", 0) or 0) == 101
    and int(training_repair.get("person_lite_caught_up", 0) or 0) == 38,
)

# Four Bastion Corps were introduced as already-qualified current-setting formations.
# Their saved capability is an explicit baseline, not missing historical EDU, and
# their future standing development shares the universal 48h/week House military clock.
bastion_rules = j("game/data/mechanics/bastion-corps.json")
bastion_regimen = bastion_rules.get("qualification_regimen", {}) if isinstance(bastion_rules, dict) else {}
check(
    "bastion_training_uses_universal_clock",
    abs(float(bastion_regimen.get("deliberate_hours_per_30d", 0.0) or 0.0) - universal_target) <= 1e-6,
)
bastion_baseline_missing = []
for bastion_path in (
    "state/forces/bastion-iron-rampart.json",
    "state/forces/bastion-red-crane.json",
    "state/forces/bastion-white-lantern.json",
    "state/forces/bastion-deep-earth.json",
):
    force = j(bastion_path)
    ledger = force.get("cohort_ledger", {}).get("cohorts", {}) if isinstance(force, dict) else {}
    for cohort_id, cohort in sorted(ledger.items() if isinstance(ledger, dict) else []):
        baseline = cohort.get("training_tracking_baseline", {}) if isinstance(cohort, dict) else {}
        if (
            not isinstance(baseline, dict)
            or baseline.get("baseline_kind") != "current_setting_qualified_capability"
            or baseline.get("migration_ref") != "universal_active_48h_week_v1"
        ):
            bastion_baseline_missing.append((bastion_path, cohort_id, baseline))
check(
    "bastion_current_setting_training_baselines_explicit",
    not bastion_baseline_missing
    and int(training_repair.get("bastion_current_setting_baseline_cohorts", 0) or 0) == 14
    and training_repair.get("bastion_future_training_owner") == "host_sword_manor",
    str(bastion_baseline_missing[:12]),
)

# Every aggregate cohort with saved capability must either carry verified training
# counters or an explicit pre-tracking capability baseline. Service duration alone
# must never be interpreted as permission to mint retrospective EDU.
cohort_tracking_missing = []
for force_path in sorted((ROOT / "state/forces").glob("*.json")):
    force = json.loads(force_path.read_text(encoding="utf-8"))
    cohorts = force.get("cohort_ledger", {}).get("cohorts", {}) if isinstance(force, dict) else {}
    if not isinstance(cohorts, dict):
        continue
    for cohort_ref, cohort in sorted(cohorts.items()):
        if not isinstance(cohort, dict) or not (cohort.get("skill_means") or cohort.get("attribute_means")):
            continue
        if "verified_training_hours_per_person" not in cohort and not isinstance(cohort.get("development_tracking_baseline"), dict):
            cohort_tracking_missing.append((force.get("owner_id"), cohort_ref))
check("aggregate_cohort_training_provenance_complete", not cohort_tracking_missing, str(cohort_tracking_missing[:12]))

# The baseline House Tang/Sword Manor/Bastion institutions must have the command
# echelons their saved authorized Unit establishments require. These commanders are
# conserved fighting bodies, not extra manpower.
training_chain_mismatches = []
for formation_path in sorted((ROOT / "state/formations").glob("*.json")):
    formation = json.loads(formation_path.read_text(encoding="utf-8"))
    owner = str(formation.get("owner_force_ref", "") or "")
    if owner not in {"force_house_tang", "force_sword_manor"} and not owner.startswith("force_bastion_"):
        continue
    targets = _target_billets(formation)
    active = formation.get("command_structure", {}).get("officer_cadre", {}).get("active_billets", {})
    if not isinstance(active, dict):
        training_chain_mismatches.append((formation.get("formation_ref"), "missing_officer_cadre")); continue
    bad = {rank: (int(active.get(rank, 0) or 0), int(target)) for rank, target in targets.items() if int(active.get(rank, 0) or 0) != int(target)}
    if bad:
        training_chain_mismatches.append((formation.get("formation_ref"), bad))
check("house_tang_sword_bastion_training_chains_staffed", not training_chain_mismatches, str(training_chain_mismatches[:12]))

final_training_repair = j("state/meta.json").get("last_universal_training_hierarchy_finalization", {})
check(
    "universal_training_hierarchy_finalization_recorded",
    isinstance(final_training_repair, dict)
    and final_training_repair.get("migration_ref") == "universal_training_hierarchy_final_v1"
    and int(final_training_repair.get("baseline_cohorts_registered", 0) or 0) == 18
    and int(final_training_repair.get("formations_hierarchy_completed", 0) or 0) == 18
    and int(final_training_repair.get("headcount_created", -1) or 0) == 0,
)

# Major-canon calibration is explicit, floor-only current capability. Validate the
# saved characters still meet every configured floor and carry its provenance ref.
canon_calibration = j("game/data/people/canon-capability-calibration.json")
canon_ref = str(canon_calibration.get("calibration_ref", ""))
canon_floor_violations = []
for person_ref, spec in sorted(canon_calibration.get("characters", {}).items() if isinstance(canon_calibration, dict) else []):
    route = owners.get(person_ref)
    if not isinstance(route, str):
        canon_floor_violations.append((person_ref, "missing_owner_route")); continue
    person = _read_owner_route(route)
    for field, floor_key in (("aptitude", "aptitude_floors"), ("attributes", "attribute_floors"), ("skills", "skill_floors")):
        values = person.get(field, {}) if isinstance(person, dict) else {}
        floors = spec.get(floor_key, {}) if isinstance(spec, dict) else {}
        for key, floor in floors.items():
            if float(values.get(key, 0.0) or 0.0) + 1e-9 < float(floor):
                canon_floor_violations.append((person_ref, field, key, values.get(key), floor))
    ds = person.get("development_state", {}) if isinstance(person, dict) else {}
    prov = ds.get("canon_capability_calibration") if isinstance(ds, dict) else None
    if not isinstance(prov, dict) or prov.get("calibration_ref") != canon_ref:
        canon_floor_violations.append((person_ref, "missing_calibration_provenance"))
check("canon_current_capability_calibration_holds", not canon_floor_violations, str(canon_floor_violations[:12]))

# Current causal scheduler integrity. A committed world time may never sit
# beyond a host's declared safe horizon. Future recurring routes must also
# retain one matching event and may not already be overdue.
rt_scheduler = j("state/runtime.json")
now_scheduler = CampaignTime.parse(str(rt_scheduler["world_time"]))
events_by_host: dict[str, list[dict]] = {}
for event in rt_scheduler.get("events", []):
    if isinstance(event, dict) and isinstance(event.get("target_host"), str):
        events_by_host.setdefault(str(event["target_host"]), []).append(event)
stale_safe_horizons = []
overdue_hosts = []
route_mismatches = []
future_resolved_hosts = []
for host_id, host in sorted(rt_scheduler.get("hosts", {}).items()):
    if not isinstance(host, dict):
        route_mismatches.append((host_id, "host_not_object"))
        continue
    resolved_text = host.get("resolved_through")
    if isinstance(resolved_text, str):
        resolved = CampaignTime.parse(resolved_text)
        if resolved > now_scheduler:
            future_resolved_hosts.append((host_id, resolved_text, str(now_scheduler)))
    next_text = host.get("next_due")
    if next_text is None:
        continue
    next_due = CampaignTime.parse(str(next_text))
    safe_text = host.get("safe_through")
    if not isinstance(safe_text, str) or CampaignTime.parse(safe_text) < now_scheduler:
        stale_safe_horizons.append((host_id, safe_text, str(now_scheduler), str(next_due)))
    if next_due <= now_scheduler:
        overdue_hosts.append((host_id, str(next_due), str(now_scheduler)))
    routed = events_by_host.get(str(host_id), [])
    matching = [row for row in routed if str(row.get("due_at")) == str(next_text)]
    if len(routed) != 1 or len(matching) != 1:
        route_mismatches.append((host_id, str(next_text), [(row.get("event_id"), row.get("due_at")) for row in routed]))
for target_host in sorted(set(events_by_host) - set(rt_scheduler.get("hosts", {}))):
    route_mismatches.append((target_host, "event_targets_missing_host"))
check("causal_host_safe_horizons_cover_current_time", not stale_safe_horizons, str(stale_safe_horizons[:12]))
check("causal_host_events_match_next_due", not route_mismatches, str(route_mismatches[:12]))
check("no_overdue_causal_hosts", not overdue_hosts, str(overdue_hosts[:12]))
check("causal_host_resolved_through_not_future", not future_resolved_hosts, str(future_resolved_hosts[:12]))

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

# Global scheduler frontier and reconciliation coverage.  World time may never
# outrun the causal settled frontier, and the periodic reconciliation route must
# remain live so long skips can discover newly schedulable owners mid-skip.
scheduler_state = rt_scheduler.get("scheduler") if isinstance(rt_scheduler, dict) else None
frontier_errors = []
if not isinstance(scheduler_state, dict):
    frontier_errors.append("missing_scheduler_state")
else:
    if scheduler_state.get("causal_settled_through") != rt_scheduler.get("world_time"):
        frontier_errors.append(("frontier", scheduler_state.get("causal_settled_through"), rt_scheduler.get("world_time")))
    if rt_scheduler.get("world_time") != meta.get("time"):
        frontier_errors.append(("meta_runtime_time", meta.get("time"), rt_scheduler.get("world_time")))
    if not isinstance(scheduler_state.get("last_reconciled_at"), str):
        frontier_errors.append("missing_last_reconciled_at")
    if not isinstance(scheduler_state.get("next_safety_reconcile_at"), str):
        frontier_errors.append("missing_next_safety_reconcile_at")
check("global_causal_frontier_matches_world_time", not frontier_errors, str(frontier_errors[:8]))

reconcile_host = rt_scheduler.get("hosts", {}).get(RECONCILE_HOST_ID)
reconcile_events = [
    row for row in rt_scheduler.get("events", [])
    if isinstance(row, dict) and row.get("event_id") == RECONCILE_EVENT_ID and row.get("target_host") == RECONCILE_HOST_ID
]
check(
    "scheduler_reconciliation_host_live",
    isinstance(reconcile_host, dict)
    and reconcile_host.get("kind") == "scheduler_reconcile"
    and reconcile_host.get("next_due") is not None
    and len(reconcile_events) == 1
    and reconcile_events[0].get("due_at") == reconcile_host.get("next_due"),
)
route_integrity = runtime_route_integrity(rt_scheduler)
check("runtime_scheduler_registry_integrity", bool(route_integrity.get("complete")), str(route_integrity))

# Core autonomous owner coverage is derived from the explicit owner index, not
# directory scans.  Dynamic specialized domains keep their own bounded indexes.
host_owners_by_kind = {}
for _host in rt_scheduler.get("hosts", {}).values():
    if isinstance(_host, dict) and isinstance(_host.get("kind"), str) and isinstance(_host.get("owner_ref"), str):
        host_owners_by_kind.setdefault(_host["kind"], set()).add(_host["owner_ref"])
core_missing = []
for owner_ref, route in owners.items():
    base = str(route).split("#", 1)[0]
    expected_kind = None
    if base.startswith("state/states/"):
        expected_kind = "state"
    elif base.startswith("state/institutions/"):
        expected_kind = "institution"
    elif base.startswith("state/houses/"):
        expected_kind = "house"
    elif base.startswith("state/factions/"):
        expected_kind = "faction"
    elif base.startswith("state/char/"):
        expected_kind = "person"
    elif base.startswith("state/merc/") and str(owner_ref).startswith("merc_"):
        expected_kind = "mercenary"
    elif base.startswith("state/population/") and str(owner_ref).removeprefix("population_") in {"qin","zhao","wei","chu","han","yan","qi"}:
        expected_kind = "population"
    if expected_kind and owner_ref not in host_owners_by_kind.get(expected_kind, set()):
        core_missing.append((owner_ref, expected_kind, base))
check("core_autonomous_owners_have_scheduler_hosts", not core_missing, str(core_missing[:12]))

if FAILURES:
    print(f"\nvalidate_release: FAIL ({len(FAILURES)}/{CHECKS})")
    for failure in FAILURES: print(" - "+failure)
    raise SystemExit(1)
print(f"\nvalidate_release: PASS ({CHECKS} checks)")
