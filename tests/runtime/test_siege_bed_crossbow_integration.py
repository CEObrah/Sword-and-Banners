from pathlib import Path

from sword_runtime.fortified_site_runtime import FortifiedSiteRuntimeMixin



class _FakeFortress(FortifiedSiteRuntimeMixin):
    def __init__(self, root: Path, *, bolts: int, crew_control: float = 100.0, condition: float = 100.0):
        self.root = root
        self.depot = {"stocks": {"war_bolts": bolts, "trebuchet_stones_50kg": 0, "prepared_drop_stones_20kg": 0, "prepared_firepots": 0}}
        self.art = {"installed": {"bed_crossbows": 2, "counterweight_trebuchets": 0, "stone_drop_cranes": 0, "firepot_systems": 0}, "condition": {"condition_percent": condition}}
        self.crew_control = crew_control
        self.saved = {}

    def read(self, rel):
        import json
        return json.loads((self.root / rel).read_text())

    def _fortified_site_runtime_records(self, site_ref, *, at):
        return "depot.json", self.depot, "art.json", self.art

    def _garrison_summary(self, refs):
        return {"personnel": 120, "mounts": 0, "bow_personnel": 0, "crossbow_personnel": 12, "engineer_personnel": 0}

    def _siege_crossbow_crew_control(self, refs):
        return self.crew_control

    def _siege_bed_crossbow_target_profile(self, refs):
        return {
            "personnel": 500, "rows": 1, "shield_share": 0.6, "shield_structure": 105.0,
            "shield_coverage_degrees": 120.0, "armor_protection_index": 95.0, "mounted_share": 0.2,
            "mount_protection_index": 80.0, "order_factor": 0.7,
        }

    def put(self, path, value):
        self.saved[path] = value



def test_bed_crossbow_mechanism_power_is_independent_of_crew_skill():
    runtime = _FakeFortress(Path(__file__).resolve().parents[2], bolts=0)
    low = runtime._siege_bed_crossbow_physics(
        range_m=320, condition_pct=100, fit_crew=6, active_weapons=1, crew_control=50
    )
    high = runtime._siege_bed_crossbow_physics(
        range_m=320, condition_pct=100, fit_crew=6, active_weapons=1, crew_control=250
    )
    assert low["legal"] and high["legal"]
    assert low["impact_index"] == high["impact_index"]
    assert low["penetration_index"] == high["penetration_index"]
    assert high["dispersion_radius_m"] < low["dispersion_radius_m"]
    assert high["cycle_seconds"] < low["cycle_seconds"]


def test_bed_crossbow_range_condition_and_crew_legality():
    runtime = _FakeFortress(Path(__file__).resolve().parents[2], bolts=0)
    close = runtime._siege_bed_crossbow_physics(
        range_m=200, condition_pct=100, fit_crew=6, active_weapons=1, crew_control=100
    )
    long = runtime._siege_bed_crossbow_physics(
        range_m=410, condition_pct=100, fit_crew=6, active_weapons=1, crew_control=100
    )
    damaged = runtime._siege_bed_crossbow_physics(
        range_m=200, condition_pct=50, fit_crew=6, active_weapons=1, crew_control=100
    )
    uncrewed = runtime._siege_bed_crossbow_physics(
        range_m=200, condition_pct=100, fit_crew=3, active_weapons=1, crew_control=250
    )
    assert long["impact_index"] < close["impact_index"]
    assert long["penetration_index"] < close["penetration_index"]
    assert damaged["impact_index"] < close["impact_index"]
    assert damaged["penetration_index"] < close["penetration_index"]
    assert uncrewed["legal"] is False
    assert uncrewed["reason"] == "insufficient_fit_crew"


def test_fortress_fire_consumes_exact_bolts_and_cannot_fire_without_ammunition():
    root = Path(__file__).resolve().parents[2]
    runtime = _FakeFortress(root, bolts=5)
    record = runtime._siege_prepare_fortress_artillery(
        {"site_ref": "loc_test"}, defender_refs=["formation_defender"], attacker_refs=["formation_attacker"], battle_hours=1, at="test"
    )
    bed = record["bed_crossbow_fire"]
    assert bed["active_weapons"] == 2
    assert bed["possible_releases"] > 5
    assert bed["releases_fired"] == 5
    assert record["ammunition_consumed"]["war_bolts"] == 5
    assert runtime.depot["stocks"]["war_bolts"] == 0
    assert bed["contact_profile"]["shots_fired"] == 5

    empty = _FakeFortress(root, bolts=0)
    empty_record = empty._siege_prepare_fortress_artillery(
        {"site_ref": "loc_test"}, defender_refs=["formation_defender"], attacker_refs=["formation_attacker"], battle_hours=1, at="test"
    )
    assert empty_record["bed_crossbow_fire"]["releases_fired"] == 0
    assert empty_record["bed_crossbow_fire"]["contact_profile"]["estimated_contacts"] == 0.0
    assert empty_record["defender_power_factor_milli"] == 1000


def test_fortress_fire_crew_skill_changes_cycle_not_launch_energy():
    root = Path(__file__).resolve().parents[2]
    low = _FakeFortress(root, bolts=10000, crew_control=50)._siege_prepare_fortress_artillery(
        {"site_ref": "loc_test"}, defender_refs=["d"], attacker_refs=["a"], battle_hours=1, at="test"
    )["bed_crossbow_fire"]
    high = _FakeFortress(root, bolts=10000, crew_control=250)._siege_prepare_fortress_artillery(
        {"site_ref": "loc_test"}, defender_refs=["d"], attacker_refs=["a"], battle_hours=1, at="test"
    )["bed_crossbow_fire"]
    assert low["physics"]["impact_index"] == high["physics"]["impact_index"]
    assert low["physics"]["penetration_index"] == high["physics"]["penetration_index"]
    assert high["physics"]["dispersion_radius_m"] < low["physics"]["dispersion_radius_m"]
    assert high["completed_cycles_per_weapon"] >= low["completed_cycles_per_weapon"]
