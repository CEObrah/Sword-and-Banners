#!/usr/bin/env python3
from __future__ import annotations
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')

def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding='utf-8')

def load(rel: str):
    return json.loads(read(rel))

def save(rel: str, obj) -> None:
    write(rel, json.dumps(obj, ensure_ascii=False, indent=2) + '\n')

def replace(rel: str, old: str, new: str, *, required: bool = False) -> None:
    s = read(rel)
    if old not in s:
        if required:
            raise SystemExit(f'missing required pattern in {rel}: {old[:100]!r}')
        return
    write(rel, s.replace(old, new))

# ------------------------------------------------------------------
# Active mutable/static terminology: Sword Manor -> physical Inner Walls.
# ------------------------------------------------------------------
p = 'state/population/tang-manor.json'; d = load(p)
strata = d.setdefault('strata', {})
if 'sword_manor_civilian_medical' in strata:
    strata['inner_walls_civilian_medical'] = int(strata.pop('sword_manor_civilian_medical'))
dem = d.get('demography', {})
if isinstance(dem, dict) and isinstance(dem.get('working_strata'), list):
    dem['working_strata'] = ['inner_walls_civilian_medical' if x == 'sword_manor_civilian_medical' else x for x in dem['working_strata']]
rr = d.get('recruitment_runtime', {})
if isinstance(rr, dict) and 'last_sword_manor_intake' in rr:
    rr['last_inner_walls_intake'] = rr.pop('last_sword_manor_intake')
d.pop('sword_manor', None)
save(p, d)

p = 'state/art/tang-manor-artillery.json'; d = load(p)
dist = d.get('derivation', {}).get('trebuchet_distribution', {}) if isinstance(d.get('derivation'), dict) else {}
if isinstance(dist, dict) and 'sword_manor' in dist:
    dist['inner_walls'] = dist.pop('sword_manor')
save(p, d)

p = 'game/data/world/tang-manor-master-plan.json'; d = load(p)
if 'sword_manor' in d and 'inner_walls' not in d:
    d['inner_walls'] = d.pop('sword_manor')
save(p, d)

p = 'state/runtime.json'; d = load(p)
for row in d.get('events', []):
    if isinstance(row, dict) and row.get('event_id') == 'event_host_sword_manor_review' and row.get('target_host') in {'host_house_tang_development','host_house_tang_training'}:
        row['event_id'] = 'event_host_house_tang_training_review'
        row['kind'] = 'institution_review'
save(p, d)

replace('runtime/sword_runtime/tang_population.py', 'SWORD_MANOR_REF = "loc_tang_inner_walls"', 'INNER_WALLS_REF = "loc_tang_inner_walls"')
replace('runtime/sword_runtime/tang_population.py', '"camp_medical_support": ("sword_manor_civilian_medical",),', '"camp_medical_support": ("inner_walls_civilian_medical",),')
replace('runtime/sword_runtime/tang_population.py', 'SWORD_MANOR_REF', 'INNER_WALLS_REF')

p = 'game/schemas/sword-population.schema.json'; d = load(p)
d.get('properties', {}).pop('sword_manor', None)
save(p, d)

# ------------------------------------------------------------------
# Current player-facing household routing.
# ------------------------------------------------------------------
p = 'runtime/sword_runtime/api/household_operations.py'; s = read(p)
s = s.replace('_SWORD_MANOR_REF = "force_sword_manor"\n_PLAYER_RETINUE_ROOT = "cmdgrp.tang_wei.personal_force"', '_INNER_WALLS_COMMAND_REF = "cmdgrp.house_tang.inner_walls"\n_PLAYER_RETINUE_ROOT = "cmdgrp.tang_wei.field_army"')
s = s.replace('_SWORD_MANOR_REF', '_INNER_WALLS_COMMAND_REF')
s = s.replace('Inner Walls is an exact House Tang military-force owner.', 'Inner Walls is an exact House Tang command owner.')
s = s.replace('"relation": "House Tang military force",', '"relation": "House Tang Inner Walls command",')
write(p, s)

replace('runtime/sword_runtime/api/command_discovery.py', '("institutions", ("institution_", "house_", "commission_", "sword_manor_")),', '("institutions", ("institution_", "house_", "commission_", "inner_walls_")),')

# ------------------------------------------------------------------
# Retire Bastion as a personnel institution/command surface.
# ------------------------------------------------------------------
replace('runtime/sword_runtime/production_planner.py', 'from sword_runtime.bastion_personnel import BastionPersonnelLifecycleMixin\n', '')
replace('runtime/sword_runtime/production_planner.py', '    BastionPersonnelLifecycleMixin,\n', '')
replace('runtime/sword_runtime/command_integration.py', '    "_command_layer_bastion_personnel",\n', '')

