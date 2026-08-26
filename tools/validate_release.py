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
from sword_runtime.officer_cadre import _target_billets, officer_cadre_summary
from sword_runtime.warfare_depth import build_formation_command_structure
from sword_runtime.scheduler_frontier import RECONCILE_HOST_ID, RECONCILE_EVENT_ID, runtime_route_integrity
from sword_runtime.cohort_personnel import validate_cohort_ledger, conserved_establishment_role_count
from sword_runtime.service_runtime import CommandRoutedProductionPlanner

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
check("github_actions_verification_present", (ROOT / ".github/workflows/verify.yml").is_file())

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

# The player sheet's personal-combat doctrine is a live player-facing dependency.
# It must resolve through the static registry to a physical personal-combat record,
# otherwise even bounded play_context construction can fail.
player_doc=j("state/player.json")
combat_ref=str(player_doc.get("combat_doctrine_ref","") or "")
doctrine_registry=j("game/data/mil/doctrines.json")
doctrine_route=(doctrine_registry.get("record_index",{}) or {}).get(combat_ref) if combat_ref else None
combat_doctrine_ok=False
if isinstance(doctrine_route,str) and (ROOT/doctrine_route).is_file():
    try:
        doctrine_record=j(doctrine_route)
        combat_doctrine_ok=(
            doctrine_record.get("schema")=="doctrine-record"
            and doctrine_record.get("id")==combat_ref
            and isinstance(doctrine_record.get("doctrine"),dict)
            and doctrine_record["doctrine"].get("domain")=="personal_combat"
        )
    except Exception:
        combat_doctrine_ok=False
check("player_combat_doctrine_resolves", bool(combat_ref) and combat_doctrine_ok, str((combat_ref,doctrine_route)))

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

# Every exact House uses the same formal non-royal nobility ladder. Royal dynasty
# and succession remain separate family/polity authorities.
nobility_rules=j("game/data/mechanics/nobility.json")
valid_nobility_grades=set((nobility_rules.get("grade_order") or {}).keys())
house_nobility_errors=[]
for path in sorted((ROOT/"state/houses").glob("*.json")):
    house=json.loads(path.read_text(encoding="utf-8"))
    if house.get("schema")!="sword-house":
        continue
    nobility=house.get("nobility")
    grade=nobility.get("grade") if isinstance(nobility,dict) else None
    if grade not in valid_nobility_grades:
        house_nobility_errors.append((house.get("owner_id"),grade))
check("house_nobility_grades_valid", not house_nobility_errors, str(house_nobility_errors[:8]))

# Command hierarchy is a zero-body routing layer. Every saved command-group
# file must be discoverable through the index, every direct formation may have
# only one primary parent, and exact commander references must resolve.
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
    for key in ("commander_ref",):
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

# Staff appointments are additive routing, separate from primary troop command.
staff_policy = j("game/data/mechanics/command-staff.json")
registered_staff_roles = set((staff_policy.get("roles") or {}).keys()) if isinstance(staff_policy, dict) else set()
expected_staff_routes = {}
command_group_staff_errors = []
for group_ref, rel_path in saved_command_groups.items():
    group = j(rel_path)
    assignments = group.get("role_assignments", {})
    if not isinstance(assignments, dict):
        command_group_staff_errors.append((group_ref, "role_assignments_not_object"))
        continue
    for person_ref, role in assignments.items():
        if role not in registered_staff_roles:
            command_group_staff_errors.append((group_ref, person_ref, "unregistered_role", role))
            continue
        try:
            owner_path = owner_index.get("owners", {}).get(person_ref) if isinstance(owner_index, dict) else None
            if not owner_path:
                command_group_staff_errors.append((group_ref, person_ref, "unresolved_person"))
        except Exception:
            command_group_staff_errors.append((group_ref, person_ref, "unresolved_person"))
        expected_staff_routes.setdefault(person_ref, []).append(group_ref)
expected_staff_routes = {k: sorted(set(v)) for k, v in sorted(expected_staff_routes.items())}
actual_staff_routes = command_group_index.get("staff_person_groups", {})
if actual_staff_routes != expected_staff_routes:
    command_group_staff_errors.append(("staff_person_groups", actual_staff_routes, expected_staff_routes))
check("command_group_staff_routes_exact", not command_group_staff_errors, str(command_group_staff_errors[:8]))

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
stale_state_keys = []
for path in all_json(ROOT/"state"):
    value=json.loads(path.read_text(encoding="utf-8"))
    stack=[((),value)]
    while stack:
        key_path,cur=stack.pop()
        if isinstance(cur,dict):
            for key,child in cur.items():
                child_path=key_path+(str(key),)
                if key in {
                    "last_progression_integrity_repair", "last_training_fairness_canon_repair",
                    "last_universal_training_hierarchy_finalization", "last_universal_training_repair",
                    "last_repository_integrity_cleanup", "universal_training_migration_history",
                    "training_regimen_migration_history", "progression_repair_history",
                    "canon_capability_calibration_history", "canon_capability_calibration",
                    "inherited_training_baseline", "progression_tracking_baseline",
                    "training_tracking_baseline", "development_tracking_baseline",
                    "appearance_source", "birth_date_source", "source_class",
                    "geographic_provenance",
                    # Static/explanatory prose and repair-era fields must never
                    # leak back into authoritative hot state.  Current links
                    # such as source_cohort_ref/source_force_ref are deliberately
                    # excluded because they enforce conservation.
                    "last_reorganization_reason", "hot_baseline", "attachment_rule",
                    "capital_provenance", "capability_rule", "return_rule",
                    "composition_rule", "resupply_history", "current_role_calibration_note",
                    "equipment_note", "quality_rule", "change_history", "autarky_note",
                    "authority_note", "causal_impossibility_rule", "identity_source_refs",
                    "loss_rule", "wake_policy", "audience_membership_rule",
                    "audience_profile_rule", "capital_conservation_rule",
                    "command_establishment_rule", "containment_rule", "crew_assignment_rule",
                    "damage_rule", "determinism_rule", "divergence_rule",
                    "geographic_rule", "infrastructure_rule", "internal_loadout_rule",
                    "mission_creation_rule", "mount_category_rule", "no_free_crew_rule",
                    "organization_rule", "progression_routing_note", "project_rule",
                    "receipt_rule", "representation_note", "rule_basis", "size_rule",
                    "source_basis", "standing_training_history_summary",
                    "standout_materialization_policy", "throughput_rule", "weapon_id_rule",
                    "narrative_constraints", "replacement_policy",
                    "conservation_rule", "staffing_policy", "campaign_resupply_rule",
                    "cash_close_rule", "replacement_rule", "last_reconstitution_basis",
                    "creation_basis", "outcome_rule", "accounting_rule", "projection_basis",
                    "population_authority_rule", "outcome_authority",
                    "order_state_correction", "historical_event_policy",
                    "combat_history", "procurement_history", "care_history", "death_history",
                    "local_service_casualties", "local_private_service_casualties",
                    "material_issue_request_id", "manufacturing_truth", "house_stock_snapshot",
                    "shortfall_review",
                }:
                    stale_state_keys.append((path.relative_to(ROOT).as_posix(), ".".join(child_path)))
                stack.append((child_path,child))
        elif isinstance(cur,list):
            for idx,child in enumerate(cur):
                stack.append((key_path+(str(idx),),child))
