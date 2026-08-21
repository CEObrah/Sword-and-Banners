from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.training_facilities import program_facility_access, training_facility_access
from sword_runtime.training_instructors import exact_person_drill_access
from sword_runtime.training_programs import REGISTRY_PATH, formation_drill_access

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = json.loads((ROOT / REGISTRY_PATH).read_text(encoding="utf-8"))


class RepoRead:
    def read(self, path: str):
        return json.loads((ROOT / path).read_text(encoding="utf-8"))


RUNTIME = RepoRead()


def test_specialist_facility_tags_require_physical_site_evidence() -> None:
    assert training_facility_access(
        RUNTIME, location_ref="loc_tang_manor_defense_camp", facility_tag="engineering_yard"
    ) == 1.0
    assert training_facility_access(
        RUNTIME, location_ref="loc_tang_manor_defense_camp", facility_tag="artillery_range"
    ) == 1.0
    # Medical training is available through the enclosing Tang Manor training+medical site.
    assert training_facility_access(
        RUNTIME, location_ref="loc_tang_manor_defense_camp", facility_tag="medical_training"
    ) == 1.0
    # A normal eastern Qin field location cannot invent fixed Bastion infrastructure.
    assert training_facility_access(
        RUNTIME, location_ref="loc_qin_regional_02", facility_tag="artillery_range"
    ) == 0.0
    assert training_facility_access(
        RUNTIME, location_ref="loc_qin_regional_02", facility_tag="engineering_yard"
    ) == 0.0


def test_household_and_estate_training_use_saved_containment_chain() -> None:
    location = "loc_tang_manor_inner_citadel_family_hall"
    access = program_facility_access(
        RUNTIME, registry=REGISTRY, program_ref="program.tang_heir_child", location_ref=location
    )
    assert access["drill.heir_household_learning"] == 1.0
    assert access["drill.heir_route_observation"] == 1.0
    assert access["drill.heir_riding_familiarity"] == 1.0
    assert access["drill.heir_safe_martial_observation"] == 1.0


def test_field_army_can_establish_portable_drill_ground_but_not_fixed_specialist_works() -> None:
    access = program_facility_access(
        RUNTIME, registry=REGISTRY, program_ref="program.tang_field_senior_command", location_ref="loc_qin_eastern_depot"
    )
    assert access
    assert all(value == 1.0 for value in access.values())

    bastion = program_facility_access(
        RUNTIME, registry=REGISTRY, program_ref="program.bastion_senior_command", location_ref="loc_qin_regional_02"
    )
    assert bastion["drill.command_orders"] == 1.0
    assert bastion["drill.command_staff"] == 1.0
    assert bastion["drill.command_battlefield"] == 1.0
    assert bastion["drill.engineering_works"] == 0.0
    assert bastion["drill.artillery_service"] == 0.0


def test_exact_person_access_combines_equipment_and_facility_evidence() -> None:
    shin = json.loads((ROOT / "state/char/shin.json").read_text(encoding="utf-8"))
    access = exact_person_drill_access(
        RUNTIME, registry=REGISTRY, program_ref="program.martial_aspirant", person=shin
    )
    assert access["drill.martial_sword_fundamentals"] == 1.0
    assert access["drill.martial_grappling_fundamentals"] == 1.0
    assert access["drill.conditioning_march"] == 1.0
    assert access["drill.martial_leadership_fundamentals"] == 1.0


def test_formation_facility_gate_multiplies_conserved_equipment_access() -> None:
    artillery = {
        "location_ref": "loc_qin_regional_02",
        "composition": {"bastion_artillery": 500},
        "equipment_units_by_role": {"bastion_artillery": 500},
        "equipment_condition_by_role": {"bastion_artillery": 100.0},
        "shield_units_by_role": {},
        "shield_condition_by_role": {},
        "mounts": {},
    }
    access = formation_drill_access(
        REGISTRY, "program.artillery", artillery, role="bastion_artillery", runtime=RUNTIME
    )
    assert access["drill.artillery_service"] == 0.0

    artillery["location_ref"] = "loc_tang_manor_defense_camp"
    access = formation_drill_access(
        REGISTRY, "program.artillery", artillery, role="bastion_artillery", runtime=RUNTIME
    )
    assert access["drill.artillery_service"] == 1.0


def test_distributed_house_tang_cohort_resolves_real_formation_locations() -> None:
    from sword_runtime.force_cohort_living_world import ForceCohortLivingWorldMixin

    class Harness(ForceCohortLivingWorldMixin):
        def __init__(self):
            self.index = json.loads((ROOT / "state/index/owner-index.json").read_text(encoding="utf-8"))["owners"]

        def read(self, path: str):
            return json.loads((ROOT / path).read_text(encoding="utf-8"))

        def owner_path(self, ref: str) -> str:
            return str(self.index[ref])

        def _load_formation(self, ref: str):
            path = self.owner_path(ref)
            return path, self.read(path)

    force = json.loads((ROOT / "state/forces/house-tang.json").read_text(encoding="utf-8"))
    cohort = force["cohort_ledger"]["cohorts"]["cohort_force_house_tang_house_guard_standing"]
    slices = Harness()._fc_training_slices(cohort)
    by_location: dict[str, int] = {}
    for row in slices:
        by_location[str(row["location_ref"])] = by_location.get(str(row["location_ref"]), 0) + int(row["count"])

    expected: dict[str, int] = {}
    harness = Harness()
    for key in ("allocated_by_formation", "allocated_external_by_formation"):
        for formation_ref, count in cohort.get(key, {}).items():
            _, formation = harness._load_formation(str(formation_ref))
            loc = str(formation["location_ref"])
            expected[loc] = expected.get(loc, 0) + int(count)
    for loc, count in cohort.get("reserve_by_location", {}).items():
        expected[str(loc)] = expected.get(str(loc), 0) + int(count)
    expected = {loc: count for loc, count in expected.items() if count > 0}
    assert by_location == expected


def test_complete_role_loadout_supplies_shield_until_separate_ledger_exists(campaign):
    from copy import deepcopy
    from sword_runtime.service_runtime import CommandRoutedProductionPlanner
    from sword_runtime.training_programs import REGISTRY_PATH, formation_drill_access, resolve_program_ref

    planner = CommandRoutedProductionPlanner(campaign)
    planner._reset()
    registry = planner.read(REGISTRY_PATH)
    formation = deepcopy(planner.read("state/formations/bastion-iron-wall-01.json"))
    program_ref = resolve_program_ref(registry, role="bastion_heavy_infantry")

    inherited = formation_drill_access(registry, program_ref, formation, role="bastion_heavy_infantry", runtime=planner)
    assert inherited["drill.spear_shield_line"] == 1.0
    assert inherited["drill.guard_protection"] == 1.0

    formation["shield_units_by_role"] = {"bastion_heavy_infantry": 0}
    explicit_zero = formation_drill_access(registry, program_ref, formation, role="bastion_heavy_infantry", runtime=planner)
    assert explicit_zero["drill.spear_shield_line"] == 0.0
    assert explicit_zero["drill.guard_protection"] == 0.0