p = 'runtime/sword_runtime/api/input_guidance.py'; s = read(p)
s = s.replace('["assign_duty", "set_policy", "grant_nobility", "proclaim_territorial_authority", "accept_bastion_applicants"]', '["assign_duty", "set_policy", "grant_nobility", "proclaim_territorial_authority"]')
for line in [
'        "corps_key": {"allowed_values": ["iron_wall", "red_thunder", "white_blade", "stone_spear"], "applies_to": ["accept_bastion_applicants"]},\n',
'        "source_state": {"allowed_values": ["qin", "zhao", "chu", "wei", "han", "yan", "qi", "jo"], "applies_to": ["accept_bastion_applicants"]},\n',
'        "source_site_ref": {"rule": "exact demographic origin outside Tang Manor with a physical route to loc_tang_manor", "applies_to": ["accept_bastion_applicants"]},\n',
'        "applicant_count": {"type": "integer", "minimum": 1, "maximum": 10000, "rule": "accepted for relocation and later consideration only; does not guarantee selection, qualification, or appointment", "applies_to": ["accept_bastion_applicants"]},\n',
]: s = s.replace(line, '')
write(p, s)

p = 'runtime/sword_runtime/engine.py'; s = read(p)
s = s.replace('allowed={"assign_duty","set_policy","grant_nobility","proclaim_territorial_authority","accept_bastion_applicants"}', 'allowed={"assign_duty","set_policy","grant_nobility","proclaim_territorial_authority"}')
old = '''            elif action=="accept_bastion_applicants":\n                require_text(payload,"corps_key",allowed={"iron_wall","red_thunder","white_blade","stone_spear"})\n                source_state=require_text(payload,"source_state",allowed={"qin","zhao","chu","wei","han","yan","qi","jo"})\n                source_site=require_text(payload,"source_site_ref"); self._location_record(source_site)\n                if not isinstance(self.read_optional(f"state/population/{source_state}.json"),Mapping): raise ValueError("outside applicant source population is not represented")\n                require_int(payload,"applicant_count",minimum=1,maximum=10000)\n'''
s = s.replace(old, '')
s = s.replace('{"force_house_tang", "force_sword_manor", "force_tang_wei_personal"}', '{"force_house_tang", "force_tang_wei_personal"}')
write(p, s)

bastion_py = ROOT / 'runtime/sword_runtime/bastion_personnel.py'
if bastion_py.exists(): bastion_py.unlink()

# ------------------------------------------------------------------
# No House troop-species promotion ladder remains.
# ------------------------------------------------------------------
write('runtime/sword_runtime/training_promotion.py', '''"""Promotion-aware training hooks.\n\nHouse Tang troop species no longer form a prestige evolution ladder. Durable military\nrank and command-billet progression are owned by the career/command systems. This\nhook therefore contributes no troop-role promotion thresholds.\n"""\nfrom __future__ import annotations\nfrom collections.abc import Mapping\nfrom typing import Any\n\ndef exact_promotion_facts(runtime: Any, person: Mapping[str, Any]) -> Mapping[str, Any]:\n    return {}\n\n__all__ = ["exact_promotion_facts"]\n''')

p = 'runtime/sword_runtime/force_cohort_living_world.py'; s = read(p)
start = s.index(' def _fc_promotion_facts(')
end = s.index('\n def _fc_regimen(', start)
s = s[:start] + ''' def _fc_promotion_facts(self, force: Mapping[str, Any], role: str) -> Mapping[str, Any]:\n  # Troop species do not promote into other species. Officer/rank progression is\n  # handled by the dedicated military career and command owners.\n  return {}\n''' + s[end:]
write(p, s)

# ------------------------------------------------------------------
# Unified House training/capability branches only.
# ------------------------------------------------------------------
replace('runtime/sword_runtime/standing_force_capability.py', '        if owner == "force_sword_manor":\n            return self.read("game/data/mil/sword-manor-cohort-profiles.json")\n', '')
replace('runtime/sword_runtime/downtime.py', '{"force_house_tang", "force_sword_manor"}', '{"force_house_tang"}')
replace('runtime/sword_runtime/standing_training.py', '{"force_house_tang", "force_sword_manor"}', '{"force_house_tang"}')
replace('runtime/sword_runtime/player_group_actions.py', '{"force_house_tang", "force_sword_manor", "force_tang_wei_personal"}', '{"force_house_tang", "force_tang_wei_personal"}')
replace('runtime/sword_runtime/cohort_tx_support.py', '("cavalry", "mounted", "house_champion", "guardian_cavalry")', '("cavalry", "mounted")')
replace('runtime/sword_runtime/cohort_tx_support.py', '{"force_house_tang", "force_sword_manor"}', '{"force_house_tang"}')
replace('runtime/sword_runtime/army_organization.py', 'if authority in {"house_tang", "force_sword_manor"}:', 'if authority == "house_tang":')