check("state_has_no_stale_migration_or_annotation_keys", not stale_state_keys, str(stale_state_keys[:12]))

# Gameplay causality must never depend on the transport/idempotency request ID.
# The request-bound digest remains lawful only at transaction/preview boundaries;
# domain evidence, seeds, event identities and persisted semantic refs use
# CommandEnvelope.semantic_digest instead.
_gameplay_command_sources = (
    "runtime/sword_runtime/campaign_depth.py",
    "runtime/sword_runtime/civil_world.py",
    "runtime/sword_runtime/downtime.py",
    "runtime/sword_runtime/military_career_loyalty_politics.py",
    "runtime/sword_runtime/player_group_actions.py",
    "runtime/sword_runtime/production_planner.py",
    "runtime/sword_runtime/standing_training.py",
)
_transport_identity_leaks = []
for _rel in _gameplay_command_sources:
    _text = (ROOT / _rel).read_text(encoding="utf-8")
    for _token in ("command.request_id", "command.digest"):
        if _token in _text:
            _transport_identity_leaks.append((_rel, _token))
_engine_text = (ROOT / "runtime/sword_runtime/engine.py").read_text(encoding="utf-8")
if "command.request_id" in _engine_text:
    _transport_identity_leaks.append(("runtime/sword_runtime/engine.py", "command.request_id"))
_engine_digest_lines = [
    line.strip() for line in _engine_text.splitlines() if "command.digest" in line
]
if _engine_digest_lines != [
    'txid="sword-"+hashlib.sha256((command.digest+":"+str(command.expected_revision)).encode()).hexdigest()[:24]'
]:
    _transport_identity_leaks.append(("runtime/sword_runtime/engine.py", "unexpected command.digest use", _engine_digest_lines))
_interaction_text = (ROOT / "runtime/sword_runtime/api/interaction_surface.py").read_text(encoding="utf-8")
if '"surface_digest": command.semantic_digest' not in _interaction_text:
    _transport_identity_leaks.append(("runtime/sword_runtime/api/interaction_surface.py", "surface_digest_not_semantic"))
check("gameplay_identity_excludes_transport_request_id", not _transport_identity_leaks, str(_transport_identity_leaks[:12]))
check("state_has_no_request_id_scaffolding", not state_request_ids, str(state_request_ids[:8]))
check("state_has_no_historical_receipt_chains", not state_receipt_refs, str(state_receipt_refs[:8]))
check("state_has_no_release_scaffolding", not state_release_scaffolding, str(state_release_scaffolding[:8]))
check("no_state_migration_tree", not (ROOT/"state/migrations").exists())


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
    external_allocated=sum(
        max(0,int(count))
        for roles in force.get("external_personnel_allocations",{}).values() if isinstance(roles,dict)
        for count in roles.values()
    ) if isinstance(force.get("external_personnel_allocations"),dict) else 0
    assignments=force.get("materialized_assignments",{})
    internal_refs=set(assignments) if isinstance(assignments,dict) else set()
    materialized=sum(
        int(v.get("personnel",1)) if isinstance(v,dict) else int(v)
        for ref,v in force.get("materialized_people",{}).items() if ref not in internal_refs
    )
    check(f"force_conserved:{state}", available+allocated+external_allocated+materialized == int(force.get("headcount",-1)))
    mounts=j(f"state/mounts/{state}.json")
    check(f"mount_pool_conserved:{state}", sum(int(v) for v in mounts.get("types",{}).values()) == int(mounts.get("total",-1)))

# Every positive formation mount allocation must route to a live formation owner.
unrouted_mount_allocations=[]
for mount_path in sorted((ROOT / "state/mounts").glob("*.json")):
    pool=json.loads(mount_path.read_text(encoding="utf-8"))
    for formation_ref, row in pool.get("allocated_to_formations",{}).items():
        if not isinstance(row,dict) or sum(max(0,int(v)) for v in row.values()) <= 0:
            continue
        routed=owners.get(formation_ref)
        if not isinstance(routed,str) or not routed.startswith("state/formations/"):
            unrouted_mount_allocations.append((mount_path.name,formation_ref,routed))
check("mount_allocations_route_to_live_formations", not unrouted_mount_allocations, str(unrouted_mount_allocations[:8]))

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

# Unified House Tang and current Tang Wei Army invariants.
def _conserved_force_ok(force: dict) -> tuple[bool, str]:
    try:
        validate_cohort_ledger(force)
        return True, ""
    except Exception as exc:
        return False, str(exc)

house_force=j("state/forces/house-tang.json")
house_ok, house_detail = _conserved_force_ok(house_force)
expected_house_roles={"house_infantry":164060,"house_cavalry":12000}
check(
    "house_tang_unified_establishment_conserved",
    house_ok
    and int(house_force.get("headcount",0))==176060
    and int(house_force.get("authorized_strength",0))==176060
    and house_force.get("authorized_by_role")==expected_house_roles,
    house_detail,
)
house_role_counts={role:conserved_establishment_role_count(house_force,role) for role in expected_house_roles}
check(
    "house_tang_exact_materialized_roles_preserve_establishment",
    house_role_counts==expected_house_roles
    and all(isinstance(v,dict) and str(v.get("role","")) in expected_house_roles and int(v.get("personnel",0))>0 for v in house_force.get("materialized_people",{}).values()),
    str(house_role_counts),
)
legal_house_roles=set(expected_house_roles)
equipment_role_keys=set(str(k) for k in house_force.get("available_equipment_units_by_role",{}))
for _pool in house_force.get("available_equipment_by_location",{}).values():
    if isinstance(_pool,dict): equipment_role_keys.update(str(k) for k in _pool)
