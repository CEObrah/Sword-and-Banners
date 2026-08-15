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

# Mutable owner routing.
owner_index=j("state/index/owner-index.json")
owners=owner_index.get("owners",{})
broken=[(k,v) for k,v in owners.items() if not (ROOT/v).is_file()]
missing=[]
for path in all_json(ROOT/"state"):
    value=json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value,dict):
        oid=value.get("owner_id")
        if isinstance(oid,str) and oid and oid not in owners:
            missing.append((oid,path.relative_to(ROOT).as_posix()))
check("owner_routes_exist", not broken, str(broken[:8]))
check("all_top_level_owner_ids_routed", not missing, str(missing[:8]))

# Current transaction state and campaign chronology.
meta=j("state/meta.json")
check("campaign_revision_valid", isinstance(meta.get("revision"), int) and meta.get("revision") >= 0)
check("world_time_present", isinstance(meta.get("time"),str) and "BCE" in meta["time"])
invalidations=j("runtime/contracts/transaction-invalidations.json")
check("transaction_invalidation_registry_valid", isinstance(invalidations, dict))

# Force/population conservation and theater liveness.
for state in ("qin","zhao","chu","wei","han","yan","qi"):
    pop=j(f"state/population/{state}.json")
    check(f"population_conserved:{state}", sum(int(v) for v in pop.get("strata",{}).values()) == int(pop.get("population_total",-1)))
    force=j(f"state/forces/state-{state}.json")
    available=sum(int(v) for v in force.get("available_by_role",{}).values())
    allocated=sum(int(v.get("personnel",0)) if isinstance(v,dict) else int(v) for v in force.get("allocated_to_formations",{}).values())
    materialized=sum(int(v.get("personnel",1)) if isinstance(v,dict) else int(v) for v in force.get("materialized_people",{}).values())
    check(f"force_conserved:{state}", available+allocated+materialized == int(force.get("headcount",-1)))
    mounts=j(f"state/mounts/{state}.json")
    check(f"mount_pool_conserved:{state}", sum(int(v) for v in mounts.get("types",{}).values()) == int(mounts.get("total",-1)))

for theater in j("game/data/world/autonomous-theaters.json").get("theaters",[]):
    refs=list(theater.get("formation_refs",{}).values())
    check(f"theater_formations_routed:{theater.get('theater_ref')}", all(ref in owners for ref in refs))

# Tang Champion and personal-retinue representation invariants.
champ=j("state/formations/tang-champions-first.json")
check("single_tang_champion_formation", champ.get("personnel")==100 and not (ROOT/"state/formations/tang-champions-second.json").exists())
check("champion_material_owner", champ.get("owner_force_ref")=="force_house_tang" and champ.get("administrative_owner")=="house_tang")
check("champion_assignment_authority", champ.get("command_authority")=="char_tang_wei" and champ.get("commander_ref")=="char_duan_jin" and champ.get("deputy_ref")=="char_shen_rui")
check("champion_tang_horses", champ.get("mounts")=={"horse_tang_heavy_war":100})
check("no_champion_individual_roster", not (ROOT/"state/personnel/house-tang-champions.json").exists())
pforce=j("state/pforce/wei.json")
check("champions_assigned_not_owned", "formation_tang_champions_first" in pforce.get("assigned_formations",[]) and not pforce.get("permanent_formations"))
policy_text = json.dumps(pforce.get("policy",{})).lower()
check("personal_recruits_cohort_first_policy", "cohort" in policy_text and "selective" in policy_text)
check("personal_recruit_campaign_runtime_present", (ROOT/"runtime/sword_runtime/recruitment_campaigns.py").is_file())
check("obsolete_exact_intake_runtime_absent", not (ROOT/"runtime/sword_runtime/personal_recruits.py").exists())

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