p = 'runtime/sword_runtime/service_runtime.py'; s = read(p)
s = s.replace('any(token in formation_ref for token in ("house_tang", "sword_manor", "tang_champion", "house_guard"))', 'any(token in formation_ref for token in ("house_tang", "red_lance", "high_guard"))')
s = s.replace('program_ref.startswith(("program.sword_", "program.commander_champion", "program.commander_guard", "program.commander_cavalry", "program.bastion_", "program.tang_field_"))', 'program_ref.startswith(("program.house_infantry", "program.house_cavalry", "program.commander_cavalry", "program.tang_field_"))')
write(p, s)

p = 'runtime/sword_runtime/warfare_depth_integrity.py'; s = read(p)
s = s.replace('_SCOPED_OWNER_FORCES = frozenset({"force_house_tang", "force_sword_manor"})', '_SCOPED_OWNER_FORCES = frozenset({"force_house_tang"})')
s = s.replace('return "house_or_sword_institution_wide"', 'return "house_tang_institution_wide"')
s = s.replace('"loadout_ref": "loadout_house_guard",', '"loadout_ref": "loadout_tang_foot",')
s = s.replace('"House Tang and Inner Walls inherit one full-character persistent unit commander "', '"House Tang formations inherit one full-character persistent unit commander "')
write(p, s)

# ------------------------------------------------------------------
# Civil-world dynamic House-backed forces use generic household retainers.
# ------------------------------------------------------------------
p = 'runtime/sword_runtime/civil_world.py'; s = read(p)
s = s.replace('''        if str(inst.get("owner_id")) == "force_sword_manor":\n            return "state/treasury/treasury-house-tang.json", copy.deepcopy(self.read("state/treasury/treasury-house-tang.json")), "qin"\n''', '')
s = s.replace('add_recruits(force, "house_guard", recruits, location_ref=str(location_ref))', 'add_recruits(force, "household_retainer", recruits, location_ref=str(location_ref))')
s = s.replace('record_recruitment_cohort(force, role="house_guard", count=recruits,', 'record_recruitment_cohort(force, role="household_retainer", count=recruits,')
s = s.replace('''        if str(host.get("owner_ref")) == "force_sword_manor":\n            super()._autonomy_institution(host, occurrences, at)\n            return\n''', '')
write(p, s)

# ------------------------------------------------------------------
# Current doctrine defaults only.
# ------------------------------------------------------------------
p = 'runtime/sword_runtime/military_doctrine.py'; s = read(p)
start = s.index('def default_formation_doctrine_ref(')
end = s.index('\n\ndef default_command_group_doctrine_ref(', start)
new_form = '''def default_formation_doctrine_ref(formation: Mapping[str, Any]) -> str:\n    """Choose one registered doctrine from ownership and actual role mix."""\n    admin = str(formation.get("administrative_owner") or "")\n    force_ref = str(formation.get("owner_force_ref") or "")\n    role = _dominant_role(formation).lower()\n\n    if admin in {"polity_northern_steppe", "state_northern_steppe"}:\n        return "doc.organization.steppe_confederation"\n    if admin in {"polity_yotanwa_confederation", "state_yotanwa_confederation"}:\n        return "doc.organization.mountain_force"\n    if admin in {"polity_quanrong", "state_quanrong"}:\n        return "doc.organization.raider_band"\n    if admin == "house_tang" or force_ref.startswith("force_house_tang") or force_ref == "force_tang_wei_personal":\n        if "cavalry" in role or "mounted" in role:\n            return "doc.house_tang.house_cavalry"\n        return "doc.house_tang.house_infantry"\n    if admin.startswith("house_") or force_ref.startswith("force_house_"):\n        return "household_combined_arms"\n    if admin.startswith("state_"):\n        if "chariot" in role:\n            return "doc.external_state_force.chariot"\n        if "heavy_cavalry" in role:\n            return "doc.external_state_force.heavy_cavalry"\n        if "mounted_archer" in role:\n            return "doc.external_state_force.mounted_archer"\n        if "cavalry" in role or "mounted" in role:\n            return "doc.external_state_force.cavalry"\n        if role == "archer" or role.endswith("_archer"):\n            return "doc.external_state_force.archer"\n        if any(token in role for token in ("missile", "crossbow")):\n            return "doc.external_state_force.missile_crossbow"\n        return "doc.external_state_force.line_infantry"\n    return "doc.world_force.standard"\n'''
s = s[:start] + new_form + s[end:]
start = s.index('def default_command_group_doctrine_ref(')
end = s.index('\n\n\ndef formation_doctrine_ref_for_role', start)
new_group = '''def default_command_group_doctrine_ref(group: Mapping[str, Any]) -> str:\n    """Return the standing command doctrine for one zero-body army command."""\n    existing = group.get("standing_doctrine_ref")\n    if isinstance(existing, str) and existing:\n        return existing\n    ref = str(group.get("id") or "")\n    authority = str(group.get("authority_ref") or "")\n    context = str(group.get("context") or "").lower()\n    if ref == "cmdgrp.tang_wei.field_army":\n        return "doc.tang_wei.field_army"\n    if authority.startswith("state_"):\n        state = authority.removeprefix("state_").lower()\n        if state in _STATE_ARMY_DOCTRINES:\n            return _STATE_ARMY_DOCTRINES[state]\n    if authority == "house_tang" or ref.startswith("cmdgrp.house_tang"):\n        return "doc.house_tang.core"\n    if authority == "pforce.tang_wei" or ref == "cmdgrp.tang_wei.personal_force":\n        return "doc.house_tang.core"\n    if authority.startswith("house_") or context == "private_house_field_army":\n        return "household_combined_arms"\n    return "doc.world_force.standard"\n'''
s = s[:start] + new_group + s[end:]
write(p, s)

