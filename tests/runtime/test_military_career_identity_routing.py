from __future__ import annotations

import copy

from sword_runtime.production_planner import ProductionCampaignPlanner


def test_service_release_score_honors_commander_bond_for_non_char_person_authority(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    officer_ref = "char_han_shou"
    service_ref = "officer.qin.kankoku.army.chief_of_staff"
    officer_path = planner.owner_path(officer_ref)
    officer = copy.deepcopy(planner.read(officer_path))
    loyalty = officer.setdefault("military_loyalty_state", {})
    loyalty.setdefault("commander_bonds", {})[service_ref] = 950
    planner.put(officer_path, officer)

    common = {
        "officer_ref": officer_ref,
        "attraction_milli": 650,
    }
    bonded = planner._service_authority_release_score({**common, "service_authority_ref": service_ref})
    unknown = planner._service_authority_release_score({**common, "service_authority_ref": "object.test.not_a_person"})
    assert bonded < unknown


def test_non_char_person_administrative_owner_remains_a_personal_patron(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    person_ref = "officer.qin.kankoku.army.chief_of_staff"
    path = planner.owner_path(person_ref)
    person = planner.read(path)
    assert person.get("schema") in {"person-lite", "sab_character", "sword-materialized-person"}

    formation = {"administrative_owner": person_ref}
    assert planner._formation_patron_ref(formation) == person_ref
    assert planner._patron_leader_ref(person_ref) == person_ref


def test_non_char_person_force_administrator_is_not_erased_by_identity_spelling(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    person_ref = "officer.qin.kankoku.army.chief_of_staff"
    force_ref = "force_test_non_char_person_admin"
    force_path = "state/forces/test-non-char-person-admin.json"
    planner.put(force_path, {
        "schema": "sword-force",
        "force_ref": force_ref,
        "administrative_owner": person_ref,
        "manpower_pool": 0,
        "cohort_ledger": {"cohorts": {}},
    })
    owner_index = copy.deepcopy(planner.read("state/index/owner-index.json"))
    owner_index.setdefault("owners", {})[force_ref] = force_path
    planner.put("state/index/owner-index.json", owner_index)

    assert planner._formation_patron_ref({"owner_force_ref": force_ref}) == person_ref


def test_stale_career_dossier_route_cannot_substitute_another_commander(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    target_ref = "char_test_career_target"
    decoy_ref = "char_test_career_decoy"
    target_path = "state/military/career-network/commanders/char_test_career_target.json"
    decoy_path = "state/military/career-network/commanders/char_test_career_decoy.json"
    common = {
        "schema": "sword-commander-career-dossier",
        "authority": False,
        "state_ref": "state_qin",
        "formation_ref": None,
        "public_reputation_milli": 500,
        "institutional_reputation_milli": 500,
        "promotion_opportunity_milli": 500,
        "casualty_stewardship_milli": 500,
        "logistics_reliability_milli": 500,
        "political_risk_milli": 200,
        "command_scale": 0,
        "evidence_refs": [],
        "published_at": str(planner._world_time()),
        "public_summary": "routing regression fixture",
    }
    planner.put(target_path, {**common, "commander_ref": target_ref})
    planner.put(decoy_path, {**common, "commander_ref": decoy_ref, "public_reputation_milli": 999})

    network = planner._career_network()
    network.setdefault("commanders", {})[target_ref] = decoy_path
    planner.put("state/military/career-network/index.json", network)

    dossier = planner._career_dossier(target_ref)
    assert dossier is not None
    assert dossier["commander_ref"] == target_ref
    assert dossier["public_reputation_milli"] == 500
