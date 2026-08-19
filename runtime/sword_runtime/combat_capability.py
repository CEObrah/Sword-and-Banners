"""Scale-aware formation combat capability built from conserved personnel state.

Rank-and-file capability comes from cohort distributions. Weapons, reach, missile
range/cadence/ammunition, mounts, protection, frontage and terrain determine how
that capability can be expressed. Exact people and person-lite standouts remain
individual contributions and risks rather than being averaged into the anonymous
mass. Command depth is applied by bounded organizational domain: local cohesion,
maneuver, operational coordination, unit throughput and actually staffed support.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from sword_runtime.cohort_personnel import ensure_cohort_ledger, ensure_formation_composition
from sword_runtime.fatigue import RULES_PATH as FATIGUE_RULES_PATH, settle_formation_idle_fatigue
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.contact_physics import (
    armor_contact_resolution,
    condition_factor,
    mount_effective_speed_mps,
    mounted_charge_resolution,
    projectile_flight_resolution,
    shield_contact_resolution,
    weapon_penetration_factor,
)


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
    if fatigue is None and isinstance(person.get("health"), Mapping): fatigue = person.get("health", {}).get("fatigue", 0)
    return _clampf(1.0 - _num(fatigue) / 140.0, 0.25, 1.0)


class CombatCapabilityMixin:
    ROLE_PATH = "game/data/mil/combat-role-profiles.json"
    AMMO_RESOURCE_BY_ITEM = {"ammo_arrow_hunting":"war_arrows","ammo_arrow_war":"war_arrows","ammo_bolt_war":"war_bolts"}

    def _combat_role_registry(self) -> Mapping[str, Any]:
        cached=getattr(self,"_combat_role_registry_cache",None)
        if isinstance(cached,Mapping): return cached
        cached=self.read(self.ROLE_PATH); self._combat_role_registry_cache=cached; return cached

    def _combat_interaction_rules(self) -> Mapping[str, Any]:
        cached=getattr(self,"_combat_interaction_rules_cache",None)
        if isinstance(cached,Mapping): return cached
        formation=self.read("game/data/mechanics/formation.json"); rules=formation.get("mass_battle_weapon_interaction",{}) if isinstance(formation,Mapping) else {}; value=rules if isinstance(rules,Mapping) else {}; self._combat_interaction_rules_cache=value; return value

    def _combat_shield_breakage_resolution(self,serviceable_units:int,condition_pct:float,wear_pct:float)->dict[str,Any]:
        """Split aggregate shield damage into surviving condition and destroyed units.

        ``shield_condition_by_role`` is the mean condition of still-serviceable
        shields. ``shield_units_by_role`` is the physical count of those shields.
        A zero-condition shield is never allowed to remain as a half-effective
        defensive object through the generic equipment-condition floor.
        """
        units=max(0,int(serviceable_units)); prior=_clampf(_num(condition_pct,100.0),0.0,100.0); wear=max(0.0,_num(wear_pct,0.0))
        if units<=0:return {"units_before":0,"units_destroyed":0,"units_after":0,"condition_before_pct":round(prior,3),"condition_after_pct":0.0,"wear_pct":round(wear,3)}
        rules=self._combat_interaction_rules()
        base=_clampf(_num(rules.get("shield_breakage_share_of_wear_at_full_condition",.20),.20),0.0,1.0)
        extra=_clampf(_num(rules.get("shield_breakage_extra_share_at_zero_condition",.60),.60),0.0,1.0)
        cap=_clampf(_num(rules.get("shield_breakage_fraction_cap_per_battle",.35),.35),0.0,1.0)
        minimum=_clampf(_num(rules.get("shield_minimum_serviceable_condition_pct",8.0),8.0),0.0,100.0)
        after=max(0.0,prior-wear); weakness=_clampf(1.0-prior/100.0,0.0,1.0)
        breakage_share=_clampf(base+extra*weakness,0.0,1.0); fraction=min(cap,(wear/100.0)*breakage_share)
        destroyed=min(units,max(0,int(round(units*fraction))))
        if after<minimum and units-destroyed>0:
            destroyed=units; after=0.0
        remaining=max(0,units-destroyed)
        if remaining<=0:after=0.0
        return {"units_before":units,"units_destroyed":destroyed,"units_after":remaining,"condition_before_pct":round(prior,3),"condition_after_pct":round(after,3),"wear_pct":round(wear,3)}

    def _combat_armor_breakage_resolution(self,serviceable_units:int,condition_pct:float,wear_pct:float)->dict[str,Any]:
        """Split aggregate armor-set damage into condition loss and destroyed sets."""
        units=max(0,int(serviceable_units)); prior=_clampf(_num(condition_pct,100.0),0.0,100.0); wear=max(0.0,_num(wear_pct,0.0))
        if units<=0:return {"units_before":0,"units_destroyed":0,"units_after":0,"condition_before_pct":round(prior,3),"condition_after_pct":0.0,"wear_pct":round(wear,3)}
        rules=self._combat_interaction_rules()
        base=_clampf(_num(rules.get("armor_breakage_share_of_wear_at_full_condition",.10),.10),0.0,1.0)
        extra=_clampf(_num(rules.get("armor_breakage_extra_share_at_zero_condition",.45),.45),0.0,1.0)
        cap=_clampf(_num(rules.get("armor_breakage_fraction_cap_per_battle",.20),.20),0.0,1.0)
        minimum=_clampf(_num(rules.get("armor_minimum_serviceable_condition_pct",5.0),5.0),0.0,100.0)
        after=max(0.0,prior-wear); weakness=_clampf(1.0-prior/100.0,0.0,1.0)
        breakage_share=_clampf(base+extra*weakness,0.0,1.0); fraction=min(cap,(wear/100.0)*breakage_share)
        destroyed=min(units,max(0,int(round(units*fraction))))
        if after<minimum and units-destroyed>0:
            destroyed=units; after=0.0
        remaining=max(0,units-destroyed)
        if remaining<=0:after=0.0
        return {"units_before":units,"units_destroyed":destroyed,"units_after":remaining,"condition_before_pct":round(prior,3),"condition_after_pct":round(after,3),"wear_pct":round(wear,3)}

    def _combat_command_rules(self) -> Mapping[str, Any]:
        cached=getattr(self,"_combat_command_rules_cache",None)
        if isinstance(cached,Mapping): return cached
        rules=self.read("game/data/mechanics/warfare-organization.json"); value=rules if isinstance(rules,Mapping) else {}; self._combat_command_rules_cache=value; return value

    def _combat_role_profile(self, role: str) -> Mapping[str, Any]:
        registry=self._combat_role_registry(); profiles=registry.get("profiles",{})
        if isinstance(profiles,Mapping) and isinstance(profiles.get(role),Mapping): return profiles[role]
        text=role.lower(); fallbacks=registry.get("fallbacks",{})
        if isinstance(fallbacks,Mapping):
            for needle,target in fallbacks.items():
                if str(needle) in text and isinstance(profiles,Mapping) and isinstance(profiles.get(str(target)),Mapping): return profiles[str(target)]
        return profiles.get("line_infantry",{}) if isinstance(profiles,Mapping) else {}

    def _combat_role_uses_shield(self, role: str) -> bool:
        profile=self._combat_role_profile(str(role)); loadout=self._combat_loadout(str(profile.get("loadout_id", "")))
        return bool(loadout.get("shield"))

    def _combat_role_uses_armor(self, role: str) -> bool:
        profile=self._combat_role_profile(str(role)); loadout=self._combat_loadout(str(profile.get("loadout_id", "")))
        return bool(loadout.get("body_armor") or loadout.get("helmet"))

    def _combat_loadout(self, loadout_id: str) -> Mapping[str, Any]:
        if not loadout_id:return {}
        cache=getattr(self,"_combat_loadout_cache",None)
        if not isinstance(cache,dict): cache={}; self._combat_loadout_cache=cache
        if loadout_id in cache:return cache[loadout_id]
        index=getattr(self,"_combat_loadout_index_cache",None)
        if not isinstance(index,Mapping): index=self.read("game/data/loadouts.json"); self._combat_loadout_index_cache=index
        template=str(index.get("path_template","game/data/loadout-records/{loadout_id}.json")); record=self.read_optional(template.replace("{loadout_id}",loadout_id)); loadout=record.get("loadout",{}) if isinstance(record,Mapping) else {}; value=loadout if isinstance(loadout,Mapping) else {}; cache[loadout_id]=value; return value

    def _combat_weapon(self,item_id:Any)->Mapping[str,Any]:
        if not isinstance(item_id,str) or not item_id:return {}
        cache=getattr(self,"_combat_item_cache",None)
        if not isinstance(cache,dict):cache={};self._combat_item_cache=cache
        if item_id in cache:return cache[item_id]
        try:value=self._item_record(item_id)
        except (ValueError,KeyError,FileNotFoundError):value={}
        cache[item_id]=value;return value

    def _combat_prepare_formation(self,ref:str)->tuple[str,dict[str,Any],dict[str,Any]]:
        runtime_time=str(self.read("state/runtime.json").get("world_time") or "")
        current=CampaignTime.parse(runtime_time) if runtime_time else None
        fatigue_rules=self.read(FATIGUE_RULES_PATH) if current is not None else {}
        if hasattr(self,"_ct_formation"):
            # _ct_formation already stages isolated mutable formation/force images.
            # Re-copying those large cohort ledgers here was pure planning overhead.
            path,formation,force_path=self._ct_formation(ref);force=self.read(force_path)
            if hasattr(self,"_seed_standing_force_capability"):self._seed_standing_force_capability(force);self.put(force_path,force)
            formation=self.read(path)
            if current is not None: settle_formation_idle_fatigue(formation,current=current,rules=fatigue_rules)
            ensure_formation_composition(force,formation);self.put(path,formation);return path,formation,force
        path,formation0=self._load_formation(ref);formation=deepcopy(formation0)
        if current is not None: settle_formation_idle_fatigue(formation,current=current,rules=fatigue_rules)
        force_path=self.owner_path(str(formation["owner_force_ref"]));force=deepcopy(self.read(force_path));causal_at=runtime_time or None;ensure_cohort_ledger(force,at=causal_at);ensure_formation_composition(force,formation,at=causal_at);return path,formation,force

    @staticmethod
    def _combat_cohort_role(formation:Mapping[str,Any],cohort:Mapping[str,Any])->str:
        role=str(cohort.get("role",""))
        if role:return role
        comp=formation.get("composition",{});return str(next(iter(comp))) if isinstance(comp,Mapping) and comp else "line_infantry"

    def _combat_protection_index(self,loadout:Mapping[str,Any],condition_pct:float=100.0)->float:
        """Human protection only; horse barding never protects the rider."""
        values:list[float]=[]
        condition=condition_factor(condition_pct)
        for key in ("body_armor","helmet","shield"):
            item=self._combat_weapon(loadout.get(key))
            if not item:continue
            if key=="shield":
                coverage=_clampf(_num(item.get("coverage_arc_degrees",90),90)/180.0,0.0,1.0)
                structure=_num(item.get("structural_resistance",50),50)
                handling=_num(item.get("handling",1.0),1.0)
                values.append(coverage*structure*max(.45,handling)*condition)
            else:
                cut=_num(item.get("cut_resistance",item.get("primary_plate_cut_resistance",0)))
                thrust=_num(item.get("thrust_resistance",item.get("primary_plate_thrust_resistance",0)))
                blunt=_num(item.get("blunt_resistance",item.get("primary_plate_blunt_resistance",0)))
                if not (cut or thrust or blunt):
                    cut=_num(item.get("primary_cut_resistance",0)); thrust=_num(item.get("primary_thrust_resistance",0)); blunt=_num(item.get("primary_blunt_resistance",0))
                if cut or thrust or blunt:values.append((cut+thrust+blunt)/3.0*condition)
        return sum(values)/len(values) if values else 0.0

    def _combat_shield_only_index(self,loadout:Mapping[str,Any],condition_pct:float=100.0)->float:
        if condition_pct <= 0:
            return 0.0
        shield=self._combat_weapon(loadout.get("shield"))
        if not shield:
            return 0.0
        coverage=_clampf(_num(shield.get("coverage_arc_degrees",90),90)/180.0,0.0,1.0)
        structure=_num(shield.get("structural_resistance",50),50)
        handling=_num(shield.get("handling",1.0),1.0)
        return coverage*structure*max(.45,handling)*condition_factor(condition_pct)

    def _combat_armor_only_index(self,loadout:Mapping[str,Any],condition_pct:float=100.0)->float:
        if condition_pct <= 0:
            return 0.0
        values:list[float]=[]; condition=condition_factor(condition_pct)
        for key in ("body_armor","helmet"):
            item=self._combat_weapon(loadout.get(key))
            if not item: continue
            cut=_num(item.get("cut_resistance",item.get("primary_plate_cut_resistance",0)))
            thrust=_num(item.get("thrust_resistance",item.get("primary_plate_thrust_resistance",0)))
            blunt=_num(item.get("blunt_resistance",item.get("primary_plate_blunt_resistance",0)))
            if not (cut or thrust or blunt):
                cut=_num(item.get("primary_cut_resistance",0)); thrust=_num(item.get("primary_thrust_resistance",0)); blunt=_num(item.get("primary_blunt_resistance",0))
            if cut or thrust or blunt: values.append((cut+thrust+blunt)/3.0*condition)
        return sum(values)/len(values) if values else 0.0

    def _combat_mount_protection_index(self,loadout:Mapping[str,Any],condition_pct:float=100.0)->float:
        barding=self._combat_weapon(loadout.get("horse_armor"))
        if not barding:return 0.0
        cut=_num(barding.get("primary_cut_resistance",barding.get("cut_resistance",0)))
        thrust=_num(barding.get("primary_thrust_resistance",barding.get("thrust_resistance",0)))
        blunt=_num(barding.get("primary_blunt_resistance",barding.get("blunt_resistance",0)))
        articulated=(_num(barding.get("articulated_cut_resistance",0))+_num(barding.get("articulated_thrust_resistance",0))+_num(barding.get("articulated_blunt_resistance",0)))/3.0
        primary=(cut+thrust+blunt)/3.0
        return (primary+.35*articulated)*condition_factor(condition_pct)

    def _combat_load_burden(self,loadout:Mapping[str,Any],attrs:Mapping[str,Any])->dict[str,float]:
        total_mass=0.0; articulation=1.0; heat=1.0; vision=1.0; hearing=1.0
        for key in ("body_armor","helmet","ranged_weapon","primary_melee_weapon","shield","sidearm","tack"):
            item=self._combat_weapon(loadout.get(key))
            if not item: continue
            total_mass+=max(0.0,_num(item.get("mass_kg",0)))
            articulation*=max(.70,min(1.05,_num(item.get("articulation_factor",item.get("neck_articulation_factor",1.0)),1.0)))
            heat*=max(.75,min(1.5,_num(item.get("heat_retention_factor",1.0),1.0)))
            if key=="helmet":
                awareness=max(0.0,_num(attrs.get("Awareness",50),50)); aperture=max(.1,min(1.0,_num(item.get("vision_aperture_fraction",1.0),1.0))); occ=max(0.0,min(.8,_num(item.get("hearing_occlusion_fraction",0),0)))
                vision*=max(.70,min(1.0,1.0-(1.0-aperture)*max(.50,min(.90,1.0-awareness/400.0))))
                hearing*=max(.70,min(1.0,1.0-occ*max(.55,min(.95,1.0-awareness/450.0))))
        strength=max(0.0,_num(attrs.get("Strength",50),50)); endurance=max(0.0,_num(attrs.get("Endurance",50),50)); agility=max(0.0,_num(attrs.get("Agility",50),50)); coordination=max(0.0,_num(attrs.get("Coordination",50),50))
        comfortable=max(8.0,8.0+.18*strength+.08*endurance); ratio=total_mass/comfortable; penalty=max(0.0,(ratio-.75)*32.0)
        movement=max(.45,min(1.0,1.0-penalty/max(1.0,140.0+.35*agility+.25*coordination)))
        fatigue=max(1.0,min(2.75,1.0+max(0.0,ratio-.75)*max(.55,min(1.20,1.15-endurance/400.0))*max(.9,heat**.20)))
        recovery=max(.40,min(1.0,1.0-penalty/max(1.0,125.0+.30*coordination+.20*agility+.15*strength)))
        return {"total_load_kg":total_mass,"comfortable_load_kg":comfortable,"load_ratio":ratio,"movement_factor":movement,"fatigue_multiplier":fatigue,"recovery_factor":recovery,"articulation_factor":articulation,"vision_factor":vision,"hearing_factor":hearing}

    def _combat_mount_index(self,loadout:Mapping[str,Any])->float:
        mount=self._combat_weapon(loadout.get("mount"))
        if not mount:return 0.0
        vals=[_num(mount.get(k,mount.get(k.lower(),0))) for k in ("Strength","Agility","Speed","Endurance","Composure")];training=_num(mount.get("training_score",mount.get("Training",mount.get("training",0))))
        if training>0:vals.append(training)
        vals=[v for v in vals if v>0]; base=sum(vals)/len(vals) if vals else 0.0
        barding=self._combat_weapon(loadout.get("horse_armor"))
        if barding:
            strength=max(1.0,_num(mount.get("Strength",mount.get("strength",50)),50)); endurance=max(1.0,_num(mount.get("Endurance",mount.get("endurance",50)),50)); agility=max(1.0,_num(mount.get("Agility",mount.get("agility",50)),50)); mass=max(0.0,_num(barding.get("mass_kg",0))); comfortable=max(35.0,20.0+.55*strength+.30*endurance); ratio=mass/comfortable; articulation=max(.70,min(1.0,_num(barding.get("articulation_factor",1.0),1.0))); heat=max(1.0,_num(barding.get("heat_modifier",1.0),1.0)); burden=max(.70,min(1.0,1.0-max(0.0,ratio-.35)*(0.20+max(0.0,100.0-agility)/500.0)))*articulation/max(1.0,heat**.08)
            base*=burden
        return base

    def _combat_cohort_snapshot(self,formation:Mapping[str,Any],force:Mapping[str,Any])->list[dict[str,Any]]:
        ledger=force.get("cohort_ledger",{})
        cohorts=ledger.get("cohorts",{}) if isinstance(ledger,Mapping) else {}
        # Mounts are conserved physical equipment, just like shields. A cavalry
        # role naming a horse in its standard loadout does not prove that every
        # surviving cavalry body still has a horse after remount shortages or
        # battle attrition. Allocate the exact formation mount count across the
        # currently represented mounted cohorts before deriving charge geometry.
        mounted_required_total=0
        for item in formation.get("cohort_composition",[]):
            if not isinstance(item,Mapping): continue
            cid=str(item.get("cohort_id","")); count=max(0,int(item.get("count",0)))
            cohort=cohorts.get(cid) if isinstance(cohorts,Mapping) else None
            if not isinstance(cohort,Mapping) or count<=0: continue
            role=self._combat_cohort_role(formation,cohort); profile=self._combat_role_profile(role); loadout=self._combat_loadout(str(profile.get("loadout_id","")))
            if self._combat_weapon(loadout.get("mount")): mounted_required_total+=count
        physical_mounts=max(0,sum(max(0,int(v)) for v in (formation.get("mounts",{}) if isinstance(formation.get("mounts"),Mapping) else {}).values()))
        mount_fill=_clampf(physical_mounts/max(1,mounted_required_total),0.0,1.0) if mounted_required_total>0 else 0.0
        condition_by_role=formation.get("equipment_condition_by_role",{}) if isinstance(formation.get("equipment_condition_by_role"),Mapping) else {}
        shield_condition_by_role=formation.get("shield_condition_by_role",{}) if isinstance(formation.get("shield_condition_by_role"),Mapping) else {}
        armor_condition_by_role=formation.get("armor_condition_by_role",{}) if isinstance(formation.get("armor_condition_by_role"),Mapping) else {}
        equipment_units_by_role=formation.get("equipment_units_by_role",{}) if isinstance(formation.get("equipment_units_by_role"),Mapping) else {}
        shield_units_by_role=formation.get("shield_units_by_role",{}) if isinstance(formation.get("shield_units_by_role"),Mapping) else {}
        armor_units_by_role=formation.get("armor_units_by_role",{}) if isinstance(formation.get("armor_units_by_role"),Mapping) else {}
        formation_composition=formation.get("composition",{}) if isinstance(formation.get("composition"),Mapping) else {}
        equipment_completeness=_clampf(_num(formation.get("equipment_completeness",1.0),1.0),0.0,100.0)
        if equipment_completeness>1.0: equipment_completeness/=100.0
        rows:list[dict[str,Any]]=[]
        for item in formation.get("cohort_composition",[]):
            if not isinstance(item,Mapping):continue
            cid=str(item.get("cohort_id",""));count=max(0,int(item.get("count",0)))
            cohort=cohorts.get(cid) if isinstance(cohorts,Mapping) else None
            if not isinstance(cohort,Mapping) or count<=0:continue
            role=self._combat_cohort_role(formation,cohort)
            profile=self._combat_role_profile(role)
            attrs=cohort.get("attribute_means",{}) if isinstance(cohort.get("attribute_means"),Mapping) else {}
            skills=cohort.get("skill_means",{}) if isinstance(cohort.get("skill_means"),Mapping) else {}
            loadout=self._combat_loadout(str(profile.get("loadout_id","")))
            equipment_condition=_clampf(_num(condition_by_role.get(role),100.0),0.0,100.0)
            shield_condition=_clampf(_num(shield_condition_by_role.get(role),equipment_condition),0.0,100.0)
            armor_condition=_clampf(_num(armor_condition_by_role.get(role),equipment_condition),0.0,100.0)
            condition=condition_factor(equipment_condition)
            burden=self._combat_load_burden(loadout,attrs)
            control=max(.35,burden["movement_factor"]*burden["recovery_factor"]*burden["articulation_factor"])*(.75+.25*condition)
            melee_skill=_weighted(skills,profile.get("melee_skill_weights",{})); attr_score=_weighted(attrs,profile.get("attribute_weights",{})); ranged_skill=_weighted(skills,profile.get("ranged_skill_weights",{}))
            melee=(.68*melee_skill+.32*attr_score)*control
            ranged=(.68*ranged_skill+.32*attr_score)*max(.35,burden["recovery_factor"]*burden["vision_factor"])*(.78+.22*condition) if ranged_skill>0 else 0.0
            melee_weapon=self._combat_weapon(loadout.get("primary_melee_weapon") or loadout.get("sidearm")); ranged_weapon=self._combat_weapon(loadout.get("ranged_weapon")); shield=self._combat_weapon(loadout.get("shield")); mount=self._combat_weapon(loadout.get("mount")); barding=self._combat_weapon(loadout.get("horse_armor")); tack=self._combat_weapon(loadout.get("tack"))
            role_personnel=max(1,int(formation_composition.get(role,count) or count))
            if role in equipment_units_by_role:
                role_equipped=max(0,min(role_personnel,int(equipment_units_by_role.get(role,0) or 0)))
            else:
                role_equipped=max(0,min(role_personnel,int(round(role_personnel*equipment_completeness))))
            if shield:
                minimum_shield_condition=_clampf(_num(self._combat_interaction_rules().get("shield_minimum_serviceable_condition_pct",8.0),8.0),0.0,100.0)
                role_shields=max(0,min(role_equipped,int(shield_units_by_role.get(role,role_equipped) or 0)))
                row_shield_units=max(0.0,min(float(count),float(role_shields)*float(count)/max(1.0,float(role_personnel)))) if shield_condition>=minimum_shield_condition else 0.0
                shield_availability=_clampf(row_shield_units/max(1.0,float(count)),0.0,1.0)
            else:
                role_shields=0; row_shield_units=0.0; shield_availability=0.0
            has_armor=bool(self._combat_weapon(loadout.get("body_armor")) or self._combat_weapon(loadout.get("helmet")))
            if has_armor:
                minimum_armor_condition=_clampf(_num(self._combat_interaction_rules().get("armor_minimum_serviceable_condition_pct",5.0),5.0),0.0,100.0)
                role_armor=max(0,min(role_equipped,int(armor_units_by_role.get(role,role_equipped) or 0)))
                row_armor_units=max(0.0,min(float(count),float(role_armor)*float(count)/max(1.0,float(role_personnel)))) if armor_condition>=minimum_armor_condition else 0.0
                armor_availability=_clampf(row_armor_units/max(1.0,float(count)),0.0,1.0)
            else:
                role_armor=0; row_armor_units=0.0; armor_availability=0.0
            armor_component_count=sum(1 for k in ("body_armor","helmet") if self._combat_weapon(loadout.get(k)))
            shield_component_count=1 if shield else 0
            armor_index=self._combat_armor_only_index(loadout,armor_condition)*armor_availability
            shield_index=self._combat_shield_only_index(loadout,shield_condition)*shield_availability
            component_denominator=max(1,armor_component_count+shield_component_count)
            effective_protection=(armor_index*armor_component_count+shield_index*shield_component_count)/component_denominator
            ammo_item=str(loadout.get("ammunition_item","")); ammo_resource=self.AMMO_RESOURCE_BY_ITEM.get(ammo_item)
            combat_hours=_num(cohort.get("verified_combat_exposure_hours_per_person",0.0)); engagements=max(0,int(cohort.get("field_engagements",0))); experience_factor=1.0+min(.14,combat_hours/3000.0+engagements*.003)
            mount_profile=mount_effective_speed_mps(mount,barding=barding,rider_mass_kg=75.0,rider_equipment_kg=burden["total_load_kg"],tack_mass_kg=_num(tack.get("mass_kg",0)),terrain_factor=1.0) if mount else {"mounted":False}
            mounted_units=(float(count)*mount_fill) if mount and mounted_required_total>0 else 0.0
            mount_availability=_clampf(mounted_units/max(1.0,float(count)),0.0,1.0)
            force_choices={
                "cut":_num(melee_weapon.get("base_force_cut")),
                "thrust":_num(melee_weapon.get("base_force_thrust")),
                "blunt":_num(melee_weapon.get("base_force_blunt")),
            }
            dominant_mode=max(force_choices,key=force_choices.get) if force_choices else "blunt"
            rows.append({
                "cohort_id":cid,"count":count,"role":role,"loadout_id":str(profile.get("loadout_id","")),
                "melee_score":melee,"ranged_score":ranged,"experience_factor":experience_factor,
                "melee_weapon_id":str(melee_weapon.get("id","")),"melee_weapon_family":str(melee_weapon.get("family","")),"melee_weapon_variant":str(melee_weapon.get("variant","")),
                "melee_reach_m":_num(melee_weapon.get("reach_m",.75),.75),"melee_minimum_range_m":_num(melee_weapon.get("minimum_range_m",.10),.10),
                "melee_handling":_num(melee_weapon.get("handling",.8),.8)*(.80+.20*condition),
                "melee_force":max(_num(melee_weapon.get("base_force_cut")),_num(melee_weapon.get("base_force_thrust")),_num(melee_weapon.get("base_force_blunt")),.35)*condition,
                "melee_attack_mode":dominant_mode,
                "melee_penetration_factor":weapon_penetration_factor(melee_weapon,dominant_mode)*condition,
                "ranged_effective_range_m":_num(ranged_weapon.get("effective_range_m",0)),"ranged_max_direct_range_m":_num(ranged_weapon.get("maximum_direct_range_m",0)),
                "ranged_cycle_seconds":_num(ranged_weapon.get("base_shot_cycle_seconds",ranged_weapon.get("base_reload_cycle_seconds",0))),"ranged_power_index":_num(ranged_weapon.get("draw_power_index",ranged_weapon.get("launch_power_index",0)))*condition,
                "ammunition_item":ammo_item,"ammunition_resource":ammo_resource,"carried_ammunition":max(0,int(loadout.get("carried_ammunition",0) or 0)),
                "protection_index":effective_protection,"armor_protection_index":armor_index,"armor_units":round(row_armor_units,6),"armor_availability":round(armor_availability,6),"mount_protection_index":self._combat_mount_protection_index(loadout,equipment_condition),
                "mount_index":self._combat_mount_index(loadout),"mounted":bool(mount_profile.get("mounted")) and mounted_units>0,"mounted_units":round(mounted_units,6),"mount_required_units":count if mount else 0,"mount_availability":round(mount_availability,6),"mount_speed_mps":_num(mount_profile.get("effective_speed_mps",0)),"mount_total_mass_kg":_num(mount_profile.get("total_mass_kg",0)),"charge_legal":bool(mount_profile.get("charge_legal")) and mounted_units>0,
                "shield_id":str(shield.get("id","")),"shield_structure":_num(shield.get("structural_resistance",0))*_clampf(shield_condition/100.0,0.0,1.0) if row_shield_units>0 else 0.0,"shield_coverage_degrees":_num(shield.get("coverage_arc_degrees",0)),"shield_handling":_num(shield.get("handling",0)),"shield_condition_pct":shield_condition,"shield_units":round(row_shield_units,6),"shield_availability":round(shield_availability,6),"armor_condition_pct":armor_condition,
                "ranged_weapon_id":str(ranged_weapon.get("id","")),"ranged_weapon_family":str(ranged_weapon.get("family",ranged_weapon.get("schema",""))),"ranged_strength":_num(attrs.get("Strength",0)),"ranged_coordination":_num(attrs.get("Coordination",0)),"ranged_awareness":_num(attrs.get("Awareness",0)),
                "formation_fighting":_num(skills.get("Formation Fighting",skills.get("Formation_Fighting",0))),"riding":_num(skills.get("Riding",0)),
                "equipment_condition_pct":equipment_condition,"formation_cohesion":_num(formation.get("cohesion",50),50),"formation_training":_num(formation.get("training_progress",20),20),"load_burden":burden,
                "frontage_spacing_m":max(.45,_num(profile.get("frontage_spacing_m",.9),.9)),"depth_support_factor":_clampf(_num(profile.get("depth_support_factor",.3),.3),0,.7),
                "skills":deepcopy(dict(skills)),"attributes":deepcopy(dict(attrs)),
            })
        return rows

    def _combat_person(self,ref:str)->Mapping[str,Any]|None:
        try:_,person=self.owner(ref)
        except (ValueError,KeyError,FileNotFoundError):return None
        return person if isinstance(person,Mapping) and str(person.get("schema")) in {"sab_character","sword-materialized-person","person-lite"} else None

    @staticmethod
    def _combat_weapon_skill_name(weapon:Mapping[str,Any])->str:
        family=str(weapon.get("family",weapon.get("combat_profile",""))).lower();aliases={"spear":"Spear","lance":"Spear","sword":"Sword","one_handed_sword":"Sword","two_handed_sword":"Sword","glaive":"Glaive","axe":"Axe","mace":"Mace","mace_hammer":"Mace","staff":"Staff","dagger":"Dagger","bow":"Bow","crossbow":"Crossbow"};return aliases.get(family,family.title() if family else "")

    def _combat_person_loadout(self,person:Mapping[str,Any])->Mapping[str,Any]:
        loadout_id=""
        for key in ("equipment_loadout_id","equipment_standard","loadout_ref","loadout_id"):
            value=person.get(key)
            if isinstance(value,str) and value:loadout_id=value;break
        loadout=deepcopy(dict(self._combat_loadout(loadout_id))) if loadout_id else {};mount=person.get("mount")
        if isinstance(mount,str) and mount:loadout["mount"]=mount
        return loadout

    def _combat_command_admission(self, formation: Mapping[str, Any]) -> dict[str, Any]:
        """Describe the lawful command path for battle admission without inventing people."""
        commander_ref=formation.get("commander_ref")
        if isinstance(commander_ref,str) and commander_ref:
            return {"mode":"exact_commander","commander_ref":commander_ref,"aggregate_unit_post":False,"higher_command":False}
        structure=formation.get("command_structure",{}) if isinstance(formation.get("command_structure"),Mapping) else {}
        unit=structure.get("unit_command",{}) if isinstance(structure,Mapping) else {}
        aggregate_post=bool(isinstance(unit,Mapping) and (unit.get("commander_post") or unit.get("external_to_fighting_establishment") or int(unit.get("commander_billets",0) or 0)>0 or int(unit.get("effective_billets_staffed",0) or 0)>0))
        higher=bool(self._combat_higher_command_participants(formation))
        if not aggregate_post and not higher:
            raise ValueError(f"battle rejected: {formation.get('formation_ref','formation')} has neither an exact commander nor a staffed aggregate/higher command path")
        return {"mode":"aggregate_unit_command" if aggregate_post else "higher_command_only","commander_ref":None,"aggregate_unit_post":aggregate_post,"higher_command":higher}

    def _combat_higher_command_participants(self, formation: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Resolve the bounded zero-body command chain above a formation.

        Command groups are organizational authority only. Their commander/deputy
        can improve operational coordination, but they are never inserted into the
        subordinate formation's fighting strength or exposed as extra combat bodies.
        """
        current = formation.get("higher_command_ref")
        if not isinstance(current, str) or not current.startswith("cmdgrp."):
            return []
        rows: list[dict[str, Any]] = []
        seen_groups: set[str] = set()
        seen_people: set[str] = set()
        depth = 0
        while isinstance(current, str) and current.startswith("cmdgrp.") and depth < 8:
            if current in seen_groups:
                break
            seen_groups.add(current)
            group = self.read_optional(f"state/cmd/command-groups/{current}.json")
            if not isinstance(group, Mapping):
                break
            depth += 1
            for key, role in (("commander_ref", "higher_commander"), ("deputy_ref", "higher_deputy")):
                ref = group.get(key)
                if not isinstance(ref, str) or not ref or ref in seen_people:
                    continue
                seen_people.add(ref)
                rows.append({"person_ref": ref, "role": role, "command_group_ref": current, "command_depth": depth})
            parent = group.get("parent_command_group_ref")
            current = parent if isinstance(parent, str) else None
        return rows

    def _combat_named_participants(self,formation:Mapping[str,Any],force:Mapping[str,Any]|None=None)->list[dict[str,Any]]:
        roles:dict[str,str]={}; command_meta:dict[str,dict[str,Any]]={}
        for key,role in (("commander_ref","commander"),("deputy_ref","deputy")):
            ref=formation.get(key)
            if isinstance(ref,str) and ref:roles[ref]=role
        for field,role in (("embedded_person_refs","embedded"),("notable_person_refs","notable"),("staff_refs","staff"),("specialist_refs","specialist")):
            raw=formation.get(field,[])
            if isinstance(raw,Sequence) and not isinstance(raw,(str,bytes)):
                for ref in raw:
                    if isinstance(ref,str) and ref:roles.setdefault(ref,role)
        for row in self._combat_higher_command_participants(formation):
            ref=str(row.get("person_ref",""))
            if ref and ref not in roles:
                roles[ref]=str(row.get("role","higher_commander")); command_meta[ref]={"command_group_ref":row.get("command_group_ref"),"command_depth":int(row.get("command_depth",0) or 0),"command_scope":"higher"}
        assignments=force.get("materialized_assignments",{}) if isinstance(force,Mapping) else {}; fref=str(formation.get("formation_ref",""))
        if isinstance(assignments,Mapping):
            for ref,assignment in assignments.items():
                if not isinstance(ref,str) or not isinstance(assignment,Mapping) or str(assignment.get("formation_ref",""))!=fref:continue
                assigned_role=str(assignment.get("combat_role") or assignment.get("role") or "embedded"); roles.setdefault(ref,assigned_role if assigned_role in {"commander","deputy","staff","specialist","notable","embedded"} else "embedded")
        details:list[dict[str,Any]]=[]
        for ref,role in sorted(roles.items()):
            person=self._combat_person(ref)
            if not isinstance(person,Mapping):continue
            assignment=assignments.get(ref) if isinstance(assignments,Mapping) else None
            included=bool(isinstance(assignment,Mapping) and str(assignment.get("formation_ref",""))==fref)
            person_command=person.get("command_assignment",{}) if isinstance(person.get("command_assignment"),Mapping) else {}
            scale=max(0,int((assignment.get("command_scale",0) if isinstance(assignment,Mapping) else 0) or person_command.get("scale",0) or 0))
            if included and role not in {"commander","deputy","higher_commander","higher_deputy"} and scale in {100,500,1000}:
                role=f"internal_{scale}_commander"
            formation_location=str(formation.get("location_ref",formation.get("location","")) or "")
            person_location=""
            has_location_authority=hasattr(self,"_person_location")
            if has_location_authority:
                try: person_location=str(self._person_location(person) or "")
                except Exception: person_location=""
            # In production, frontline participation requires positive location
            # evidence.  Missing exact-person location must never be interpreted
            # as proof that the person is physically present with the formation.
            # Lightweight unit harnesses without the production location owner
            # retain their historical local-only behavior.
            co_located=(formation_location==person_location) if has_location_authority else True
            attrs,skills=_stats(person); health=_health_factor(person)
            command=_weighted(skills,{"Formation Command":.28,"Tactics":.22,"Leadership":.18,"Strategy":.14,"Mass Combat":.18})*health
            direct_attr=_weighted(attrs,{"Strength":.12,"Agility":.14,"Endurance":.10,"Toughness":.08,"Coordination":.20,"Awareness":.18,"Composure":.18})
            if hasattr(self,"_personal_equipment_profile"):
                try: exact=self._personal_equipment_profile(ref,person); loadout=deepcopy(dict(exact.get("loadout",{}))); condition_by_item=exact.get("condition_by_item",{}) if isinstance(exact.get("condition_by_item"),Mapping) else {}
                except Exception: loadout=deepcopy(dict(self._combat_person_loadout(person))); condition_by_item={}
            else: loadout=deepcopy(dict(self._combat_person_loadout(person))); condition_by_item={}
            melee_candidates:list[tuple[float,Mapping[str,Any],str,str]]=[]
            for key in ("primary_melee_weapon","sidearm"):
                weapon_id=loadout.get(key); weapon=self._combat_weapon(weapon_id)
                if not weapon:continue
                skill_name=self._combat_weapon_skill_name(weapon); skill=_num(skills.get(skill_name,0)); defense=_num(skills.get("Defense",0)); force_index=max(_num(weapon.get("base_force_cut")),_num(weapon.get("base_force_thrust")),_num(weapon.get("base_force_blunt")),.25); handling=_num(weapon.get("handling",.8),.8); cond=condition_factor(_num(condition_by_item.get(str(weapon_id),100),100)); mechanics=max(.55,.90+.06*handling+.06*math.sqrt(max(.01,force_index)))*cond; score=(.68*(.82*skill+.18*defense)+.32*direct_attr)*mechanics*health; melee_candidates.append((score,weapon,skill_name,str(weapon_id)))
            if melee_candidates: melee_direct,melee_weapon,melee_skill_name,melee_weapon_id=max(melee_candidates,key=lambda x:x[0])
            else:
                fallback_skill_name=max(("Spear","Sword","Glaive","Axe","Mace","Staff","Dagger","Defense"),key=lambda k:_num(skills.get(k,0))); melee_direct=(.68*_num(skills.get(fallback_skill_name,0))+.32*direct_attr)*health; melee_weapon={}; melee_skill_name=fallback_skill_name; melee_weapon_id=""
            ranged_weapon=self._combat_weapon(loadout.get("ranged_weapon")); ranged_skill_name=self._combat_weapon_skill_name(ranged_weapon) if ranged_weapon else ""; ranged_skill=_num(skills.get(ranged_skill_name,0)) if ranged_skill_name else 0.0; ranged_direct=(.68*(.88*ranged_skill+.12*_num(skills.get("Defense",0)))+.32*direct_attr)*health if ranged_skill>0 else 0.0
            ammo_item=str(loadout.get("ammunition_item","")); ammo_resource=self.AMMO_RESOURCE_BY_ITEM.get(ammo_item)
            default_carried_ammunition=max(0,int(loadout.get("carried_ammunition",0) or 0))
            combat_state=person.get("combat_state",{}) if isinstance(person.get("combat_state"),Mapping) else {}
            saved_projectiles=combat_state.get("projectile_ammunition",{}) if isinstance(combat_state.get("projectile_ammunition"),Mapping) else {}
            carried_ammunition=max(0,int(saved_projectiles.get(ammo_item,default_carried_ammunition) or 0)) if ammo_item else 0
            exposure={"commander":.55,"deputy":.70,"staff":.35,"specialist":.80,"notable":.90,"embedded":1.0,"internal_100_commander":.82,"internal_500_commander":.72,"internal_1000_commander":.62,"higher_commander":0.05,"higher_deputy":0.08}.get(role,.75)
            tempo=.25*_num(attrs.get("Agility"))+.20*_num(attrs.get("Coordination"))+.20*_num(skills.get(melee_skill_name,0))+.15*_num(attrs.get("Awareness"))+.10*_num(skills.get("Mass Combat",skills.get("Mass_Combat",0)))+.10*_num(attrs.get("Endurance")); action_interval=max(.40,360.0/(max(0.0,tempo)+60.0))
            mount=self._combat_weapon(loadout.get("mount")); barding=self._combat_weapon(loadout.get("horse_armor")); tack=self._combat_weapon(loadout.get("tack")); burden=self._combat_load_burden(loadout,attrs); mount_profile=mount_effective_speed_mps(mount,barding=barding,rider_mass_kg=75.0,rider_equipment_kg=burden["total_load_kg"],tack_mass_kg=_num(tack.get("mass_kg",0))) if mount else {"mounted":False}
            shield_id=str(loadout.get("shield","")); body_armor_id=str(loadout.get("body_armor","")); helmet_id=str(loadout.get("helmet",""))
            shield_condition=_clampf(_num(condition_by_item.get(shield_id,100),100),0,100) if shield_id else 0.0
            armor_condition=_clampf(_num(condition_by_item.get(body_armor_id,100),100),0,100) if body_armor_id else 100.0
            command_available=health>.25 and (co_located or str(command_meta.get(ref,{}).get("command_scope",""))=="higher")
            row={"person_ref":ref,"representation":str(person.get("schema")),"role":role,"command_score":command,"health_factor":health,"command_available":command_available,"co_located":co_located,"person_location_ref":person_location or None,"formation_location_ref":formation_location or None,"direct_combat_score":max(melee_direct,ranged_direct),"melee_direct_score":melee_direct,"ranged_direct_score":ranged_direct,
                 "included_in_personnel":included,"exposure_factor":exposure,"loadout_id":str(loadout.get("id","")),"melee_skill":melee_skill_name,"melee_weapon_id":str(melee_weapon.get("id",melee_weapon_id)),"melee_weapon_family":str(melee_weapon.get("family","")),"melee_weapon_variant":str(melee_weapon.get("variant","")),"melee_reach_m":_num(melee_weapon.get("reach_m",.75),.75),"melee_minimum_range_m":_num(melee_weapon.get("minimum_range_m",.10),.10),"melee_handling":_num(melee_weapon.get("handling",.8),.8),"melee_force":max(_num(melee_weapon.get("base_force_cut")),_num(melee_weapon.get("base_force_thrust")),_num(melee_weapon.get("base_force_blunt")),.35),"hero_tempo":tempo,"minimum_action_interval_seconds":action_interval,
                 "ranged_skill":ranged_skill_name,"ranged_skill_value":ranged_skill,"ranged_weapon_id":str(ranged_weapon.get("id","")) if ranged_weapon else "","ranged_effective_range_m":_num(ranged_weapon.get("effective_range_m",0)) if ranged_weapon else 0.0,"ranged_max_direct_range_m":_num(ranged_weapon.get("maximum_direct_range_m",0)) if ranged_weapon else 0.0,"ranged_cycle_seconds":_num(ranged_weapon.get("base_shot_cycle_seconds",ranged_weapon.get("base_reload_cycle_seconds",0))) if ranged_weapon else 0.0,"ranged_power_index":_num(ranged_weapon.get("draw_power_index",ranged_weapon.get("launch_power_index",0))) if ranged_weapon else 0.0,"ammunition_item":ammo_item,"ammunition_resource":ammo_resource,"carried_ammunition":carried_ammunition,"default_carried_ammunition":default_carried_ammunition,
                 "protection_index":self._combat_protection_index(loadout),"shield_id":shield_id,"body_armor_id":body_armor_id,"helmet_id":helmet_id,"shield_condition_pct":shield_condition,"armor_condition_pct":armor_condition,"defense_skill_value":_num(skills.get("Defense",0)),"agility":_num(attrs.get("Agility",0)),"toughness":_num(attrs.get("Toughness",0)),"mount_protection_index":self._combat_mount_protection_index(loadout),"mount_index":self._combat_mount_index(loadout),"mounted":bool(mount_profile.get("mounted")),"mount_speed_mps":_num(mount_profile.get("effective_speed_mps",0)),"mount_total_mass_kg":_num(mount_profile.get("total_mass_kg",0)),"charge_legal":bool(mount_profile.get("charge_legal")),"riding":_num(skills.get("Riding",0)),"coordination":_num(attrs.get("Coordination",0)),"awareness":_num(attrs.get("Awareness",0)),"composure":_num(attrs.get("Composure",0)),"horse_training":_num(mount.get("training_score",0)),"strength":_num(attrs.get("Strength",0)),"endurance":_num(attrs.get("Endurance",0)),
                 "combat_targeting_doctrine":deepcopy(dict(person.get("behavior",{}).get("combat_targeting_doctrine",{}))) if isinstance(person.get("behavior"),Mapping) and isinstance(person.get("behavior",{}).get("combat_targeting_doctrine"),Mapping) else {}}
            row.update(command_meta.get(ref,{})); details.append(row)
        return details

    @staticmethod
    def _combat_ammunition_targets(rows:Sequence[Mapping[str,Any]])->dict[str,int]:
        targets={}
        for row in rows:
            resource=row.get("ammunition_resource");count=max(0,int(row.get("count",0)));carried=max(0,int(row.get("carried_ammunition",0)))
            if not resource or count<=0 or carried<=0:continue
            targets[str(resource)]=targets.get(str(resource),0)+count*carried
        return targets

    def _combat_frontage_equivalent(self,rows:Sequence[Mapping[str,Any]],personnel:int,terrain_kind:str)->float:
        rules=self._combat_interaction_rules();terrain_map=rules.get("terrain_frontage_factor",{}) if isinstance(rules,Mapping) else {};terrain=_num(terrain_map.get(terrain_kind,.75) if isinstance(terrain_map,Mapping) else .75,.75);ref_width=_num(rules.get("frontage_reference_m_per_1000_open",500),500);available_width=ref_width*terrain*math.sqrt(max(.05,personnel/1000.0))
        if not rows:return max(1.0,personnel*min(1.0,.35+.65*terrain))
        total=max(1,sum(int(r.get("count",0)) for r in rows));effective=0.0
        for row in rows:
            count=max(0,int(row.get("count",0)));share=available_width*count/total;front=min(count,share/max(.45,_num(row.get("frontage_spacing_m",.9),.9)));depth=max(0,count-front)*_clampf(_num(row.get("depth_support_factor",.3)),0,.7);effective+=front+depth
        return max(1.0,min(float(personnel),effective))

    def _combat_reach_factor(self,own:Sequence[Mapping[str,Any]],opposing:Sequence[Mapping[str,Any]],cohesion:float,terrain_kind:str)->float:
        if not own or not opposing:return 1.0
        own_n=max(1,sum(int(r.get("count",0)) for r in own));opp_n=max(1,sum(int(r.get("count",0)) for r in opposing));own_reach=sum(_num(r.get("melee_reach_m",.8))*int(r.get("count",0)) for r in own)/own_n;opp_reach=sum(_num(r.get("melee_reach_m",.8))*int(r.get("count",0)) for r in opposing)/opp_n;own_min=sum(_num(r.get("melee_minimum_range_m",.1))*int(r.get("count",0)) for r in own)/own_n;opp_min=sum(_num(r.get("melee_minimum_range_m",.1))*int(r.get("count",0)) for r in opposing)/opp_n;rules=self._combat_interaction_rules();per_m=_num(rules.get("ordered_reach_advantage_per_meter",.16),.16);cap=_num(rules.get("ordered_reach_advantage_cap",.22),.22);retention=_num(rules.get("disorder_reach_retention",.35),.35);tight=terrain_kind in {"pass","fort","fortress","city","capital","town","estate","hall","forest","mountain"};order=_clampf(cohesion/80.0,0,1)*(.70 if tight else 1.0);reach_bonus=_clampf((own_reach-opp_reach)*per_m,-cap,cap)*(retention+(1-retention)*order);compression=_clampf((60-cohesion)/60.0+(.25 if tight else 0),0,1);min_cap=_num(rules.get("compressed_minimum_range_penalty_cap",.22),.22);min_penalty=min(min_cap,max(0,own_min-.25)*.22*compression);close_cap=_num(rules.get("compressed_short_weapon_bonus_cap",.14),.14);close_per_m=_num(rules.get("compressed_short_weapon_bonus_per_meter",.18),.18);close_bonus=min(close_cap,max(0.0,opp_min-own_min)*close_per_m*compression);return _clampf(1+reach_bonus-min_penalty+close_bonus,.72,1.28)

    def _combat_ammunition_stock_targets(self,rows:Sequence[Mapping[str,Any]],*,carried_loads:float=1.0)->dict[str,int]:
        targets={};loads=max(0.0,float(carried_loads))
        for row in rows:
            resource=row.get("ammunition_resource");count=max(0,int(row.get("count",0)));carried=max(0,int(row.get("carried_ammunition",0)))
            if not resource or count<=0 or carried<=0:continue
            targets[str(resource)]=targets.get(str(resource),0)+int(math.ceil(count*carried*loads))
        return targets

    def _combat_ammunition_plan(self,rows:Sequence[Mapping[str,Any]],logistics:Mapping[str,Any],battle_hours:float)->dict[str,Any]:
        rules=self._combat_interaction_rules();duty=_clampf(_num(rules.get("ranged_fire_duty_fraction",.10),.10),.01,.35);opening=max(0,int(rules.get("minimum_opening_shots_per_ranged_person",2)));desired_by_resource={};ranged_by_resource={}
        for row in rows:
            resource=row.get("ammunition_resource");count=max(0,int(row.get("count",0)));cycle=max(1.0,_num(row.get("ranged_cycle_seconds",0),0))
            if not resource or count<=0 or cycle<=0 or _num(row.get("ranged_score"))<=0:continue
            carried=max(0,int(row.get("carried_ammunition",0)));cadence_shots=max(opening,int(math.ceil(max(0.0,battle_hours)*3600.0*duty/cycle)));per_person=min(carried if carried else cadence_shots,cadence_shots) if carried else cadence_shots;desired_by_resource[str(resource)]=desired_by_resource.get(str(resource),0)+count*max(0,per_person);ranged_by_resource[str(resource)]=ranged_by_resource.get(str(resource),0)+count
        consumed={};suff={}
        for resource,desired in desired_by_resource.items():available=max(0,int(logistics.get(resource,0)));used=min(available,desired);consumed[resource]=used;suff[resource]=1.0 if desired<=0 else used/max(1,desired)
        total_desired=sum(desired_by_resource.values());total_used=sum(consumed.values());overall=1.0 if total_desired<=0 else total_used/max(1,total_desired);return {"desired_by_resource":desired_by_resource,"consumed_by_resource":consumed,"sufficiency_by_resource":suff,"overall_sufficiency":overall,"ranged_personnel":sum(ranged_by_resource.values())}

    def _combat_ranged_contact_profile(self,rows:Sequence[Mapping[str,Any]],ammo_plan:Mapping[str,Any],opposing:Sequence[Mapping[str,Any]]|None=None)->dict[str,Any]:
        ranged=[r for r in rows if _num(r.get("ranged_effective_range_m"))>0 and _num(r.get("ranged_score"))>0 and r.get("ammunition_item")]
        opposing=list(opposing or [])
        if not ranged or not opposing:
            return {"projectiles_fired":0,"weighted_impact_index":0.0,"weighted_penetration_index":0.0,"shield_intercept_fraction":0.0,"shield_wear_pct":0.0,"armor_penetration_ratio":0.0,"armor_wear_pct":0.0,"combat_factor":1.0,"contact_distribution":{}}
        consumed=ammo_plan.get("consumed_by_resource",{}) if isinstance(ammo_plan,Mapping) else {}
        total_shots=0; impact_sum=penetration_sum=flight_sum=0.0; recovery_weight=0.0
        for row in ranged:
            resource=str(row.get("ammunition_resource") or ""); shots=max(0,int(consumed.get(resource,0)))
            resource_personnel=max(1,sum(max(0,int(x.get("count",0))) for x in ranged if str(x.get("ammunition_resource") or "")==resource))
            share_shots=shots*max(0,int(row.get("count",0)))/resource_personnel
            if share_shots<=0: continue
            weapon=self._combat_weapon(row.get("ranged_weapon_id")); projectile=self._combat_weapon(row.get("ammunition_item"))
            representative_distance=min(max(15.0,_num(row.get("ranged_effective_range_m"))*.72),max(15.0,_num(row.get("ranged_max_direct_range_m"),_num(row.get("ranged_effective_range_m")))))
            flight=projectile_flight_resolution(weapon,projectile,distance_m=representative_distance,weapon_skill=_num(row.get("ranged_score")),strength=_num(row.get("ranged_strength")),coordination=_num(row.get("ranged_coordination")),awareness=_num(row.get("ranged_awareness")),weapon_condition_pct=_num(row.get("equipment_condition_pct"),100))
            total_shots+=share_shots; impact_sum+=_num(flight.get("impact_index"))*share_shots; penetration_sum+=_num(flight.get("penetration_index"))*share_shots; flight_sum+=_num(flight.get("flight_time_seconds"))*share_shots; recovery_weight+=_num(flight.get("projectile_recovery_base"))*share_shots
        if total_shots<=0:
            return {"projectiles_fired":0,"weighted_impact_index":0.0,"weighted_penetration_index":0.0,"shield_intercept_fraction":0.0,"shield_wear_pct":0.0,"armor_penetration_ratio":0.0,"armor_wear_pct":0.0,"combat_factor":1.0,"contact_distribution":{}}
        impact=impact_sum/total_shots; penetration=penetration_sum/total_shots; avg_flight=flight_sum/total_shots
        opp_total=max(1,sum(max(0,int(r.get("count",0))) for r in opposing))
        shield_rows=[r for r in opposing if _num(r.get("shield_structure"))>0 and _num(r.get("shield_units",r.get("count",0)))>0]
        shield_n=sum(max(0.0,_num(r.get("shield_units",r.get("count",0)))) for r in shield_rows)
        shield_share=shield_n/opp_total
        shield_structure=sum(_num(r.get("shield_structure"))*_num(r.get("shield_units",r.get("count",0))) for r in shield_rows)/max(1.0,shield_n) if shield_n else 0.0
        shield_coverage=sum(_num(r.get("shield_coverage_degrees"))*_num(r.get("shield_units",r.get("count",0))) for r in shield_rows)/max(1.0,shield_n) if shield_n else 0.0
        opp_order=sum((.58*_num(r.get("formation_cohesion",50))+.42*_num(r.get("formation_training",20)))*int(r.get("count",0)) for r in opposing)/opp_total
        facing=1.0-math.exp(-max(0.0,opp_order)/85.0)
        intercept=_clampf(shield_share*(shield_coverage/150.0)*(.55+.45*facing),0.0,.92)
        # Ordered shields can meet incoming missiles obliquely. The angle is a
        # physical interception geometry: it changes normal impulse, effective
        # path through the shield, wear and residual penetration.
        interception_angle=0.0 if shield_n<=0 else _clampf(8.0+44.0*facing,8.0,58.0)
        normal_fraction=max(.20,math.cos(math.radians(interception_angle))) if shield_n else 1.0
        path_factor=min(1.85,1.0/max(.20,normal_fraction)) if shield_n else 1.0
        effective_shield_structure=shield_structure*path_factor
        intercepted=total_shots*intercept
        shield_wear=0.0 if shield_n<=0 else min(28.0,(intercepted/max(1,shield_n))*max(.15,(impact*normal_fraction)/max(1.0,effective_shield_structure))*2.6)
        armor=sum(_num(r.get("armor_protection_index",r.get("protection_index",0)))*int(r.get("count",0)) for r in opposing)/opp_total
        deflection=1.0-normal_fraction
        shield_penetration_absorption=intercept*effective_shield_structure*.55*(1.0+.35*deflection)
        residual_penetration=max(0.0,penetration-shield_penetration_absorption)
        armor_ratio=residual_penetration/max(20.0,armor if armor>0 else 28.0)
        armor_wear=min(12.0,(total_shots/opp_total)*min(2.0,armor_ratio)*.55)
        penetration_expression=math.tanh(max(0.0,armor_ratio-.55)*.55)
        combat_factor=1.0+.10*penetration_expression
        # Statistical contact locations for aggregate soldiers. Exact named-person
        # contacts use the personal anatomy resolver instead of this distribution.
        contact_distribution={"upper_torso":0.34,"head_neck":0.12,"arms_hands":0.18,"lower_torso":0.13,"legs_feet":0.23}
        return {"projectiles_fired":int(round(total_shots)),"weighted_impact_index":round(impact,3),"weighted_penetration_index":round(penetration,3),"average_flight_time_seconds":round(avg_flight,4),"shield_intercept_fraction":round(intercept,5),"average_shield_interception_angle_deg":round(interception_angle,3),"shield_effective_path_factor":round(path_factor,5),"shield_wear_pct":round(shield_wear,3),"armor_penetration_ratio":round(armor_ratio,5),"armor_wear_pct":round(armor_wear,3),"combat_factor":round(combat_factor,6),"projectile_recovery_base":round(recovery_weight/total_shots,5),"contact_distribution":contact_distribution}

    def _combat_ranged_factor(self,rows:Sequence[Mapping[str,Any]],ammo_plan:Mapping[str,Any],opposing:Sequence[Mapping[str,Any]]|None=None)->float:
        ranged=[r for r in rows if _num(r.get("ranged_effective_range_m"))>0 and _num(r.get("ranged_score"))>0]
        if not ranged:return 1.0
        ammo_overall=_clampf(_num(ammo_plan.get("overall_sufficiency",0) if isinstance(ammo_plan,Mapping) else 0),0,1)
        if ammo_overall<=0:return 1.0
        n=max(1,sum(int(r.get("count",0)) for r in rows));rules=self._combat_interaction_rules();suff=ammo_plan.get("sufficiency_by_resource",{}) if isinstance(ammo_plan,Mapping) else {};bonus=0.0;opposing_ranged=[r for r in (opposing or []) if _num(r.get("ranged_effective_range_m"))>0 and _num(r.get("ranged_score"))>0];opp_n=max(1,sum(int(r.get("count",0)) for r in opposing_ranged));opp_range=(sum(_num(r.get("ranged_effective_range_m"))*int(r.get("count",0)) for r in opposing_ranged)/opp_n) if opposing_ranged else 0.0;own_ranged_n=max(1,sum(int(r.get("count",0)) for r in ranged));own_range=sum(_num(r.get("ranged_effective_range_m"))*int(r.get("count",0)) for r in ranged)/own_ranged_n;range_superiority=0.0
        if opp_range>0:
            ref=max(1.0,_num(rules.get("ranged_effective_range_reference_m",120),120));range_superiority=_clampf(((own_range-opp_range)/ref)*_num(rules.get("range_superiority_per_reference",.12),.12),-_num(rules.get("range_superiority_cap",.18),.18),_num(rules.get("range_superiority_cap",.18),.18))
        elif own_range>0:range_superiority=min(_num(rules.get("range_superiority_cap",.18),.18),.08)
        opp_total=max(1,sum(max(0,int(r.get("count",0))) for r in (opposing or [])));opp_mounted=sum(max(0.0,_num(r.get("mounted_units",r.get("count",0)))) for r in (opposing or []) if _num(r.get("mount_index"))>0);closing_speed=_num(rules.get("mounted_closing_speed_mps",3.4),3.4) if opp_mounted/opp_total>=.40 else _num(rules.get("default_closing_speed_mps",1.6),1.6);volley_cap=max(0,int(rules.get("opening_volley_opportunity_cap",4)));volley_weight=_num(rules.get("opening_volley_bonus_per_opportunity",.035),.035);minimum_window=max(0.0,_num(rules.get("minimum_range_window_m",12.0),12.0));opening_bonus=0.0
        for row in ranged:
            count=max(0,int(row.get("count",0)));share=count/n;resource=str(row.get("ammunition_resource") or "");ammo=_clampf(_num(suff.get(resource,0) if isinstance(suff,Mapping) else 0),0,1)
            if ammo<=0:continue
            effective_range=_num(row.get("ranged_effective_range_m"));max_range=_num(row.get("ranged_max_direct_range_m",effective_range));range_ref=_num(rules.get("ranged_effective_range_reference_m",120),120);range_factor=_clampf(effective_range/range_ref,.40,1.65)*_clampf(.92+.08*(max_range/max(1.0,effective_range)),.92,1.10);cycle=max(1.0,_num(row.get("ranged_cycle_seconds",8),8));cadence=_clampf(_num(rules.get("ranged_cycle_reference_seconds",6),6)/cycle,.35,1.7);power=_clampf(_num(row.get("ranged_power_index",70),70)/70.0,.45,1.75);skill=max(.35,.35+max(0.0,_num(row.get("ranged_score")))/100.0);bonus+=_num(rules.get("ranged_opening_weight",.28),.28)*share*range_factor*cadence*power*skill*ammo;window=effective_range if opp_range<=0 else max(0.0,effective_range-opp_range)
            if window>=minimum_window and closing_speed>0 and volley_cap>0:opportunities=min(volley_cap,int((window/closing_speed)//cycle));opening_bonus+=opportunities*volley_weight*share*skill*ammo
        return _clampf(1.0+min(.75,bonus)+min(.22,opening_bonus)+range_superiority*ammo_overall,.72,1.95)

    def _combat_melee_weapon_factor(self,rows:Sequence[Mapping[str,Any]])->float:
        total=max(1,sum(max(0,int(r.get("count",0))) for r in rows))
        if not rows:return 1.0
        handling=sum(_num(r.get("melee_handling",.8))*max(0,int(r.get("count",0))) for r in rows)/total;force=sum(_num(r.get("melee_force",.7))*max(0,int(r.get("count",0))) for r in rows)/total;return _clampf(1.0+(handling-.85)*.12+(force-.80)*.10,.90,1.12)

    def _combat_protection_factor(self,rows:Sequence[Mapping[str,Any]])->float:
        total=max(1,sum(int(r.get("count",0)) for r in rows));protection=sum(_num(r.get("armor_protection_index",r.get("protection_index",0)))*int(r.get("count",0)) for r in rows)/total if rows else 0;return _clampf(1.0+protection/800.0,1.0,1.18)

    def _combat_mount_factor(self,rows:Sequence[Mapping[str,Any]],formation:Mapping[str,Any])->float:
        mounted=[r for r in rows if _num(r.get("mount_index"))>0]
        required=sum(max(0.0,_num(r.get("mount_required_units",r.get("count",0)))) for r in mounted)
        actual=sum(max(0.0,_num(r.get("mounted_units",0))) for r in mounted)
        if required<=0:return 1.0
        complete=_clampf(actual/max(1.0,required),0,1)
        quality=sum(_num(r.get("mount_index"))*max(0.0,_num(r.get("mounted_units",0))) for r in mounted)/max(1.0,actual) if actual>0 else 0.0
        return _clampf(.82+.18*complete+max(0,quality-70)/900.0,.75,1.16)

    def _combat_phase_mount_attrition(self,serviceable_mounts:int,mounted_share:float,mount_casualty_risk:float,phase_hours:float,contact_wear_factor:float)->dict[str,Any]:
        """Resolve bounded horse losses during one aggregate contact phase.

        This exists so a cavalry body stopped on spears in the opening phase
        cannot reuse every opening horse in the sustained/resolution phases. It
        remains aggregate and conserved; no individual horses are materialized.
        """
        units=max(0,int(serviceable_mounts)); share=_clampf(_num(mounted_share),0.0,1.0); risk=max(.0,_num(mount_casualty_risk,1.0)); hours=max(0.0,_num(phase_hours)); wear=max(0.0,_num(contact_wear_factor,1.0)); rules=self._combat_interaction_rules()
        if units<=0 or share<=0 or hours<=0:return {"units_before":units,"units_lost":0,"units_after":units,"loss_fraction":0.0}
        base=max(0.0,_num(rules.get("mount_phase_base_loss_fraction_per_hour",.002),.002))
        risk_scale=max(0.0,_num(rules.get("mount_phase_risk_excess_loss_fraction_per_hour",.006),.006))
        cap=_clampf(_num(rules.get("mount_phase_loss_fraction_cap",.12),.12),0.0,1.0)
        hazard=(base+max(0.0,risk-.75)*risk_scale)*hours*wear*share
        fraction=min(cap,max(0.0,hazard)); lost=min(units,max(0,int(round(units*fraction))))
        return {"units_before":units,"units_lost":lost,"units_after":units-lost,"loss_fraction":round(fraction,8),"mounted_share":round(share,6),"mount_casualty_risk":round(risk,6)}

    def _combat_formation_method_profile(self,rows:Sequence[Mapping[str,Any]],formation:Mapping[str,Any],opposing_rows:Sequence[Mapping[str,Any]],terrain_kind:str)->dict[str,Any]:
        """Derive shield-wall, spear-brace, phalanx and charge expression from physics.

        These are not doctrine-name bonuses. They require the actual shields, long
        weapons, mounts, training/cohesion, frontage and terrain that make the
        method physically possible.
        """
        total=max(1,sum(max(0,int(r.get("count",0))) for r in rows))
        opp_total=max(1,sum(max(0,int(r.get("count",0))) for r in opposing_rows))
        cohesion=max(0.0,_num(formation.get("cohesion",50),50)); training=max(0.0,_num(formation.get("training_progress",20),20))
        order_raw=(.58*cohesion+.42*training)
        # Diminishing organizational expression, not a stat ceiling. Values above
        # 100 continue to improve toward perfect physical coordination.
        order=1.0-math.exp(-max(0.0,order_raw)/85.0)
        shield_n=sum(max(0.0,_num(r.get("shield_units",r.get("count",0)))) for r in rows if _num(r.get("shield_structure"))>0)
        long_spear_n=sum(int(r.get("count",0)) for r in rows if str(r.get("melee_weapon_family","")).lower() in {"spear","lance"} and _num(r.get("melee_reach_m"))>=1.8)
        mounted_n=sum(max(0.0,_num(r.get("mounted_units",r.get("count",0)))) for r in rows if r.get("mounted"))
        opp_mounted_n=sum(max(0.0,_num(r.get("mounted_units",r.get("count",0)))) for r in opposing_rows if r.get("mounted"))
        shield_share=shield_n/total; spear_share=long_spear_n/total; mounted_share=mounted_n/total; opp_mounted_share=opp_mounted_n/opp_total if opposing_rows else 0.0
        ff=sum(_num(r.get("formation_fighting"))*int(r.get("count",0)) for r in rows)/total if rows else 0.0
        formation_skill=1.0-math.exp(-max(0.0,ff)/100.0)
        avg_shield_structure=sum(_num(r.get("shield_structure"))*_num(r.get("shield_units",r.get("count",0))) for r in rows)/max(1.0,shield_n) if shield_n else 0.0
        avg_shield_coverage=sum(_num(r.get("shield_coverage_degrees"))*_num(r.get("shield_units",r.get("count",0))) for r in rows)/max(1.0,shield_n) if shield_n else 0.0
        avg_reach=sum(_num(r.get("melee_reach_m",.75))*int(r.get("count",0)) for r in rows)/total if rows else .75
        depth=sum(_num(r.get("depth_support_factor",0))*int(r.get("count",0)) for r in rows)/total if rows else 0.0
        foot_share=max(0.0,1.0-mounted_share)
        shieldwall_integrity=shield_share*foot_share*order*(.55+.45*formation_skill)*_clampf(avg_shield_coverage/110.0,.45,1.25) if shield_n else 0.0
        phalanx_integrity=min(shield_share,spear_share)*foot_share*order*(.50+.50*formation_skill)*(1.0+.30*depth)
        brace_integrity=spear_share*foot_share*order*(.55+.45*formation_skill)*(1.0+.25*depth)*opp_mounted_share
        constrained=terrain_kind in {"pass","fort","fortress","capital","city","town","estate","hall","forest","mountain"}
        lane_factor=.50 if constrained else 1.0
        charge_rows=[r for r in rows if r.get("mounted") and r.get("charge_legal") and _num(r.get("mounted_units",r.get("count",0)))>0]
        charge_units=sum(max(0.0,_num(r.get("mounted_units",r.get("count",0)))) for r in charge_rows)
        charge_mass=sum(_num(r.get("mount_total_mass_kg"))*max(0.0,_num(r.get("mounted_units",r.get("count",0)))) for r in charge_rows)/max(1.0,charge_units) if charge_rows else 0.0
        charge_speed=sum(_num(r.get("mount_speed_mps"))*max(0.0,_num(r.get("mounted_units",r.get("count",0)))) for r in charge_rows)/max(1.0,charge_units) if charge_rows else 0.0
        riding=sum(_num(r.get("riding"))*max(0.0,_num(r.get("mounted_units",r.get("count",0)))) for r in rows)/max(1.0,mounted_n) if mounted_n>0 else 0.0
        alignment=(1.0-math.exp(-max(0.0,riding)/110.0))*order if charge_rows else 0.0
        collision_index=(charge_mass*charge_speed*charge_speed/100.0)*alignment*lane_factor*mounted_share if charge_rows else 0.0
        # Opposing spear depth and order attacks the horse/rider system before the
        # charge can fully express. This is derived from the opposing rows, not an
        # arbitrary anti-cavalry tag.
        opp_spear_n=sum(int(r.get("count",0)) for r in opposing_rows if str(r.get("melee_weapon_family","")).lower() in {"spear","lance"} and _num(r.get("melee_reach_m"))>=1.8)
        opp_spear_share=opp_spear_n/opp_total if opposing_rows else 0.0
        opp_ff=sum(_num(r.get("formation_fighting"))*int(r.get("count",0)) for r in opposing_rows)/opp_total if opposing_rows else 0.0
        opp_cohesion=sum(_num(r.get("formation_cohesion",50))*int(r.get("count",0)) for r in opposing_rows)/opp_total if opposing_rows else 0.0
        opp_training=sum(_num(r.get("formation_training",20))*int(r.get("count",0)) for r in opposing_rows)/opp_total if opposing_rows else 0.0
        opp_order=1.0-math.exp(-max(0.0,.58*opp_cohesion+.42*opp_training)/85.0) if opposing_rows else 0.0
        opp_skill=1.0-math.exp(-max(0.0,opp_ff)/100.0) if opposing_rows else 0.0
        opp_reach=sum(_num(r.get("melee_reach_m",.75))*int(r.get("count",0)) for r in opposing_rows)/opp_total if opposing_rows else .75
        opposing_brace_integrity=opp_spear_share*opp_order*(.55+.45*opp_skill)*mounted_share
        brace_absorption=1.0-math.exp(-max(0.0,opposing_brace_integrity*opp_reach*1.4))
        charge_expression=math.log1p(max(0.0,collision_index))/8.0 if collision_index>0 else 0.0
        charge_factor=1.0+mounted_share*charge_expression*(1.0-.72*brace_absorption)
        formation_factor=1.0
        if shieldwall_integrity>0: formation_factor*=1.0+.06*shieldwall_integrity*math.log1p(max(1.0,avg_shield_structure))/5.0
        if phalanx_integrity>0: formation_factor*=1.0+.075*phalanx_integrity*math.sqrt(max(.5,avg_reach/2.0))
        if brace_integrity>0: formation_factor*=1.0+.10*brace_integrity
        formation_factor*=charge_factor
        # Melee penetration is resolved against the opposing physical protection
        # layers instead of being hidden inside a generic weapon bonus. This stays
        # aggregate: one cohort pressure versus one opposing protection envelope.
        own_penetration_pressure=sum(
            _num(r.get("melee_score"))*_num(r.get("melee_force",.5))*_num(r.get("melee_penetration_factor",.7))*int(r.get("count",0))
            for r in rows
        )/total if rows else 0.0
        opp_protection=sum(_num(r.get("armor_protection_index",r.get("protection_index",0)))*int(r.get("count",0)) for r in opposing_rows)/opp_total if opposing_rows else 0.0
        opp_shield_n=sum(max(0.0,_num(r.get("shield_units",r.get("count",0)))) for r in opposing_rows if _num(r.get("shield_structure"))>0)
        opp_shield_share=opp_shield_n/opp_total if opposing_rows else 0.0
        opp_shield_structure=sum(_num(r.get("shield_structure"))*_num(r.get("shield_units",r.get("count",0))) for r in opposing_rows)/max(1.0,opp_shield_n) if opp_shield_n else 0.0
        defensive_layer=35.0+.62*opp_protection+.28*opp_shield_share*opp_shield_structure
        penetration_ratio=own_penetration_pressure/max(1.0,defensive_layer)
        penetration_expression=math.tanh(max(0.0,penetration_ratio-.70)*.55)
        formation_factor*=1.0+.055*penetration_expression
        avg_mount_protection=sum(_num(r.get("mount_protection_index"))*max(0.0,_num(r.get("mounted_units",r.get("count",0)))) for r in rows)/max(1.0,mounted_n) if mounted_n else 0.0
        horse_armor_survival=1.0/(1.0+max(0.0,avg_mount_protection)/180.0)
        mount_casualty_risk=(1.0+1.20*brace_absorption*mounted_share)*(.65+.35*horse_armor_survival) if mounted_n else 1.0
        methods=[]
        if shieldwall_integrity>=.28: methods.append("shield_wall")
        if phalanx_integrity>=.24: methods.append("phalanx_or_spear_wall")
        if brace_integrity>=.12: methods.append("braced_anti_cavalry")
        if collision_index>0 and mounted_share>=.20: methods.append("mounted_charge")
        return {
            "methods":methods,"order_expression":round(order,5),"shield_share":round(shield_share,5),"long_spear_share":round(spear_share,5),"mounted_share":round(mounted_share,5),"opposing_mounted_share":round(opp_mounted_share,5),
            "shieldwall_integrity":round(shieldwall_integrity,5),"phalanx_integrity":round(phalanx_integrity,5),"brace_integrity":round(brace_integrity,5),"average_shield_structure":round(avg_shield_structure,3),"average_shield_coverage_degrees":round(avg_shield_coverage,3),"average_melee_reach_m":round(avg_reach,3),
            "charge_collision_index":round(collision_index,3),"charge_speed_mps":round(charge_speed,3),"charge_mass_kg":round(charge_mass,3),"charge_alignment":round(alignment,5),"opposing_brace_integrity":round(opposing_brace_integrity,5),"brace_absorption":round(brace_absorption,5),
            "melee_penetration_pressure":round(own_penetration_pressure,3),"opposing_protection_layer":round(defensive_layer,3),"penetration_ratio":round(penetration_ratio,5),"penetration_expression":round(penetration_expression,5),
            "combat_factor":round(formation_factor,6),"mount_casualty_risk":round(max(.25,mount_casualty_risk),6),"average_mount_protection":round(avg_mount_protection,3),
        }

    def _combat_hero_interventions(self,named:Sequence[Mapping[str,Any]],own_rows:Sequence[Mapping[str,Any]],opposing_rows:Sequence[Mapping[str,Any]],*,battle_hours:float,terrain_kind:str)->dict[str,Any]:
        """Resolve bounded local hero windows through the normal physical layers.

        This remains aggregate at the anonymous-soldier level: it never creates
        phantom individual enemies.  A named person's local contact window is
        bounded to at most 120 seconds, then its representative contacts are
        resolved against the actual opposing role loadouts, shield condition,
        armor condition, formation defense quality and weapon/projectile physics.
        The resulting casualty, frontage, officer and cohesion pressure feeds the
        formation battle instead of converting the hero into equivalent bodies.
        """
        opp_total=max(0,sum(max(0,int(r.get("count",0))) for r in opposing_rows))
        if opp_total<=0:
            return {"interventions":[],"disruption_factor":1.0,"casualty_pressure":0,"frontage_displacement_m":0.0,"officer_pressure":0.0,"cohesion_shock_pressure":0.0,"artillery_pressure":0.0,"command_attention_seconds":0.0}
        opp_melee=sum(_num(r.get("melee_score"))*int(r.get("count",0)) for r in opposing_rows)/max(1,opp_total)
        opp_ranged=sum(_num(r.get("ranged_score"))*int(r.get("count",0)) for r in opposing_rows)/max(1,opp_total)
        own_total=max(1,sum(max(0,int(r.get("count",0))) for r in own_rows))
        own_melee=sum(_num(r.get("melee_score"))*int(r.get("count",0)) for r in own_rows)/own_total if own_rows else 0.0
        own_ranged=sum(_num(r.get("ranged_score"))*int(r.get("count",0)) for r in own_rows)/own_total if own_rows else 0.0
        opp_protection=sum(_num(r.get("armor_protection_index",r.get("protection_index",0)))*int(r.get("count",0)) for r in opposing_rows)/max(1,opp_total)
        constrained=terrain_kind in {"pass","fort","fortress","capital","city","town","estate","hall","forest","mountain"}
        geometry=.70 if constrained else 1.0
        interventions=[]; total_pressure=0; total_displacement=0.0; total_officer_pressure=0.0; total_cohesion_shock=0.0; total_artillery_pressure=0.0; total_command_attention=0.0
        duty={"commander":.045,"deputy":.075,"staff":.012,"specialist":.12,"notable":.20,"embedded":.24,"higher_commander":0.0,"higher_deputy":0.0}
        def tissue_injury_expression(maximum_ratio: float) -> float:
            # Preserve the full continuous post-defense contact result instead
            # of flattening every contact inside a severity label to one value.
            # This is asymptotic rather than capped, so armor still changes the
            # expected injury pressure even when both contacts are "critical".
            ratio=max(0.0,_num(maximum_ratio))
            if ratio<=0.0:
                return .0
            return _clampf(.015+.965*(ratio/(ratio+1.50)),.0,.999)

        def target_plan(person:Mapping[str,Any])->dict[str,str]:
            doctrine=person.get("combat_targeting_doctrine",{}) if isinstance(person.get("combat_targeting_doctrine"),Mapping) else {}
            priorities=doctrine.get("lethal_priority",[]) if isinstance(doctrine,Mapping) else []
            if isinstance(priorities,list):
                for raw in priorities:
                    if isinstance(raw,Mapping) and raw.get("zone") and raw.get("structure"):
                        return {"zone":str(raw.get("zone")),"structure":str(raw.get("structure")),"purpose":str(raw.get("purpose","battlefield_incapacitation")),"basis":"saved_combat_targeting_doctrine"}
            return {"zone":"upper_torso","structure":"upper_torso","purpose":"battlefield_incapacitation","basis":"formation_contact_default"}

        def physical_layer_profile(target:Mapping[str,Any],*,mode:str,impact:float,penetration:float,hero_score:float,plan:Mapping[str,str])->dict[str,Any]:
            loadout=self._combat_loadout(str(target.get("loadout_id","")))
            shield_id=target.get("shield_id") or loadout.get("shield")
            body_armor_id=target.get("body_armor_id") or loadout.get("body_armor")
            helmet_id=target.get("helmet_id") or loadout.get("helmet")
            shield=self._combat_weapon(shield_id)
            shield_availability=_clampf(_num(target.get("shield_availability",1.0 if shield else 0.0),1.0 if shield else 0.0),0.0,1.0)
            if shield_availability<=0.0:
                shield={}
            target_control=max(0.0,_num(target.get("melee_score")))
            formation_fighting=max(0.0,_num(target.get("formation_fighting")))
            control_ratio=_clampf((target_control+.35*formation_fighting+25.0)/max(25.0,hero_score+35.0),.25,1.35)
            order_raw=.58*_num(target.get("formation_cohesion",50))+.42*_num(target.get("formation_training",20))
            order=1.0-math.exp(-max(0.0,order_raw)/85.0)
            timing_factor=_clampf(.35+.55*order+.10*control_ratio,.20,1.0)
            interception_angle=8.0+44.0*order if shield else 0.0
            shield_result=shield_contact_resolution(
                shield,impact_index=impact,penetration_index=penetration,mode=mode,
                condition_pct=_num(target.get("shield_condition_pct",target.get("equipment_condition_pct",100)),100),
                timing_factor=timing_factor,block_control_ratio=control_ratio,
                interception_angle_deg=interception_angle if shield else None,
            )
            residual_impact=_num(shield_result.get("residual_impact"),impact)
            residual_penetration=_num(shield_result.get("residual_penetration_index"),penetration)
            armor=self._combat_weapon(body_armor_id); helmet=self._combat_weapon(helmet_id)
            zone=str(plan.get("zone","upper_torso")); structure=str(plan.get("structure",zone))
            covering={}
            if hasattr(self,"_personal_zone_covered"):
                try:
                    covered,covering=self._personal_zone_covered(zone,armor,helmet,structure)
                    if not covered: covering={}
                except Exception:
                    covering=helmet if zone=="head" else armor
            else:
                covering=helmet if zone=="head" else armor
            armor_condition=_num(target.get("armor_condition_pct",target.get("equipment_condition_pct",100)),100)
            armor_result=armor_contact_resolution(
                covering,mode=mode,impact_index=residual_impact,penetration_index=residual_penetration,
                condition_pct=armor_condition,structure=structure,
            )
            # Aggregate role rows may have fewer physical shields than bodies.
            # Resolve the shielded and unshielded paths separately and blend only
            # their expected tissue expression. A role loadout naming a shield is
            # never proof that every surviving soldier still carries one.
            if 0.0 < shield_availability < 1.0:
                unshielded_armor=armor_contact_resolution(
                    covering,mode=mode,impact_index=impact,penetration_index=penetration,
                    condition_pct=armor_condition,structure=structure,
                )
                maximum_ratio=(
                    shield_availability*_num(armor_result.get("maximum_ratio",0))
                    +(1.0-shield_availability)*_num(unshielded_armor.get("maximum_ratio",0))
                )
                residual_impact_expected=(
                    shield_availability*_num(armor_result.get("residual_impact_index",0))
                    +(1.0-shield_availability)*_num(unshielded_armor.get("residual_impact_index",0))
                )
                residual_penetration_expected=(
                    shield_availability*_num(armor_result.get("residual_penetration_index",0))
                    +(1.0-shield_availability)*_num(unshielded_armor.get("residual_penetration_index",0))
                )
                armor_penetrated_fraction=(
                    shield_availability*(1.0 if armor_result.get("penetrated") else 0.0)
                    +(1.0-shield_availability)*(1.0 if unshielded_armor.get("penetrated") else 0.0)
                )
            else:
                maximum_ratio=_num(armor_result.get("maximum_ratio",0))
                residual_impact_expected=_num(armor_result.get("residual_impact_index",0))
                residual_penetration_expected=_num(armor_result.get("residual_penetration_index",0))
                armor_penetrated_fraction=1.0 if armor_result.get("penetrated") else 0.0
            return {
                "target_role":str(target.get("role","")),"target_loadout_id":str(target.get("loadout_id","")),
                "aim_zone":zone,"aim_structure":structure,"aim_purpose":str(plan.get("purpose","")),"aim_basis":str(plan.get("basis","")),
                "shield_present":bool(shield),"shield_availability_fraction":round(shield_availability,6),
                "shield_residual_impact":round(residual_impact,3),"shield_residual_penetration":round(residual_penetration,3),
                "shield_condition_loss_pct":round(_num(shield_result.get("condition_loss_pct",0))*shield_availability,4),"shield_failed":bool(shield_result.get("failed",False)) and shield_availability>=.999,
                "armor_covered":bool(armor_result.get("covered",False)),"armor_penetrated":armor_penetrated_fraction>=.5,
                "armor_penetrated_fraction":round(armor_penetrated_fraction,6),
                "armor_severity":str(armor_result.get("severity","none")),"armor_maximum_ratio":round(maximum_ratio,6),
                "armor_residual_impact":round(residual_impact_expected,6),"armor_residual_penetration":round(residual_penetration_expected,6),
            }

        def transient_contact_timeline(*, active_seconds: float, outgoing_contacts: int, outgoing_interval: float, incoming_expected: float, ranged: bool, flight_seconds: float = 0.0) -> dict[str,Any]:
            """Compact continuous-time bridge for an exact hero inside an aggregate frontage.

            Anonymous soldiers remain aggregate and are never materialized.  The
            timeline nevertheless preserves the same causal ordering used by exact
            combat: action start, release/contact, recovery, incoming pressure and
            near-simultaneous contact groups.  It is a deterministic representative
            schedule, not a second casualty authority.
            """
            duration=max(0.0,float(active_seconds)); out_n=max(0,int(outgoing_contacts)); interval=max(.20,float(outgoing_interval or 1.0)); incoming=max(0.0,float(incoming_expected))
            events=[]
            # Keep trace bounded while preserving the beginning, middle and end of
            # very dense hero windows.  Counts remain exact in the surrounding row.
            sample_cap=24
            if out_n>0 and duration>0:
                indices=list(range(out_n)) if out_n<=sample_cap else sorted(set(int(round(i*(out_n-1)/(sample_cap-1))) for i in range(sample_cap)))
                for index in indices:
                    start=min(duration,max(0.0,index*interval)); contact=min(duration,start+(float(flight_seconds) if ranged else min(.55,interval*.42))); recovery=min(duration,max(contact,start+interval))
                    events.append({
                        "kind":"hero_projectile_contact" if ranged else "hero_melee_contact",
                        "ordinal":index+1,
                        "start_at_s":round(start,3),
                        "contact_at_s":round(contact,3),
                        "recovery_complete_at_s":round(recovery,3),
                    })
            incoming_n=max(0,int(round(incoming)))
            if incoming_n>0 and duration>0:
                indices=list(range(incoming_n)) if incoming_n<=sample_cap else sorted(set(int(round(i*(incoming_n-1)/(sample_cap-1))) for i in range(sample_cap)))
                step=duration/max(1,incoming_n)
                for index in indices:
                    contact=min(duration,(index+.5)*step)
                    events.append({
                        "kind":"incoming_contact_pressure",
                        "ordinal":index+1,
                        "contact_at_s":round(contact,3),
                    })
            events.sort(key=lambda row:(float(row.get("contact_at_s",row.get("start_at_s",0)) or 0),0 if str(row.get("kind")).startswith("incoming") else 1,int(row.get("ordinal",0))))
            simultaneous=.08
            group=0; anchor=-999.0
            for row in events:
                t=float(row.get("contact_at_s",row.get("start_at_s",0)) or 0)
                if t-anchor>simultaneous:
                    group+=1; anchor=t
                row["contact_group_id"]=f"hero_group_{group:03d}"
            return {
                "mode":"transient_continuous_contact_adapter",
                "persistent_anonymous_people_materialized":False,
                "window_seconds":round(duration,3),
                "simultaneous_window_seconds":simultaneous,
                "outgoing_contact_count":out_n,
                "incoming_expected_contacts":round(incoming,5),
                "representative_events":events,
                "representative_events_truncated":(out_n+incoming_n)>len(events),
            }

        def incoming_exposure_profile(person:Mapping[str,Any],*,active_seconds:float,local_front:int,intervention_mode:str)->dict[str,Any]:
            """Estimate only the contacts created by this hero's local intervention.

            Anonymous enemies stay aggregate, but their actual weapon family,
            strength/skill means and the hero's real shield/armor layers determine
            the injury hazard. This is separate from generic formation casualty
            exposure and can therefore be used to settle the named person's own
            risk from personally entering the contact window.
            """
            hero_defense=(
                .46*max(0.0,_num(person.get("defense_skill_value")))
                +.18*max(0.0,_num(person.get("agility")))
                +.16*max(0.0,_num(person.get("coordination")))
                +.12*max(0.0,_num(person.get("awareness")))
                +.08*max(0.0,_num(person.get("composure")))
            )
            hero_target={
                "role":"named_hero","loadout_id":str(person.get("loadout_id","")),
                "shield_id":str(person.get("shield_id","")),"body_armor_id":str(person.get("body_armor_id","")),"helmet_id":str(person.get("helmet_id","")),
                "shield_condition_pct":_num(person.get("shield_condition_pct",100),100),
                "armor_condition_pct":_num(person.get("armor_condition_pct",100),100),"equipment_condition_pct":100.0,
                "melee_score":hero_defense,"formation_fighting":max(0.0,_num(person.get("defense_skill_value"))),
                "formation_cohesion":85.0,"formation_training":85.0,
            }
            incoming_plan={"zone":"upper_torso","structure":"upper_torso","purpose":"battlefield_contact","basis":"aggregate_enemy_contact_geometry"}
            expected_contacts=0.0; injury_hazard=0.0; death_hazard=0.0; samples=[]
            concurrency=min(4.0,max(1.0,1.0+math.sqrt(max(1,local_front))/3.0))*(.78 if constrained else 1.0)
            for enemy in opposing_rows:
                count=max(0,int(enemy.get("count",0)))
                if count<=0: continue
                share=count/max(1,opp_total)
                enemy_score=max(0.0,_num(enemy.get("melee_score")))
                if enemy_score<=0: continue
                enemy_weapon=self._combat_weapon(enemy.get("melee_weapon_id"))
                mode=str(enemy.get("melee_attack_mode") or "")
                if mode not in {"cut","thrust","blunt"}:
                    mode=max((("cut",_num(enemy_weapon.get("base_force_cut"))),("thrust",_num(enemy_weapon.get("base_force_thrust"))),("blunt",_num(enemy_weapon.get("base_force_blunt")))),key=lambda pair:pair[1])[0] if enemy_weapon else "blunt"
                attrs=enemy.get("attributes",{}) if isinstance(enemy.get("attributes"),Mapping) else {}
                strength=max(1.0,_num(attrs.get("Strength"),60.0))
                force=max(.20,_num(enemy.get("melee_force",.45),.45))
                enemy_impact=strength*force*(.78+math.sqrt(enemy_score)/36.0)
                enemy_penetration=enemy_impact*max(.10,_num(enemy.get("melee_penetration_factor",weapon_penetration_factor(enemy_weapon,mode)),.7))
                layer=physical_layer_profile(hero_target,mode=mode,impact=enemy_impact,penetration=enemy_penetration,hero_score=max(1.0,enemy_score),plan=incoming_plan)
                ratio=max(0.0,_num(layer.get("armor_maximum_ratio")))
                severity=str(layer.get("armor_severity","none")); injury_expression=tissue_injury_expression(ratio)
                contact_relative=1.0/(1.0+math.exp(_clampf((hero_defense-enemy_score)/42.0,-12.0,12.0)))
                # Only a small subset of surrounding enemy action opportunities
                # reaches a clean body-contact line against an actively defending
                # exact hero. Higher local concurrency increases pressure without
                # granting every anonymous soldier a simultaneous free attack.
                contact_mode_factor=.24 if intervention_mode=="ranged" else 1.0
                contact_rate=(.012+.075*contact_relative)*concurrency*max(.20,exposure)*contact_mode_factor
                expected=max(0.0,active_seconds*contact_rate*share)
                expected_contacts+=expected
                injury_hazard+=expected*injury_expression
                critical_component=injury_expression if severity=="critical" else (injury_expression*.28 if severity=="serious" else 0.0)
                death_hazard+=expected*critical_component*.085
                samples.append((count,{**layer,"enemy_role":str(enemy.get("role","")),"enemy_weapon_id":str(enemy.get("melee_weapon_id","")),"enemy_attack_mode":mode,"expected_contacts":round(expected,4),"injury_expression":round(injury_expression,6)}))
            samples.sort(key=lambda pair:(-pair[0],str(pair[1].get("enemy_role",""))))
            return {
                "expected_contacts":round(expected_contacts,5),
                "injury_hazard":round(injury_hazard,6),
                "injury_risk":round(1.0-math.exp(-max(0.0,injury_hazard)),6),
                "death_risk":round(1.0-math.exp(-max(0.0,death_hazard)),6),
                "hero_defense_control":round(hero_defense,4),
                "representative_layers":[row for _count,row in samples[:3]],
            }

        for person in named:
            if person.get("command_scope")=="higher" or person.get("co_located") is False:continue
            role=str(person.get("role","embedded")); exposure=max(0.0,_num(person.get("exposure_factor",.75)))
            available_seconds=max(0.0,battle_hours*3600.0*duty.get(role,.10)*exposure)
            active_seconds=min(120.0,available_seconds)
            if active_seconds<=0:continue
            melee=max(0.0,_num(person.get("melee_direct_score",person.get("direct_combat_score",0))))
            ranged=max(0.0,_num(person.get("ranged_direct_score",0)))
            ranged_weapon=self._combat_weapon(person.get("ranged_weapon_id")); projectile=self._combat_weapon(person.get("ammunition_item"))
            ranged_legal=bool(ranged_weapon and projectile and ranged>0 and int(person.get("carried_ammunition",0) or 0)>0 and _num(person.get("ranged_effective_range_m"))>0)
            use_ranged=bool(ranged_legal and ranged>melee*1.03)
            hero=ranged if use_ranged else melee
            baseline=own_ranged if use_ranged else own_melee
            opposition_quality=max(opp_ranged,opp_melee*.72) if use_ranged else opp_melee
            relative=(hero-opposition_quality)/max(18.0,38.0+math.sqrt(max(0.0,opposition_quality))*2.0); success=1.0/(1.0+math.exp(-relative))
            local_front=max(1,int(round(math.sqrt(opp_total)*(1.0+math.sqrt(max(.1,battle_hours))*1.35)*(.55+.75*exposure)*geometry)))
            mounted_collision=0.0; flight=None; shots=0
            if use_ranged:
                effective=max(10.0,_num(person.get("ranged_effective_range_m"),60.0)); max_direct=max(effective,_num(person.get("ranged_max_direct_range_m"),effective))
                distance=min(max_direct*.72,effective*(.58 if constrained else .78)); distance=max(8.0,distance)
                flight=projectile_flight_resolution(
                    ranged_weapon,projectile,distance_m=distance,
                    weapon_skill=_num(person.get("ranged_skill_value",ranged)),strength=_num(person.get("strength",0)),
                    coordination=_num(person.get("coordination",0)),awareness=_num(person.get("awareness",0)),
                )
                cycle=max(.8,_num(person.get("ranged_cycle_seconds",6.0),6.0)); shots=min(max(0,int(person.get("carried_ammunition",0) or 0)),max(0,int(active_seconds//cycle)))
                aim_quality=_num(flight.get("aim_control",0)); dispersion=max(.02,_num(flight.get("dispersion_m",1.0),1.0))
                hit_probability=_clampf((.22+.58*success)*(1.0-math.exp(-max(0.0,aim_quality+35.0)/95.0))/(1.0+dispersion/2.0),.02,.92)
                contacts=min(opp_total,local_front,max(0,int(round(shots*hit_probability))))
                impact=max(0.0,_num(flight.get("impact_index",0))); penetration=max(0.0,_num(flight.get("penetration_index",0))); hero_mode="thrust"
            else:
                interval=max(.40,_num(person.get("minimum_action_interval_seconds",1.5),1.5)); opportunities=active_seconds/interval
                contacts=min(opp_total,local_front,max(0,int(round(opportunities*(.18+.72*success)))))
                impact=max(1.0,_num(person.get("strength",50)))*max(.25,_num(person.get("melee_force",.5)))*(0.80+math.sqrt(max(0.0,hero))/35.0)
                hero_weapon=self._combat_weapon(person.get("melee_weapon_id"))
                hero_mode=max((("cut",_num(hero_weapon.get("base_force_cut"))),("thrust",_num(hero_weapon.get("base_force_thrust"))),("blunt",_num(hero_weapon.get("base_force_blunt")))),key=lambda row:row[1])[0] if hero_weapon else "blunt"
                penetration=impact*weapon_penetration_factor(hero_weapon,hero_mode)
                if person.get("mounted") and person.get("charge_legal"):
                    profile={"mounted":True,"charge_legal":True,"total_mass_kg":_num(person.get("mount_total_mass_kg",0))}
                    charge=mounted_charge_resolution(profile,riding=_num(person.get("riding",0)),coordination=_num(person.get("coordination",0)),awareness=_num(person.get("awareness",0)),composure=_num(person.get("composure",0)),horse_training=_num(person.get("horse_training",0)),relative_speed_mps=_num(person.get("mount_speed_mps",0)),weapon=hero_weapon)
                    mounted_collision=_num(charge.get("collision_index",0)); motion=max(1.0,_num(charge.get("weapon_motion_multiplier",1.0))); impact*=motion; penetration*=motion

            plan=target_plan(person)
            layer_samples=[]; weighted_injury=0.0; weighted_ratio=0.0; weighted_shield_loss=0.0; weighted_armor_pen=0.0
            for target in opposing_rows:
                count=max(0,int(target.get("count",0)))
                if count<=0:continue
                layer=physical_layer_profile(target,mode=hero_mode,impact=impact,penetration=penetration,hero_score=hero,plan=plan)
                share=count/max(1,opp_total)
                ratio=max(0.0,_num(layer.get("armor_maximum_ratio")))
                injury_expression=tissue_injury_expression(ratio)
                weighted_injury+=injury_expression*share; weighted_ratio+=ratio*share; weighted_shield_loss+=_num(layer.get("shield_condition_loss_pct"))*share; weighted_armor_pen+=(1.0 if layer.get("armor_penetrated") else 0.0)*share
                layer_samples.append((count,layer))
            layer_samples.sort(key=lambda pair:(-pair[0],str(pair[1].get("target_role",""))))
            representative_layers=[row for _count,row in layer_samples[:3]]
            physical_pressure=max(0,int(round(contacts*_clampf(.04+.92*weighted_injury,.02,.96))))
            if person.get("included_in_personnel"):
                excess=max(0.0,hero-baseline); incremental_share=1.0-math.exp(-excess/max(35.0,baseline+.01))
            else:incremental_share=1.0
            casualty_pressure=max(0,int(round(physical_pressure*incremental_share)))
            reach=.6 if use_ranged else max(.45,_num(person.get("melee_reach_m",.75)))
            displacement=math.sqrt(max(0.0,contacts))*reach*(1.0+math.log1p(max(0.0,mounted_collision))/12.0)*incremental_share
            doctrine=person.get("combat_targeting_doctrine",{}) if isinstance(person.get("combat_targeting_doctrine"),Mapping) else {}
            awareness_curve=1.0-math.exp(-max(0.0,_num(person.get("awareness",0)))/120.0)
            command_target_fraction=(.10+.18*awareness_curve) if doctrine else (.035+.055*awareness_curve)
            officer_pressure=casualty_pressure*command_target_fraction
            cohesion_shock=casualty_pressure*.70+displacement*.55+contacts*.035
            artillery_share=sum(max(0,int(r.get("count",0))) for r in opposing_rows if any(tok in str(r.get("role","")).lower() for tok in ("siege","engineer","artillery","engine")))/max(1,opp_total)
            artillery_pressure=casualty_pressure*artillery_share*(.70+.30*awareness_curve)
            command_attention=active_seconds if role in {"commander","deputy"} else 0.0
            incoming=incoming_exposure_profile(person,active_seconds=active_seconds,local_front=local_front,intervention_mode="ranged" if use_ranged else "melee")
            timeline_interval=(max(.8,_num(person.get("ranged_cycle_seconds",6.0),6.0)) if use_ranged else max(.40,_num(person.get("minimum_action_interval_seconds",1.5),1.5)))
            contact_timeline=transient_contact_timeline(active_seconds=active_seconds,outgoing_contacts=contacts,outgoing_interval=timeline_interval,incoming_expected=float(incoming.get("expected_contacts",0) or 0),ranged=use_ranged,flight_seconds=float(flight.get("flight_time_seconds",0) or 0) if isinstance(flight,Mapping) else 0.0)
            total_pressure+=casualty_pressure; total_displacement+=displacement; total_officer_pressure+=officer_pressure; total_cohesion_shock+=cohesion_shock; total_artillery_pressure+=artillery_pressure; total_command_attention+=command_attention
            row={
                "person_ref":person.get("person_ref"),"representation":person.get("representation"),"role":role,
                "intervention_mode":"ranged" if use_ranged else "melee",
                "available_personal_contact_seconds":round(available_seconds,3),"active_window_seconds":round(active_seconds,3),"local_window_bounded":True,
                "local_enemy_frontage":local_front,"physical_contacts":contacts,"physical_casualty_pressure":physical_pressure,
                "incremental_casualty_pressure":casualty_pressure,"casualty_pressure":casualty_pressure,"frontage_displacement_m":round(displacement,3),
                "officer_pressure":round(officer_pressure,4),"cohesion_shock_pressure":round(cohesion_shock,4),"artillery_pressure":round(artillery_pressure,4),"command_attention_seconds":round(command_attention,3),
                "mounted":bool(person.get("mounted")),"charge_collision_index":round(mounted_collision,3),
                "weapon_id":person.get("ranged_weapon_id") if use_ranged else person.get("melee_weapon_id"),"attack_mode":hero_mode,
                "impact_index":round(impact,3),"penetration_index":round(penetration,3),"opposing_protection_index":round(opp_protection,3),
                "aim_zone":plan.get("zone"),"aim_structure":plan.get("structure"),"aim_purpose":plan.get("purpose"),"aim_selection_basis":plan.get("basis"),
                "weighted_post_layer_injury_expression":round(weighted_injury,6),"weighted_post_layer_maximum_ratio":round(weighted_ratio,6),
                "weighted_shield_condition_loss_pct":round(weighted_shield_loss,4),"weighted_armor_penetration_fraction":round(weighted_armor_pen,6),
                "representative_contact_layers":representative_layers,
                "incoming_expected_contacts":incoming.get("expected_contacts",0.0),"incoming_injury_hazard":incoming.get("injury_hazard",0.0),
                "incoming_injury_risk":incoming.get("injury_risk",0.0),"incoming_death_risk":incoming.get("death_risk",0.0),
                "incoming_hero_defense_control":incoming.get("hero_defense_control",0.0),"representative_incoming_contact_layers":incoming.get("representative_layers",[]),
                "local_contact_timeline":contact_timeline,
            }
            if use_ranged and flight is not None:
                row.update({"projectile_item_id":person.get("ammunition_item"),"projectiles_released":shots,"projectile_recovery_base":flight.get("projectile_recovery_base",0.0),"distance_m":flight.get("distance_m"),"flight_time_seconds":flight.get("flight_time_seconds"),"mechanism_sets_launch_power":flight.get("mechanism_sets_launch_power"),"aim_control":flight.get("aim_control"),"dispersion_m":flight.get("dispersion_m")})
            else:
                interval=max(.40,_num(person.get("minimum_action_interval_seconds",1.5),1.5)); row.update({"action_interval_seconds":round(interval,4),"action_opportunities":int(round(active_seconds/interval))})
            interventions.append(row)
        disruption=1.0+(1.0-math.exp(-max(0.0,total_pressure)/120.0))*.10+(1.0-math.exp(-max(0.0,total_displacement)/70.0))*.06+(1.0-math.exp(-max(0.0,total_cohesion_shock)/90.0))*.035
        return {"interventions":interventions,"disruption_factor":round(disruption,6),"casualty_pressure":total_pressure,"frontage_displacement_m":round(total_displacement,3),"officer_pressure":round(total_officer_pressure,4),"cohesion_shock_pressure":round(total_cohesion_shock,4),"artillery_pressure":round(total_artillery_pressure,4),"command_attention_seconds":round(total_command_attention,3)}

    def _combat_command_effects(self,formation:Mapping[str,Any],named:Sequence[Mapping[str,Any]])->dict[str,Any]:
        """Return bounded domain-specific command factors from real command state.

        Internal hierarchy creates scale coverage, constrained by saved training
        and cohesion. Unit-command terms require named or lawfully allocated
        commander/deputy bodies. Routine staff/signal/logistics/medical work has
        no separate headcount multiplier; those functions are expressed through
        the normal command, communications, logistics, medical, supply and
        readiness mechanics.
        """
        rules=self._combat_command_rules();cfg=rules.get("command_effect_scales",{}) if isinstance(rules,Mapping) else {};structure=formation.get("command_structure",{}) if isinstance(formation.get("command_structure"),Mapping) else {};raw_hierarchy=structure.get("internal_hierarchy",[]) if isinstance(structure,Mapping) else []
        hierarchy=[]
        if isinstance(raw_hierarchy,list):
            hierarchy=[dict(row) for row in raw_hierarchy if isinstance(row,Mapping)]
        elif isinstance(raw_hierarchy,Mapping):
            summary=raw_hierarchy.get("summary",[])
            if isinstance(summary,list):
                hierarchy=[dict(row) for row in summary if isinstance(row,Mapping)]
            if not hierarchy:
                by_role=raw_hierarchy.get("by_role",{})
                if isinstance(by_role,Mapping):
                    counts:dict[int,int]={}
                    for role_row in by_role.values():
                        if not isinstance(role_row,Mapping):continue
                        for scale,key in ((1000,"commanders_1000"),(500,"commanders_500"),(100,"commanders_100")):
                            count=max(0,int(role_row.get(key,0) or 0))
                            if count:counts[scale]=counts.get(scale,0)+count
                    hierarchy=[{"scale":scale,"count":count,"counted_inside_troop_strength":True} for scale,count in sorted(counts.items(),reverse=True)]
        if not hierarchy:
            levels=rules.get("formation_command_structure",{}).get("generic_internal_levels",[2000,1000,500,100]) if isinstance(rules,Mapping) else [2000,1000,500,100];n=max(0,int(formation.get("personnel",0)));hierarchy=[]
            for scale in levels if isinstance(levels,list) else []:
                s=max(1,int(scale))
                if n>=s:hierarchy.append({"scale":s,"count":n//s+(1 if n%s else 0)})
        commander=next((x for x in named if x.get("role")=="commander"),None);deputy=next((x for x in named if x.get("role")=="deputy"),None);commander_ok=bool(commander and commander.get("command_available"));deputy_ok=bool(deputy and deputy.get("command_available"));commander_score=_num(commander.get("command_score")) if commander_ok and commander else 0.0;deputy_score=_num(deputy.get("command_score")) if deputy_ok and deputy else 0.0
        higher_commander=next((x for x in named if x.get("role")=="higher_commander" and x.get("command_available")),None);higher_deputy=next((x for x in named if x.get("role")=="higher_deputy" and x.get("command_available")),None);higher_commander_score=_num(higher_commander.get("command_score")) if higher_commander else 0.0;higher_deputy_score=_num(higher_deputy.get("command_score")) if higher_deputy else 0.0
        if commander_score>0:acting_score=commander_score;continuity="commander";deputy_throughput=_clampf(deputy_score/120.0,0,1) if deputy_score>0 else 0.0
        elif deputy_score>0:acting_score=deputy_score*.82;continuity="acting_deputy";deputy_throughput=0.0
        else:acting_score=0.0;continuity="aggregate_or_internal_only";deputy_throughput=0.0
        training=_clampf(_num(formation.get("training_progress",20))/100.0,0,1);cohesion=_clampf(_num(formation.get("cohesion",50))/100.0,0,1);organizational_quality=_clampf(.35+.35*training+.30*cohesion,.25,1.0)
        scales=[max(1,int(row.get("scale",1))) for row in hierarchy if isinstance(row,Mapping) and int(row.get("count",0))>0]
        local_coverage=1.0 if any(100<=s<=200 for s in scales) else 0.0;maneuver_coverage=1.0 if any(500<=s<=1000 for s in scales) else 0.0
        hierarchy_targets={max(0,int(row.get("scale",0) or 0)):max(0,int(row.get("count",0) or 0)) for row in hierarchy if isinstance(row,Mapping)}
        def _internal_quality(scale_set:set[int])->tuple[float,float,float]:
            eligible=[row for row in named if row.get("command_available") and any(row.get("role")==f"internal_{scale}_commander" for scale in scale_set)]
            target=sum(hierarchy_targets.get(scale,0) for scale in scale_set)
            coverage=_clampf(len(eligible)/max(1,target),0,1) if target>0 else 0.0
            score=sum(_num(row.get("command_score",0)) for row in eligible)/len(eligible) if eligible else 0.0
            named_quality=_clampf(.35+.65*(score/100.0),.35,1.45) if score>0 else organizational_quality
            blended=organizational_quality*(1.0-coverage)+named_quality*coverage
            return coverage,score,blended
        internal_local_coverage,internal_local_score,local_quality=_internal_quality({100})
        internal_maneuver_coverage,internal_maneuver_score,maneuver_quality=_internal_quality({500,1000})
        # The Unit commander/deputy own the Unit echelon itself. A 2,000+ Unit
        # therefore has operational-scale command even though no redundant internal
        # 2,000 commander is generated below its commander. Current casualty
        # strength never shrinks this establishment-scale command responsibility.
        authorized_scale=max(0,int(formation.get("authorized_strength",formation.get("establishment_personnel",formation.get("personnel",0))) or 0))
        operational_coverage=1.0 if authorized_scale>=2000 else 0.0
        local_cfg=cfg.get("local_100_200",{}) if isinstance(cfg,Mapping) else {};maneuver_cfg=cfg.get("maneuver_500_1000",{}) if isinstance(cfg,Mapping) else {};operational_cfg=cfg.get("operational_2000_plus",{}) if isinstance(cfg,Mapping) else {};unit_cfg=cfg.get("unit_command",{}) if isinstance(cfg,Mapping) else {}
        unit=structure.get("unit_command",{}) if isinstance(structure,Mapping) else {};target=max(0,int(unit.get("target_bodies",unit.get("commander_billets",0)+unit.get("deputy_billets",0)))) if isinstance(unit,Mapping) else 0;effective=max(0,int(unit.get("effective_billets_staffed",0))) if isinstance(unit,Mapping) else 0
        aggregate_unit_post=bool(isinstance(unit,Mapping) and (unit.get("commander_post") or unit.get("external_to_fighting_establishment") or effective>0))
        if target<=0:unit_coverage=1.0 if acting_score>0 or aggregate_unit_post else 0.0
        else:unit_coverage=_clampf(effective/max(1,target),0,1)
        if acting_score>0:unit_quality=_clampf(.35+.65*(acting_score/100.0),.35,1.35)
        else:unit_quality=organizational_quality
        if higher_commander_score>0:
            higher_quality=_clampf(.35+.65*(higher_commander_score/100.0),.35,1.40)
            if higher_deputy_score>0:higher_quality*=(1.0+.10*_clampf(higher_deputy_score/120.0,0,1))
            higher_mode="higher_commander"
        elif higher_deputy_score>0:
            higher_quality=_clampf(.30+.55*(higher_deputy_score/100.0),.30,1.20)
            higher_mode="acting_higher_deputy"
        else:
            higher_quality=organizational_quality;higher_mode="internal_only"
        bonuses={"local":max(0.0,_num(local_cfg.get("maximum_quality_delta",.05)))*local_coverage*local_quality,"maneuver":max(0.0,_num(maneuver_cfg.get("maximum_quality_delta",.08)))*maneuver_coverage*maneuver_quality,"operational":max(0.0,_num(operational_cfg.get("maximum_quality_delta",.07)))*operational_coverage*higher_quality,"unit":max(0.0,_num(unit_cfg.get("maximum_quality_delta",.12)))*unit_coverage*unit_quality*(1.0+.18*deputy_throughput)}
        cap=max(1.0,_num(cfg.get("combined_cap",1.28),1.28)) if isinstance(cfg,Mapping) else 1.28
        def product(scale:float)->float:
            out=1.0
            for bonus in bonuses.values():out*=1.0+bonus*scale
            return out
        scale=1.0
        if product(1.0)>cap:
            lo,hi=0.0,1.0
            for _ in range(24):
                mid=(lo+hi)/2.0
                if product(mid)>cap:hi=mid
                else:lo=mid
            scale=lo
        factors={key:1.0+bonus*scale for key,bonus in bonuses.items()};factors["combined_factor"]=product(scale);factors["continuity_mode"]=continuity;factors["acting_command_score"]=round(acting_score,3);factors["higher_command_mode"]=higher_mode;factors["higher_command_score"]=round(max(higher_commander_score,higher_deputy_score),3);factors["higher_command_group_ref"]=(higher_commander or higher_deputy or {}).get("command_group_ref");factors["unit_staffing_ratio"]=round(unit_coverage,6);factors["internal_100_person_lite_coverage"]=round(internal_local_coverage,6);factors["internal_100_command_score"]=round(internal_local_score,3);factors["internal_500_1000_person_lite_coverage"]=round(internal_maneuver_coverage,6);factors["internal_500_1000_command_score"]=round(internal_maneuver_score,3);return factors

    @staticmethod
    def _combat_melee_capability_factor(melee_mean: float, experience: float = 1.0) -> float:
        # Character/cohort capability has no historical 200-stat ceiling.
        # Physical expression is bounded elsewhere by frontage, reach, equipment,
        # fatigue, terrain and command rather than by discarding skill above 200.
        return max(0.35, 0.35 + max(0.0, float(melee_mean)) / 100.0) * max(0.0, float(experience))

    def _formation_combat_snapshot(self,formation:Mapping[str,Any],force:Mapping[str,Any],*,terrain_kind:str,ammo_plan:Mapping[str,Any]|None=None,battle_hours:float=3.0,opposing_rows:Sequence[Mapping[str,Any]]|None=None)->dict[str,Any]:
        rows=self._combat_cohort_snapshot(formation,force); n=max(1,int(formation.get("personnel",0))); cohort_n=max(1,sum(int(r.get("count",0)) for r in rows)); opposing=list(opposing_rows or [])
        melee_mean=sum(_num(r.get("melee_score"))*int(r.get("count",0)) for r in rows)/cohort_n if rows else 55.0; experience=sum(_num(r.get("experience_factor",1))*int(r.get("count",0)) for r in rows)/cohort_n if rows else 1.0
        capability=self._combat_melee_capability_factor(melee_mean,experience); cohesion=_num(formation.get("cohesion",50),50); reach=self._combat_reach_factor(rows,opposing,cohesion,terrain_kind)
        named=self._combat_named_participants(formation,force); plan=dict(ammo_plan or self._combat_ammunition_plan(rows,formation.get("logistics",{}),battle_hours)); ranged_contact=self._combat_ranged_contact_profile(rows,plan,opposing); ranged=self._combat_ranged_factor(rows,plan,opposing)*_num(ranged_contact.get("combat_factor",1.0),1.0); frontage=self._combat_frontage_equivalent(rows,n,terrain_kind)
        method=self._combat_formation_method_profile(rows,formation,opposing,terrain_kind); hero=self._combat_hero_interventions(named,rows,opposing,battle_hours=battle_hours,terrain_kind=terrain_kind); command=self._combat_command_effects(formation,named)
        battle_seconds=max(1.0,float(battle_hours)*3600.0); attention=max(0.0,_num(hero.get("command_attention_seconds",0))); attention_fraction=_clampf(attention/battle_seconds,0.0,.35); attention_factor=1.0-min(.10,attention_fraction*.65)
        command["personal_combat_attention_seconds"]=round(attention,3); command["personal_combat_attention_fraction"]=round(attention_fraction,6); command["personal_combat_attention_factor"]=round(attention_factor,6); command["combined_factor"]=round(_num(command.get("combined_factor",1.0),1.0)*attention_factor,6)
        return {"rows":rows,"cohort_personnel":cohort_n,"melee_capability_mean":melee_mean,"capability_factor":capability,"melee_weapon_factor":self._combat_melee_weapon_factor(rows),"reach_factor":reach,"ranged_factor":ranged,"frontage_equivalent":frontage,"named_participants":named,"hero_interventions":hero,"hero_disruption_factor":_num(hero.get("disruption_factor",1.0),1.0),"formation_method":method,"formation_method_factor":_num(method.get("combat_factor",1.0),1.0),"mount_casualty_risk":_num(method.get("mount_casualty_risk",1.0),1.0),"command_effects":command,"command_factor":command["combined_factor"],"protection_factor":self._combat_protection_factor(rows),"mount_factor":self._combat_mount_factor(rows,formation),"ranged_contact":ranged_contact,"ammo_plan":plan}

    def _combat_autonomy_formation_inputs(self,ref:str)->tuple[str,Mapping[str,Any],Mapping[str,Any]]:
        """Return combat inputs without rewriting already-valid cohort owners.

        Autonomous interstate reviews score the same formations repeatedly across long
        horizons.  Combat preparation is allowed to seed legacy cohort state, but an
        already-current formation must not deep-copy and re-put its entire force ledger
        merely to answer a read-only power question.
        """
        try:
            path,formation=self._load_formation(ref)
            force_path=self.owner_path(str(formation["owner_force_ref"]))
            force=self.read(force_path)
            ledger=force.get("cohort_ledger",{}) if isinstance(force,Mapping) else {}
            cohorts=ledger.get("cohorts",{}) if isinstance(ledger,Mapping) else {}
            cohort_composition=formation.get("cohort_composition") if isinstance(formation,Mapping) else None
            current=bool(isinstance(cohorts,Mapping) and cohorts and isinstance(cohort_composition,list))
            if current or max(0,int(formation.get("personnel",0) or 0))<=0:
                return path,formation,force
        except (ValueError,KeyError,FileNotFoundError,TypeError):
            pass
        return self._combat_prepare_formation(ref)

    def _autonomy_formation_power(self,ref:str,defender:bool=False,opposing_ref:str|None=None)->float:
        try:_,formation,force=self._combat_autonomy_formation_inputs(ref)
        except (ValueError,KeyError,FileNotFoundError):return 0.0
        n=max(0,int(formation.get("personnel",0)))
        if n<=0:return 0.0
        logistics=formation.get("logistics",{});food_ratio=min(1.0,_num(logistics.get("food_kg",0))/max(1,n*2)) if isinstance(logistics,Mapping) else 0;terrain_kind=str(self._location_record(str(formation.get("location_ref"))).get("kind","open"));opposing=[]
        if opposing_ref:
            try:_,of,oforce=self._combat_autonomy_formation_inputs(opposing_ref);opposing=self._combat_cohort_snapshot(of,oforce)
            except (ValueError,KeyError,FileNotFoundError):pass
        hours=3.0;rows=self._combat_cohort_snapshot(formation,force);ammo=self._combat_ammunition_plan(rows,logistics if isinstance(logistics,Mapping) else {},hours);snap=self._formation_combat_snapshot(formation,force,terrain_kind=terrain_kind,ammo_plan=ammo,battle_hours=hours,opposing_rows=opposing);command=snap["command_effects"];readiness=_num(formation.get("readiness",50));morale=_num(formation.get("morale",50));cohesion=_num(formation.get("cohesion",50));fatigue=_num(formation.get("fatigue",0));training=_num(formation.get("training_progress",20));organization=_clampf((readiness+morale+cohesion+max(0,100-fatigue))/400,.18,1.15)*_num(command.get("local",1.0),1.0);integration=_clampf(.72+training/250,.72,1.12)*_num(command.get("maneuver",1.0),1.0);equipment=max(.20,_num(formation.get("equipment_completeness",0)));equipment=equipment/100 if equipment>1 else equipment;supply=(.72+.28*food_ratio);defense_terrain=1.08 if defender and terrain_kind in {"pass","fort","fortress","city","capital"} else 1;bodies=snap["frontage_equivalent"]*_num(command.get("operational",1.0),1.0);unit=_num(command.get("unit",1.0),1.0)
        return max(1.0,bodies*snap["capability_factor"]*snap["melee_weapon_factor"]*snap["reach_factor"]*snap["ranged_factor"]*snap["protection_factor"]*snap["mount_factor"]*_num(snap.get("formation_method_factor",1.0),1.0)*_num(snap.get("hero_disruption_factor",1.0),1.0)*organization*integration*equipment*supply*unit*defense_terrain)


__all__=["CombatCapabilityMixin"]