# ------------------------------------------------------------------
# House Tang development: preserve only unified training + current expansion.
# ------------------------------------------------------------------
p = 'runtime/sword_runtime/house_tang_development.py'; s = read(p)
s = s.replace('''Inner Walls, House Guards, Guardian Cavalry, and Tang Champions remain aggregate\ncohorts at Sword & Banners scale. Monthly settlement advances verified cohort\ntraining, moves only eligible conserved headcount through the progression ladder,\nand performs capacity-bounded recruitment without creating people from nothing.\n''', '''House Tang's military population is represented only as House Infantry and House\nCavalry cohorts. Monthly settlement advances verified cohort capability without a\ntroop-species promotion ladder; replacement intake remains capacity-bounded and\nconservation-backed.\n''')
for line in [
'    qualification_capacity,\n','    release_qualified_formation_slices_to_reserve,\n','    transfer_qualified_between_forces,\n','    transfer_qualified_role,\n',
'from sword_runtime.recruitment_campaigns import (\n    PROFILE_PATH as CANDIDATE_PROFILE_PATH,\n    REGISTRY_PATH as CANDIDATE_REGISTRY_PATH,\n    _apportion,\n    _credit_recruitment_payment,\n    _registry as _candidate_registry,\n    _slice_id,\n)\n',
'from sword_runtime.mount_custody import (\n    force_role_horses,\n    regional_horses,\n    release_formation_horses_to_role_reserve,\n    reserve_regional_horses_for_role,\n    transfer_force_role_horses,\n)\n',
'SWORD_FORCE = "state/forces/sword-manor.json"\n',
'BASTION_FORCES = (\n    "state/forces/bastion-iron-wall.json",\n    "state/forces/bastion-red-thunder.json",\n    "state/forces/bastion-white-blade.json",\n    "state/forces/bastion-stone-spear.json",\n)\n',
'SWORD_PROGRESSION = "game/data/mil/sword-manor-progression.json"\n',
'CHAMPION_PROGRESSION = "game/data/mil/house-tang-champion-progression.json"\n',
]: s = s.replace(line, '')
s = s.replace('_EXPANSION_REQUEST_KIND = "sword_manor_infrastructure_expansion"', '_EXPANSION_REQUEST_KIND = "inner_walls_infrastructure_expansion"')
s = s.replace('"sword_manor_civilian_medical": "camp_medical_support",', '"inner_walls_civilian_medical": "camp_medical_support",')
# Remove obsolete promotion helpers from the class.
needle = 'class HouseTangDevelopmentMixin:\n    def _qualified_reserve('
if needle in s:
    a = s.index(needle)
    b = s.index('    @staticmethod\n    def _civil_intake(', a)
    s = s[:a] + 'class HouseTangDevelopmentMixin:\n' + s[b:]
s = s.replace('rules.get("sword_manor_expansion", {})', 'rules.get("inner_walls_expansion", {})')
s = s.replace('project_house_tang_sword_manor_', 'project_house_tang_inner_walls_')
s = s.replace('programs.get("sword_manor_expansion")', 'programs.get("inner_walls_expansion")')
s = s.replace('programs["sword_manor_expansion"]', 'programs["inner_walls_expansion"]')
s = s.replace('house_tang_sword_manor_construction', 'house_tang_inner_walls_construction')
s = s.replace('_perform_house_requested_sword_intake', '_perform_house_requested_military_intake')
s = s.replace('_sword_manor_status', '_house_tang_force_status')
s = s.replace('"sword_manor": status', '"house_force": status')
s = s.replace('key=f"sword_manor_expansion_complete:', 'key=f"inner_walls_expansion_complete:')
s = s.replace("Current physical trainee capacity is {status['physical_trainee_capacity']}, with a 30-day assessment throughput of {status['physical_intake_throughput_30d']}.", "Current practical replacement intake is {status['practical_intake_now']}, with a 30-day assessment throughput of {status['physical_intake_throughput_30d']}.")
write(p, s)

