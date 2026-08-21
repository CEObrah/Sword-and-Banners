from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.fortified_site_logistics import current_garrison_requirements
from sword_runtime.fatigue import RULES_PATH as FATIGUE_RULES_PATH, settle_formation_idle_fatigue, stamp_formation_activity_fatigue


def site_slug(site_ref: str) -> str:
    raw = str(site_ref or "fortified-site")
    if raw.startswith("loc_"):
        raw = raw[4:]
    return raw.replace("_", "-")
from sword_runtime.geography import enclosing_fortification_site, shortest_path
from sword_runtime.sim.calendar import CampaignTime


class FortifiedSiteRuntimeMixin:
    """Materialize mutable fortified-site logistics only when a site is strategically hot."""

    def _fortification_profile_for_site(self, site_ref: str) -> dict[str, Any]:
        doc = self.read("game/data/world/fortification-profiles.json")
        row = next((x for x in doc.get("profiles", []) if isinstance(x, Mapping) and str(x.get("site_ref", x.get("location_ref", ""))) == str(site_ref)), None)
        if not isinstance(row, Mapping):
            raise ValueError("site has no exact fortified-site blueprint")
        profile = copy.deepcopy(dict(row))
        # Current finite land/enclosure state overrides the cold starting blueprint.
        # This keeps city expansion and nested defenses causally real without turning
        # static reference data into a second mutable geometry authority.
        try:
            land = self.read("state/development/land.json")
            site = land.get("sites", {}).get(str(site_ref)) if isinstance(land, Mapping) else None
        except Exception:
            site = None
        if isinstance(site, Mapping):
            fort = site.get("fortification", {}) if isinstance(site.get("fortification"), Mapping) else {}
            if bool(fort.get("active")) and float(site.get("enclosed_area_km2", 0) or 0) > 0:
                baseline = profile.setdefault("physical_baseline", {})
                baseline["constructed_wall_centerline_perimeter_km"] = float(fort.get("constructed_outer_perimeter_km", baseline.get("constructed_wall_centerline_perimeter_km", 0)) or 0)
                outer = baseline.setdefault("outer_wall", {})
                keymap = {
                    "wall_height_m":"wall_height_m", "wall_base_thickness_m":"wall_base_thickness_m",
                    "wall_crown_thickness_m":"wall_crown_thickness_m", "tower_count":"tower_count",
                    "moat_width_m":"moat_width_m", "moat_depth_m":"moat_depth_m",
                    "external_strategic_gate_count":"gate_count",
                }
                for out_key, fort_key in keymap.items():
                    if fort_key in fort: outer[out_key] = fort[fort_key]
                per=max(0.001,float(baseline.get("constructed_wall_centerline_perimeter_km",0) or 0))
                towers=max(1,int(outer.get("tower_count",1) or 1)); gates=max(1,int(outer.get("external_strategic_gate_count",1) or 1))
                outer["tower_station_interval_m"] = round(per*1000/towers,3)
                outer["gate_station_m"] = round(per*1000/gates,3)
                explicit=site.get("enclosures")
                if isinstance(explicit,list) and explicit:
                    profile["current_enclosure_layers"] = copy.deepcopy([x for x in explicit if isinstance(x,Mapping)])
        return profile

    def _location_parent_map(self) -> dict[str, str]:
        doc = self.read("game/data/world/locations.json")
        return {str(x.get("ref")): str(x.get("parent_ref")) for x in doc.get("locations", []) if isinstance(x, Mapping) and isinstance(x.get("ref"), str) and isinstance(x.get("parent_ref"), str)}

    def _site_contains_location(self, site_ref: str, location_ref: str) -> bool:
        if str(site_ref) == str(location_ref):
            return True
        parents = self._location_parent_map(); cur = str(location_ref); seen: set[str] = set()
        while cur in parents and cur not in seen:
            seen.add(cur); cur = parents[cur]
            if cur == str(site_ref): return True
        return False

    def _formations_at(self, site_ref: str) -> list[str]:
        """Return formations belonging to this defended enclosure's logistics scope.

        A parent enclosure never absorbs formations physically inside another
        registered defended enclosure nested within it.  Each nested fortress,
        citadel, or keep owns its own local logistics scope and may draw from an
        upstream strategic depot through conserved transfer.
        """
        idx = self.read("state/index/location-formation-index.json")
        locations = idx.get("locations", {}) if isinstance(idx, Mapping) else {}
        profiles = self.read("game/data/world/fortification-profiles.json")
        nested_sites: list[str] = []
        for row in profiles.get("profiles", []) if isinstance(profiles, Mapping) else []:
            if not isinstance(row, Mapping):
                continue
            child = str(row.get("site_ref", row.get("location_ref", "")))
            if not child or child == str(site_ref):
                continue
            if self._site_contains_location(str(site_ref), child):
                nested_sites.append(child)
        out: list[str] = []
        if isinstance(locations, Mapping):
            for loc, refs in locations.items():
                location_ref = str(loc)
                if not self._site_contains_location(site_ref, location_ref):
                    continue
                if any(self._site_contains_location(child, location_ref) for child in nested_sites):
                    continue
                if isinstance(refs, list):
                    out.extend(str(x) for x in refs if isinstance(x, str))
        return sorted(set(out))

    def _fortified_site_authority(self, site_ref: str, authority_ref: str | None = None) -> str:
        if authority_ref:
            return str(authority_ref)
        if self._site_contains_location("loc_tang_manor", site_ref):
            return "house_tang"
        state = self._native_site_state(site_ref)
        return f"state_{state}" if state else ""

    @staticmethod
    def _site_depot_identity(site_ref: str) -> tuple[str, str]:
        if site_ref == "loc_kankoku_pass":
            return "state_depot_qin_kankoku", "state/depots/qin-kankoku.json"
        # House Tang's one strategic reserve is physically inside the Inner
        # Citadel.  The enclosing Tang Manor and Sword Manor may materialize
        # ordinary local logistics depots, but they must never reuse this owner
        # or pull the strategic stock back outward during a hot-site review.
        if site_ref == "loc_tang_inner_citadel":
            return "depot_house_tang", "state/depots/house-tang.json"
        slug = site_slug(site_ref)
        return f"depot_fort_{slug.replace('-', '_')}", f"state/depots/fort-{slug}.json"

    @staticmethod
    def _site_artillery_identity(site_ref: str) -> tuple[str, str]:
        if site_ref == "loc_kankoku_pass":
            return "artillery_qin_kankoku", "state/art/kankoku-artillery.json"
        if site_ref == "loc_tang_manor":
            return "tang_manor_artillery", "state/art/tang-manor-artillery.json"
        slug = site_slug(site_ref)
        return f"artillery_fort_{slug.replace('-', '_')}", f"state/art/fort-{slug}.json"

    def _garrison_summary(self, refs: list[str]) -> dict[str, int]:
        personnel = mounts = bow = crossbow = engineer = 0
        for ref in refs:
            try: _p, f = self._load_formation(ref)
            except ValueError: continue
            n = max(0, int(f.get("personnel", 0))); personnel += n
            mounts += sum(max(0, int(v)) for v in (f.get("mounts", {}) or {}).values())
            composition = f.get("composition", {}) if isinstance(f.get("composition"), Mapping) else {}
            if not composition:
                composition = f.get("role_composition", {}) if isinstance(f.get("role_composition"), Mapping) else {}
            for role, raw in composition.items():
                count = max(0, int(raw)); text = str(role).lower()
                if "crossbow" in text: crossbow += count
                elif "archer" in text or "bow" in text: bow += count
                if "engineer" in text or "sapper" in text: engineer += count
        return {"personnel": personnel, "mounts": mounts, "bow_personnel": bow, "crossbow_personnel": crossbow, "engineer_personnel": engineer}

    def _siege_crossbow_crew_control(self, refs: list[str]) -> float:
        """Return bounded observed crossbow control from the exact garrison cohorts."""
        weighted = total = 0.0
        if not hasattr(self, "_combat_prepare_formation") or not hasattr(self, "_combat_cohort_snapshot"):
            return 0.0
        for ref in refs:
            try:
                _p, formation, force = self._combat_prepare_formation(str(ref))
                rows = self._combat_cohort_snapshot(formation, force)
            except (ValueError, KeyError, FileNotFoundError):
                continue
            for row in rows:
                family = str(row.get("ranged_weapon_family", "")).lower()
                role = str(row.get("role", "")).lower()
                if family != "crossbow" and "crossbow" not in role:
                    continue
                count = max(0, int(row.get("count", 0) or 0))
                if count <= 0:
                    continue
                weighted += float(row.get("ranged_score", 0) or 0) * count
                total += count
        return weighted / total if total > 0 else 0.0

    def _siege_bed_crossbow_physics(self, *, range_m: float, condition_pct: float, fit_crew: int, active_weapons: int, crew_control: float) -> dict[str, Any]:
        """Physical bed-crossbow release envelope without human-powered launch scaling."""
        rules = self.read("game/data/mechanics/siege.json")
        cfg = rules.get("bed_crossbow", {}) if isinstance(rules, Mapping) else {}
        count = max(0, int(active_weapons))
        if count <= 0:
            return {"legal": False, "reason": "no_active_bed_crossbows"}
        minimum = max(1, int(cfg.get("minimum_crew", 4) or 4))
        optimal = max(minimum, int(cfg.get("optimal_crew", 6) or 6))
        fit = max(0, int(fit_crew))
        if fit < count * minimum:
            return {"legal": False, "reason": "insufficient_fit_crew", "required_crew": count * minimum, "fit_crew": fit}
        effective = max(1.0, float(cfg.get("effective_range_m", 280) or 280))
        maximum = max(effective, float(cfg.get("maximum_range_m", 420) or 420))
        distance = max(0.0, float(range_m))
        if distance > maximum:
            return {"legal": False, "reason": "beyond_maximum_range", "maximum_range_m": maximum, "range_m": distance}
        if distance <= effective:
            range_factor = 1.0
        else:
            range_factor = 1.0 - 0.30 * ((distance - effective) / max(1.0, maximum - effective))
        condition = max(0.0, min(1.0, float(condition_pct) / 100.0))
        crew_factor = max(0.50, min(1.0, fit / max(1.0, count * optimal)))
        control_factor = max(0.60, min(1.25, 0.70 + max(0.0, float(crew_control)) / 400.0))
        base_cycle = max(1.0, float(cfg.get("base_cycle_seconds", 48) or 48))
        cycle_factor = max(0.70, min(1.30, crew_factor * control_factor * max(0.05, condition)))
        cycle = base_cycle / cycle_factor
        base_dispersion = max(0.01, float(cfg.get("base_dispersion_m", 1.5) or 1.5))
        distance_ratio = max(0.05, distance / effective)
        dispersion = base_dispersion * (distance_ratio ** 1.15) / max(0.20, crew_factor * control_factor)
        # Crucial invariant: crew skill never appears in these two expressions.
        impact = max(0.0, float(cfg.get("base_impact", 165) or 165)) * range_factor * condition
        penetration = max(0.0, float(cfg.get("base_penetration", 190) or 190)) * range_factor * condition
        return {
            "legal": True, "mechanism_sets_launch_power": True, "range_m": round(distance, 3),
            "range_factor": round(range_factor, 5), "condition_factor": round(condition, 5),
            "fit_crew": fit, "crew_factor": round(crew_factor, 5), "crew_control": round(float(crew_control), 3),
            "control_factor": round(control_factor, 5), "cycle_seconds": round(cycle, 3),
            "dispersion_radius_m": round(dispersion, 4), "impact_index": round(impact, 3),
            "penetration_index": round(penetration, 3),
            "rule": "mechanism sets launch impact/penetration; crew capability controls pointing, ranging, release timing and reload cycle only",
        }

    def _siege_bed_crossbow_target_profile(self, refs: list[str]) -> dict[str, Any]:
        """Aggregate only the physical target surfaces needed by fixed crossbow fire."""
        rows: list[dict[str, Any]] = []
        if hasattr(self, "_combat_prepare_formation") and hasattr(self, "_combat_cohort_snapshot"):
            for ref in refs:
                try:
                    _path, formation, force = self._combat_prepare_formation(str(ref))
                    rows.extend(dict(x) for x in self._combat_cohort_snapshot(formation, force) if isinstance(x, Mapping))
                except (ValueError, KeyError, FileNotFoundError):
                    continue
        total = max(0, sum(max(0, int(r.get("count", 0) or 0)) for r in rows))
        if total <= 0:
            return {"personnel": 0, "rows": 0, "shield_share": 0.0, "shield_structure": 0.0, "shield_coverage_degrees": 0.0, "armor_protection_index": 0.0, "mounted_share": 0.0, "mount_protection_index": 0.0, "order_factor": 0.0}
        shield_rows = [r for r in rows if float(r.get("shield_structure", 0) or 0) > 0]
        shield_n = sum(max(0, int(r.get("count", 0) or 0)) for r in shield_rows)
        mounted_rows = [r for r in rows if bool(r.get("mounted")) or float(r.get("mount_index", 0) or 0) > 0]
        mounted_n = sum(max(0, int(r.get("count", 0) or 0)) for r in mounted_rows)
        def weighted(field: str, subset: list[dict[str, Any]], denominator: int) -> float:
            if denominator <= 0:
                return 0.0
            return sum(float(r.get(field, 0) or 0) * max(0, int(r.get("count", 0) or 0)) for r in subset) / denominator
        cohesion = weighted("formation_cohesion", rows, total)
        training = weighted("formation_training", rows, total)
        order_raw = 0.58 * cohesion + 0.42 * training
        order = 1.0 - math.exp(-max(0.0, order_raw) / 85.0)
        return {
            "personnel": total,
            "rows": len(rows),
            "shield_share": round(shield_n / total, 6),
            "shield_structure": round(weighted("shield_structure", shield_rows, shield_n), 4),
            "shield_coverage_degrees": round(weighted("shield_coverage_degrees", shield_rows, shield_n), 4),
            "armor_protection_index": round(weighted("armor_protection_index", rows, total), 4),
            "mounted_share": round(mounted_n / total, 6),
            "mount_protection_index": round(weighted("mount_protection_index", mounted_rows, mounted_n), 4),
            "order_factor": round(order, 6),
        }

    @staticmethod
    def _siege_bed_crossbow_contact_profile(physics: Mapping[str, Any], target: Mapping[str, Any], *, shots_fired: int) -> dict[str, Any]:
        """Resolve aggregate bolt contacts without turning soldiers into individual objects.

        Named-person strikes, when materialized, belong in the exact personal-contact
        kernel.  This profile describes formation surfaces only.
        """
        shots = max(0, int(shots_fired))
        personnel = max(0, int(target.get("personnel", 0) or 0))
        if shots <= 0 or personnel <= 0 or not bool(physics.get("legal")):
            return {"shots_fired": shots, "estimated_contacts": 0.0, "shield_intercept_fraction": 0.0, "person_penetrating_contacts": 0.0, "mount_penetrating_contacts": 0.0, "shield_wear_pct": 0.0, "armor_wear_pct": 0.0, "contact_pressure": 0.0}
        dispersion = max(0.01, float(physics.get("dispersion_radius_m", 1.0) or 1.0))
        impact = max(0.0, float(physics.get("impact_index", 0) or 0))
        penetration = max(0.0, float(physics.get("penetration_index", 0) or 0))
        # Dense assault formations remain easier to hit than isolated people, while
        # crew-controlled dispersion materially changes contact probability.
        density = min(1.0, math.sqrt(personnel / 600.0))
        hit_fraction = max(0.04, min(0.94, 0.12 + 0.78 * density / (1.0 + dispersion / 4.0)))
        contacts = shots * hit_fraction
        shield_share = max(0.0, min(1.0, float(target.get("shield_share", 0) or 0)))
        coverage = max(0.0, float(target.get("shield_coverage_degrees", 0) or 0))
        order = max(0.0, min(1.0, float(target.get("order_factor", 0) or 0)))
        shield_structure = max(0.0, float(target.get("shield_structure", 0) or 0))
        intercept = max(0.0, min(0.90, shield_share * min(1.0, coverage / 145.0) * (0.48 + 0.52 * order)))
        shield_contacts = contacts * intercept
        # An intercepted bolt can still perforate.  This is penetration through a
        # material path, not a binary shield bonus.
        shield_ratio = penetration / max(20.0, shield_structure * 1.35 if shield_structure > 0 else 20.0)
        shield_perforation = max(0.01, min(0.98, 0.5 + 0.5 * math.tanh((shield_ratio - 1.0) * 1.7))) if shield_contacts > 0 else 0.0
        post_shield = contacts * (1.0 - intercept) + shield_contacts * shield_perforation
        mounted_share = max(0.0, min(1.0, float(target.get("mounted_share", 0) or 0)))
        # A bed-crossbow bolt aimed into a mounted formation can strike either horse
        # or rider.  Mount surface exposure is deliberately bounded below the full
        # mounted share because riders and shields still occupy the line of fire.
        mount_contact_fraction = mounted_share * 0.42
        mount_contacts = post_shield * mount_contact_fraction
        person_contacts = max(0.0, post_shield - mount_contacts)
        armor = max(0.0, float(target.get("armor_protection_index", 0) or 0))
        mount_armor = max(0.0, float(target.get("mount_protection_index", 0) or 0))
        person_ratio = penetration / max(24.0, armor if armor > 0 else 24.0)
        mount_ratio = penetration / max(24.0, mount_armor if mount_armor > 0 else 24.0)
        person_pen = max(0.02, min(0.99, 0.5 + 0.5 * math.tanh((person_ratio - 1.0) * 1.35)))
        mount_pen = max(0.02, min(0.99, 0.5 + 0.5 * math.tanh((mount_ratio - 1.0) * 1.35)))
        person_penetrating = person_contacts * person_pen
        mount_penetrating = mount_contacts * mount_pen
        shield_wear = 0.0 if shield_contacts <= 0 or shield_share <= 0 else min(35.0, (shield_contacts / max(1.0, personnel * shield_share)) * max(0.20, impact / max(30.0, shield_structure)) * 6.0)
        armor_wear = min(18.0, (person_contacts / max(1.0, personnel)) * max(0.15, impact / max(35.0, armor if armor > 0 else 35.0)) * 3.5)
        pressure = person_penetrating + 0.65 * mount_penetrating
        return {
            "shots_fired": shots,
            "hit_fraction": round(hit_fraction, 6),
            "estimated_contacts": round(contacts, 3),
            "shield_intercept_fraction": round(intercept, 6),
            "shield_perforation_fraction": round(shield_perforation, 6),
            "person_penetrating_contacts": round(person_penetrating, 3),
            "mount_penetrating_contacts": round(mount_penetrating, 3),
            "shield_wear_pct": round(shield_wear, 4),
            "armor_wear_pct": round(armor_wear, 4),
            "contact_pressure": round(pressure, 3),
            "rule": "dispersion sets contact probability; shield arc/structure intercept first; residual penetration then meets armor or barding",
        }

    def _ensure_hot_fortified_site_resources(self, site_ref: str, *, at: str, authority_ref: str | None = None) -> dict[str, Any]:
        site_ref = str(site_ref)
        profile = self._fortification_profile_for_site(site_ref)
        blueprint = profile.get("logistics_blueprint") if isinstance(profile.get("logistics_blueprint"), Mapping) else None
        if not isinstance(blueprint, Mapping):
            raise ValueError("fortified site is missing its exact logistics blueprint")
        authority = self._fortified_site_authority(site_ref, authority_ref)
        garr_refs = self._formations_at(site_ref)
        summary = self._garrison_summary(garr_refs)
        targets = current_garrison_requirements(
            personnel=summary["personnel"], mounts=summary["mounts"], bow_personnel=summary["bow_personnel"], crossbow_personnel=summary["crossbow_personnel"], blueprint=blueprint,
        )
        capacity = copy.deepcopy(dict(blueprint.get("storage_capacity", {})))
        depot_ref, depot_path = self._site_depot_identity(site_ref)
        existing = self.read_optional(depot_path)
        if isinstance(existing, Mapping):
            depot = copy.deepcopy(dict(existing))
        else:
            native = self._native_site_state(site_ref) or str(authority).removeprefix("state_")
            source_ref = "depot_house_tang" if authority == "house_tang" else (f"state_depot_{native}" if native else None)
            depot = {
                "schema": "sword-depot", "owner_id": depot_ref, "kind": "fortified_site_military_depot", "state": authority or native,
                "location_ref": site_ref, "site_ref": site_ref, "fortification_profile_ref": str(profile.get("profile_id", "")),
                "storage_class": str(blueprint.get("storage_class", "")), "source_aggregate_depot_ref": source_ref,
                "stocks": {k: 0 for k in capacity}, "materialized_at": at, "transfer_history": [], "consumption_history": [], "damage_history": [],
                "geography": {"access_node_ref": site_ref, "owns_local_population": False, "rule": "military stock owner only; demographic and private-economy owners remain separate"},
            }
        depot["owner_id"] = depot_ref
        depot["site_ref"] = site_ref
        if site_ref == "loc_tang_inner_citadel" and depot_ref == "depot_house_tang":
            depot["location_ref"] = "loc_tang_inner_citadel_strategic_depot"
        elif site_ref != "loc_tang_manor":
            depot["location_ref"] = site_ref
        depot["fortification_profile_ref"] = str(profile.get("profile_id", ""))
        depot["storage_class"] = str(blueprint.get("storage_class", ""))
        depot["storage_capacity"] = capacity
        depot["garrison_formation_refs"] = garr_refs
        depot["garrison_summary"] = summary
        depot["garrison_support_targets"] = targets
        depot.setdefault("stocks", {})
        depot.setdefault("transfer_history", [])
        depot.setdefault("consumption_history", [])
        depot.setdefault("damage_history", [])
        depot["hot_state"] = {"status": "hot", "materialized_at": depot.get("materialized_at", at), "last_reviewed_at": at, "cold_blueprint_ref": str(profile.get("profile_id", ""))}
        water = blueprint.get("water_system", {}) if isinstance(blueprint.get("water_system"), Mapping) else {}
        water_capacity = max(0, int(water.get("reserve_capacity_person_days", 0)))
        fill_milli = max(0, min(1000, int(water.get("initial_hot_fill_fraction_milli", 800))))
        water0 = depot.get("water_reserve") if isinstance(depot.get("water_reserve"), Mapping) else {}
        initial_water = int(water_capacity * fill_milli / 1000)
        current_water = max(0, int(water0.get("current_person_days", initial_water)))
        depot["water_reserve"] = {
            "capacity_person_days": water_capacity,
            "current_person_days": min(current_water, water_capacity),
        }
        depot["medical_reserve"] = copy.deepcopy(dict(blueprint.get("medical_system", {}))) if isinstance(blueprint.get("medical_system"), Mapping) else {}
        depot["wagon_staging"] = copy.deepcopy(dict(blueprint.get("wagon_staging", {}))) if isinstance(blueprint.get("wagon_staging"), Mapping) else {}
        depot.setdefault("damage_state", {"overall_condition_percent": 100, "magazine_damage_percent": 0, "granary_damage_percent": 0, "water_system_damage_percent": 0, "medical_facility_damage_percent": 0, "wagon_yard_damage_percent": 0, "last_damage_at": None})

        native_state = self._native_site_state(site_ref) or str(authority).removeprefix("state_")
        source_ref = "depot_house_tang" if authority == "house_tang" else (f"state_depot_{native_state}" if native_state else None)
        if site_ref != "loc_tang_manor":
            if depot_ref == "depot_house_tang":
                depot["source_aggregate_depot_ref"] = None
                depot["resupply_sources"] = {
                    "industrial_region_ref": "state/economy/private/qin.json#local_regions.regions.loc_tang_manor",
                    "rule": "House Tang's strategic reserve is the terminal conserved depot. Replenishment must arrive from exact Tang Manor production, procurement or transfer; the depot is never its own upstream source.",
                }
            else:
                depot["source_aggregate_depot_ref"] = source_ref
                if authority == "house_tang":
                    depot["resupply_sources"] = {
                        "strategic_depot_ref": "depot_house_tang",
                        "industrial_region_ref": "state/economy/private/qin.json#local_regions.regions.loc_tang_manor",
                        "rule": "House Tang local military stock is replenished only from exact House Tang/Tang Manor conserved production and inventory; Qin state depots are not an implicit source",
                    }
        # Runtime materialization/review never teleports campaign stock.  Baseline
        # hot forts already own their conserved starting reserves in state.  A cold
        # fort activated later materializes empty mutable magazines and must receive
        # any campaign replenishment through an exact logistics convoy.
        depot["current_shortfalls"] = {k: max(0, int(v)-int(depot.get("stocks", {}).get(k, 0))) for k,v in targets.items() if max(0, int(v)-int(depot.get("stocks", {}).get(k, 0))) > 0}

        art_ref, art_path = self._site_artillery_identity(site_ref)
        if site_ref == "loc_tang_manor":
            artillery_ref = art_ref
        else:
            installed = blueprint.get("installed_equipment", {}) if isinstance(blueprint.get("installed_equipment"), Mapping) else {}
            art = self.read_optional(art_path)
            art = copy.deepcopy(dict(art)) if isinstance(art, Mapping) else {
                "schema": "fortress-artillery", "owner_id": art_ref, "state": authority or native_state, "site_ref": site_ref,
                "fortification_profile_ref": str(profile.get("profile_id", "")), "materialized_at": at,
                "condition": {"condition_percent": 100.0, "damaged_installations": 0, "destroyed_installations": 0},
                "damage_history": [], "consumption_history": [],
            }
            art["owner_id"] = art_ref; art["depot_ref"] = depot_ref
            if str(installed.get("mode", "")) == "reference_existing_exact_fixture_authority" and site_ref == "loc_sword_manor":
                art["installed"] = {"bed_crossbows": 60, "counterweight_trebuchets": 18, "stone_drop_cranes": 0, "firepot_systems": 0, "gate_mechanism_sets": 1, "signal_tower_sets": 0}
                art["parent_fixture_authority_ref"] = "tang_manor_artillery"
                art["rule"] = "physical Sword Manor subset of the Tang Manor artillery authority; not duplicate systems"
            else:
                art["installed"] = {k: max(0, int(v)) for k,v in installed.items() if k not in {"authority_ref", "mode"} and isinstance(v, (int,float))}
                art["rule"] = "fixed fortress equipment; usable firepower depends on serviceability, crews, ammunition, access and physical damage"
            self.put(art_path, art); self._register_owner(art_ref, art_path); artillery_ref = art_ref
        depot["artillery_ref"] = artillery_ref
        self.put(depot_path, depot); self._register_owner(depot_ref, depot_path)
        # Exact formations point at the local depot. Tang Manor outer forces retain the House strategic depot.
        if site_ref != "loc_tang_manor":
            for fr in garr_refs:
                try: fp, f0 = self._load_formation(fr)
                except ValueError: continue
                f = copy.deepcopy(f0); f["supply_depot_ref"] = depot_ref; f.setdefault("logistics", {})["source_depot_ref"] = depot_ref; self.put(fp, f)
        return {"site_ref": site_ref, "depot_ref": depot_ref, "artillery_ref": artillery_ref, "storage_class": str(blueprint.get("storage_class", "")), "garrison_personnel": summary["personnel"], "current_shortfalls": copy.deepcopy(depot.get("current_shortfalls", {}))}

    def _fortified_site_runtime_records(self, site_ref: str, *, at: str) -> tuple[str, dict[str, Any], str, dict[str, Any]]:
        """Return the canonical mutable depot and fixed-artillery state for one hot site."""
        self._ensure_hot_fortified_site_resources(site_ref, at=at, authority_ref=self._fortified_site_authority(site_ref))
        depot_ref, depot_path = self._site_depot_identity(site_ref)
        art_ref, art_path = self._site_artillery_identity(site_ref)
        depot = copy.deepcopy(dict(self.read(depot_path)))
        art0 = self.read_optional(art_path)
        art = copy.deepcopy(dict(art0)) if isinstance(art0, Mapping) else {}
        # Tang Manor predates the generic fortress-artillery schema.  Normalize its
        # mutable interface in-place without duplicating the installed systems.
        if site_ref == "loc_tang_manor":
            installed = art.get("installed") if isinstance(art.get("installed"), Mapping) else art.get("installed_systems", {})
            art["installed"] = {str(k): max(0, int(v)) for k, v in (installed or {}).items() if isinstance(v, (int, float))}
            art["depot_ref"] = depot_ref
            art["site_ref"] = site_ref
            art.setdefault("condition", {"condition_percent": 100.0, "damaged_installations": 0, "destroyed_installations": 0})
            art.setdefault("damage_history", [])
            art.setdefault("consumption_history", [])
            self.put(art_path, art)
        return depot_path, depot, art_path, art

    def _siege_defender_reserve_draw(self, fort: dict[str, Any], *, days: int, defenders: int, at: str) -> dict[str, Any]:
        """Consume exact fortified-site food/water for a siege interval.

        Strategic autarky means the site may keep producing internally if its
        productive districts survive.  It never means zero consumption or
        infinite stores.
        """
        site_ref = str(fort.get("site_ref") or fort.get("location_ref") or "")
        depot_path, depot, _art_path, _art = self._fortified_site_runtime_records(site_ref, at=at)
        stocks = depot.setdefault("stocks", {})
        ration = 2.0
        grain_need = max(0, int(math.ceil(max(0, defenders) * max(0, days) * ration)))
        grain_before = max(0, int(stocks.get("grain_kg", 0)))
        grain_used = min(grain_need, grain_before)
        stocks["grain_kg"] = grain_before - grain_used
        grain_shortfall = max(0, grain_need - grain_used)
        water = depot.setdefault("water_reserve", {})
        water_need = max(0, int(max(0, defenders) * max(0, days)))
        water_before = max(0, int(water.get("current_person_days", 0)))
        water_used = min(water_need, water_before)
        water["current_person_days"] = water_before - water_used
        water_shortfall = max(0, water_need - water_used)
        entry = {
            "at": at,
            "reason": "siege garrison daily consumption",
            "days": max(0, int(days)),
            "garrison_personnel": max(0, int(defenders)),
            "consumed": {"grain_kg": grain_used, "water_person_days": water_used},
            "shortfall": {"grain_kg": grain_shortfall, "water_person_days": water_shortfall},
        }
        depot.setdefault("consumption_history", []).append(entry)
        depot["consumption_history"] = depot["consumption_history"][-64:]
        self.put(depot_path, depot)
        # Legacy fortification fields remain projections only so old readers do not
        # become a second stock authority.
        fort["food_kg"] = max(0, int(stocks.get("grain_kg", 0)))
        fort["food_projection_only"] = True
        fort["fortified_site_depot_ref"] = str(depot.get("owner_id", ""))
        if grain_shortfall or water_shortfall:
            severity = min(1.0, max(grain_shortfall / max(1, grain_need), water_shortfall / max(1, water_need)))
            for fr in fort.get("garrison_formation_refs", []):
                try:
                    fp, f0 = self._load_formation(str(fr))
                except ValueError:
                    continue
                f = copy.deepcopy(f0)
                current = CampaignTime.parse(at)
                settle_formation_idle_fatigue(f, current=current, rules=self.read(FATIGUE_RULES_PATH))
                f["morale"] = max(0, int(f.get("morale", 50)) - max(1, int(round(20 * severity))))
                stamp_formation_activity_fatigue(
                    f, completed_at=current, fatigue_gain=max(1, int(round(15 * severity))), activity_kind="siege_deprivation"
                )
                self.put(fp, f)
        return entry

    def _siege_prepare_fortress_artillery(self, fort: Mapping[str, Any], *, defender_refs: list[str], battle_hours: int, at: str, attacker_refs: list[str] | None = None, engagement_range_m: float | None = None) -> dict[str, Any]:
        """Crew, cycle and fire fixed fortress systems from exact stocks.

        Bed crossbows deliberately use mechanism physics for launch energy.  Human
        capability can improve pointing, dispersion, timing and cycle execution, but
        never the latched mechanism's impact or penetration.
        """
        site_ref = str(fort.get("site_ref") or fort.get("location_ref") or "")
        depot_path, depot, art_path, art = self._fortified_site_runtime_records(site_ref, at=at)
        installed = art.get("installed", {}) if isinstance(art.get("installed"), Mapping) else {}
        cond = art.setdefault("condition", {})
        condition_pct = max(0.0, min(100.0, float(cond.get("condition_percent", 100.0))))
        condition = condition_pct / 100.0
        summary = self._garrison_summary([str(x) for x in defender_refs])
        crossbow = max(0, int(summary.get("crossbow_personnel", 0)))
        engineers = max(0, int(summary.get("engineer_personnel", 0)))
        personnel = max(0, int(summary.get("personnel", 0)))
        bed_inst = max(0, int(installed.get("bed_crossbows", 0) or 0))
        treb_inst = max(0, int(installed.get("counterweight_trebuchets", installed.get("trebuchets", 0)) or 0))
        drop_inst = max(0, int(installed.get("stone_drop_cranes", installed.get("stone_drop_systems", 0)) or 0))
        fire_inst = max(0, int(installed.get("firepot_systems", 0) or 0))

        siege_rules = self.read("game/data/mechanics/siege.json")
        bed_cfg = siege_rules.get("bed_crossbow", {}) if isinstance(siege_rules, Mapping) else {}
        bed_min_crew = max(1, int(bed_cfg.get("minimum_crew", 4) or 4))
        bed_serviceable = int(math.floor(bed_inst * condition))
        bed = min(bed_serviceable, crossbow // bed_min_crew)
        bed_fit_crew = min(crossbow, bed * max(bed_min_crew, int(bed_cfg.get("optimal_crew", 6) or 6)))
        crossbow_left = max(0, crossbow - bed_fit_crew)
        treb = min(int(math.floor(treb_inst * condition)), engineers // 60)
        engineer_left = max(0, engineers - treb * 60)
        drop = min(int(math.floor(drop_inst * condition)), engineer_left // 4)
        engineer_left = max(0, engineer_left - drop * 4)
        fire = min(int(math.floor(fire_inst * condition)), max(0, personnel - bed_fit_crew - treb * 60 - drop * 4) // 3)
        hours = max(1, int(battle_hours))
        elapsed_seconds = hours * 3600

        effective_range = max(1.0, float(bed_cfg.get("effective_range_m", 280) or 280))
        maximum_range = max(effective_range, float(bed_cfg.get("maximum_range_m", 420) or 420))
        # The mass-battle layer has no per-soldier tactical coordinates.  Its exact
        # fixed-artillery contact is therefore one bounded representative approach
        # range, recorded in the trace rather than hidden behind a generic bonus.
        representative_range = float(engagement_range_m) if engagement_range_m is not None else min(maximum_range, effective_range * 1.15)
        crew_control = self._siege_crossbow_crew_control([str(x) for x in defender_refs])
        bed_physics = self._siege_bed_crossbow_physics(
            range_m=representative_range, condition_pct=condition_pct, fit_crew=bed_fit_crew, active_weapons=bed, crew_control=crew_control
        ) if bed > 0 else {"legal": False, "reason": "no_active_bed_crossbows"}
        if bed_physics.get("legal"):
            bed_cycles_per_weapon = max(0, int(math.floor(elapsed_seconds / max(1.0, float(bed_physics.get("cycle_seconds", 48) or 48)))))
            desired_bed_bolts = bed * bed_cycles_per_weapon
        else:
            bed_cycles_per_weapon = 0
            desired_bed_bolts = 0

        desired = {
            "war_bolts": desired_bed_bolts,
            "trebuchet_stones_50kg": treb * max(1, int(elapsed_seconds // 180)),
            "prepared_drop_stones_20kg": drop * min(8, max(1, hours * 2)),
            "prepared_firepots": fire * min(6, max(1, hours)),
        }
        stocks = depot.setdefault("stocks", {})
        consumed: dict[str, int] = {}
        sufficiency: dict[str, float] = {}
        for key, need in desired.items():
            available = max(0, int(stocks.get(key, 0)))
            use = min(available, max(0, int(need)))
            stocks[key] = available - use
            consumed[key] = use
            sufficiency[key] = 1.0 if need <= 0 else use / max(1, need)

        bed_shots = max(0, int(consumed.get("war_bolts", 0))) if bed_physics.get("legal") else 0
        target_profile = self._siege_bed_crossbow_target_profile([str(x) for x in (attacker_refs or [])])
        bed_contact = self._siege_bed_crossbow_contact_profile(bed_physics, target_profile, shots_fired=bed_shots)
        bed_ammo_factor = float(sufficiency.get("war_bolts", 1.0 if desired_bed_bolts <= 0 else 0.0))
        # Preserve a bounded battle-scale consequence, but derive it from physical
        # releases instead of fixed "hero/body equivalents" or mere installation count.
        bed_mechanism_expression = 0.0
        if bed_physics.get("legal") and bed_shots > 0:
            impact = max(0.0, float(bed_physics.get("impact_index", 0) or 0))
            penetration = max(0.0, float(bed_physics.get("penetration_index", 0) or 0))
            contact_pressure = max(0.0, float(bed_contact.get("contact_pressure", 0) or 0))
            target_n = max(1, int(target_profile.get("personnel", 0) or 0))
            physical_quality = max(0.25, min(2.0, (impact + penetration) / 355.0))
            bed_mechanism_expression = bed * 8.0 * bed_ammo_factor * physical_quality * max(0.20, min(1.5, 0.45 + contact_pressure / max(1.0, target_n * 0.04)))

        # Other installed systems retain their existing aggregate contribution until
        # their own release/contact kernels are upgraded.  Their ammunition factors
        # are independent: an empty trebuchet magazine cannot suppress bed crossbows.
        treb_points = treb * 50.0 * float(sufficiency.get("trebuchet_stones_50kg", 1.0 if treb <= 0 else 0.0))
        drop_points = drop * 15.0 * float(sufficiency.get("prepared_drop_stones_20kg", 1.0 if drop <= 0 else 0.0))
        fire_points = fire * 12.0 * float(sufficiency.get("prepared_firepots", 1.0 if fire <= 0 else 0.0))
        equivalent = bed_mechanism_expression + treb_points + drop_points + fire_points
        support_factor = 1.0 + min(0.35, equivalent / max(1.0, float(personnel)) * 1.25)
        active = {"bed_crossbows": bed, "counterweight_trebuchets": treb, "stone_drop_cranes": drop, "firepot_systems": fire}
        relevant_suff = [float(v) for key, v in sufficiency.items() if desired.get(key, 0) > 0]
        ammo_factor = (sum(relevant_suff) / len(relevant_suff)) if relevant_suff else 1.0
        bed_fire = {
            "active_weapons": bed,
            "fit_crew": bed_fit_crew,
            "crew_control": round(float(crew_control), 3),
            "representative_engagement_range_m": round(representative_range, 3),
            "range_basis": "exact representative approach range for the aggregate siege-assault contact window",
            "completed_cycles_per_weapon": bed_cycles_per_weapon,
            "possible_releases": desired_bed_bolts,
            "releases_fired": bed_shots,
            "ammunition_resource": "war_bolts",
            "physics": bed_physics,
            "target_profile": target_profile,
            "contact_profile": bed_contact,
        }
        record = {
            "at": at,
            "battle_hours": hours,
            "active_systems": active,
            "crew_duty_personnel": bed_fit_crew + treb * 60 + drop * 4 + fire * 3,
            "ammunition_required_for_completed_cycles": desired,
            "ammunition_consumed": consumed,
            "ammunition_sufficiency_by_resource": {k: int(round(v * 1000)) for k, v in sufficiency.items()},
            "ammunition_sufficiency_milli": int(round(ammo_factor * 1000)),
            "bed_crossbow_fire": bed_fire,
            "defender_power_factor_milli": int(round(support_factor * 1000)),
            "rule": "fixed systems contribute only when serviceable, crewed by existing garrison bodies, supplied from exact depot stocks, and physically able to complete releases; bed-crossbow mechanism sets bolt launch energy while crew controls dispersion and cycle",
        }
        depot.setdefault("consumption_history", []).append({"at": at, "reason": "fortress artillery combat fire", "consumed": consumed})
        depot["consumption_history"] = depot["consumption_history"][-64:]
        art.setdefault("consumption_history", []).append(record)
        art["consumption_history"] = art["consumption_history"][-64:]
        self.put(depot_path, depot)
        self.put(art_path, art)
        return record

    def _siege_damage_fortified_site(self, fort: Mapping[str, Any], *, damage_percent: float, target: str, at: str, cause: str) -> dict[str, Any]:
        """Persist collateral damage to site services and fixed artillery."""
        site_ref = str(fort.get("site_ref") or fort.get("location_ref") or "")
        depot_path, depot, art_path, art = self._fortified_site_runtime_records(site_ref, at=at)
        damage = max(0.0, min(100.0, float(damage_percent)))
        state = depot.setdefault("damage_state", {})
        field_map = {
            "magazine": "magazine_damage_percent", "granary": "granary_damage_percent",
            "water": "water_system_damage_percent", "medical": "medical_facility_damage_percent",
            "wagon_yard": "wagon_yard_damage_percent",
        }
        field = field_map.get(target)
        if field:
            state[field] = min(100.0, float(state.get(field, 0.0)) + damage)
        state["overall_condition_percent"] = max(0.0, 100.0 - max(float(state.get(k, 0.0)) for k in field_map.values()))
        state["last_damage_at"] = at
        event = {"at": at, "cause": cause, "target": target, "damage_percent": round(damage, 3)}
        depot.setdefault("damage_history", []).append(event)
        depot["damage_history"] = depot["damage_history"][-64:]
        if target in {"artillery", "magazine"}:
            cond = art.setdefault("condition", {})
            before = max(0.0, min(100.0, float(cond.get("condition_percent", 100.0))))
            after = max(0.0, before - damage)
            cond["condition_percent"] = round(after, 3)
            total = sum(max(0, int(v)) for v in (art.get("installed", {}) or {}).values() if isinstance(v, (int, float)))
            cond["damaged_installations"] = int(round(total * max(0.0, 1.0 - after / 100.0)))
            cond.setdefault("destroyed_installations", 0)
            art.setdefault("damage_history", []).append(event)
            art["damage_history"] = art["damage_history"][-64:]
            self.put(art_path, art)
        self.put(depot_path, depot)
        return event

    def _siege_repair_from_site_depot(self, fort: Mapping[str, Any], *, required_units: int, at: str) -> tuple[str, dict[str, Any], int]:
        site_ref = str(fort.get("site_ref") or fort.get("location_ref") or "")
        depot_path, depot, _art_path, _art = self._fortified_site_runtime_records(site_ref, at=at)
        stocks = depot.setdefault("stocks", {})
        available = max(0, int(stocks.get("construction_material_units", 0)))
        take = min(max(0, int(required_units)), available)
        if take:
            stocks["construction_material_units"] = available - take
            depot.setdefault("consumption_history", []).append({"at": at, "reason": "fortification structural repair", "consumed": {"construction_material_units": take}})
            depot["consumption_history"] = depot["consumption_history"][-64:]
            self.put(depot_path, depot)
        return depot_path, depot, take

    def _settle_private_production(self, state: str, occurrences: int, at: str) -> None:
        super()._settle_private_production(state, occurrences, at)
        if occurrences <= 0:
            return
        # House Tang's two standing fortified military sites remain strategically
        # hot at baseline.  Review them after Qin private production so local
        # construction stock and the exact House military depot can replenish
        # honest shortfalls.  This never treats Qin's state depot as House stock.
        if state == "qin":
            for site_ref in ("loc_tang_manor", "loc_sword_manor"):
                self._ensure_hot_fortified_site_resources(
                    site_ref, at=at, authority_ref="house_tang"
                )

    def _fort_logistics_convoy_index(self) -> dict[str, Any]:
        path = "state/logistics/fortification-convoys/index.json"
        raw = self.read_optional(path)
        out = copy.deepcopy(dict(raw)) if isinstance(raw, Mapping) else {"schema":"sword-logistics-convoy-index","authority":False,"convoys":{},"active_refs":[]}
        out.setdefault("convoys", {}); out.setdefault("active_refs", [])
        return out

    def _fort_dispatch_resupply_convoy(self, *, site_ref: str, source_depot_ref: str, cargo: Mapping[str, Any], at: str) -> dict[str, Any]:
        site_ref = str(site_ref)
        source_path = self.owner_path(str(source_depot_ref))
        source = copy.deepcopy(self.read(source_path))
        if str(source.get("schema", "")) != "sword-depot":
            raise ValueError("fortification resupply source must be an exact depot owner")
        _dest_dp, dest, _dest_ap, _art = self._fortified_site_runtime_records(site_ref, at=at)
        source_loc = str(source.get("location_ref") or source.get("site_ref") or "")
        if not source_loc:
            raise ValueError("source depot has no physical location")
        route = shortest_path(self.read, source_loc, site_ref, modes=("convoy",))
        requested = {str(k): max(0, int(v)) for k, v in cargo.items() if max(0, int(v)) > 0}
        if not requested or len(requested) > 16:
            raise ValueError("fortification resupply cargo must contain 1..16 positive physical stock keys")
        src = source.setdefault("stocks", {})
        cap = dest.get("storage_capacity", {}) if isinstance(dest.get("storage_capacity"), Mapping) else {}
        for key, qty in requested.items():
            if key not in src:
                raise ValueError(f"source depot does not own requested stock key {key}")
            if int(src.get(key, 0)) < qty:
                raise ValueError(f"source depot lacks {key} for resupply convoy")
            if key in cap and int(cap.get(key, 0)) <= 0:
                raise ValueError(f"destination fort cannot store {key}")
        for key, qty in requested.items():
            src[key] = int(src.get(key, 0)) - qty
        token = hashlib.sha256((str(source_depot_ref)+"|"+site_ref+"|"+at+"|"+repr(sorted(requested.items()))).encode()).hexdigest()[:18]
        ref = f"fort_supply_convoy_{token}"; path = f"state/logistics/fortification-convoys/{token}.json"
        hours = max(1, int(math.ceil(float(route.get("duration_hours", 1)))))
        doc = {
            "schema":"sword-logistics-convoy","owner_id":ref,"kind":"fortification_resupply","source_depot_ref":str(source_depot_ref),
            "destination_site_ref":site_ref,"destination_depot_ref":str(dest.get("owner_id","")),"cargo":requested,"status":"in_transit",
            "departed_at":at,"arrives_at":str(CampaignTime.parse(at).add_hours(hours)),"route_refs":[str(x) for x in route.get("route_refs",[])],
            "route_path":[str(x) for x in route.get("path",[])],"travel_hours":hours,"geography":{"owns_local_population":False},
            "rule":"cargo left the source depot at dispatch and exists only in this aggregate convoy until lawful arrival/seizure/destruction",
        }
        source.setdefault("transfer_history", []).append({"at":at,"reason":f"dispatch fortification resupply to {site_ref}","destination_ref":ref,"moved":requested})
        source["transfer_history"] = source["transfer_history"][-64:]
        self.put(source_path, source); self.put(path, doc); self._register_owner(ref, path)
        idx = self._fort_logistics_convoy_index(); idx.setdefault("convoys", {})[ref]=path; idx.setdefault("active_refs", []).append(ref); idx["active_refs"]=sorted(set(idx["active_refs"])); self.put("state/logistics/fortification-convoys/index.json", idx)
        return {"convoy_ref":ref,"status":"in_transit","arrives_at":doc["arrives_at"],"cargo":copy.deepcopy(requested),"route_refs":doc["route_refs"]}

    def _fort_dispatch_withdrawal_convoy(self, *, site_ref: str, destination_depot_ref: str, cargo: Mapping[str, Any], at: str) -> dict[str, Any]:
        """Move exact mutable fort stock back to an exact depot through travel.

        Dematerialization never deletes or teleports remaining campaign stores.  A
        cold-site withdrawal is therefore the reverse of resupply: stock leaves the
        fort depot at dispatch, exists only in this aggregate convoy in transit, and
        enters the destination depot only on arrival.
        """
        site_ref = str(site_ref)
        source_ref, source_path = self._site_depot_identity(site_ref)
        source0 = self.read_optional(source_path)
        if not isinstance(source0, Mapping):
            raise ValueError("fortified site has no hot depot to withdraw")
        source = copy.deepcopy(dict(source0))
        destination_path = self.owner_path(str(destination_depot_ref))
        destination = copy.deepcopy(self.read(destination_path))
        if str(destination.get("schema", "")) != "sword-depot":
            raise ValueError("fortification withdrawal destination must be an exact depot owner")
        source_loc = str(source.get("location_ref") or source.get("site_ref") or site_ref)
        destination_loc = str(destination.get("location_ref") or destination.get("site_ref") or "")
        if not destination_loc:
            raise ValueError("withdrawal destination depot has no physical location")
        route = shortest_path(self.read, source_loc, destination_loc, modes=("convoy",))
        requested = {str(k): max(0, int(v)) for k, v in cargo.items() if max(0, int(v)) > 0}
        if not requested or len(requested) > 16:
            raise ValueError("fortification withdrawal cargo must contain 1..16 positive physical stock keys")
        stocks = source.setdefault("stocks", {})
        for key, qty in requested.items():
            if int(stocks.get(key, 0)) < qty:
                raise ValueError(f"fortified site lacks {key} for withdrawal convoy")
        for key, qty in requested.items():
            stocks[key] = int(stocks.get(key, 0)) - qty
        token = hashlib.sha256((site_ref+"|"+str(destination_depot_ref)+"|"+at+"|"+repr(sorted(requested.items()))).encode()).hexdigest()[:18]
        ref = f"fort_withdrawal_convoy_{token}"
        path = f"state/logistics/fortification-convoys/{token}.json"
        hours = max(1, int(math.ceil(float(route.get("duration_hours", 1)))))
        doc = {
            "schema":"sword-logistics-convoy", "owner_id":ref, "kind":"fortification_withdrawal",
            "source_depot_ref":source_ref, "source_site_ref":site_ref,
            "destination_site_ref":"", "destination_depot_ref":str(destination_depot_ref),
            "cargo":requested, "status":"in_transit", "departed_at":at,
            "arrives_at":str(CampaignTime.parse(at).add_hours(hours)),
            "route_refs":[str(x) for x in route.get("route_refs",[])],
            "route_path":[str(x) for x in route.get("path",[])], "travel_hours":hours,
            "geography":{"owns_local_population":False},
            "rule":"withdrawn fort stock left the hot site at dispatch and exists only in this aggregate convoy until lawful depot arrival/seizure/destruction",
        }
        source.setdefault("transfer_history", []).append({"at":at,"reason":"dispatch fortified-site withdrawal","destination_ref":ref,"moved":requested})
        source["transfer_history"] = source["transfer_history"][-64:]
        self.put(source_path, source); self.put(path, doc); self._register_owner(ref, path)
        idx = self._fort_logistics_convoy_index(); idx.setdefault("convoys", {})[ref]=path; idx.setdefault("active_refs", []).append(ref); idx["active_refs"]=sorted(set(idx["active_refs"])); self.put("state/logistics/fortification-convoys/index.json", idx)
        return {"convoy_ref":ref,"status":"in_transit","arrives_at":doc["arrives_at"],"cargo":copy.deepcopy(requested),"route_refs":doc["route_refs"]}

    def _fort_settle_resupply_convoy(self, convoy_ref: str, *, at: str) -> dict[str, Any]:
        idx = self._fort_logistics_convoy_index(); path = idx.get("convoys", {}).get(str(convoy_ref))
        if not isinstance(path, str):
            raise ValueError("unknown fortification resupply convoy")
        convoy = copy.deepcopy(self.read(path))
        if str(convoy.get("status", "")) not in {"in_transit","arrived_holding"}:
            return {"convoy_ref":convoy_ref,"status":str(convoy.get("status","")),"delivered":{}}
        if CampaignTime.parse(str(convoy.get("arrives_at"))) > CampaignTime.parse(at):
            raise ValueError("fortification resupply convoy has not physically arrived")
        kind = str(convoy.get("kind", "fortification_resupply"))
        if kind == "fortification_withdrawal":
            depot_path = self.owner_path(str(convoy.get("destination_depot_ref", "")))
            depot = copy.deepcopy(self.read(depot_path))
            if str(depot.get("schema", "")) != "sword-depot":
                raise ValueError("withdrawal destination depot is no longer valid")
        else:
            site_ref = str(convoy.get("destination_site_ref", ""))
            depot_path, depot, _ap, _art = self._fortified_site_runtime_records(site_ref, at=at)
        stocks = depot.setdefault("stocks", {}); capacity = depot.get("storage_capacity", {}) if isinstance(depot.get("storage_capacity"), Mapping) else {}
        delivered: dict[str,int] = {}; remaining: dict[str,int] = {}
        for key, raw in (convoy.get("cargo", {}) or {}).items():
            qty=max(0,int(raw)); cap=max(0,int(capacity.get(key, qty+int(stocks.get(key,0))))); free=max(0,cap-int(stocks.get(key,0))) if key in capacity else qty
            take=min(qty,free)
            if take: stocks[key]=int(stocks.get(key,0))+take; delivered[key]=take
            if qty-take: remaining[key]=qty-take
        convoy["cargo"]=remaining; convoy["arrival"]={"at":at,"delivered":delivered,"remaining":remaining}; convoy["status"]="delivered" if not remaining else "arrived_holding"
        depot.setdefault("transfer_history", []).append({"at":at,"reason":"arrived fortified-site withdrawal" if kind=="fortification_withdrawal" else "arrived fortification resupply convoy","source_ref":convoy_ref,"moved":delivered}); depot["transfer_history"]=depot["transfer_history"][-64:]
        self.put(depot_path,depot); self.put(path,convoy)
        idx["active_refs"]=[str(x) for x in idx.get("active_refs",[]) if str(x)!=str(convoy_ref) or remaining]; self.put("state/logistics/fortification-convoys/index.json",idx)
        return {"convoy_ref":convoy_ref,"status":convoy["status"],"delivered":delivered,"remaining":remaining}

    def _fort_active_convoy_for_site(self, site_ref: str) -> bool:
        idx = self._fort_logistics_convoy_index()
        for ref in idx.get("active_refs", []):
            path = idx.get("convoys", {}).get(str(ref))
            convoy = self.read_optional(path) if isinstance(path, str) else None
            if isinstance(convoy, Mapping) and str(convoy.get("status", "")) in {"in_transit", "arrived_holding"} and str(convoy.get("destination_site_ref", "")) == str(site_ref):
                return True
        return False

    def _fort_settle_due_campaign_convoys(self, at: str) -> list[str]:
        idx = self._fort_logistics_convoy_index()
        now = CampaignTime.parse(at)
        settled: list[str] = []
        for ref in list(idx.get("active_refs", [])):
            path = idx.get("convoys", {}).get(str(ref))
            convoy = self.read_optional(path) if isinstance(path, str) else None
            if not isinstance(convoy, Mapping) or str(convoy.get("status", "")) not in {"in_transit", "arrived_holding"}:
                continue
            arrives = convoy.get("arrives_at")
            if isinstance(arrives, str) and CampaignTime.parse(arrives) <= now:
                self._fort_settle_resupply_convoy(str(ref), at=at)
                settled.append(str(ref))
        return settled

    def _fort_campaign_logistics_review(self, at: str) -> dict[str, Any]:
        """Bounded weekly campaign review for already-hot fortified sites.

        Static blueprints are never scanned from mutable owner space.  At most the
        fixed fortification-profile list is reviewed, so campaign duration and the
        number of unrelated owners cannot grow this loop.  Existing shortfalls may
        dispatch one exact inbound convoy per site; review itself moves no stock.
        """
        settled = self._fort_settle_due_campaign_convoys(at)
        idx = self._fort_logistics_convoy_index()
        rules = self.read("game/data/mechanics/fortified-site-logistics.json")
        campaign = rules.get("campaign_resupply", {}) if isinstance(rules, Mapping) else {}
        interval = max(3600, int(campaign.get("review_interval_hours", 168)) * 3600)
        last = idx.get("last_campaign_review_at")
        if isinstance(last, str) and CampaignTime.parse(at).seconds_since(CampaignTime.parse(last)) < interval:
            return {"settled_convoy_refs": settled, "dispatched_convoy_refs": [], "dematerialized_site_refs": []}
        max_keys = max(1, int(campaign.get("max_distinct_stock_keys_per_convoy", 8)))
        fraction = max(1, min(1000, int(campaign.get("target_fraction_per_convoy_milli", 500))))
        profiles = self.read("game/data/world/fortification-profiles.json")
        dispatched: list[str] = []; dematerialized: list[str] = []
        for profile in profiles.get("profiles", []):
            if not isinstance(profile, Mapping):
                continue
            site_ref = str(profile.get("site_ref", profile.get("location_ref", "")))
            if not site_ref:
                continue
            _depot_ref, depot_path = self._site_depot_identity(site_ref)
            depot0 = self.read_optional(depot_path)
            if not isinstance(depot0, Mapping):
                continue
            garrisons = self._formations_at(site_ref)
            if not garrisons:
                try:
                    result = self._fort_dematerialize_if_cold(site_ref, at=at)
                    if result.get("status") == "cold": dematerialized.append(site_ref)
                except ValueError:
                    pass
                continue
            review = self._ensure_hot_fortified_site_resources(site_ref, at=at, authority_ref=self._fortified_site_authority(site_ref))
            if self._fort_active_convoy_for_site(site_ref):
                continue
            depot = self.read(depot_path)
            source_ref = str(depot.get("source_aggregate_depot_ref", ""))
            if not source_ref or source_ref == str(depot.get("owner_id", "")):
                continue
            try:
                source = self.read(self.owner_path(source_ref))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            source_stocks = source.get("stocks", {}) if isinstance(source.get("stocks"), Mapping) else {}
            cargo: dict[str, int] = {}
            for key, raw_need in sorted((review.get("current_shortfalls", {}) or {}).items(), key=lambda kv: (-int(kv[1]), str(kv[0]))):
                if len(cargo) >= max_keys or key not in source_stocks:
                    continue
                need = max(0, int(raw_need)); available = max(0, int(source_stocks.get(key, 0)))
                if need <= 0 or available <= 0:
                    continue
                target = max(1, int((depot.get("garrison_support_targets", {}) or {}).get(key, need)))
                batch = max(1, (target * fraction + 999) // 1000)
                take = min(need, available, batch)
                if take > 0: cargo[str(key)] = take
            if cargo:
                try:
                    cv = self._fort_dispatch_resupply_convoy(site_ref=site_ref, source_depot_ref=source_ref, cargo=cargo, at=at)
                    dispatched.append(str(cv["convoy_ref"]))
                except (ValueError, KeyError):
                    continue
        idx = self._fort_logistics_convoy_index(); idx["last_campaign_review_at"] = at; self.put("state/logistics/fortification-convoys/index.json", idx)
        return {"settled_convoy_refs": settled, "dispatched_convoy_refs": dispatched, "dematerialized_site_refs": dematerialized}

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        result = super()._advance_runtime(target_text)
        # During a semantic command the causal scheduler advances runtime.world_time
        # before the outer reducer writes state/meta.json.  Calling _world_time()
        # here would therefore (correctly) reject the temporary chronology skew.
        # Fort logistics is post-scheduler work, so use the scheduler's reached
        # cursor directly and let the outer command close meta chronology once.
        runtime = self.read("state/runtime.json")
        reached_raw = runtime.get("world_time") if isinstance(runtime, Mapping) else None
        if not isinstance(reached_raw, str) or not reached_raw:
            raise ValueError("fortification logistics review lost runtime chronology")
        reached = reached_raw
        review = self._fort_campaign_logistics_review(reached)
        if any(review.values()):
            result = dict(result); result["fortification_logistics"] = review
        return result

    def _fort_dematerialize_if_cold(self, site_ref: str, *, at: str) -> dict[str, Any]:
        site_ref=str(site_ref); depot_ref,depot_path=self._site_depot_identity(site_ref); art_ref,art_path=self._site_artillery_identity(site_ref)
        depot0=self.read_optional(depot_path)
        if not isinstance(depot0,Mapping):
            return {"site_ref":site_ref,"status":"already_cold"}
        if self._formations_at(site_ref):
            raise ValueError("fortified site with a current standing garrison remains hot")
        sidx=self.read("state/sieges/index.json")
        for path in (sidx.get("sieges",{}) or {}).values():
            sg=self.read_optional(path) if isinstance(path,str) else None
            if isinstance(sg,Mapping) and str(sg.get("status"))=="active":
                fort=self.read_optional(self.owner_path(str(sg.get("fortification_ref"))))
                if isinstance(fort,Mapping) and str(fort.get("site_ref",fort.get("location_ref","")))==site_ref:
                    raise ValueError("fortified site with an active siege cannot dematerialize")
        idx=self._fort_logistics_convoy_index()
        for ref in idx.get("active_refs",[]):
            p=idx.get("convoys",{}).get(str(ref)); cv=self.read_optional(p) if isinstance(p,str) else None
            if isinstance(cv,Mapping) and str(cv.get("destination_site_ref",""))==site_ref:
                raise ValueError("fortified site with an active resupply convoy cannot dematerialize")
        depot=copy.deepcopy(dict(depot0)); nonzero={k:int(v) for k,v in (depot.get("stocks",{}) or {}).items() if isinstance(v,(int,float)) and int(v)!=0}
        water=int((depot.get("water_reserve") or {}).get("current_person_days",0))
        damage=depot.get("damage_state",{}) if isinstance(depot.get("damage_state"),Mapping) else {}
        damaged=any(float(v)>0 for k,v in damage.items() if k.endswith("_damage_percent") and isinstance(v,(int,float)))
        if nonzero or water or damaged:
            raise ValueError("hot fortified site may dematerialize only after mutable stocks/water are zero and physical damage is fully resolved/transferred")
        if site_ref in {"loc_tang_manor","loc_kankoku_pass"}:
            raise ValueError("baseline strategic fortress owner is permanently hot while its standing institution exists")
        self.delete(depot_path); self._unregister_owner(depot_ref)
        if self.read_optional(art_path) is not None:
            self.delete(art_path); self._unregister_owner(art_ref)
        return {"site_ref":site_ref,"status":"cold","dematerialized_at":at,"cold_blueprint_ref":str(depot.get("fortification_profile_ref",""))}

    def _validate_command_semantics(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._validate_command_semantics(command, payload)
        if command.command_type != "fortification_logistics":
            return
        action=str(payload.get("action","")); allowed={"dispatch_resupply","withdraw_reserve","settle_convoy","review_site","dematerialize"}
        if action not in allowed: raise ValueError("unsupported fortification logistics action")
        if action in {"dispatch_resupply","withdraw_reserve","review_site","dematerialize"}:
            site=str(payload.get("site_ref",""));
            if not site: raise ValueError("site_ref is required")
            self._fortification_profile_for_site(site)
        if action=="dispatch_resupply":
            if not str(payload.get("source_depot_ref","")): raise ValueError("source_depot_ref is required")
            cargo=payload.get("cargo")
            if not isinstance(cargo,Mapping): raise ValueError("cargo must be an object of positive exact stock quantities")
        if action=="withdraw_reserve":
            if not str(payload.get("destination_depot_ref","")): raise ValueError("destination_depot_ref is required")
            cargo=payload.get("cargo")
            if not isinstance(cargo,Mapping): raise ValueError("cargo must be an object of positive exact stock quantities")
        if action=="settle_convoy" and not str(payload.get("convoy_ref","")): raise ValueError("convoy_ref is required")

    def _authorize_command(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._authorize_command(command,payload)
        if command.command_type != "fortification_logistics" or command.actor_id == getattr(self,"INTERNAL_ACTOR","internal:sword-autonomy"):
            return
        action=str(payload.get("action",""))
        if action=="dispatch_resupply":
            source=self.read(self.owner_path(str(payload.get("source_depot_ref",""))))
            if str(source.get("state",""))!="house_tang":
                raise PermissionError("player fortification resupply may dispatch only exact House Tang depot stock; sovereign state logistics requires internal/state authority")
        else:
            site=str(payload.get("site_ref","") or "")
            if action=="settle_convoy":
                idx=self._fort_logistics_convoy_index(); path=idx.get("convoys",{}).get(str(payload.get("convoy_ref",""))); cv=self.read_optional(path) if isinstance(path,str) else None; site=str(cv.get("destination_site_ref","")) if isinstance(cv,Mapping) else ""
            if site and self._fortified_site_authority(site)!="house_tang":
                raise PermissionError("player fortification logistics authority is limited to House Tang sites")

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "fortification_logistics":
            action=str(payload.get("action","")); now=str(self._world_time())
            if action=="dispatch_resupply":
                result=self._fort_dispatch_resupply_convoy(site_ref=str(payload["site_ref"]),source_depot_ref=str(payload["source_depot_ref"]),cargo=payload.get("cargo",{}),at=now)
            elif action=="withdraw_reserve":
                result=self._fort_dispatch_withdrawal_convoy(site_ref=str(payload["site_ref"]),destination_depot_ref=str(payload["destination_depot_ref"]),cargo=payload.get("cargo",{}),at=now)
            elif action=="settle_convoy": result=self._fort_settle_resupply_convoy(str(payload["convoy_ref"]),at=now)
            elif action=="review_site": result=self._ensure_hot_fortified_site_resources(str(payload["site_ref"]),at=now,authority_ref=self._fortified_site_authority(str(payload["site_ref"])))
            elif action=="dematerialize": result=self._fort_dematerialize_if_cold(str(payload["site_ref"]),at=now)
            else: raise ValueError("unsupported fortification logistics action")
            world_time,metrics=self._advance_seconds(3600); self._write_meta(command,world_time); result=dict(result); result.update({"action":action,"world_time":world_time,**metrics}); return result
        if command.command_type == "fortification_materialize":
            requested = str(payload.get("location_ref", "")); site = enclosing_fortification_site(self.read, requested) or requested
            authority = self._fortified_site_authority(site)
            self._ensure_hot_fortified_site_resources(site, at=str(self._world_time()), authority_ref=authority)
        elif command.command_type == "siege_start":
            fort_ref = str(payload.get("fortification_ref", ""))
            if fort_ref:
                fort = self.read(self.owner_path(fort_ref)); site = str(fort.get("location_ref", fort.get("site_ref", "")))
                if site: self._ensure_hot_fortified_site_resources(site, at=str(self._world_time()), authority_ref=self._fortified_site_authority(site))
        return super()._dispatch(command, payload)
