from __future__ import annotations

from sword_runtime.combat_capability import CombatCapabilityMixin


class Harness(CombatCapabilityMixin):
    def _combat_interaction_rules(self):
        return {
            "mount_phase_base_loss_fraction_per_hour": 0.002,
            "mount_phase_risk_excess_loss_fraction_per_hour": 0.006,
            "mount_phase_loss_fraction_cap": 0.12,
        }


def _cavalry_row(*, mounted_units: float, count: int = 1000) -> dict:
    return {
        "count": count,
        "mounted": mounted_units > 0,
        "mounted_units": mounted_units,
        "mount_required_units": count,
        "mount_index": 110.0,
        "charge_legal": mounted_units > 0,
        "mount_total_mass_kg": 610.0,
        "mount_speed_mps": 10.5,
        "riding": 120.0,
        "mount_protection_index": 45.0,
        "melee_weapon_family": "spear",
        "melee_reach_m": 2.7,
        "formation_fighting": 100.0,
        "formation_cohesion": 90.0,
        "formation_training": 90.0,
        "melee_score": 110.0,
        "melee_force": 1.1,
        "melee_penetration_factor": 1.15,
    }


def _braced_row() -> dict:
    return {
        "count": 1000,
        "mounted": False,
        "mounted_units": 0.0,
        "melee_weapon_family": "spear",
        "melee_reach_m": 2.5,
        "formation_fighting": 125.0,
        "formation_cohesion": 100.0,
        "formation_training": 100.0,
        "protection_index": 50.0,
        "melee_score": 105.0,
        "melee_force": 1.0,
        "melee_penetration_factor": 1.0,
    }


def test_partial_physical_mount_count_reduces_mounted_share_and_charge_expression():
    h = Harness()
    formation = {"cohesion": 95, "training_progress": 95, "mounts": {"horse": 500}}
    half = h._combat_formation_method_profile([_cavalry_row(mounted_units=500)], formation, [_braced_row()], "open")
    full = h._combat_formation_method_profile([_cavalry_row(mounted_units=1000)], formation, [_braced_row()], "open")
    assert half["mounted_share"] == 0.5
    assert full["mounted_share"] == 1.0
    assert half["charge_collision_index"] < full["charge_collision_index"]
    assert half["combat_factor"] < full["combat_factor"]


def test_mount_factor_uses_actual_mounted_units_not_role_label():
    h = Harness()
    formation = {"mounts": {"horse": 500}}
    half = h._combat_mount_factor([_cavalry_row(mounted_units=500)], formation)
    full = h._combat_mount_factor([_cavalry_row(mounted_units=1000)], {"mounts": {"horse": 1000}})
    assert half < full


def test_braced_contact_can_destroy_mounts_between_phases_and_high_risk_loses_more():
    h = Harness()
    low = h._combat_phase_mount_attrition(1000, 1.0, 0.8, 2.0, 1.0)
    high = h._combat_phase_mount_attrition(1000, 1.0, 1.8, 2.0, 1.0)
    assert low["units_lost"] > 0
    assert high["units_lost"] > low["units_lost"]
    assert high["units_after"] < low["units_after"]


def test_mount_phase_attrition_is_bounded_and_zero_without_exposure():
    h = Harness()
    none = h._combat_phase_mount_attrition(1000, 0.0, 2.0, 3.0, 1.5)
    capped = h._combat_phase_mount_attrition(1000, 1.0, 100.0, 24.0, 5.0)
    assert none["units_lost"] == 0
    assert capped["units_lost"] <= 120
    assert capped["units_after"] >= 880

class SnapshotHarness(Harness):
    def __init__(self):
        self.items = {
            "horse": {"id": "horse", "schema": "horse", "Strength": 100, "Agility": 90, "Speed": 100, "Endurance": 90, "Composure": 80, "training_score": 90, "mass_kg": 450},
            "lance": {"id": "lance", "family": "spear", "base_force_thrust": 1.1, "reach_m": 2.6, "handling": 0.8, "mass_kg": 3.0},
            "tack": {"id": "tack", "mass_kg": 10.0},
        }
        self.loadout = {"id": "cav", "mount": "horse", "tack": "tack", "primary_melee_weapon": "lance"}

    def _combat_role_profile(self, role):
        return {
            "loadout_id": "cav",
            "melee_skill_weights": {"Spear": 1.0},
            "attribute_weights": {"Strength": 0.4, "Agility": 0.3, "Coordination": 0.3},
            "ranged_skill_weights": {},
            "frontage_spacing_m": 1.5,
            "depth_support_factor": 0.1,
        }

    def _combat_loadout(self, loadout_id):
        return self.loadout

    def _combat_weapon(self, item_id):
        if isinstance(item_id, dict):
            return item_id
        return self.items.get(str(item_id), {})


def test_cohort_snapshot_allocates_only_physical_mounts_to_mounted_role():
    h = SnapshotHarness()
    formation = {
        "personnel": 1000,
        "composition": {"cavalry": 1000},
        "cohort_composition": [{"cohort_id": "c1", "count": 1000}],
        "mounts": {"horse": 500},
        "equipment_units_by_role": {"cavalry": 1000},
        "equipment_completeness": 1.0,
    }
    force = {"cohort_ledger": {"cohorts": {"c1": {
        "role": "cavalry",
        "attribute_means": {"Strength": 80, "Agility": 80, "Coordination": 80, "Endurance": 80, "Awareness": 80},
        "skill_means": {"Spear": 90, "Riding": 90, "Formation Fighting": 90},
    }}}}
    row = h._combat_cohort_snapshot(formation, force)[0]
    assert row["mount_required_units"] == 1000
    assert row["mounted_units"] == 500.0
    assert row["mount_availability"] == 0.5
    assert row["mounted"] is True