# Fixed emplacement current key only.
replace('runtime/sword_runtime/fortified_site_runtime.py', 'deriv.get("inner_walls_bed_crossbows", deriv.get("sword_manor_bed_crossbows", 0))', 'deriv.get("inner_walls_bed_crossbows", 0)')

# ------------------------------------------------------------------
# Weekly player story flow reads unified House force/status, not extinct ranks.
# ------------------------------------------------------------------
p = 'runtime/sword_runtime/player_story_flow.py'; s = read(p)
s = s.replace('_SWORD_FORCE = "state/forces/sword-manor.json"', '_HOUSE_FORCE = "state/forces/house-tang.json"')
s = s.replace('_SWORD_PROGRESSION = "game/data/mil/sword-manor-progression.json"\n', '')
if 'from sword_runtime.household_request_flow import _house_tang_force_status\n' not in s:
    s = s.replace('from sword_runtime.cohort_personnel import conserved_establishment_role_count\n', 'from sword_runtime.cohort_personnel import conserved_establishment_role_count\nfrom sword_runtime.household_request_flow import _house_tang_force_status\n')
start = s.index('def _house_digest_event(')
end = s.index('\n\n\ndef _family_invitation_event', start)
new_digest = '''def _house_digest_event(planner: Any, at: str) -> str | None:\n    force = planner.read(_HOUSE_FORCE)\n    status = _house_tang_force_status(planner)\n    roles = ("house_infantry", "house_cavalry")\n    authorized = force.get("authorized_by_role", {}) if isinstance(force, Mapping) else {}\n    counts = {role: conserved_establishment_role_count(force, role) for role in roles}\n    caps = {role: max(0, int(authorized.get(role, 0))) for role in roles}\n    closes = max(0, int(force.get("cohort_training_closes", 0) or 0)) if isinstance(force, Mapping) else 0\n    signature = {"counts": counts, "caps": caps, "closes": closes, "intake": int(status.get("practical_intake_now", 0))}\n    event_ref = "event_story_house_digest_" + _story_digest(signature)\n    if isinstance(get_causal_event(planner, event_ref), Mapping):\n        return None\n    role_text = ", ".join(f"{r.replace('_',' ')} {counts[r]}/{caps[r]}" for r in roles)\n    vacancies = [f"{r.replace('_',' ')} {max(0, caps[r]-counts[r])}" for r in roles if caps[r] > counts[r]]\n    bottleneck = "Current establishment vacancies: " + (", ".join(vacancies) if vacancies else "none") + "."\n    summary = (f"Tang Ling sends Tang Wei the current House military ledger. The unified House force has completed {closes} monthly training closes. "\n               f"Current conserved establishments: {role_text}. {bottleneck} Current practical replacement intake is {int(status.get('practical_intake_now', 0))}, "\n               f"with assessment throughput {int(status.get('physical_intake_throughput_30d', 0))} per 30 days before equipment/remount limits. "\n               "This status report creates no soldiers; replacement intake uses the ordinary conserved vacancy and population mechanics.")\n    return _event_owner_write(planner, event_ref, {"event_ref":event_ref,"kind":"message","status":"triggered","due_at":at,"triggered_at":at,"actor_ref":"char_tang_ling","target_ref":"char_tang_wei","process_kind":"house_development_digest","process_stage":"delivered","summary":summary[:4000],"delivery":_player_delivery(planner,"House Tang direct report")}, at, source_owner_ref="house_tang")\n'''
s = s[:start] + new_digest + s[end:]
write(p, s)