check(
    "house_tang_active_equipment_roles_use_two_species_only",
    equipment_role_keys <= legal_house_roles,
    str(sorted(equipment_role_keys-legal_house_roles)),
)
retired_house_force_ids={
    "force_sword_manor","force_bastion_iron_wall","force_bastion_red_thunder",
    "force_bastion_white_blade","force_bastion_stone_spear",
    "force_house_guardian_cavalry","force_house_guards",
}
check(
    "retired_house_tang_parallel_force_owners_absent",
    not (retired_house_force_ids & set(owners))
    and all(
        (json.loads(path.read_text(encoding="utf-8")).get("owner_id") not in retired_house_force_ids)
        for path in (ROOT/"state/forces").glob("*.json")
    ),
)
obsolete_pool_tokens=("sword-manor-","bastion-","tang-champion","guardian-cavalry","house-guard")
check(
    "house_tang_old_materialized_rank_pools_removed",
    not any(any(tok in path.name for tok in obsolete_pool_tokens) for path in (ROOT/"state/person/person-lite").glob("*.json")),
)
check(
    "house_tang_programs_contains_no_mutable_force_snapshot",
    "standing_establishment" not in j("game/data/mechanics/house-tang-programs.json"),
)

pforce=j("state/pforce/wei.json")
current_house_refs={
    "formation_red_lance_a","formation_red_lance_b","formation_high_guard_cavalry",
    "formation_high_guard_infantry_01a","formation_high_guard_infantry_01b",
    "formation_high_guard_infantry_02a","formation_high_guard_infantry_02b",
    "formation_high_guard_infantry_03a","formation_high_guard_infantry_03b",
}
check(
    "tang_wei_house_assignments_rebaselined",
    set(pforce.get("assigned_formations",[]))==current_house_refs
    and not pforce.get("permanent_formations")
    and not pforce.get("permanent_units")
    and all(
        (lambda row: row.get("owner_force_ref")=="force_house_tang" and row.get("command_authority")=="char_tang_wei")(
            _read_owner_route(owners[ref])
        ) for ref in current_house_refs
    ),
)
policy_text=json.dumps(pforce.get("policy",{})).lower()
check("personal_recruits_cohort_first_policy", "cohort" in policy_text and "selective" in policy_text)
check("personal_recruit_campaign_runtime_present", (ROOT/"runtime/sword_runtime/recruitment_campaigns.py").is_file())

# Command-group hierarchy is zero-body organization. Resolve current leaf formations
def _group_doc(ref: str) -> dict:
    route=owners.get(ref)
    if isinstance(route,str):
        row=_read_owner_route(route)
        if isinstance(row,dict): return row
    path=ROOT/"state/cmd/command-groups"/f"{ref}.json"
    return json.loads(path.read_text(encoding="utf-8"))

def _group_leaf_refs(ref: str, seen: set[str] | None=None) -> list[str]:
    seen=set() if seen is None else seen
    if ref in seen: raise ValueError(f"command group cycle: {ref}")
    seen.add(ref); out=[]
    group=_group_doc(ref)
    for unit in group.get("units",[]):
        if not isinstance(unit,dict): continue
        if unit.get("kind")=="formation" and isinstance(unit.get("ref"),str): out.append(unit["ref"])
        elif unit.get("kind")=="nested_army" and isinstance(unit.get("ref"),str): out.extend(_group_leaf_refs(unit["ref"],seen.copy()))
    return out

def _formation(ref: str) -> dict:
    return _read_owner_route(owners[ref])

def _group_strength(ref: str) -> int:
    org=_group_doc(ref).get("organizational_state",{})
    return int(org.get("current_recursive_strength",org.get("authorized_strength",0)) or 0)

field_army=_group_doc("cmdgrp.tang_wei.field_army")
field_units={(row.get("kind"),row.get("ref")) for row in field_army.get("units",[]) if isinstance(row,dict)}
check(
    "tang_wei_army_9500",
    _group_strength("cmdgrp.tang_wei.field_army")==9500
    and field_units=={
        ("nested_army","cmdgrp.tang_wei.red_lance"),
        ("nested_army","cmdgrp.tang_wei.high_guard"),
        ("nested_army","cmdgrp.tang_wei.black_banner"),
    }
    and field_army.get("commander_ref")=="char_tang_wei"
    and field_army.get("role_assignments",{}).get("char_lin_zhen")=="strategist",
)

exact_500_errors=[]
for path in sorted((ROOT/"state/formations").glob("*.json")):
    formation=json.loads(path.read_text(encoding="utf-8"))
    if int(formation.get("personnel",0) or 0)<500: continue
    commander=formation.get("commander_ref"); route=owners.get(commander)
    if not isinstance(commander,str) or not isinstance(route,str) or not route.startswith(("state/char/","state/player.json")):
        exact_500_errors.append((formation.get("formation_ref"),commander,route))
for path in sorted((ROOT/"state/cmd/command-groups").glob("cmdgrp*.json")):
    if path.name=="index.json": continue
    group=json.loads(path.read_text(encoding="utf-8")); org=group.get("organizational_state",{})
    span=int(org.get("current_recursive_strength",org.get("authorized_strength",0)) or 0)
    if span<500: continue
    commander=group.get("commander_ref"); route=owners.get(commander)
    if not isinstance(commander,str) or not isinstance(route,str) or not route.startswith(("state/char/","state/player.json")):
        exact_500_errors.append((group.get("id"),commander,route))
check("universal_instantiated_500_plus_commanders_are_full_exact", not exact_500_errors, str(exact_500_errors[:12]))

