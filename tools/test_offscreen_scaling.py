from pathlib import Path
import json,sys
R=Path(__file__).resolve().parents[1]
errs=[]
def fail(x): errs.append(x)
def rj(rel): return json.loads((R/rel).read_text(encoding="utf-8"))
cat=rj("data/people/latent-identities.json")
if cat.get("schema")!="latent-identity-catalog": fail("catalog_schema")
ids=cat.get("identities",{})
if len(ids)!=cat.get("count"): fail("catalog_count")
if (R/"state/char-roster").exists(): fail("mutable_roster_present")
for cid,rec in ids.items():
    if set(rec)-{"name","source_hint"}: fail("catalog_runtime_bloat:"+cid)
    if not rec.get("name"): fail("catalog_name:"+cid)
roles=rj("state/app/role-slots.json")
if roles.get("schema")!="role-slot-registry": fail("role_schema")
required={"role.house_tang.warehouse_granary_chief","role.house_tang.forge_master","role.house_tang.chief_administrator","role.house_tang.stable_remount_master","role.house_tang.agricultural_director","role.house_tang.chief_physician","role.house_tang.estate_accountant","role.house_tang.armorer","role.house_tang.senior_scribe","role.house_tang.intelligence_contact_manager","role.house_tang.physician_assistant","role.house_tang.caravan_broker","role.house_tang.works_planner","role.house_tang.stable_deputy","role.sword_manor.escort_captain","role.sword_manor.senior_instructor"}
if set(roles.get("roles",{}))!=required: fail("role_set")
for rid,slot in roles.get("roles",{}).items():
    inc=slot.get("incumbent")
    if inc:
        raw=json.dumps(inc).lower()
        for bad in ("name","personality","biography","relationship","inventory","birth_date","skills"):
            if bad in inc: fail(f"role_secret_person_state:{rid}:{bad}")
        if inc.get("representation")=="anonymous_role_incumbent" and inc.get("materialized_character_id") is not None: fail("anonymous_role_bound:"+rid)
old=["state/char/gu-wen.json","state/char/han-qiao.json","state/char/lu-zhen.json","state/char/ma-xun.json","state/char/tian-yu.json","state/char/lin-mei.json","state/person/staff/staff-tang-chen_yu.json","state/person/staff/staff-tang-gao_fen.json","state/person/staff/staff-tang-he_mei.json","state/person/staff/staff-tang-liu_fang.json","state/person/staff/staff-tang-luo_min.json","state/person/staff/staff-tang-sun_qiao.json","state/person/staff/staff-tang-xie_an.json","state/person/staff/staff-tang-zhang_ren.json","state/prog/tang-named-staff-training.json","state/life/identity-life-course.json"]
for rel in old:
    if (R/rel).exists(): fail("obsolete_owner:"+rel)
for p in (R/"state/char").glob("*.json"):
    if rj(p.relative_to(R).as_posix()).get("runtime_status")=="cold_profile_definition": fail("cold_runtime_status:"+p.name)
fort=rj("state/geo/strategic-fortifications.json")
if fort.get("schema")!="strategic-fortification-registry": fail("fort_schema")
for loc in ("loc_kanyou","loc_kankoku_pass","loc_gyou"):
    s=fort.get("sites",{}).get(loc)
    if not s or s.get("materialization_state")!="profile_only": fail("fort_profile:"+loc)
    if "defense_state" in (s or {}): fail("invented_fort_detail:"+loc)
if "materialize" not in (R/"rules/siege.md").read_text(encoding="utf-8").lower(): fail("siege_materialization_rule")
if errs:
    print("OFFSCREEN SCALING TEST FAILED")
    for e in errs: print("-",e)
    sys.exit(1)
print("OFFSCREEN SCALING TEST OK")
print(f"source_names={len(ids)} live_role_slots={sum(1 for s in roles['roles'].values() if s.get('status')=='occupied')} capacity_role_groups={sum(1 for s in roles['roles'].values() if s.get('status')=='capacity_only')} strategic_profiles={len(fort['sites'])}")