# ------------------------------------------------------------------
# Field preparation follows current exact assigned House formations.
# ------------------------------------------------------------------
p = 'runtime/sword_runtime/house_field_preparation_issue.py'; s = read(p)
s = s.replace('_FORMATION_REFS = (\n    "formation_tang_champions_first",\n    "formation_tang_wei_house_guard",\n)\n', '_PLAYER_FORCE_PATH = "state/pforce/wei.json"\n')
helper = '''\n\ndef _current_house_field_formations(planner: Any) -> list[str]:\n    """Resolve Wei's current House-owned field formations from exact saved custody."""\n    pforce = planner.read(_PLAYER_FORCE_PATH)\n    refs = pforce.get("assigned_formations", []) if isinstance(pforce, Mapping) else []\n    out: list[str] = []\n    for ref in refs if isinstance(refs, list) else []:\n        if not isinstance(ref, str):\n            continue\n        try:\n            _path, formation = planner._load_formation(ref)\n        except (FileNotFoundError, KeyError, ValueError):\n            continue\n        if str(formation.get("administrative_owner", "")) == "house_tang":\n            out.append(ref)\n    return sorted(set(out))\n'''
marker = '\ndef _field_policy(planner: Any) -> Mapping[str, Any]:\n'
if helper.strip() not in s: s = s.replace(marker, helper + marker)
s = s.replace('''    formations: dict[str, Any] = {}\n    shortfalls: list[str] = []\n    for formation_ref in _FORMATION_REFS:\n''', '''    formations: dict[str, Any] = {}\n    shortfalls: list[str] = []\n    formation_refs = _current_house_field_formations(planner)\n    if not formation_refs:\n        raise ValueError("Tang Wei has no current House-owned assigned field formations to prepare")\n    for formation_ref in formation_refs:\n''')
# Genericize legacy summary labels without changing material issue semantics.
s = s.replace('''    labels = {\n            "formation_tang_champions_first": "Tang Champions",\n            "formation_tang_wei_house_guard": "House Guard",\n        }\n''', '')
s = s.replace('labels.get(formation_ref, formation_ref)', 'formation_ref')
write(p, s)

p = 'runtime/sword_runtime/house_field_preparation_flow.py'; s = read(p)
s = s.replace('_WEI_GUARD_PATH = "state/formations/tang-wei-house-guard.json"\n_CHAMPIONS_PATH = "state/formations/tang-champions-first.json"\n', '_PLAYER_FORCE_PATH = "state/pforce/wei.json"\n')
helper = '''\n\ndef _current_house_field_rows(planner: Any) -> list[tuple[str, Mapping[str, Any]]]:\n    pforce = planner.read(_PLAYER_FORCE_PATH)\n    refs = pforce.get("assigned_formations", []) if isinstance(pforce, Mapping) else []\n    rows: list[tuple[str, Mapping[str, Any]]] = []\n    for ref in refs if isinstance(refs, list) else []:\n        if not isinstance(ref, str):\n            continue\n        try:\n            _path, formation = planner._load_formation(ref)\n        except (FileNotFoundError, KeyError, ValueError):\n            continue\n        if str(formation.get("administrative_owner", "")) == "house_tang":\n            rows.append((ref, formation))\n    return sorted(rows, key=lambda item: item[0])\n'''
marker = '\ndef _event_owner_write(planner: Any, event_ref: str, row: Mapping[str, Any], at: str) -> str:\n'
if helper.strip() not in s: s = s.replace(marker, helper + marker)
s = s.replace('''    wei_guard = planner.read(_WEI_GUARD_PATH)\n    champions = planner.read(_CHAMPIONS_PATH)\n    guard_count = int(wei_guard.get("personnel", 0))\n''', '''    house_rows = _current_house_field_rows(planner)\n    if not house_rows:\n        raise ValueError("Tang Wei has no current House-owned assigned field formations")\n    house_count = sum(int(row.get("personnel", 0) or 0) for _ref, row in house_rows)\n    house_arrows = sum(int(row.get("logistics", {}).get("war_arrows", 0) or 0) for _ref, row in house_rows if isinstance(row.get("logistics"), Mapping))\n    house_refs = [ref for ref, _row in house_rows]\n''')
s = s.replace('''        "wei_house_guard_formation_ref": "formation_tang_wei_house_guard",\n        "champions_formation_ref": "formation_tang_champions_first",\n''', '''        "army_ref": "cmdgrp.tang_wei.field_army",\n        "house_formation_refs": house_refs,\n''')
s = s.replace("f\"For Wei's assigned House Guard, the House ledger currently sees {guard_count} fighters. The unissued armory holds ", "f\"For Wei's current House contingent, the saved assignments contain {house_count} fighters across {len(house_refs)} formations. The unissued armory holds ")
s = s.replace("f\"The Champions currently hold {int(champions.get('logistics', {}).get('war_arrows', 0))} war arrows. Ordinary army ration ", "f\"Those House field formations currently hold {house_arrows} war arrows in total. Ordinary army ration ")
write(p, s)

# ------------------------------------------------------------------
# Static registries: only House Infantry / House Cavalry as House species.
# ------------------------------------------------------------------
p = 'game/data/mil/house-tang-cohort-profiles.json'; d = load(p)
old = d.get('records', {})
if isinstance(old, dict):
    inf = copy.deepcopy(old.get('house_infantry') or old.get('house_guard') or {})
    cav = copy.deepcopy(old.get('house_cavalry') or old.get('guardian_cavalry') or {})
    d['records'] = {'house_infantry': inf, 'house_cavalry': cav}