formation_commander_sheet_errors=[]
for path in sorted((ROOT/"state/formations").glob("*.json")):
    formation=json.loads(path.read_text(encoding="utf-8"))
    authorized=int(formation.get("authorized_strength",formation.get("personnel",0)) or 0)
    if authorized < 500:
        continue
    commander=str(formation.get("commander_ref") or "")
    route=owners.get(commander)
    if not isinstance(route,str) or not route.startswith("state/char/"):
        continue
    person=_read_owner_route(route)
    assignment=person.get("command_assignment",{}) if isinstance(person.get("command_assignment"),dict) else {}
    formation_ref=str(formation.get("formation_ref") or "")
    if assignment.get("formation_ref") != formation_ref or person.get("current_formation_id") != formation_ref:
        formation_commander_sheet_errors.append((formation_ref,commander,"assignment_mismatch",assignment.get("formation_ref"),person.get("current_formation_id")))
        continue
    if int(assignment.get("current_command_span",-1) or -1) != int(formation.get("personnel",0) or 0):
        formation_commander_sheet_errors.append((formation_ref,commander,"span_mismatch",assignment.get("current_command_span"),formation.get("personnel")))
    person_location=person.get("location") if isinstance(person.get("location"),str) else person.get("current_location")
    if isinstance(formation.get("location_ref"),str) and person_location != formation.get("location_ref"):
        formation_commander_sheet_errors.append((formation_ref,commander,"location_mismatch",person_location,formation.get("location_ref")))
check("exact_formation_commander_sheets_match_live_billets", not formation_commander_sheet_errors, str(formation_commander_sheet_errors[:12]))

double_hats=[]
for path in sorted((ROOT/"state/cmd/command-groups").glob("cmdgrp*.json")):
    if path.name=="index.json": continue
    group=json.loads(path.read_text(encoding="utf-8")); parent_cmd=group.get("commander_ref")
    if not isinstance(parent_cmd,str) or not parent_cmd: continue
    for unit in group.get("units",[]):
        if not isinstance(unit,dict) or not isinstance(unit.get("ref"),str): continue
        try:
            child=_group_doc(unit["ref"]) if unit.get("kind")=="nested_army" else _formation(unit["ref"])
        except Exception:
            continue
        if child.get("commander_ref")==parent_cmd:
            double_hats.append((group.get("id"),unit.get("ref"),parent_cmd))
check("no_parent_child_commander_double_hat", not double_hats, str(double_hats[:12]))

red_refs=_group_leaf_refs("cmdgrp.tang_wei.red_lance")
high_refs=_group_leaf_refs("cmdgrp.tang_wei.high_guard")
black_refs=_group_leaf_refs("cmdgrp.tang_wei.black_banner")
check(
    "tang_wei_named_subformations",
    _group_strength("cmdgrp.tang_wei.red_lance")==1000
    and _group_strength("cmdgrp.tang_wei.high_guard")==4500
    and _group_strength("cmdgrp.tang_wei.black_banner")==4000,
)
check(
    "red_lance_1000_house_cavalry",
    set(red_refs)=={"formation_red_lance_a","formation_red_lance_b"}
    and sum(int(_formation(ref).get("personnel",0)) for ref in red_refs)==1000
    and all(_formation(ref).get("owner_force_ref")=="force_house_tang" and _formation(ref).get("composition")=={"house_cavalry":500} for ref in red_refs),
)
high_house_inf=sum(int(_formation(r).get("composition",{}).get("house_infantry",0)) for r in high_refs if _formation(r).get("owner_force_ref")=="force_house_tang")
high_house_cav=sum(int(_formation(r).get("composition",{}).get("house_cavalry",0)) for r in high_refs if _formation(r).get("owner_force_ref")=="force_house_tang")
high_qin=sum(int(_formation(r).get("personnel",0)) for r in high_refs if _formation(r).get("owner_force_ref")=="force_state_qin")
check("high_guard_4500_composition", high_house_inf==3000 and high_house_cav==500 and high_qin==1000 and sum(int(_formation(r).get("personnel",0)) for r in high_refs)==4500)
check(
    "black_banner_4000_qin",
    len(black_refs)==8
    and sum(int(_formation(r).get("personnel",0)) for r in black_refs)==4000
    and all(_formation(r).get("owner_force_ref")=="force_state_qin" for r in black_refs),
)

red_doc=j("game/data/mil/doctrine-records/doc.tang_wei.red_lance.json").get("doctrine",{})
red_policy=red_doc.get("formation_policy_v2",{}) if isinstance(red_doc,dict) else {}
check(
    "red_lance_protection_doctrine",
    red_policy.get("anchor_policy")=="army_commander_position"
    and red_policy.get("protected_asset")=="army_commander"
    and red_policy.get("pursuit_policy")=="none"
    and red_policy.get("detachment_policy")=="explicit_order_only",
)
high_doc=j("game/data/mil/doctrine-records/doc.tang_wei.high_guard.json").get("doctrine",{})
high_text=json.dumps(high_doc).lower()
check(
    "high_guard_fixed_house_core_doctrine",
    "3,000 tang infantry core never reinforces black banner" in high_text
    and _group_strength("cmdgrp.tang_wei.high_guard.foot_core")==3000
    and _group_strength("cmdgrp.tang_wei.high_guard.qin_reserve")==1000,
)
black_doc=j("game/data/mil/doctrine-records/doc.tang_wei.black_banner.json").get("doctrine",{})
black_policy=black_doc.get("formation_policy_v2",{}) if isinstance(black_doc,dict) else {}
black_text=json.dumps(black_doc).lower()
check(
    "black_banner_mission_first_not_suicidal",
    black_policy.get("casualty_posture")=="mission_first" and "not suicidal" in black_text,
)

permanent_support_roles={"siege_engineering","logistics","signal","bastion_engineer","bastion_logistics","bastion_signal","bastion_medical"}
support_role_leaks=[]
for path in (ROOT/"state/forces").glob("*.json"):
    force=json.loads(path.read_text(encoding="utf-8"))
    for role in set(force.get("available_by_role",{})) | set(force.get("authorized_by_role",{})):
        if str(role) in permanent_support_roles: support_role_leaks.append(f"{path.name}:{role}")
    for cohort in (force.get("cohort_ledger",{}).get("cohorts",{}) or {}).values():
        if isinstance(cohort,dict) and str(cohort.get("role")) in permanent_support_roles:
            support_role_leaks.append(f"{path.name}:cohort:{cohort.get('role')}")
for path in (ROOT/"state/formations").glob("*.json"):
    formation=json.loads(path.read_text(encoding="utf-8"))
    for role in (formation.get("composition",{}) or {}):
        if str(role) in permanent_support_roles: support_role_leaks.append(f"{path.name}:{role}")
