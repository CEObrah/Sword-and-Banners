"""Scale-aware formation combat capability built from conserved personnel state.

Rank-and-file capability comes from cohort distributions. Weapons, reach, missile
range/cadence/ammunition, mounts, protection, frontage and terrain determine how
that capability can be expressed. Exact people and person-lite standouts remain
individual contributions and risks rather than being averaged into the anonymous
mass.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from sword_runtime.cohort_personnel import ensure_cohort_ledger, ensure_formation_composition


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clampf(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _weighted(values: Mapping[str, Any], weights: Mapping[str, Any]) -> float:
    total = used = 0.0
    for key, raw_weight in weights.items():
        weight = max(0.0, _num(raw_weight))
        if weight <= 0:
            continue
        # Registered but unlisted cohort skills are canonically untrained (zero),
        # not omitted from the denominator. Missing low skills must not inflate a unit.
        total += _num(values.get(key, 0)) * weight
        used += weight
    return total / used if used else 0.0


def _stats(person: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if str(person.get("schema")) == "person-lite":
        stats = person.get("stats", {})
        if isinstance(stats, Mapping):
            attrs = stats.get("attributes", {})
            skills = stats.get("skills", {})
            return (attrs if isinstance(attrs, Mapping) else {}, skills if isinstance(skills, Mapping) else {})
    attrs = person.get("attributes", {})
    skills = person.get("skills", person.get("capabilities", {}))
    return (attrs if isinstance(attrs, Mapping) else {}, skills if isinstance(skills, Mapping) else {})


def _health_factor(person: Mapping[str, Any]) -> float:
    custody=person.get("custody_state")
    if isinstance(custody, Mapping) and str(custody.get("status", "")).lower() in {"captured","prisoner","detained"}: return 0.0
    raw = person.get("health_status")
    if raw is None and isinstance(person.get("health"), Mapping):
        raw = person.get("health", {}).get("status", "healthy")
    elif raw is None:
        raw = person.get("health", "healthy")
    health = str(raw).lower()
    if health in {"dead", "deceased", "killed"}: return 0.0
    if health in {"critical", "incapacitated"}: return 0.25
    if health in {"injured", "wounded"}: return 0.68
    fatigue = person.get("fatigue")
    if fatigue is None and isinstance(person.get("health"), Mapping):
        fatigue = person.get("health", {}).get("fatigue", 0)
    return _clampf(1.0 - _num(fatigue) / 140.0, 0.25, 1.0)


class CombatCapabilityMixin:
    ROLE_PATH = "game/data/mil/combat-role-profiles.json"
    AMMO_RESOURCE_BY_ITEM = {
        "ammo_arrow_hunting": "war_arrows",
        "ammo_arrow_war": "war_arrows",
        "ammo_bolt_war": "war_bolts",
    }

    def _combat_role_registry(self) -> Mapping[str, Any]:
        cached = getattr(self, "_combat_role_registry_cache", None)
        if isinstance(cached, Mapping):
            return cached
        cached = self.read(self.ROLE_PATH)
        self._combat_role_registry_cache = cached
        return cached

    def _combat_interaction_rules(self) -> Mapping[str, Any]:
        cached = getattr(self, "_combat_interaction_rules_cache", None)
        if isinstance(cached, Mapping):
            return cached
        formation = self.read("game/data/mechanics/formation.json")
        rules = formation.get("mass_battle_weapon_interaction", {}) if isinstance(formation, Mapping) else {}
        value = rules if isinstance(rules, Mapping) else {}
        self._combat_interaction_rules_cache = value
        return value

    def _combat_role_profile(self, role: str) -> Mapping[str, Any]:
        registry = self._combat_role_registry(); profiles = registry.get("profiles", {})
        if isinstance(profiles, Mapping) and isinstance(profiles.get(role), Mapping): return profiles[role]
        text = role.lower(); fallbacks = registry.get("fallbacks", {})
        if isinstance(fallbacks, Mapping):
            for needle, target in fallbacks.items():
                if str(needle) in text and isinstance(profiles, Mapping) and isinstance(profiles.get(str(target)), Mapping):
                    return profiles[str(target)]
        return profiles.get("line_infantry", {}) if isinstance(profiles, Mapping) else {}

    def _combat_loadout(self, loadout_id: str) -> Mapping[str, Any]:
        if not loadout_id:
            return {}
        cache = getattr(self, "_combat_loadout_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._combat_loadout_cache = cache
        if loadout_id in cache:
            return cache[loadout_id]
        index = getattr(self, "_combat_loadout_index_cache", None)
        if not isinstance(index, Mapping):
            index = self.read("game/data/loadouts.json")
            self._combat_loadout_index_cache = index
        template = str(index.get("path_template", "game/data/loadout-records/{loadout_id}.json"))
        record = self.read_optional(template.replace("{loadout_id}", loadout_id))
        loadout = record.get("loadout", {}) if isinstance(record, Mapping) else {}
        value = loadout if isinstance(loadout, Mapping) else {}
        cache[loadout_id] = value
        return value

    def _combat_weapon(self, item_id: Any) -> Mapping[str, Any]:
        if not isinstance(item_id, str) or not item_id:
            return {}
        cache = getattr(self, "_combat_item_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._combat_item_cache = cache
        if item_id in cache:
            return cache[item_id]
        try:
            value = self._item_record(item_id)
        except (ValueError, KeyError, FileNotFoundError):
            value = {}
        cache[item_id] = value
        return value

    def _combat_prepare_formation(self, ref: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
        if hasattr(self, "_ct_formation"):
            path, formation, force_path = self._ct_formation(ref); force = deepcopy(self.read(force_path))
            if hasattr(self, "_seed_force_baselines"):
                self._seed_force_baselines(force); self.put(force_path, force)
            formation = deepcopy(self.read(path)); ensure_formation_composition(force, formation); self.put(path, formation)
            return path, formation, force
        path, formation0 = self._load_formation(ref); formation = deepcopy(formation0)
        force_path = self.owner_path(str(formation["owner_force_ref"])); force = deepcopy(self.read(force_path))
        causal_at = str(self.read("state/runtime.json").get("world_time") or "") or None
        ensure_cohort_ledger(force, at=causal_at); ensure_formation_composition(force, formation, at=causal_at)
        return path, formation, force

    @staticmethod
    def _combat_cohort_role(formation: Mapping[str, Any], cohort: Mapping[str, Any]) -> str:
        role = str(cohort.get("role", ""))
        if role: return role
        comp = formation.get("composition", {})
        return str(next(iter(comp))) if isinstance(comp, Mapping) and comp else "line_infantry"

    def _combat_protection_index(self, loadout: Mapping[str, Any]) -> float:
        values: list[float] = []
        for key in ("body_armor", "helmet", "shield", "horse_armor"):
            item = self._combat_weapon(loadout.get(key))
            if not item: continue
            if key == "shield":
                coverage = _clampf(_num(item.get("coverage_arc_degrees", 90), 90) / 180.0, 0.0, 1.0)
                structure = _num(item.get("structural_resistance", 50), 50)
                handling = _num(item.get("handling", 1.0), 1.0)
                values.append(coverage * structure * max(.45, handling))
            else:
                cut = _num(item.get("cut_resistance", item.get("primary_plate_cut_resistance", 0)))
                thrust = _num(item.get("thrust_resistance", item.get("primary_plate_thrust_resistance", 0)))
                blunt = _num(item.get("blunt_resistance", item.get("primary_plate_blunt_resistance", 0)))
                if cut or thrust or blunt:
                    values.append((cut + thrust + blunt) / 3.0)
        return sum(values) / len(values) if values else 0.0

    def _combat_mount_index(self, loadout: Mapping[str, Any]) -> float:
        mount = self._combat_weapon(loadout.get("mount"))
        if not mount: return 0.0
        vals = [_num(mount.get(k, mount.get(k.lower(), 0))) for k in ("Strength", "Agility", "Speed", "Endurance", "Composure")]
        training = _num(mount.get("training_score", mount.get("Training", mount.get("training", 0))))
        if training > 0: vals.append(training)
        vals = [v for v in vals if v > 0]
        return sum(vals) / len(vals) if vals else 0.0

    def _combat_cohort_snapshot(self, formation: Mapping[str, Any], force: Mapping[str, Any]) -> list[dict[str, Any]]:
        ledger = force.get("cohort_ledger", {}); cohorts = ledger.get("cohorts", {}) if isinstance(ledger, Mapping) else {}
        rows: list[dict[str, Any]] = []
        for item in formation.get("cohort_composition", []):
            if not isinstance(item, Mapping): continue
            cid = str(item.get("cohort_id", "")); count = max(0, int(item.get("count", 0))); cohort = cohorts.get(cid) if isinstance(cohorts, Mapping) else None
            if not isinstance(cohort, Mapping) or count <= 0: continue
            role = self._combat_cohort_role(formation, cohort); profile = self._combat_role_profile(role)
            attrs = cohort.get("attribute_means", {}) if isinstance(cohort.get("attribute_means"), Mapping) else {}
            skills = cohort.get("skill_means", {}) if isinstance(cohort.get("skill_means"), Mapping) else {}
            melee_skill = _weighted(skills, profile.get("melee_skill_weights", {})); attr_score = _weighted(attrs, profile.get("attribute_weights", {})); ranged_skill = _weighted(skills, profile.get("ranged_skill_weights", {}))
            melee = .68 * melee_skill + .32 * attr_score; ranged = .68 * ranged_skill + .32 * attr_score if ranged_skill > 0 else 0.0
            loadout = self._combat_loadout(str(profile.get("loadout_id", "")))
            melee_weapon = self._combat_weapon(loadout.get("primary_melee_weapon") or loadout.get("sidearm")); ranged_weapon = self._combat_weapon(loadout.get("ranged_weapon"))
            ammo_item = str(loadout.get("ammunition_item", "")); ammo_resource = self.AMMO_RESOURCE_BY_ITEM.get(ammo_item)
            combat_hours = _num(cohort.get("verified_combat_exposure_hours_per_person", 0.0)); engagements = max(0, int(cohort.get("field_engagements", 0)))
            # Experience is a modest execution modifier; most improvement occurs through saved skills.
            experience_factor = 1.0 + min(.14, combat_hours / 3000.0 + engagements * .003)
            rows.append({
                "cohort_id": cid, "count": count, "role": role,
                "melee_score": melee, "ranged_score": ranged, "experience_factor": experience_factor,
                "melee_reach_m": _num(melee_weapon.get("reach_m", .75), .75),
                "melee_minimum_range_m": _num(melee_weapon.get("minimum_range_m", .10), .10),
                "melee_handling": _num(melee_weapon.get("handling", .8), .8),
                "melee_force": max(_num(melee_weapon.get("base_force_cut")), _num(melee_weapon.get("base_force_thrust")), _num(melee_weapon.get("base_force_blunt")), .35),
                "ranged_effective_range_m": _num(ranged_weapon.get("effective_range_m", 0)),
                "ranged_max_direct_range_m": _num(ranged_weapon.get("maximum_direct_range_m", 0)),
                "ranged_cycle_seconds": _num(ranged_weapon.get("base_shot_cycle_seconds", ranged_weapon.get("base_reload_cycle_seconds", 0))),
                "ranged_power_index": _num(ranged_weapon.get("draw_power_index", ranged_weapon.get("launch_power_index", 0))),
                "ammunition_item": ammo_item, "ammunition_resource": ammo_resource,
                "carried_ammunition": max(0, int(loadout.get("carried_ammunition", 0) or 0)),
                "protection_index": self._combat_protection_index(loadout), "mount_index": self._combat_mount_index(loadout),
                "frontage_spacing_m": max(.45, _num(profile.get("frontage_spacing_m", .9), .9)),
                "depth_support_factor": _clampf(_num(profile.get("depth_support_factor", .3), .3), 0, .7),
                "skills": deepcopy(dict(skills)), "attributes": deepcopy(dict(attrs)),
            })
        return rows

    def _combat_person(self, ref: str) -> Mapping[str, Any] | None:
        try: _, person = self.owner(ref)
        except (ValueError, KeyError, FileNotFoundError): return None
        return person if isinstance(person, Mapping) and str(person.get("schema")) in {"sab_character", "sword-materialized-person", "person-lite"} else None

    @staticmethod
    def _combat_weapon_skill_name(weapon: Mapping[str, Any]) -> str:
        family = str(weapon.get("family", weapon.get("combat_profile", ""))).lower()
        aliases = {
            "spear": "Spear", "lance": "Spear", "sword": "Sword", "one_handed_sword": "Sword",
            "two_handed_sword": "Sword", "glaive": "Glaive", "axe": "Axe",
            "mace": "Mace", "mace_hammer": "Mace", "staff": "Staff", "dagger": "Dagger",
            "bow": "Bow", "crossbow": "Crossbow",
        }
        return aliases.get(family, family.title() if family else "")

    def _combat_person_loadout(self, person: Mapping[str, Any]) -> Mapping[str, Any]:
        loadout_id = ""
        for key in ("equipment_loadout_id", "equipment_standard", "loadout_ref", "loadout_id"):
            value = person.get(key)
            if isinstance(value, str) and value:
                loadout_id = value
                break
        loadout = deepcopy(dict(self._combat_loadout(loadout_id))) if loadout_id else {}
        # A person-lite record may carry an explicit mount outside the standard loadout.
        mount = person.get("mount")
        if isinstance(mount, str) and mount:
            loadout["mount"] = mount
        return loadout

    def _combat_named_participants(self, formation: Mapping[str, Any], force: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        roles: dict[str, str] = {}
        for key, role in (("commander_ref", "commander"), ("deputy_ref", "deputy")):
            ref = formation.get(key)
            if isinstance(ref, str) and ref: roles[ref] = role
        for field, role in (("embedded_person_refs","embedded"),("notable_person_refs","notable"),("staff_refs","staff"),("specialist_refs","specialist")):
            raw = formation.get(field, [])
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                for ref in raw:
                    if isinstance(ref, str) and ref: roles.setdefault(ref, role)
        assignments = force.get("materialized_assignments", {}) if isinstance(force, Mapping) else {}
        fref = str(formation.get("formation_ref", ""))
        if isinstance(assignments, Mapping):
            for ref, assignment in assignments.items():
                if not isinstance(ref, str) or not isinstance(assignment, Mapping): continue
                if str(assignment.get("formation_ref", "")) != fref: continue
                assigned_role = str(assignment.get("combat_role") or assignment.get("role") or "embedded")
                roles.setdefault(ref, assigned_role if assigned_role in {"commander","deputy","staff","specialist","notable","embedded"} else "embedded")
        details: list[dict[str, Any]] = []
        for ref, role in sorted(roles.items()):
            person = self._combat_person(ref)
            if not isinstance(person, Mapping): continue
            attrs, skills = _stats(person)
            command = _weighted(skills, {"Formation Command":.28,"Tactics":.22,"Leadership":.18,"Strategy":.14,"Mass Combat":.18})
            direct_attr = _weighted(attrs, {"Strength":.12,"Agility":.14,"Endurance":.10,"Toughness":.08,"Coordination":.20,"Awareness":.18,"Composure":.18})
            health = _health_factor(person)
            loadout = self._combat_person_loadout(person)
            melee_candidates: list[tuple[float, Mapping[str, Any], str]] = []
            for key in ("primary_melee_weapon", "sidearm"):
                weapon = self._combat_weapon(loadout.get(key))
                if not weapon: continue
                skill_name = self._combat_weapon_skill_name(weapon)
                skill = _num(skills.get(skill_name, 0))
                defense = _num(skills.get("Defense", 0))
                force_index = max(_num(weapon.get("base_force_cut")), _num(weapon.get("base_force_thrust")), _num(weapon.get("base_force_blunt")), .25)
                handling = _num(weapon.get("handling", .8), .8)
                mechanics = _clampf(.90 + .06 * handling + .06 * min(2.0, force_index), .82, 1.16)
                score = (.68 * (.82 * skill + .18 * defense) + .32 * direct_attr) * mechanics * health
                melee_candidates.append((score, weapon, skill_name))
            if melee_candidates:
                melee_direct, melee_weapon, melee_skill_name = max(melee_candidates, key=lambda x: x[0])
            else:
                fallback_skill_name = max(("Spear","Sword","Glaive","Axe","Mace","Staff","Dagger","Defense"), key=lambda k: _num(skills.get(k, 0)))
                melee_direct = (.68 * _num(skills.get(fallback_skill_name, 0)) + .32 * direct_attr) * health
                melee_weapon = {}
                melee_skill_name = fallback_skill_name

            ranged_weapon = self._combat_weapon(loadout.get("ranged_weapon"))
            ranged_skill_name = self._combat_weapon_skill_name(ranged_weapon) if ranged_weapon else ""
            ranged_skill = _num(skills.get(ranged_skill_name, 0)) if ranged_skill_name else 0.0
            ranged_direct = (.68 * (.88 * ranged_skill + .12 * _num(skills.get("Defense", 0))) + .32 * direct_attr) * health if ranged_skill > 0 else 0.0
            ammo_item = str(loadout.get("ammunition_item", ""))
            ammo_resource = self.AMMO_RESOURCE_BY_ITEM.get(ammo_item)
            role_scale = {"staff":.15,"commander":.35,"deputy":.45,"specialist":.65,"notable":1.0,"embedded":1.0}.get(role,.75)

            def equivalent(score: float) -> float:
                if score <= 0: return 0.0
                return _clampf(1.0 + max(0.0, (score - 70.0) / 32.0) ** 1.28, 0.0, 16.0) * role_scale

            assignment = assignments.get(ref) if isinstance(assignments, Mapping) else None
            included = bool(isinstance(assignment, Mapping) and str(assignment.get("formation_ref", "")) == fref)
            exposure = {"commander":.55,"deputy":.70,"staff":.35,"specialist":.80,"notable":.90,"embedded":1.0}.get(role,.75)
            details.append({
                "person_ref":ref,"representation":str(person.get("schema")),"role":role,"command_score":command,
                "direct_combat_score":max(melee_direct, ranged_direct),
                "melee_direct_score":melee_direct,"ranged_direct_score":ranged_direct,
                "equivalent_frontline_bodies":equivalent(melee_direct),
                "ranged_equivalent_bodies":equivalent(ranged_direct),
                "included_in_personnel":included,"exposure_factor":exposure,
                "loadout_id":str(loadout.get("id", "")),"melee_skill":melee_skill_name,
                "melee_weapon_id":str(melee_weapon.get("id", "")),
                "melee_reach_m":_num(melee_weapon.get("reach_m", .75), .75),
                "melee_minimum_range_m":_num(melee_weapon.get("minimum_range_m", .10), .10),
                "melee_handling":_num(melee_weapon.get("handling", .8), .8),
                "ranged_skill":ranged_skill_name,
                "ranged_weapon_id":str(ranged_weapon.get("id", "")) if ranged_weapon else "",
                "ranged_effective_range_m":_num(ranged_weapon.get("effective_range_m", 0)) if ranged_weapon else 0.0,
                "ranged_max_direct_range_m":_num(ranged_weapon.get("maximum_direct_range_m", 0)) if ranged_weapon else 0.0,
                "ranged_cycle_seconds":_num(ranged_weapon.get("base_shot_cycle_seconds", ranged_weapon.get("base_reload_cycle_seconds", 0))) if ranged_weapon else 0.0,
                "ranged_power_index":_num(ranged_weapon.get("draw_power_index", ranged_weapon.get("launch_power_index", 0))) if ranged_weapon else 0.0,
                "ammunition_item":ammo_item,"ammunition_resource":ammo_resource,
                "carried_ammunition":max(0,int(loadout.get("carried_ammunition",0) or 0)),
                "protection_index":self._combat_protection_index(loadout),"mount_index":self._combat_mount_index(loadout),
            })
        return details

    @staticmethod
    def _combat_named_ammunition_rows(named: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for person in named:
            if _num(person.get("ranged_effective_range_m")) <= 0 or _num(person.get("ranged_direct_score")) <= 0:
                continue
            rows.append({
                "count": 1, "ranged_score": _num(person.get("ranged_direct_score")),
                "ranged_effective_range_m": _num(person.get("ranged_effective_range_m")),
                "ranged_max_direct_range_m": _num(person.get("ranged_max_direct_range_m")),
                "ranged_cycle_seconds": _num(person.get("ranged_cycle_seconds")),
                "ranged_power_index": _num(person.get("ranged_power_index")),
                "ammunition_item": person.get("ammunition_item"),
                "ammunition_resource": person.get("ammunition_resource"),
                "carried_ammunition": max(0, int(person.get("carried_ammunition", 0))),
            })
        return rows

    @staticmethod
    def _combat_ammunition_targets(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        targets: dict[str, int] = {}
        for row in rows:
            resource = row.get("ammunition_resource")
            count = max(0, int(row.get("count", 0)))
            carried = max(0, int(row.get("carried_ammunition", 0)))
            if not resource or count <= 0 or carried <= 0:
                continue
            targets[str(resource)] = targets.get(str(resource), 0) + count * carried
        return targets

    def _combat_frontage_equivalent(self, rows: Sequence[Mapping[str, Any]], personnel: int, terrain_kind: str) -> float:
        rules = self._combat_interaction_rules(); terrain_map = rules.get("terrain_frontage_factor", {}) if isinstance(rules, Mapping) else {}
        terrain = _num(terrain_map.get(terrain_kind, .75) if isinstance(terrain_map, Mapping) else .75, .75); ref_width = _num(rules.get("frontage_reference_m_per_1000_open", 500), 500)
        available_width = ref_width * terrain * math.sqrt(max(.05, personnel / 1000.0))
        if not rows: return max(1.0, personnel * min(1.0, .35 + .65 * terrain))
        total = max(1, sum(int(r.get("count",0)) for r in rows)); effective = 0.0
        for row in rows:
            count=max(0,int(row.get("count",0))); share=available_width*count/total; front=min(count, share/max(.45,_num(row.get("frontage_spacing_m",.9),.9))); depth=max(0,count-front)*_clampf(_num(row.get("depth_support_factor",.3)),0,.7); effective += front+depth
        return max(1.0, min(float(personnel), effective))

    def _combat_reach_factor(self, own: Sequence[Mapping[str, Any]], opposing: Sequence[Mapping[str, Any]], cohesion: float, terrain_kind: str) -> float:
        if not own or not opposing: return 1.0
        own_n=max(1,sum(int(r.get("count",0)) for r in own)); opp_n=max(1,sum(int(r.get("count",0)) for r in opposing))
        own_reach=sum(_num(r.get("melee_reach_m",.8))*int(r.get("count",0)) for r in own)/own_n; opp_reach=sum(_num(r.get("melee_reach_m",.8))*int(r.get("count",0)) for r in opposing)/opp_n
        own_min=sum(_num(r.get("melee_minimum_range_m",.1))*int(r.get("count",0)) for r in own)/own_n; opp_min=sum(_num(r.get("melee_minimum_range_m",.1))*int(r.get("count",0)) for r in opposing)/opp_n; rules=self._combat_interaction_rules()
        per_m=_num(rules.get("ordered_reach_advantage_per_meter",.16),.16); cap=_num(rules.get("ordered_reach_advantage_cap",.22),.22); retention=_num(rules.get("disorder_reach_retention",.35),.35)
        tight=terrain_kind in {"pass","fort","fortress","city","capital","town","estate","hall","forest","mountain"}; order=_clampf(cohesion/80.0,0,1)*(0.70 if tight else 1.0)
        reach_bonus=_clampf((own_reach-opp_reach)*per_m,-cap,cap)*(retention+(1-retention)*order)
        compression=_clampf((60-cohesion)/60.0+(.25 if tight else 0),0,1); min_cap=_num(rules.get("compressed_minimum_range_penalty_cap",.22),.22)
        min_penalty=min(min_cap,max(0,own_min-.25)*.22*compression)
        close_cap=_num(rules.get("compressed_short_weapon_bonus_cap",.14),.14); close_per_m=_num(rules.get("compressed_short_weapon_bonus_per_meter",.18),.18)
        close_bonus=min(close_cap,max(0.0,opp_min-own_min)*close_per_m*compression)
        return _clampf(1+reach_bonus-min_penalty+close_bonus,.72,1.28)

    def _combat_ammunition_stock_targets(self, rows: Sequence[Mapping[str, Any]], *, carried_loads: float = 1.0) -> dict[str, int]:
        """Return formation ammunition targets only for weapons actually present.

        A target is based on registered carried ammunition, not total formation
        headcount. Infantry without a missile weapon therefore requests neither
        arrows nor bolts, while mixed/role-specific formations request the exact
        resource their registered loadout uses.
        """
        targets: dict[str, int] = {}
        loads=max(0.0,float(carried_loads))
        for row in rows:
            resource=row.get("ammunition_resource"); count=max(0,int(row.get("count",0))); carried=max(0,int(row.get("carried_ammunition",0)))
            if not resource or count<=0 or carried<=0:
                continue
            targets[str(resource)]=targets.get(str(resource),0)+int(math.ceil(count*carried*loads))
        return targets

    def _combat_ammunition_plan(self, rows: Sequence[Mapping[str, Any]], logistics: Mapping[str, Any], battle_hours: float) -> dict[str, Any]:
        """Plan finite missile expenditure from actual weapon cadence and stock."""
        rules=self._combat_interaction_rules(); duty=_clampf(_num(rules.get("ranged_fire_duty_fraction",.10),.10),.01,.35); opening=max(0,int(rules.get("minimum_opening_shots_per_ranged_person",2)))
        desired_by_resource: dict[str,int]={}; ranged_by_resource: dict[str,int]={}
        for row in rows:
            resource=row.get("ammunition_resource"); count=max(0,int(row.get("count",0))); cycle=max(1.0,_num(row.get("ranged_cycle_seconds",0),0))
            if not resource or count<=0 or cycle<=0 or _num(row.get("ranged_score"))<=0: continue
            carried=max(0,int(row.get("carried_ammunition",0))); cadence_shots=max(opening,int(math.ceil(max(0.0,battle_hours)*3600.0*duty/cycle)))
            per_person=min(carried if carried else cadence_shots, cadence_shots) if carried else cadence_shots
            desired_by_resource[str(resource)]=desired_by_resource.get(str(resource),0)+count*max(0,per_person); ranged_by_resource[str(resource)]=ranged_by_resource.get(str(resource),0)+count
        consumed:dict[str,int]={}; suff:dict[str,float]={}
        for resource,desired in desired_by_resource.items():
            available=max(0,int(logistics.get(resource,0))); used=min(available,desired); consumed[resource]=used; suff[resource]=1.0 if desired<=0 else used/max(1,desired)
        total_desired=sum(desired_by_resource.values()); total_used=sum(consumed.values()); overall=1.0 if total_desired<=0 else total_used/max(1,total_desired)
        return {"desired_by_resource":desired_by_resource,"consumed_by_resource":consumed,"sufficiency_by_resource":suff,"overall_sufficiency":overall,"ranged_personnel":sum(ranged_by_resource.values())}

    def _combat_ranged_factor(self, rows: Sequence[Mapping[str, Any]], ammo_plan: Mapping[str, Any], opposing: Sequence[Mapping[str, Any]] | None = None) -> float:
        ranged=[r for r in rows if _num(r.get("ranged_effective_range_m"))>0 and _num(r.get("ranged_score"))>0]
        if not ranged: return 1.0
        ammo_overall=_clampf(_num(ammo_plan.get("overall_sufficiency",0) if isinstance(ammo_plan,Mapping) else 0),0,1)
        if ammo_overall<=0: return 1.0
        n=max(1,sum(int(r.get("count",0)) for r in rows)); rules=self._combat_interaction_rules(); suff=ammo_plan.get("sufficiency_by_resource",{}) if isinstance(ammo_plan,Mapping) else {}
        bonus=0.0
        opposing_ranged=[r for r in (opposing or []) if _num(r.get("ranged_effective_range_m"))>0 and _num(r.get("ranged_score"))>0]
        opp_n=max(1,sum(int(r.get("count",0)) for r in opposing_ranged))
        opp_range=(sum(_num(r.get("ranged_effective_range_m"))*int(r.get("count",0)) for r in opposing_ranged)/opp_n) if opposing_ranged else 0.0
        own_ranged_n=max(1,sum(int(r.get("count",0)) for r in ranged))
        own_range=sum(_num(r.get("ranged_effective_range_m"))*int(r.get("count",0)) for r in ranged)/own_ranged_n
        range_superiority=0.0
        if opp_range>0:
            ref=max(1.0,_num(rules.get("ranged_effective_range_reference_m",120),120))
            range_superiority=_clampf(((own_range-opp_range)/ref)*_num(rules.get("range_superiority_per_reference",.12),.12),-_num(rules.get("range_superiority_cap",.18),.18),_num(rules.get("range_superiority_cap",.18),.18))
        elif own_range>0:
            range_superiority=min(_num(rules.get("range_superiority_cap",.18),.18),.08)
        opp_total=max(1,sum(max(0,int(r.get("count",0))) for r in (opposing or [])))
        opp_mounted=sum(max(0,int(r.get("count",0))) for r in (opposing or []) if _num(r.get("mount_index"))>0)
        closing_speed=_num(rules.get("mounted_closing_speed_mps",3.4),3.4) if opp_mounted/opp_total>=.40 else _num(rules.get("default_closing_speed_mps",1.6),1.6)
        volley_cap=max(0,int(rules.get("opening_volley_opportunity_cap",4))); volley_weight=_num(rules.get("opening_volley_bonus_per_opportunity",.035),.035); minimum_window=max(0.0,_num(rules.get("minimum_range_window_m",12.0),12.0))
        opening_bonus=0.0
        for row in ranged:
            count=max(0,int(row.get("count",0))); share=count/n; resource=str(row.get("ammunition_resource") or ""); ammo=_clampf(_num(suff.get(resource,0) if isinstance(suff,Mapping) else 0),0,1)
            if ammo<=0: continue
            effective_range=_num(row.get("ranged_effective_range_m")); max_range=_num(row.get("ranged_max_direct_range_m",effective_range)); range_ref=_num(rules.get("ranged_effective_range_reference_m",120),120)
            range_factor=_clampf(effective_range/range_ref,.40,1.65) * _clampf(.92+.08*(max_range/max(1.0,effective_range)),.92,1.10)
            cycle=max(1.0,_num(row.get("ranged_cycle_seconds",8),8)); cadence=_clampf(_num(rules.get("ranged_cycle_reference_seconds",6),6)/cycle,.35,1.7); power=_clampf(_num(row.get("ranged_power_index",70),70)/70.0,.45,1.75); skill=_clampf(.35+_num(row.get("ranged_score"))/100.0,.35,2.2)
            bonus += _num(rules.get("ranged_opening_weight",.28),.28)*share*range_factor*cadence*power*skill*ammo
            # A weapon with greater effective range gains a finite number of additional
            # pre-contact release opportunities.  This is explicitly capped and still
            # consumes the exact projectile resource through the ammunition plan.
            window=effective_range if opp_range<=0 else max(0.0,effective_range-opp_range)
            if window>=minimum_window and closing_speed>0 and volley_cap>0:
                opportunities=min(volley_cap,int((window/closing_speed)//cycle))
                opening_bonus += opportunities*volley_weight*share*skill*ammo
        return _clampf(1.0+min(.75,bonus)+min(.22,opening_bonus)+range_superiority*ammo_overall,.72,1.95)

    def _combat_melee_weapon_factor(self, rows: Sequence[Mapping[str, Any]]) -> float:
        """Small equipment-expression factor distinct from troop skill and reach.

        Weapon handling and delivered force matter, but remain deliberately bounded:
        training/skill is the dominant capability owner and reach has its own
        matchup-sensitive term.
        """
        total=max(1,sum(max(0,int(r.get("count",0))) for r in rows))
        if not rows: return 1.0
        handling=sum(_num(r.get("melee_handling",.8))*max(0,int(r.get("count",0))) for r in rows)/total
        force=sum(_num(r.get("melee_force",.7))*max(0,int(r.get("count",0))) for r in rows)/total
        return _clampf(1.0+(handling-.85)*.12+(force-.80)*.10,.90,1.12)

    def _combat_protection_factor(self, rows: Sequence[Mapping[str, Any]]) -> float:
        total=max(1,sum(int(r.get("count",0)) for r in rows)); protection=sum(_num(r.get("protection_index"))*int(r.get("count",0)) for r in rows)/total if rows else 0
        return _clampf(1.0+protection/800.0,1.0,1.18)

    def _combat_mount_factor(self, rows: Sequence[Mapping[str, Any]], formation: Mapping[str, Any]) -> float:
        mounted=[r for r in rows if _num(r.get("mount_index"))>0]; mounted_n=sum(int(r.get("count",0)) for r in mounted)
        if mounted_n<=0: return 1.0
        actual=sum(max(0,int(v)) for v in formation.get("mounts",{}).values()); complete=_clampf(actual/max(1,mounted_n),0,1); quality=sum(_num(r.get("mount_index"))*int(r.get("count",0)) for r in mounted)/mounted_n
        return _clampf(.82+.18*complete+max(0,quality-70)/900.0,.75,1.16)

    def _formation_combat_snapshot(self, formation: Mapping[str, Any], force: Mapping[str, Any], *, terrain_kind: str, ammo_plan: Mapping[str, Any] | None = None, battle_hours: float=3.0, opposing_rows: Sequence[Mapping[str, Any]] | None=None) -> dict[str, Any]:
        rows=self._combat_cohort_snapshot(formation,force); n=max(1,int(formation.get("personnel",0))); cohort_n=max(1,sum(int(r.get("count",0)) for r in rows))
        melee_mean=sum(_num(r.get("melee_score"))*int(r.get("count",0)) for r in rows)/cohort_n if rows else 55.0; experience=sum(_num(r.get("experience_factor",1))*int(r.get("count",0)) for r in rows)/cohort_n if rows else 1.0
        capability=_clampf(.35+melee_mean/100.0,.35,2.35)*experience; cohesion=_num(formation.get("cohesion",50),50); reach=self._combat_reach_factor(rows,opposing_rows or [],cohesion,terrain_kind)
        named=self._combat_named_participants(formation,force); ammo_rows=list(rows)+self._combat_named_ammunition_rows(named)
        plan=dict(ammo_plan or self._combat_ammunition_plan(ammo_rows,formation.get("logistics",{}),battle_hours)); ranged=self._combat_ranged_factor(rows,plan,opposing_rows or []); frontage=self._combat_frontage_equivalent(rows,n,terrain_kind)
        # Cohort rows explicitly exclude materialized formation slots. Named exact/person-lite
        # participants therefore stay separate and use their own saved weapon/loadout/stats.
        # Reach is contact-dependent and missile contribution disappears when the exact
        # projectile resource is exhausted. Command effect is accounted separately below.
        named_equiv=0.0
        suff=plan.get("sufficiency_by_resource",{}) if isinstance(plan,Mapping) else {}
        rules=self._combat_interaction_rules()
        for person in named:
            melee_eq=max(0.0,_num(person.get("equivalent_frontline_bodies")))
            if melee_eq>0:
                melee_eq *= self._combat_reach_factor([{
                    "count":1,"melee_reach_m":person.get("melee_reach_m",.75),
                    "melee_minimum_range_m":person.get("melee_minimum_range_m",.10),
                }], opposing_rows or [], cohesion, terrain_kind)
                protection=_clampf(1.0+_num(person.get("protection_index"))/1000.0,1.0,1.12)
                mount=_clampf(1.0+max(0.0,_num(person.get("mount_index"))-70.0)/1100.0,1.0,1.10)
                melee_eq *= protection*mount
            ranged_eq=max(0.0,_num(person.get("ranged_equivalent_bodies")))
            resource=str(person.get("ammunition_resource") or "")
            ammo=_clampf(_num(suff.get(resource,0) if isinstance(suff,Mapping) else 0),0,1) if resource else 0.0
            if ranged_eq>0 and ammo>0:
                range_factor=_clampf(_num(person.get("ranged_effective_range_m"))/_num(rules.get("ranged_effective_range_reference_m",120),120),.40,1.65)
                cadence=_clampf(_num(rules.get("ranged_cycle_reference_seconds",6),6)/max(1,_num(person.get("ranged_cycle_seconds",8),8)),.35,1.7)
                power=_clampf(_num(person.get("ranged_power_index",70),70)/70.0,.45,1.75)
                ranged_eq *= _clampf(.68+.12*range_factor+.10*cadence+.10*power,.65,1.35)*ammo
            else:
                ranged_eq=0.0
            effective=max(melee_eq,ranged_eq)
            person["effective_equivalent_bodies"]=effective
            named_equiv += effective
        commander=next((x for x in named if x.get("role")=="commander"),None); deputy=next((x for x in named if x.get("role")=="deputy"),None)
        command_score=_num(commander.get("command_score")) if commander else 0; deputy_score=_num(deputy.get("command_score")) if deputy else 0; command_factor=1+min(.24,command_score/2200.0)+min(.08,deputy_score/3000.0)
        return {"rows":rows,"cohort_personnel":cohort_n,"melee_capability_mean":melee_mean,"capability_factor":capability,"melee_weapon_factor":self._combat_melee_weapon_factor(rows),"reach_factor":reach,"ranged_factor":ranged,"frontage_equivalent":frontage,"named_participants":named,"named_equivalent":named_equiv,"command_factor":command_factor,"protection_factor":self._combat_protection_factor(rows),"mount_factor":self._combat_mount_factor(rows,formation),"ammo_plan":plan}

    def _autonomy_formation_power(self, ref: str, defender: bool=False, opposing_ref: str|None=None) -> float:
        try: _,formation,force=self._combat_prepare_formation(ref)
        except (ValueError,KeyError,FileNotFoundError): return 0.0
        n=max(0,int(formation.get("personnel",0)))
        if n<=0:return 0.0
        logistics=formation.get("logistics",{}); food_ratio=min(1.0,_num(logistics.get("food_kg",0))/max(1,n*2)) if isinstance(logistics,Mapping) else 0; terrain_kind=str(self._location_record(str(formation.get("location_ref"))).get("kind","open")); opposing=[]
        if opposing_ref:
            try: _,of,oforce=self._combat_prepare_formation(opposing_ref); opposing=self._combat_cohort_snapshot(of,oforce)
            except (ValueError,KeyError,FileNotFoundError): pass
        hours=3.0; rows=self._combat_cohort_snapshot(formation,force); ammo_rows=list(rows)+self._combat_named_ammunition_rows(self._combat_named_participants(formation,force)); ammo=self._combat_ammunition_plan(ammo_rows,logistics if isinstance(logistics,Mapping) else {},hours); snap=self._formation_combat_snapshot(formation,force,terrain_kind=terrain_kind,ammo_plan=ammo,battle_hours=hours,opposing_rows=opposing)
        readiness=_num(formation.get("readiness",50)); morale=_num(formation.get("morale",50)); cohesion=_num(formation.get("cohesion",50)); fatigue=_num(formation.get("fatigue",0)); training=_num(formation.get("training_progress",20)); organization=_clampf((readiness+morale+cohesion+max(0,100-fatigue))/400,.18,1.15); integration=_clampf(.72+training/250,.72,1.12)
        equipment=max(.20,_num(formation.get("equipment_completeness",0))); equipment=equipment/100 if equipment>1 else equipment; supply=.72+.28*food_ratio; defense_terrain=1.08 if defender and terrain_kind in {"pass","fort","fortress","city","capital"} else 1; bodies=snap["frontage_equivalent"]+snap["named_equivalent"]
        return max(1.0,bodies*snap["capability_factor"]*snap["melee_weapon_factor"]*snap["reach_factor"]*snap["ranged_factor"]*snap["protection_factor"]*snap["mount_factor"]*organization*integration*equipment*supply*snap["command_factor"]*defense_terrain)


__all__=["CombatCapabilityMixin"]