d['authority'] = 'Canonical current standing capability profiles for House Tang Infantry and House Tang Cavalry only. Veteran cohorts retain their saved explicit capability; these profiles seed only otherwise-uninitialized current cohorts.'
save(p, d)

p = 'game/data/mil/recruitment-cohort-profiles.json'; d = load(p)
rp = d.setdefault('role_training_profiles', {})
inf = copy.deepcopy(rp.get('house_infantry') or rp.get('house_guard') or {})
cav = copy.deepcopy(rp.get('house_cavalry') or rp.get('guardian_cavalry') or {})
rp['house_infantry'] = inf; rp['house_cavalry'] = cav
for key in ('house_guard','guardian_cavalry','tang_champion'): rp.pop(key, None)
save(p, d)

p = 'game/data/mil/deterministic-training-programs.json'; d = load(p)
cs = d.get('command_specialization_programs', {})
if isinstance(cs, dict):
    for key in list(cs):
        if key in {'program.guardian_cavalry','program.house_guard','program.tang_champion','program.sword_trainee','program.sword_junior','program.sword_general','program.sword_senior','program.sword_officer'}:
            cs.pop(key, None)
# Rename instructor pool identities without changing instructor membership.
for drill in d.get('drills', {}).values() if isinstance(d.get('drills'), dict) else ():
    if isinstance(drill, dict):
        if drill.get('instructor_role') == 'sword_manor_instructor': drill['instructor_role'] = 'house_tang_instructor'
        if drill.get('instructor_role') == 'sword_manor_senior_instructor': drill['instructor_role'] = 'house_tang_senior_instructor'
pools = d.get('instructor_pools', {})
if isinstance(pools, dict):
    if 'sword_manor_instructor' in pools and 'house_tang_instructor' not in pools: pools['house_tang_instructor'] = pools.pop('sword_manor_instructor')
    if 'sword_manor_senior_instructor' in pools and 'house_tang_senior_instructor' not in pools: pools['house_tang_senior_instructor'] = pools.pop('sword_manor_senior_instructor')
save(p, d)

p = 'game/data/mechanics/officer-representation.json'; d = load(p)
d.get('institutional_scopes', {}).pop('sword_manor', None)
d['automatic_full_character'] = {
    'minimum_persistent_commanded_personnel': 500,
    'rule': 'Every persistent 500-person or larger command billet is held by a full exact named character. A 100-person command may remain aggregate by default. Representation changes never create manpower.'
}
d['automatic_person_lite'] = {
    'triggers': ['direct_player_interaction','saved_exceptional_performance','individual_injury_capture_or_death','political_or_social_consequence'],
    'rule': 'Person-lite remains available for individually relevant conserved people who do not hold a persistent 500+ command. Persistent 500+ commanders use full exact character sheets.',
    'storage': 'Person-lite records are routed roster shards and never a population authority.'
}
save(p, d)

p = 'game/data/mechanics/unit-duties.json'; d = load(p)
rt = d.setdefault('role_tags', {})
rt.pop('tang_champion', None)
rt['house_infantry'] = ['infantry']
rt['house_cavalry'] = ['cavalry','mobile']
save(p, d)

p = 'game/data/people/role-profiles.json'; d = load(p)
d['profiles'] = {k:v for k,v in d.get('profiles', {}).items() if k != 'role.tang_champion'}
save(p, d)

p = 'game/data/mil/combat-role-profiles.json'; d = load(p)
for key in ('trainee','junior_disciple','general_disciple','senior_disciple'):
    d.get('profiles', {}).pop(key, None)
for key in ('bastion_heavy_infantry','bastion_crossbow','bastion_archer','bastion_artillery'):
    d.get('fallbacks', {}).pop(key, None)
save(p, d)

p = 'game/data/mechanics/house-tang-programs.json'; d = load(p)
base = {k:v for k,v in d.items() if k not in {'sword_manor_initiates','sword_manor_officer_cadre'}}
base['house_tang_military_replacement_intake'] = {
    'roles': ['house_infantry','house_cavalry'],
    'selection_profile': 'household_retainer_screen',
    'training_ground_ref': 'loc_tang_manor_training_ground',
    'physical_capacity_ref': 'state/infrastructure/settlements.json#/sites/loc_tang_inner_walls',
    'force_ref': 'force_house_tang',
    'rule': 'Replacement intake fills only real vacancies from conserved population and is bounded by assessment throughput, standard equipment, cavalry harness, remounts, and the ordinary House training clock.'
}
base['house_tang_command_cadre'] = {
    'rule': 'Persistent 500+ command billets require distinct exact named characters; officer is a billet/career appointment, never a troop species or promotion outcome.'
}
save(p, base)