check("no_permanent_military_support_manpower_roles", not support_role_leaks, str(support_role_leaks[:16]))

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
activity_route_planner = CommandRoutedProductionPlanner(ROOT)
activity_route_planner._reset()
activity_route_profiles = activity_route_planner.read("game/data/mil/recruitment-cohort-profiles.json")
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
    contract = activity_route_planner._command_activity_contract(person)
    if not isinstance(contract, dict) or contract.get("autonomous_enabled") is False:
        continue
    if not activity_route_planner._activity_focuses(person, contract):
        continue
    cadence = int(person.get("autonomous_activity_state", {}).get("cadence_seconds", 30 * 86400))
    cycle_hours = verified_activity_hours_per_cycle(person, contract, activity_route_profiles, cadence)
    if cycle_hours > 0 and person_ref not in activity_route_refs:
        missing_command_activity.append(person_ref)
check("exact_command_life_hosts_complete", not missing_command_life, str(missing_command_life[:12]))
check("exact_command_activity_routes_complete", not missing_command_activity, str(missing_command_activity[:12]))

# Command-personnel routes are first-class exact routing, including JSON-pointer
# person-lite fragments. The projection may not point somewhere different from
# owner-index authority or retain a physically missing shard record.
command_route_errors=[]
for person_ref, route in sorted(command_personnel.items() if isinstance(command_personnel, dict) else []):
    if owners.get(person_ref) != route or not _owner_route_exists(route):
        command_route_errors.append((person_ref, route, owners.get(person_ref)))
check("command_personnel_routes_authoritative", not command_route_errors, str(command_route_errors[:12]))

# Non-force person-lite staff are persistent named people. They use the routed
# activity clock for development and exactly one annual person host for mortality.
# Force-owned person-lite officers stay on their conserved cohort mortality path
# and therefore must not receive a second annual person host.
person_lite_lifecycle_errors=[]
for person_ref, route in sorted(command_personnel.items() if isinstance(command_personnel, dict) else []):
    try:
        person=_read_owner_route(route)
    except Exception:
        continue
    if not isinstance(person,dict) or person.get("schema")!="person-lite":
        continue
    if str(person.get("life_status",person.get("status","active"))).lower() in {"dead","deceased","destroyed"}:
        continue
    owner_ref=str(person.get("owner","") or "")
    force_owned=False
    if owner_ref in owners:
        try:
            owner_doc=_read_owner_route(owners[owner_ref])
            materialized=owner_doc.get("materialized_people") if isinstance(owner_doc,dict) else None
            force_owned=isinstance(materialized,dict) and person_ref in materialized
        except Exception:
            force_owned=False
    life_count=sum(1 for host in rt_for_progression.get("hosts",{}).values() if isinstance(host,dict) and host.get("kind")=="person" and host.get("owner_ref")==person_ref)
    if force_owned:
        if life_count!=0:
            person_lite_lifecycle_errors.append((person_ref,"force_owned_double_life_host",life_count))
        continue
    activity=person.get("autonomous_activity_state") if isinstance(person.get("autonomous_activity_state"),dict) else {}
    needs_activity=activity.get("enabled") is not False and float(activity.get("verified_hours_per_cycle",0.0) or 0.0)>0.0
    if life_count!=1 or (needs_activity and person_ref not in activity_route_refs):
        person_lite_lifecycle_errors.append((person_ref,"nonforce_lifecycle",life_count,person_ref in activity_route_refs))
check("person_lite_lifecycle_routes_exact", not person_lite_lifecycle_errors, str(person_lite_lifecycle_errors[:12]))

# The two migrated House operations officers have one current identity each. The
# retired Guard/Guardian labels may survive only in history/evidence, never as live
# owner routes or duplicate scheduler identities.
old_house_ops={
    "char_house_tang_guardian_cavalry_operations_officer",
    "char_house_tang_house_guard_operations_officer",
}
current_house_ops={
    "char_house_tang_house_cavalry_operations_officer",
    "char_house_tang_house_infantry_operations_officer",
}
old_house_ops_live=[ref for ref in sorted(old_house_ops) if ref in owners or ref in command_personnel or ref in life_host_refs]
current_house_ops_errors=[]
for ref in sorted(current_house_ops):
    route=owners.get(ref)
    life_count=sum(1 for host in rt_for_progression.get("hosts",{}).values() if isinstance(host,dict) and host.get("kind")=="person" and host.get("owner_ref")==ref)
    if not route or command_personnel.get(ref)!=route or life_count!=1:
        current_house_ops_errors.append((ref,route,command_personnel.get(ref),life_count))
check("house_operations_officer_identity_consolidated", not old_house_ops_live and not current_house_ops_errors, str((old_house_ops_live,current_house_ops_errors)))
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
all_person_routes = dict(owners)
if isinstance(command_personnel, dict):
    all_person_routes.update(command_personnel)
for person_ref, route in sorted(all_person_routes.items()):
    try:
        person = _read_owner_route(route)
    except Exception:
        continue
    if not isinstance(person, dict) or person.get("schema") != "sab_character" or person_ref == "char_tang_wei":
        continue
    activity = person.get("autonomous_activity_state", {})
    ds = person.get("development_state", {})
    if not isinstance(activity, dict) or not isinstance(ds, dict):
        continue
    contract = person.get("activity_contract", {})
    if not isinstance(contract, dict) or str(contract.get("mode", "")) == "age_appropriate_household_training":
        continue
    proof = exact_activity_shortfall(person, contract, j("game/data/mil/recruitment-cohort-profiles.json"))
    if int(proof.get("shortfall_hours", 0) or 0) > 0:
        progression_shortfalls.append((person_ref, proof.get("expected_hours"), proof.get("verified_deliberate_training_hours")))
check("no_current_exact_progression_shortfalls", not progression_shortfalls, str(progression_shortfalls[:12]))

# Every persistent fighting formation must obey the same-echelon command law.
# The commander owns the formation's top echelon; active internal 1,000/500/100
# billets must be strictly smaller. Earned rank may survive in cadre reserve.
from sword_runtime.unit_establishment import authorized_strength_for, formation_class_for
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
    active = officer_cadre_summary(formation).get("active_billets", {})
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

