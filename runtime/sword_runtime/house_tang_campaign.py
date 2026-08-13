"""House Tang/Sword Manor production autonomy.

This layer repairs the Gold regression that reduced Sword Manor autonomy to a
counter increment.  It preserves ordinary personnel as aggregate cohorts while
allowing only explicitly configured elite/player-personal pools to use latent
individual identities.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sword_runtime.activity_living_world import ActivityCampaignEventPlanner
from sword_runtime.cohort_personnel import (
    add_recruits,
    advance_aggregate_development,
    consume_population_recruits,
    role_count,
    transfer_role,
)

_SWORD_FORCE = "state/forces/sword-manor.json"
_HOUSE_FORCE = "state/forces/house-tang.json"
_QIN_POPULATION = "state/population/qin.json"
_TANG_MANOR_POPULATION = "state/population/tang-manor.json"
_PROGRESSION = "state/prog/sword-manor-progression.json"
_CHAMPION_CATALOG = "state/personnel/house-tang-champions.json"
_TRAINING_GROUND = "loc_tang_manor_training_ground"
_GARRISON = "loc_tang_manor_garrison_yard"

_DEFAULT_DEVELOPMENT: dict[str, dict[str, Any]] = {
    "trainee": {
        "minimum_service_months": 12,
        "service_months_mean": 6.0,
        "verified_training_hours_per_month": 150,
        "monthly_newly_qualified_fraction": 0.018,
        "assessment_ready": 0,
        "qualification_fraction_carry": 0.0,
    },
    "junior_disciple": {
        "minimum_service_months": 18,
        "service_months_mean": 12.0,
        "verified_training_hours_per_month": 140,
        "monthly_newly_qualified_fraction": 0.014,
        "assessment_ready": 0,
        "qualification_fraction_carry": 0.0,
    },
    "general_disciple": {
        "minimum_service_months": 24,
        "service_months_mean": 18.0,
        "verified_training_hours_per_month": 130,
        "monthly_newly_qualified_fraction": 0.009,
        "assessment_ready": 0,
        "qualification_fraction_carry": 0.0,
    },
    "senior_disciple": {
        "minimum_service_months": 18,
        "service_months_mean": 30.0,
        "verified_training_hours_per_month": 120,
        "monthly_newly_qualified_fraction": 0.005,
        "assessment_ready": 0,
        "qualification_fraction_carry": 0.0,
    },
    "officer": {
        "minimum_service_months": 0,
        "service_months_mean": 36.0,
        "verified_training_hours_per_month": 96,
        "monthly_newly_qualified_fraction": 0.0,
        "assessment_ready": 0,
        "qualification_fraction_carry": 0.0,
    },
    "mounted_scout": {
        "minimum_service_months": 0,
        "service_months_mean": 24.0,
        "verified_training_hours_per_month": 120,
        "monthly_newly_qualified_fraction": 0.0,
        "assessment_ready": 0,
        "qualification_fraction_carry": 0.0,
    },
}


def _development(force: dict[str, Any]) -> dict[str, Any]:
    profiles = force.setdefault("cohort_development", {})
    for role, defaults in _DEFAULT_DEVELOPMENT.items():
        profile = profiles.setdefault(role, {})
        for key, value in defaults.items():
            profile.setdefault(key, deepcopy(value))
        profile.setdefault(
            "representation",
            "aggregate_distribution_only_no_persistent_individuals",
        )
    return profiles


def _take_ready(profile: dict[str, Any], count: int) -> int:
    take = min(max(0, int(count)), max(0, int(profile.get("assessment_ready", 0))))
    profile["assessment_ready"] = int(profile.get("assessment_ready", 0)) - take
    return take


def _mix_new_promotions(profile: dict[str, Any], moved: int) -> None:
    if moved <= 0:
        return
    # New entrants have zero service in their new rank.  Keep a cheap weighted
    # mean rather than pretending every anonymous member has the same history.
    profile["new_entrants_last_review"] = int(profile.get("new_entrants_last_review", 0)) + moved
    profile["assessment_ready"] = max(0, int(profile.get("assessment_ready", 0)))


class HouseTangCampaignPlanner(ActivityCampaignEventPlanner):
    """Production planner with causal House Tang personnel development."""

    def _autonomy_manor(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        owner = str(host.get("owner_ref", ""))
        if owner not in {"institution_sword_manor", "sword_manor_progression", ""}:
            return super()._autonomy_manor(host, occurrences, at)

        occ = max(0, int(occurrences))
        if occ <= 0:
            return

        sword = deepcopy(self.read(_SWORD_FORCE))
        house = deepcopy(self.read(_HOUSE_FORCE))
        qin = deepcopy(self.read(_QIN_POPULATION))
        manor = deepcopy(self.read(_TANG_MANOR_POPULATION))
        progression = deepcopy(self.read(_PROGRESSION))
        champions = deepcopy(self.read(_CHAMPION_CATALOG))

        profiles = _development(sword)
        house_profiles = house.setdefault("cohort_development", {})
        house_profiles.setdefault(
            "house_guard",
            {
                "representation": "aggregate_distribution_only_no_persistent_individuals",
                "minimum_service_months": 18,
                "service_months_mean": 30.0,
                "verified_training_hours_per_month": 96,
                "monthly_newly_qualified_fraction": 0.004,
                "assessment_ready": 0,
                "qualification_fraction_carry": 0.0,
            },
        )
        house_profiles.setdefault(
            "guardian_cavalry",
            {
                "representation": "aggregate_distribution_only_until_champion_promotion",
                "minimum_service_months": 24,
                "service_months_mean": 36.0,
                "verified_training_hours_per_month": 120,
                "monthly_newly_qualified_fraction": 0.002,
                "assessment_ready": 0,
                "qualification_fraction_carry": 0.0,
            },
        )

        for _ in range(occ):
            # Development first: service/training evidence creates assessment
            # candidates, but promotion still requires a real opening below.
            for role, profile in profiles.items():
                advance_aggregate_development(profile, role_count(sword, role), 1)
            for role in ("house_guard", "guardian_cavalry"):
                advance_aggregate_development(house_profiles[role], role_count(house, role), 1)

            # Internal Sword Manor ladder.  Whole bodies move; total headcount is
            # unchanged.  The rank profiles remain distributions, not hidden NPCs.
            for source, dest in (
                ("trainee", "junior_disciple"),
                ("junior_disciple", "general_disciple"),
                ("general_disciple", "senior_disciple"),
            ):
                ready = _take_ready(profiles[source], role_count(sword, source))
                moved = transfer_role(sword, source, dest, ready, location_ref=_TRAINING_GROUND)
                if moved < ready:
                    profiles[source]["assessment_ready"] = int(profiles[source].get("assessment_ready", 0)) + (ready - moved)
                _mix_new_promotions(profiles[dest], moved)

            # Senior -> Sword Manor Officer only fills actual authorized vacancies.
            officer_cap = int(sword.get("authorized_by_role", {}).get("officer", 50))
            officer_vacancy = max(0, officer_cap - role_count(sword, "officer"))
            if officer_vacancy:
                ready = _take_ready(profiles["senior_disciple"], officer_vacancy)
                moved = transfer_role(sword, "senior_disciple", "officer", ready, location_ref=_TRAINING_GROUND)
                _mix_new_promotions(profiles["officer"], moved)

            # Senior -> House Guard can occur only when House Tang has a genuine
            # House Guard vacancy.  This conserves one body across force owners.
            house_caps = house.setdefault(
                "authorized_by_role",
                {"house_guard": 700, "guardian_cavalry": 300, "tang_champion": 100},
            )
            guard_vacancy = max(0, int(house_caps.get("house_guard", 700)) - role_count(house, "house_guard"))
            if guard_vacancy:
                ready = _take_ready(profiles["senior_disciple"], guard_vacancy)
                moved = min(ready, role_count(sword, "senior_disciple"))
                if moved:
                    sword["available_by_role"]["senior_disciple"] -= moved
                    sword["available_by_location"][_TRAINING_GROUND]["senior_disciple"] -= moved
                    sword["headcount"] -= moved
                    add_recruits(house, "house_guard", moved, location_ref=_GARRISON)
                    _mix_new_promotions(house_profiles["house_guard"], moved)
                if moved < ready:
                    profiles["senior_disciple"]["assessment_ready"] += ready - moved

            # House Guard -> Guardian Cavalry fills only a real cavalry vacancy.
            cavalry_vacancy = max(0, int(house_caps.get("guardian_cavalry", 300)) - role_count(house, "guardian_cavalry"))
            if cavalry_vacancy:
                ready = _take_ready(house_profiles["house_guard"], cavalry_vacancy)
                moved = transfer_role(house, "house_guard", "guardian_cavalry", ready, location_ref=_GARRISON)
                _mix_new_promotions(house_profiles["guardian_cavalry"], moved)

            # Guardian Cavalry -> Tang Champion is where anonymous aggregation
            # ends.  Each promoted body gains a permanent latent identity exactly
            # once.  Assigned and reserve Champions share this one institutional
            # catalog; assignment never creates a second person.
            allocated_champions = sum(
                int(v.get("personnel", 0)) if isinstance(v, Mapping) and str(v.get("role")) == "tang_champion" else 0
                for v in house.get("allocated_to_formations", {}).values()
            )
            active_champions = role_count(house, "tang_champion") + allocated_champions
            champion_vacancy = max(0, int(house_caps.get("tang_champion", 100)) - active_champions)
            if champion_vacancy:
                ready = _take_ready(house_profiles["guardian_cavalry"], champion_vacancy)
                moved = transfer_role(house, "guardian_cavalry", "tang_champion", ready, location_ref=_GARRISON)
                if moved:
                    old_count = int(champions.get("count", 0))
                    champions["count"] = old_count + moved
                    champions["active_count"] = int(champions.get("active_count", old_count)) + moved
                    champions.setdefault("promotion_batches", []).append(
                        {
                            "at": at,
                            "from_role": "guardian_cavalry",
                            "start_index": old_count + 1,
                            "count": moved,
                            "evidence": "aggregate qualification gates plus actual Tang Champion vacancy",
                        }
                    )

            # Sword Manor standing policy: recruit as many initiates as current
            # housing and monthly intake allow.  These are real Qin residents
            # transferred from civilian strata; parent population total is fixed.
            trainee_count = role_count(sword, "trainee")
            intake_cap = int(manor.get("sword_manor", {}).get("monthly_intake_capacity", 500))
            housing = int(manor.get("sword_manor", {}).get("trainee_housing_capacity", 6000))
            wanted = max(0, min(intake_cap, housing - trainee_count))
            moved = consume_population_recruits(
                qin,
                wanted,
                source_roles=("agricultural", "craft_and_industry", "household_and_service", "merchant_and_transport"),
            )
            if moved:
                add_recruits(sword, "trainee", moved, location_ref=_TRAINING_GROUND)
                manor.setdefault("sword_manor", {})["provisional_trainees"] = role_count(sword, "trainee")
                manor.setdefault("recruitment_runtime", {})["last_sword_manor_intake"] = moved

            # Civil settlement recruitment is voluntary and job-capacity bound.
            policy = manor.setdefault("civil_recruitment_policy", {})
            monthly_civil_cap = max(0, int(policy.get("monthly_capacity", 200)))
            remaining = monthly_civil_cap
            local_strata = manor.setdefault("strata", {})
            recruited_civil = 0
            for role, target in policy.get("target_staffing", {}).items():
                if remaining <= 0:
                    break
                current = int(local_strata.get(role, 0))
                hire = min(remaining, max(0, int(target) - current))
                if hire:
                    local_strata[role] = current + hire
                    manor["population_total"] = int(manor.get("population_total", 0)) + hire
                    recruited_civil += hire
                    remaining -= hire
            manor.setdefault("recruitment_runtime", {})["last_civil_intake"] = recruited_civil

        sword["cohort_training_closes"] = int(sword.get("cohort_training_closes", 0)) + occ
        sword["last_review"] = at
        manor.setdefault("recruitment_runtime", {})["last_review"] = at
        progression.setdefault("runtime", {})["last_settled_at"] = at
        progression["runtime"]["completed_monthly_reviews"] = int(
            progression["runtime"].get("completed_monthly_reviews", 0)
        ) + occ

        self.put(_SWORD_FORCE, sword)
        self.put(_HOUSE_FORCE, house)
        self.put(_QIN_POPULATION, qin)
        self.put(_TANG_MANOR_POPULATION, manor)
        self.put(_PROGRESSION, progression)
        self.put(_CHAMPION_CATALOG, champions)


__all__ = ["HouseTangCampaignPlanner"]