p = 'game/data/mechanics/house-tang-development.json'; d = load(p)
exp = copy.deepcopy(d.get('inner_walls_expansion') or d.get('sword_manor_expansion') or {})
save(p, {'authority':'Registered House Tang Inner Walls physical expansion package. Mutable project state remains in House, treasury, infrastructure, land, population and runtime owners.','inner_walls_expansion':exp})

# Heavy-cavalry legacy training alias may remain as a file, but routes to current House Cavalry program.
p = 'game/data/mil/training-records/train.house_tang_internal.heavy_cavalry.json'; d = load(p)
if isinstance(d.get('profile'), dict): d['profile']['deterministic_program_policy'] = 'program.house_cavalry'
save(p, d)

# Remove extinct doctrine index aliases, then recalc counts after file retirement.
p = 'game/data/mil/doctrines.json'; d = load(p)
idx = d.get('record_index', {})
for key in ('doc.house_tang_internal.guardian_cavalry','doc.house_tang_internal.tang_champion'):
    if isinstance(idx, dict): idx.pop(key, None)
d['logical_count'] = len(idx) if isinstance(idx, dict) else 0
d['physical_record_count'] = len(set(idx.values())) if isinstance(idx, dict) else 0
save(p, d)

# Current repository routes only.
p = 'runtime/contracts/repository-map.json'; d = load(p)
for key in ('four_bastion_corps_force_authority','four_bastion_corps_policy','sword_manor_officer_establishment'):
    d.pop(key, None)
d['house_tang_officer_representation_policy'] = 'game/data/mechanics/officer-representation.json + state/cmd/command-groups/cmdgrp.house_tang.outer_wall.json + state/cmd/command-groups/cmdgrp.house_tang.inner_walls.json + state/cmd/command-groups/cmdgrp.house_tang.inner_citadel.json'
save(p, d)

# Exactly the retired static authorities/records from the lost final pass.
retired = [
'game/data/mechanics/bastion-corps.json',
'game/data/mechanics/sword-manor-officer-establishment.json',
'game/data/mechanics/sword-manor-organization.json',
'game/data/mil/house-tang-champion-progression.json',
'game/data/mil/sword-manor-progression.json',
'game/data/mil/sword-manor-cohort-profiles.json',
'game/data/mil/doctrine-records/doc.bastion.iron_wall.json',
'game/data/mil/doctrine-records/doc.bastion.red_thunder.json',
'game/data/mil/doctrine-records/doc.bastion.stone_spear.json',
'game/data/mil/doctrine-records/doc.bastion.white_blade.json',
'game/data/mil/doctrine-records/doc.house_tang.tang_champions.json',
'game/data/mil/doctrine-records/doc.house_tang_internal.house_guard.json',
'game/data/mil/doctrine-records/doc.sword_manor.officer.json',
'game/data/mil/doctrine-records/doc.sword_manor.scout.json',
'game/data/mil/training-records/train.bastion.iron_wall.json',
'game/data/mil/training-records/train.bastion.red_thunder.json',
'game/data/mil/training-records/train.bastion.stone_spear.json',
'game/data/mil/training-records/train.bastion.white_blade.json',
'game/data/mil/training-records/train.sword_manor.trainee.json',
'game/data/mil/training-records/train.sword_manor.junior_disciple.json',
'game/data/mil/training-records/train.sword_manor.general_disciple.json',
'game/data/mil/training-records/train.sword_manor.senior_disciple.json',
'game/data/mil/training-records/train.sword_manor.officer.json',
'game/data/mil/training-records/train.house_tang_internal.house_guard.json',
'game/data/mil/training-records/train.tang_wei.household_champions.json',
]
removed = 0
for rel in retired:
    path = ROOT / rel
    if path.exists():
        path.unlink(); removed += 1

# Skill docs: no active Bastion personnel owner and no stale House Guard display override.
p = 'plugins/sword-and-banners/sword-and-banners-skill/sword-and-banners-game-master/references/repository-map.md'; s = read(p)
s = s.replace('`runtime/sword_runtime/bastion_personnel.py` + `game/data/mechanics/bastion-corps.json` — permanent Four Bastion Corps applicant reservation, Corps qualification, active-vacancy admission and conserved replacement/reconstitution. Bastion bodies are House Tang military personnel, never mercenary-market bodies.\n\n', '')
s = s.replace('Large armies, House Tang troops, Sword Manor ranks, and ordinary Tang Champions are aggregate cohorts/formations.', 'Large armies and House Tang troops are cohort-first; House Tang military species are House Infantry and House Cavalry only.')
write(p, s)
p = 'plugins/sword-and-banners/sword-and-banners-skill/sword-and-banners-game-master/references/player-interface.md'; s = read(p)
lines = [line for line in s.splitlines() if 'formation_tang_wei_house_guard' not in line]
write(p, '\n'.join(lines) + '\n')

print(f'retired legacy House institutions; removed_static_files={removed}')
