import copy

from sword_runtime.officer_cadre import (
    ensure_officer_cadre,
    reorganize_officer_cadre,
    settle_aggregate_officer_losses,
    develop_officer_cadre,
    record_officer_cadre_combat_experience,
    officer_cadre_summary,
)


def _formation(n=5000):
    return {
        "personnel": n,
        "command_structure": {
            "internal_hierarchy": {
                "summary": [
                    {"scale":1000,"count":5},
                    {"scale":500,"count":10},
                    {"scale":100,"count":50},
                ]
            }
        },
    }


def test_casualties_do_not_demote_surviving_officer_rank_inventory():
    formation = _formation()
    cadre = ensure_officer_cadre(formation)
    before = copy.deepcopy(cadre["rank_inventory"])
    formation["personnel"] = 1000
    reorganize_officer_cadre(formation, reason="post_battle")
    cadre = officer_cadre_summary(formation)
    assert cadre["rank_inventory"] == before
    assert cadre["active_billets"]["1000_commander"] == 5
    assert cadre["cadre_reserve"]["1000_commander"] == 0
    assert cadre["active_billets"]["500_commander"] == 10
    assert cadre["cadre_reserve"]["500_commander"] == 0
    assert formation["personnel"] == 1000  # establishment remains 5,000; commands are understrength


def test_aggregate_officer_casualties_are_classification_not_extra_deaths():
    formation = _formation()
    ensure_officer_cadre(formation)
    formation["personnel"] = 2500
    losses = settle_aggregate_officer_losses(formation, before_personnel=5000, casualties=2500, seed="officer-test")
    assert sum(losses.values()) <= 2500
    cadre = officer_cadre_summary(formation)
    assert sum(cadre["rank_inventory"].values()) == 65 - sum(losses.values())


def test_reconstitution_reactivates_surviving_cadre_before_creating_new_rank():
    formation = _formation()
    ensure_officer_cadre(formation)
    formation["personnel"] = 1000
    reorganize_officer_cadre(formation)
    formation["personnel"] = 5000
    reorganize_officer_cadre(formation, reason="reconstituted")
    cadre = officer_cadre_summary(formation)
    assert cadre["cadre_reserve"]["1000_commander"] == 0
    assert cadre["active_billets"]["1000_commander"] == 5
    assert cadre["rank_inventory"]["1000_commander"] == 5


def test_verified_training_can_fill_rank_vacancies_without_changing_headcount():
    formation = _formation()
    cadre = ensure_officer_cadre(formation)
    cadre["rank_inventory"]["1000_commander"] -= 1
    reorganize_officer_cadre(formation)
    before = formation["personnel"]
    promoted = develop_officer_cadre(formation, training_hours=120, at="244-BCE-08-01T00:00:00+08:00")
    assert promoted["1000_commander"] == 1
    assert formation["personnel"] == before
    assert officer_cadre_summary(formation)["vacant_billets"]["1000_commander"] == 0


def test_combat_experience_seasons_unit_and_aggregate_officers_without_new_bodies(campaign):
    formation = {
        "formation_ref": "formation_test_combat_cadre",
        "personnel": 1000,
        "authorized_strength": 1000,
        "formation_class": "unit",
        "training_progress": 20,
    }
    before_personnel = formation["personnel"]
    before = ensure_officer_cadre(formation)
    before_inventory = dict(before["rank_inventory"])
    result = record_officer_cadre_combat_experience(
        formation, battle_hours=6.0, contact_fraction=0.8, at="244-BCE-08-01T12:00:00+08:00"
    )
    cadre = ensure_officer_cadre(formation)
    assert formation["personnel"] == before_personnel
    assert sum(cadre["rank_inventory"].values()) >= sum(before_inventory.values())
    assert cadre["verified_combat_exposure_hours"] == result["combat_exposure_hours"]
    assert cadre["field_engagements"] == 1
    assert result["promotion_credit_hours"] > 0
    assert formation["training_progress"] > 20
