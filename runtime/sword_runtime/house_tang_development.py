"""Causal House Tang and Sword Manor aggregate development.

Sword Manor, House Guards, Guardian Cavalry, and Tang Champions remain aggregate
cohorts at Sword & Banners scale. Monthly settlement advances verified cohort
training, moves only eligible conserved headcount through the progression ladder,
and performs capacity-bounded recruitment without creating people from nothing.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sword_runtime.cohort_personnel import (
    add_recruits,
    consume_population_recruits,
    ensure_cohort_ledger,
    qualification_capacity,
    record_recruitment_cohort,
    role_count,
    transfer_between_forces,
    transfer_role,
    validate_cohort_ledger,
)

SWORD_FORCE = "state/forces/sword-manor.json"
HOUSE_FORCE = "state/forces/house-tang.json"
QIN_POPULATION = "state/population/qin.json"
MANOR_POPULATION = "state/population/tang-manor.json"
SWORD_PROGRESSION = "state/prog/sword-manor-progression.json"
CHAMPION_PROGRESSION = "state/prog/house-tang-champion-progression.json"
TRAINING_GROUND = "loc_tang_manor_training_ground"
GARRISON = "loc_tang_manor_garrison_yard"


def _records(doc: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row["record_id"]): row
        for row in doc.get("records", [])
        if isinstance(row, Mapping) and row.get("record_id")
    }


def _allocation_count(value: Any) -> int:
    return int(value.get("personnel", 0)) if isinstance(value, Mapping) else int(value)


def _months(value: Any, default: int = 0) -> int:
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else default


_CIVIL_PARENT_STRATUM = {
    "agricultural_workers_and_supervisors": "agricultural",
    "forge_and_armory_workers": "craft_and_industry",
    "stable_remount_and_carriage_workers": "merchant_and_transport",
    "warehouse_and_granary_workers": "merchant_and_transport",
    "construction_and_maintenance_workers": "craft_and_industry",
    "household_service": "household_and_service",
    "sword_manor_civilian_medical": "camp_medical_support",
    "administrative_clerks": "administration_and_education",
    "water_sanitation_and_firefighting": "household_and_service",
}


class HouseTangDevelopmentMixin:
    def _qualified_reserve(
        self,
        force: Mapping[str, Any],
        role: str,
        row: Mapping[str, Any],
        location_ref: str,
        minimum_service_months: int = 0,
    ) -> int:
        facts = row.get("facts", {}) if isinstance(row, Mapping) else {}
        total = 0
        for cohort in force.get("cohort_ledger", {}).get("cohorts", {}).values():
            if not isinstance(cohort, Mapping) or str(cohort.get("role")) != role:
                continue
            available = int(cohort.get("reserve_by_location", {}).get(location_ref, 0))
            if available <= 0:
                continue
            total += qualification_capacity(
                cohort,
                minimum_attribute_values=facts.get("minimum_attribute_values"),
                minimum_skill_values=facts.get("minimum_skill_values"),
                minimum_service_months=minimum_service_months,
                available_count=available,
            )
        return total

    @staticmethod
    def _civil_intake(
        qin: Mapping[str, Any], manor: dict[str, Any], *, at: str, cycle_ref: str
    ) -> int:
        """Add voluntary permanent residents from the Qin parent population.

        Tang Manor is an explicit subset of Qin. Moving an agricultural worker
        from elsewhere in Qin into a Tang Manor agricultural vacancy therefore
        increases the subset ledger but does not alter Qin's total or broad
        occupational stratum. Availability is bounded by the parent stratum and
        the saved House staffing vacancy; no outside-Qin person is invented.
        """
        policy = manor.get("civil_recruitment_policy", {})
        if not isinstance(policy, Mapping):
            return 0
        capacity = max(0, int(policy.get("monthly_capacity", 0)))
        targets = policy.get("target_staffing", {})
        strata = manor.setdefault("strata", {})
        qin_strata = qin.get("strata", {}) if isinstance(qin.get("strata"), Mapping) else {}
        remaining = capacity
        moved = 0
        mix: list[dict[str, Any]] = []
        for manor_role, target in targets.items() if isinstance(targets, Mapping) else ():
            if remaining <= 0:
                break
            parent_role = _CIVIL_PARENT_STRATUM.get(str(manor_role))
            if parent_role is None:
                continue
            current = max(0, int(strata.get(manor_role, 0)))
            vacancy = max(0, int(target) - current)
            parent_available = max(0, int(qin_strata.get(parent_role, 0)))
            take = min(remaining, vacancy, parent_available)
            if take <= 0:
                continue
            strata[manor_role] = current + take
            remaining -= take
            moved += take
            mix.append({"target_stratum": str(manor_role), "parent_stratum": parent_role, "count": take})
        if moved:
            manor["population_total"] = int(manor.get("population_total", 0)) + moved
            history = manor.setdefault("civil_recruitment_history", [])
            history.append({"at": at, "ref": cycle_ref, "count": moved, "source_population_ref": "population_qin", "mix": mix})
            manor["civil_recruitment_history"] = history[-24:]
        return moved

    def _autonomy_manor(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        occurrences = max(0, int(occurrences))
        if not occurrences:
            return

        sword = deepcopy(self.read(SWORD_FORCE))
        house = deepcopy(self.read(HOUSE_FORCE))
        qin = deepcopy(self.read(QIN_POPULATION))
        manor = deepcopy(self.read(MANOR_POPULATION))
        progression = deepcopy(self.read(SWORD_PROGRESSION))
        champion_progression = deepcopy(self.read(CHAMPION_PROGRESSION))
        ensure_cohort_ledger(sword, at=at)
        ensure_cohort_ledger(house, at=at)
        sword_rules = _records(progression)
        champion_rules = _records(champion_progression)
        profiles = self._fc_profiles()

        for cycle in range(occurrences):
            event_ref = f"sword_manor:{at}:{cycle}"
            self._fc_train(sword, "house_tang_max_sustainable", 1, event_ref)
            self._fc_train(house, "house_tang_max_sustainable", 1, event_ref + ":house")

            ladder = (
                ("trainee", "junior_disciple", "trainee_to_junior_disciple", "required_verified_training_months"),
                ("junior_disciple", "general_disciple", "junior_to_general_disciple", "required_verified_service_months_at_junior"),
                ("general_disciple", "senior_disciple", "general_to_senior_disciple", "required_verified_service_months_at_general"),
            )
            for source, destination, record_id, service_key in ladder:
                row = sword_rules.get(record_id, {})
                facts = row.get("facts", {}) if isinstance(row, Mapping) else {}
                eligible = self._qualified_reserve(
                    sword, source, row, TRAINING_GROUND, _months(facts.get(service_key), 0)
                )
                transfer_role(
                    sword, source, destination, eligible,
                    location_ref=TRAINING_GROUND,
                    evidence_ref=f"{event_ref}:{record_id}",
                )

            officer_rule = sword_rules.get("sword_manor_officer", {})
            officer_vacancy = max(0, int(sword.get("authorized_by_role", {}).get("officer", 50)) - role_count(sword, "officer"))
            transfer_role(
                sword, "senior_disciple", "officer",
                min(officer_vacancy, self._qualified_reserve(sword, "senior_disciple", officer_rule, TRAINING_GROUND)),
                location_ref=TRAINING_GROUND,
                evidence_ref=f"{event_ref}:officer",
            )

            caps = house.setdefault("authorized_by_role", {"house_guard": 700, "guardian_cavalry": 300, "tang_champion": 100})
            guard_vacancy = max(0, int(caps.get("house_guard", 700)) - role_count(house, "house_guard"))
            guard_rule = sword_rules.get("house_guard_candidate", {})
            transfer_between_forces(
                sword, house,
                source_role="senior_disciple", destination_role="house_guard",
                count=min(guard_vacancy, self._qualified_reserve(sword, "senior_disciple", guard_rule, TRAINING_GROUND)),
                source_location_ref=TRAINING_GROUND, destination_location_ref=GARRISON,
                evidence_ref=f"{event_ref}:guard",
            )

            cavalry_vacancy = max(0, int(caps.get("guardian_cavalry", 300)) - role_count(house, "guardian_cavalry"))
            cavalry_rule = sword_rules.get("house_guard_to_house_guardian_cavalry", {})
            transfer_role(
                house, "house_guard", "guardian_cavalry",
                min(cavalry_vacancy, self._qualified_reserve(house, "house_guard", cavalry_rule, GARRISON)),
                location_ref=GARRISON,
                evidence_ref=f"{event_ref}:cavalry",
            )

            allocated_champions = sum(
                _allocation_count(value)
                for value in house.get("allocated_to_formations", {}).values()
                if not isinstance(value, Mapping) or str(value.get("role", "")) == "tang_champion"
            )
            champion_vacancy = max(
                0,
                int(caps.get("tang_champion", 100))
                - role_count(house, "tang_champion")
                - allocated_champions,
            )
            champion_rule = champion_rules.get("guardian_cavalry_to_tang_champion", {})
            champion_facts = champion_rule.get("facts", {}) if isinstance(champion_rule, Mapping) else {}
            eligible_champions = self._qualified_reserve(
                house,
                "guardian_cavalry",
                champion_rule,
                GARRISON,
                int(champion_facts.get("minimum_verified_service_months_at_guardian_cavalry", 24)),
            )
            transfer_role(
                house, "guardian_cavalry", "tang_champion",
                min(champion_vacancy, eligible_champions),
                location_ref=GARRISON,
                evidence_ref=f"{event_ref}:champion",
            )

            trainee_count = role_count(sword, "trainee")
            monthly_capacity = int(manor.get("sword_manor", {}).get("monthly_intake_capacity", 500))
            housing_capacity = int(manor.get("sword_manor", {}).get("trainee_housing_capacity", 6000))
            wanted = max(0, min(monthly_capacity, housing_capacity - trainee_count))
            moved, source_mix = consume_population_recruits(
                qin,
                wanted,
                source_roles=("agricultural", "craft_and_industry", "household_and_service", "merchant_and_transport"),
                destination_role="private_household_military",
            )
            for source, count in source_mix.items():
                add_recruits(sword, "trainee", count, location_ref=TRAINING_GROUND)
                record_recruitment_cohort(
                    sword,
                    role="trainee",
                    count=count,
                    location_ref=TRAINING_GROUND,
                    source_population_ref="population_qin",
                    source_stratum=source,
                    recruited_at=at,
                    profile_registry=profiles,
                    selection_profile="sword_manor_screened_initiate",
                    provenance_ref=f"{event_ref}:intake:{source}",
                )
            manor.setdefault("sword_manor", {})["provisional_trainees"] = role_count(sword, "trainee")
            runtime = manor.setdefault("recruitment_runtime", {})
            runtime["last_sword_manor_intake"] = moved
            runtime["last_civil_intake"] = self._civil_intake(qin, manor, at=at, cycle_ref=event_ref)

        sword["cohort_training_closes"] = int(sword.get("cohort_training_closes", 0)) + occurrences
        sword["last_review"] = at
        manor.setdefault("recruitment_runtime", {})["last_review"] = at
        progression.setdefault("runtime", {})["last_settled_at"] = at
        progression["runtime"]["completed_monthly_reviews"] = int(progression["runtime"].get("completed_monthly_reviews", 0)) + occurrences
        validate_cohort_ledger(sword)
        validate_cohort_ledger(house)
        self.put(SWORD_FORCE, sword)
        self.put(HOUSE_FORCE, house)
        self.put(QIN_POPULATION, qin)
        self.put(MANOR_POPULATION, manor)
        self.put(SWORD_PROGRESSION, progression)
        self.put(CHAMPION_PROGRESSION, champion_progression)


__all__ = ["HouseTangDevelopmentMixin"]