# Formation hot state stores durable establishment/cadre facts only. Command
# topology and current billet allocation are deterministic projections.
formation_files = sorted((ROOT / "state/formations").glob("*.json"))
formation_rows = [json.loads(path.read_text(encoding="utf-8")) for path in formation_files]
check("formation_command_structure_is_derived_only", all("command_structure" not in row for row in formation_rows))
check("formation_establishment_is_explicit", all(isinstance(row.get("formation_class"), str) and int(row.get("authorized_strength", 0) or 0) > 0 for row in formation_rows))
check("formation_cadre_state_contains_no_derived_allocations", all(
    isinstance(row.get("officer_cadre"), dict)
    and not any(key in row.get("officer_cadre", {}) for key in ("active_billets", "cadre_reserve", "vacant_billets"))
    for row in formation_rows
))
check("formation_establishment_personnel_has_one_authority", all("establishment_personnel" not in row for row in formation_rows))
formation_override_errors=[]
for row in formation_rows:
    override=row.get("establishment_composition")
    if not isinstance(override,dict):
        continue
    current=row.get("composition",{}) if isinstance(row.get("composition"),dict) else {}
    authorized=int(row.get("authorized_strength",0) or 0)
    if sum(int(v) for v in override.values()) != authorized:
        formation_override_errors.append((row.get("formation_ref"),"wrong_total"))
    elif int(row.get("personnel",0) or 0)==authorized and override==current:
        formation_override_errors.append((row.get("formation_ref"),"redundant_full_strength_copy"))
check("formation_establishment_composition_is_override_only", not formation_override_errors, str(formation_override_errors[:12]))

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

# Current House Tang training law. One monthly host advances the unified two-role
# force; deleted Sword Manor/Bastion institutions have no separate training host.
training_host=j("state/runtime.json").get("hosts",{}).get("host_house_tang_training",{})
check(
    "house_training_host_is_live",
    isinstance(training_host,dict)
    and training_host.get("kind")=="house_tang_training"
    and training_host.get("owner_ref")=="force_house_tang"
    and training_host.get("next_due") is not None,
)
legal_house_training={"train.house_tang.house_infantry","train.house_tang.house_infantry_outer_wall","train.house_tang.house_cavalry"}
house_training_bad=[]
for path in sorted((ROOT/"state/formations").glob("*.json")):
    formation=json.loads(path.read_text(encoding="utf-8"))
    if formation.get("owner_force_ref")!="force_house_tang": continue
    if formation.get("training_ref") not in legal_house_training:
        house_training_bad.append((formation.get("formation_ref"),formation.get("training_ref")))
check("house_tang_training_uses_current_two_role_programs", not house_training_bad, str(house_training_bad[:12]))

cohort_counter_missing=[]
for force_path in sorted((ROOT/"state/forces").glob("*.json")):
    force=json.loads(force_path.read_text(encoding="utf-8"))
    cohorts=force.get("cohort_ledger",{}).get("cohorts",{}) if isinstance(force,dict) else {}
    if not isinstance(cohorts,dict): continue
    for cohort_ref,cohort in sorted(cohorts.items()):
        if not isinstance(cohort,dict) or not (cohort.get("skill_means") or cohort.get("attribute_means")): continue
        if "verified_training_hours_per_person" not in cohort or "verified_role_exposure_hours_per_person" not in cohort:
            cohort_counter_missing.append((force.get("owner_id"),cohort_ref))
check("aggregate_cohort_current_training_counters_complete", not cohort_counter_missing, str(cohort_counter_missing[:12]))

training_chain_mismatches=[]
for formation_path in sorted((ROOT/"state/formations").glob("*.json")):
    formation=json.loads(formation_path.read_text(encoding="utf-8"))
    if formation.get("owner_force_ref")!="force_house_tang": continue
    targets=_target_billets(formation)
    active=officer_cadre_summary(formation).get("active_billets",{})
    if not isinstance(active,dict):
        training_chain_mismatches.append((formation.get("formation_ref"),"missing_officer_cadre")); continue
    bad={rank:(int(active.get(rank,0) or 0),int(target)) for rank,target in targets.items() if int(active.get(rank,0) or 0)!=int(target)}
    if bad: training_chain_mismatches.append((formation.get("formation_ref"),bad))
check("house_tang_training_chains_staffed", not training_chain_mismatches, str(training_chain_mismatches[:12]))

# Skill ontology is 21 universal military skills plus sparse professional disciplines.
# Persisting professional zeroes in every person/cohort recreates the old broad matrix.
stat_profile = j("game/data/mechanics/stat-orders.json").get("profiles", {}).get("military_person", {})
core_skill_set = set(stat_profile.get("skill_order", [])) if isinstance(stat_profile, dict) else set()
professional_skill_set = set(stat_profile.get("professional_skill_order", [])) if isinstance(stat_profile, dict) else set()
skill_partition_violations = []
for person_path in [ROOT / "state/player.json", *sorted((ROOT / "state/char").glob("*.json"))]:
    person = json.loads(person_path.read_text(encoding="utf-8"))
    skills = person.get("skills", {}) if isinstance(person, dict) else {}
    professional = person.get("professional_skills", {}) if isinstance(person, dict) else {}
    if not isinstance(skills, dict) or set(skills) != core_skill_set:
        skill_partition_violations.append((str(person_path.relative_to(ROOT)), "core", len(skills) if isinstance(skills, dict) else None))
    if not isinstance(professional, dict) or not set(professional).issubset(professional_skill_set) or any(float(v) == 0.0 for v in professional.values()):
        skill_partition_violations.append((str(person_path.relative_to(ROOT)), "professional"))
for shard_path in sorted((ROOT / "state/person/person-lite").glob("*.json")):
    shard = json.loads(shard_path.read_text(encoding="utf-8"))
    records = shard.get("records", {}) if isinstance(shard, dict) else {}
    rows = records.values() if isinstance(records, dict) else records if isinstance(records, list) else []
    for person in rows:
        if not isinstance(person, dict):
            continue
        stats = person.get("stats", {}) if isinstance(person.get("stats"), dict) else {}
        skills = stats.get("skills", {}) if isinstance(stats, dict) else {}
        professional = person.get("professional_skills", {})
        if not isinstance(skills, dict) or set(skills) != core_skill_set:
            skill_partition_violations.append((person.get("id"), "person_lite_core", len(skills) if isinstance(skills, dict) else None))
        if professional and (not isinstance(professional, dict) or not set(professional).issubset(professional_skill_set) or any(float(v) == 0.0 for v in professional.values())):
            skill_partition_violations.append((person.get("id"), "person_lite_professional"))
for force_path in sorted((ROOT / "state/forces").glob("*.json")):
    force = json.loads(force_path.read_text(encoding="utf-8"))
    cohorts = force.get("cohort_ledger", {}).get("cohorts", {}) if isinstance(force, dict) else {}
    if not isinstance(cohorts, dict):
        continue
    for cohort_ref, cohort in cohorts.items():
        if not isinstance(cohort, dict):
            continue
        core = cohort.get("skill_means", {})
        professional = cohort.get("professional_skill_means", {})
        if isinstance(core, dict) and set(core) & professional_skill_set:
            skill_partition_violations.append((cohort_ref, "cohort_core_contains_professional"))
        if professional and (not isinstance(professional, dict) or not set(professional).issubset(professional_skill_set) or any(float(v) == 0.0 for v in professional.values())):
            skill_partition_violations.append((cohort_ref, "cohort_professional"))
# Mercenary troop-pool capability uses the same current ontology. Core values
# are a 21-position vector under stat-orders; professional disciplines are a
# sparse named map. Legacy 35-position vectors are not a supported hot-state
# representation in current campaign state.
for merc_path in sorted((ROOT / "state/merc").glob("*.json")):
    try:
        merc = json.loads(merc_path.read_text(encoding="utf-8"))
    except Exception:
        continue
    for pool in merc.get("troop_pools", []) if isinstance(merc, dict) else []:
        if not isinstance(pool, dict):
            continue
        caps = pool.get("capability", {}).get("capabilities", {}) if isinstance(pool.get("capability"), dict) else {}
        if not isinstance(caps, dict) or "skill_values" not in caps:
            continue
        values = caps.get("skill_values")
        professional = caps.get("professional_skill_values", {})
        if not isinstance(values, list) or len(values) != len(core_skill_set):
            skill_partition_violations.append((str(merc_path.relative_to(ROOT)), pool.get("id", pool.get("role")), "mercenary_core_vector", len(values) if isinstance(values, list) else None))
        if professional and (not isinstance(professional, dict) or not set(professional).issubset(professional_skill_set) or any(float(v) == 0.0 for v in professional.values())):
            skill_partition_violations.append((str(merc_path.relative_to(ROOT)), pool.get("id", pool.get("role")), "mercenary_professional"))

profiles = j("game/data/mil/recruitment-cohort-profiles.json")
for profile_ref, profile_row in (profiles.get("background_profiles", {}) if isinstance(profiles, dict) else {}).items():
    if not isinstance(profile_row, dict):
        continue
    if set(profile_row.get("skill_means", {})) & professional_skill_set:
        skill_partition_violations.append((profile_ref, "background_core_contains_professional"))
    professional = profile_row.get("professional_skill_means", {})
    if professional and (not isinstance(professional, dict) or not set(professional).issubset(professional_skill_set)):
        skill_partition_violations.append((profile_ref, "background_professional"))
check("core_and_professional_skill_state_is_partitioned", not skill_partition_violations, str(skill_partition_violations[:12]))


# Unified House Tang current-authority cleanup. Historical cohort/provenance IDs
# may retain old institutional names, but hot force/population authority may not.
_house_force = j("state/forces/house-tang.json")
_house_auth = _house_force.get("formation_authorizations")
_house_scope = str((_house_force.get("infrastructure") or {}).get("support_scope", "")) if isinstance(_house_force.get("infrastructure"), dict) else ""
_house_auth_errors = []
if isinstance(_house_auth, dict) and any(int(v) > 0 for v in _house_auth.values()):
    _house_auth_errors.append(("live_formation_authorizations", _house_auth))
if any(token in _house_scope for token in ("Bastion Corps", "Sword Manor", "Tang Champions", "House Guard")):
    _house_auth_errors.append(("retired_support_scope", _house_scope))
check("house_tang_hot_authority_has_no_retired_formation_authorizations", not _house_auth_errors, str(_house_auth_errors[:8]))

_qin_population = j("state/population/qin.json")
_tang_row = (((_qin_population.get("local_population") or {}).get("sites") or {}).get("loc_tang_manor") or {}) if isinstance(_qin_population, dict) else {}
_tang_allocations = _tang_row.get("service_allocations", {}) if isinstance(_tang_row, dict) else {}
_tang_service_errors = []
if not isinstance(_tang_allocations, dict) or set(_tang_allocations) != {"force_house_tang"}:
    _tang_service_errors.append(("allocation_keys", sorted(_tang_allocations) if isinstance(_tang_allocations, dict) else None))
else:
    _alloc = _tang_allocations["force_house_tang"]
    _sources = _alloc.get("source_strata", {}) if isinstance(_alloc, dict) else {}
    if int(_alloc.get("personnel", -1)) != 176060:
        _tang_service_errors.append(("personnel", _alloc.get("personnel")))
    if _alloc.get("exact_force_owner_ref") != "force_house_tang" or _alloc.get("service_class") != "private_house_military":
        _tang_service_errors.append(("owner_or_class", _alloc.get("exact_force_owner_ref"), _alloc.get("service_class")))
    if not isinstance(_sources, dict) or {str(k): int(v) for k, v in _sources.items()} != {"agricultural": 36060, "private_household_military": 140000}:
        _tang_service_errors.append(("source_strata", _sources))
    if sum(int(v) for v in _sources.values()) != int(_alloc.get("personnel", 0)):
        _tang_service_errors.append(("source_total", _sources, _alloc.get("personnel")))
check("house_tang_local_service_allocation_is_unified_with_exact_provenance", not _tang_service_errors, str(_tang_service_errors[:8]))

_service_provenance_errors = []
for _pop_path in sorted((ROOT / "state/population").glob("*.json")):
    try:
        _pop = json.loads(_pop_path.read_text(encoding="utf-8"))
    except Exception:
        continue
    _sites = ((_pop.get("local_population") or {}).get("sites") or {}) if isinstance(_pop, dict) else {}
    if not isinstance(_sites, dict):
        continue
    for _loc, _row in _sites.items():
        _allocs = _row.get("service_allocations", {}) if isinstance(_row, dict) else {}
        if not isinstance(_allocs, dict):
            continue
        for _owner, _rec in _allocs.items():
            if not isinstance(_rec, dict) or not isinstance(_rec.get("source_strata"), dict):
                continue
            _source_total = sum(max(0, int(v)) for v in _rec["source_strata"].values())
            if _source_total != max(0, int(_rec.get("personnel", 0))):
                _service_provenance_errors.append((str(_pop_path.relative_to(ROOT)), _loc, _owner, _source_total, _rec.get("personnel")))
check("local_service_source_strata_conserve_personnel", not _service_provenance_errors, str(_service_provenance_errors[:12]))

_duan = j("state/char/duan-jin.json")
_duan_live = json.dumps(_duan.get("goal_state", {}), ensure_ascii=False)
check(
    "duan_jin_live_goals_follow_red_lance_command",
    "formation_red_lance_a" in _duan_live and "Tang Champions" not in _duan_live and "formation_tang_champions_first" not in _duan_live,
    _duan_live,
)

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
        if base.startswith("state/institutions/regional-") and "#/records/" in str(route):
            state_key = base.rsplit("regional-", 1)[-1].removesuffix(".json")
            if f"state_{state_key}" not in host_owners_by_kind.get("institution_bundle", set()):
                core_missing.append((owner_ref, "institution_bundle", base))
            continue
        expected_kind = "institution"
    elif base.startswith("state/houses/"):
        expected_kind = "house"
    elif base.startswith("state/factions/"):
        expected_kind = "faction"
    elif base.startswith("state/char/"):
        try:
            _person_owner = j(base)
        except Exception:
            _person_owner = {}
        if str(_person_owner.get("life_status", _person_owner.get("status", "active"))).lower() not in {"dead", "deceased"}:
            expected_kind = "person"
    elif base.startswith("state/merc/") and str(owner_ref).startswith("merc_"):
        # Background/accounting-only mercenary market rows intentionally have no
        # independent scheduler clock. Tactical/materialized companies do.
        try:
            _merc_owner = j(base)
        except Exception:
            _merc_owner = {}
        if not bool(_merc_owner.get("accounting_only")):
            expected_kind = "mercenary"
    elif base.startswith("state/population/"):
        try:
            _population_owner = j(base)
        except Exception:
            _population_owner = {}
        _demography = _population_owner.get("demography") if isinstance(_population_owner, dict) else None
        if isinstance(_demography, dict) and _demography.get("birth_rate_per_thousand") is not None and _demography.get("death_rate_per_thousand") is not None:
            expected_kind = "population"
    if expected_kind and owner_ref not in host_owners_by_kind.get(expected_kind, set()):
        core_missing.append((owner_ref, expected_kind, base))
check("core_autonomous_owners_have_scheduler_hosts", not core_missing, str(core_missing[:12]))

# Operational battlefield chronology is routed only through operations that
# actually own a currently active tactical battlefield.  This projection must
# be exact: missing refs would skip causal work, while extra refs reintroduce
# world-scale scans during long time advancement.
operation_index = j("state/operations/index.json")
operation_routes = operation_index.get("active_battlefield_operation_refs", [])
operation_paths = operation_index.get("operations", {})
expected_battlefield_routes = set()
battlefield_route_errors = []
if not isinstance(operation_routes, list) or not isinstance(operation_paths, dict):
    battlefield_route_errors.append("invalid_operation_battlefield_routing_shape")
else:
    for operation_ref, operation_path in operation_paths.items():
        if not isinstance(operation_ref, str) or not isinstance(operation_path, str) or not (ROOT / operation_path).is_file():
            battlefield_route_errors.append(("invalid_operation_route", operation_ref, operation_path))
            continue
        operation = j(operation_path)
        battlefields = operation.get("battlefields", {})
        has_active = (
            operation.get("status") in {"active", "engaged"}
            and isinstance(battlefields, dict)
            and any(isinstance(row, dict) and row.get("status") == "active" for row in battlefields.values())
        )
        if has_active:
            expected_battlefield_routes.add(operation_ref)
    actual_battlefield_routes = {ref for ref in operation_routes if isinstance(ref, str) and ref}
    if len(actual_battlefield_routes) != len(operation_routes):
        battlefield_route_errors.append("duplicate_or_invalid_active_battlefield_route")
    if actual_battlefield_routes != expected_battlefield_routes:
        battlefield_route_errors.append(("route_mismatch", sorted(actual_battlefield_routes), sorted(expected_battlefield_routes)))
check("active_battlefield_operation_routing_exact", not battlefield_route_errors, str(battlefield_route_errors[:8]))

# The House Tang collapse must retain every current fighting body in an exact
# cohort slice. The prior migration briefly left 165 dematerialized internal
# officers in reserve while their formations still counted those bodies. Named
# top commanders are external exact people, so no duplicate aggregate Unit-
# command attachment may remain for these current House formations.
_house_force = j("state/forces/house-tang.json")
_house_assignments = _house_force.get("materialized_assignments", {}) if isinstance(_house_force.get("materialized_assignments"), dict) else {}
_house_cohort_errors = []
_house_named_external = []
for _formation_path in sorted((ROOT / "state/formations").glob("*.json")):
    _formation = json.loads(_formation_path.read_text(encoding="utf-8"))
    if _formation.get("owner_force_ref") != "force_house_tang":
        continue
    _ref = str(_formation.get("formation_ref", ""))
    _sliced = sum(int(row.get("count", 0)) for row in _formation.get("cohort_composition", []) if isinstance(row, dict))
    _inside = sum(
        max(1, int(row.get("personnel", 1)))
        for row in _house_assignments.values()
        if isinstance(row, dict) and row.get("formation_ref") == _ref
    )
    if _sliced + _inside != int(_formation.get("personnel", 0)):
        _house_cohort_errors.append((_ref, _sliced, _inside, int(_formation.get("personnel", 0))))
    if _formation.get("commander_ref") and _ref in _house_force.get("external_personnel_allocations", {}):
        _house_named_external.append((_ref, _formation.get("commander_ref"), _house_force["external_personnel_allocations"][_ref]))
check("house_tang_formation_cohort_slices_cover_all_fighting_bodies", not _house_cohort_errors, str(_house_cohort_errors[:12]))
check("house_tang_named_commanders_have_no_duplicate_aggregate_unit_command_body", not _house_named_external, str(_house_named_external[:12]))

if FAILURES:
    print(f"\nvalidate_release: FAIL ({len(FAILURES)}/{CHECKS})")
    for failure in FAILURES: print(" - "+failure)
    raise SystemExit(1)
print(f"\nvalidate_release: PASS ({CHECKS} checks)")
