from __future__ import annotations

import copy

from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.history_store import write_history_index
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime



def _materialized_personnel(force, person_ref):
    value = force.get("materialized_people", {}).get(person_ref, 0)
    return int(value.get("personnel", 1)) if isinstance(value, dict) else int(value)

def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def _synthetic_civilian_aspirant(person):
    """Return a test-only living aspirant without rewinding current campaign truth."""
    aspirant = copy.deepcopy(dict(person))
    aspirant["life_status"] = "active"
    aspirant.pop("death_reason", None)
    aspirant["goal_state"] = {
        "primary": "enter the world of generals through lawful Qin military service",
        "current_goals": ["enter the world of generals through lawful Qin military service"],
        "institutional_duties": [],
    }
    aspirant["career_state"] = {
        "current_professional_path": "martial_aspirant",
        "office_or_command": "No military office; independent martial aspirant",
        "current_assignment_ref": None,
    }
    aspirant["military_rank"] = {"durable": True, "grade": "not_formally_recorded"}
    aspirant.pop("current_formation_id", None)
    aspirant.pop("military_career_state", None)
    activity = copy.deepcopy(aspirant.get("autonomous_activity_state", {}))
    activity["enabled"] = True
    activity["resolved_training_regimen_ref"] = "martial_aspirant"
    aspirant["autonomous_activity_state"] = activity
    contract = copy.deepcopy(aspirant.get("activity_contract", {}))
    contract["autonomous_enabled"] = True
    aspirant["activity_contract"] = contract
    return aspirant


def test_military_career_routing_uses_scheduler_known_people_without_global_scans(campaign):
    planner = _planner(campaign)
    before = copy.deepcopy(planner.read("state/runtime.json"))
    planner._ensure_military_career_routes()
    runtime = planner.read("state/runtime.json")
    military_hosts = [host for host in runtime["hosts"].values() if isinstance(host, dict) and host.get("kind") == "military_career"]
    assert military_hosts
    routed = {ref for host in military_hosts for ref in host.get("routed_person_refs", [])}
    assert "char_ouki" in routed
    assert len(routed) == len(set(routed))
    assert all(
        runtime["metrics"][key] == before["metrics"][key]
        for key in ("global_person_scans", "global_faction_scans", "global_force_scans", "global_house_scans")
    )


def test_commander_dossiers_are_general_and_player_not_special_cased(campaign):
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._settle_person_career("char_ouki", at)
    planner._settle_person_career("char_tang_wei", at)
    network = planner.read("state/military/career-network/index.json")
    assert "char_ouki" in network["commanders"]
    assert "char_tang_wei" in network["commanders"]
    ouki = planner.read(network["commanders"]["char_ouki"])
    wei = planner.read(network["commanders"]["char_tang_wei"])
    assert ouki["schema"] == wei["schema"] == "sword-commander-career-dossier"
    assert ouki["authority"] is False and wei["authority"] is False
    player = planner.read("state/player.json")
    assert not player.get("military_career_state", {}).get("active_petition_refs")


def test_transfer_interest_creates_petition_and_never_teleports_officer(campaign):
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    path, original = planner._exact_person("char_ouki", active=False)
    person = copy.deepcopy(dict(original))
    before_location = person.get("current_location", person.get("location"))
    before_formation = person.get("current_formation_id")
    petition_ref = planner._create_petition(
        person,
        state_ref="state_qin",
        desired_commander_ref="char_tang_wei",
        request_kind="campaign_attachment",
        attraction_milli=900,
        evidence_refs=[],
        at=at,
    )
    assert petition_ref
    planner.put(path, person)
    petition = planner.read(planner._petition_path(petition_ref))
    assert petition["status"] == "submitted"
    after = planner.read(path)
    assert after.get("current_location", after.get("location")) == before_location
    assert after.get("current_formation_id") == before_formation

    review_at = str(CampaignTime.parse(at).add_days(15))
    planner._settle_petitions("state_qin", review_at)
    petition = planner.read(planner._petition_path(petition_ref))
    assert petition["status"] == "awaiting_commander_response"
    assert petition["institutional_decision"] == "approved_subject_to_prospective_commander_response"
    assert get_causal_event(planner, petition["delivered_event_ref"])["target_ref"] == "char_tang_wei"
    after_review = planner.read(path)
    assert after_review.get("current_formation_id") == before_formation


def test_resolved_petition_reference_does_not_permanently_latch_officer(campaign):
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    path, original = planner._exact_person("char_ouki", active=False)
    person = copy.deepcopy(dict(original))
    petition_ref = planner._create_petition(
        person,
        state_ref="state_qin",
        desired_commander_ref="char_tang_wei",
        request_kind="campaign_attachment",
        attraction_milli=900,
        evidence_refs=[],
        at=at,
    )
    assert petition_ref
    planner.put(path, person)
    petition_path = planner._petition_path(petition_ref)
    petition = copy.deepcopy(planner.read(petition_path))
    petition["status"] = "rejected"
    planner.put(petition_path, petition)
    persisted = planner.read(path)
    assert petition_ref in persisted["military_career_state"]["active_petition_refs"]
    assert planner._active_petition_refs(persisted) == []


def test_cross_state_service_is_not_treated_as_ordinary_transfer(campaign):
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    network = planner._career_network()
    dossier_path = "state/military/career-network/commanders/char_test_zhao_general.json"
    planner.put(dossier_path, {
        "schema": "sword-commander-career-dossier",
        "authority": False,
        "commander_ref": "char_test_zhao_general",
        "state_ref": "state_zhao",
        "formation_ref": None,
        "command_scale": 10000,
        "public_reputation_milli": 900,
        "institutional_reputation_milli": 900,
        "casualty_stewardship_milli": 800,
        "logistics_reliability_milli": 800,
        "promotion_opportunity_milli": 800,
        "political_risk_milli": 200,
        "evidence_refs": [],
        "published_at": at,
        "public_summary": "A distinguished Zhao general.",
    })
    network.setdefault("commanders", {})["char_test_zhao_general"] = dossier_path
    planner.put("state/military/career-network/index.json", network)

    person_path, original = planner._exact_person("char_ouki", active=False)
    person = copy.deepcopy(dict(original))
    person["military_loyalty_state"] = {
        "schema": "sword-named-military-loyalty",
        "state_ref": "state_qin",
        "state_allegiance_milli": 900,
        "institutional_professional_milli": 900,
        "formation_bond_milli": 500,
        "legitimacy_belief_milli": 800,
        "commander_bonds": {},
        "house_patron_bonds": {},
        "resentment_by_person": {},
        "recent_memory": [],
    }
    petition_ref = planner._create_petition(
        person,
        state_ref="state_qin",
        desired_commander_ref="char_test_zhao_general",
        request_kind="permanent_transfer",
        attraction_milli=900,
        evidence_refs=[],
        at=at,
    )
    assert petition_ref
    planner.put(person_path, person)
    review_at = str(CampaignTime.parse(at).add_days(15))
    planner._settle_petitions("state_qin", review_at)
    petition = planner.read(planner._petition_path(petition_ref))
    assert petition["request_kind"] == "foreign_service_request"
    assert petition["desired_state_ref"] == "state_zhao"
    assert petition["attraction_milli"] == 540
    assert planner.read(person_path).get("state") == original.get("state")


def test_formation_loyalty_is_cohort_scale_and_preserves_ownership_and_manpower(campaign):
    planner = _planner(campaign)
    path, original = planner._load_formation("formation_black_banner_01a")
    formation = copy.deepcopy(dict(original))
    before_personnel = int(formation["personnel"])
    before_owner = formation["administrative_owner"]
    formation["commander_ref"] = "char_ouki"
    planner.put(path, formation)
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._update_formation_loyalty("formation_black_banner_01a", at)
    settled = planner.read(path)
    loyalty = settled["military_loyalty_state"]
    assert loyalty["schema"] == "sword-formation-loyalty"
    assert "commander_bonds" in loyalty and "char_ouki" in loyalty["commander_bonds"]
    assert "state_allegiance" in loyalty["axes"]
    assert "formation_identity" in loyalty["axes"]
    assert "allegiance_distribution" in loyalty
    assert int(settled["personnel"]) == before_personnel
    assert settled["administrative_owner"] == before_owner
    assert "soldiers" not in loyalty


def test_causal_battle_memory_changes_loyalty_without_changing_manpower(campaign):
    planner = _planner(campaign)
    path, original = planner._load_formation("formation_black_banner_01a")
    formation = copy.deepcopy(dict(original))
    formation["commander_ref"] = "char_ouki"
    planner.put(path, formation)
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._update_formation_loyalty("formation_black_banner_01a", at)
    before = copy.deepcopy(planner.read(path))
    before_loyalty = before["military_loyalty_state"]
    before_bond = int(before_loyalty["commander_bonds"]["char_ouki"])
    before_disaffection = int(before_loyalty["axes"]["disaffection"])

    history = copy.deepcopy(planner.read("state/history/events/index.json"))
    history["events"].append({
        "at": at,
        "event_id": "event_test_loyalty_catastrophic_loss",
        "kind": "battle_result",
        "summary": "formation_black_banner_01a suffered catastrophic mass casualty losses after being sacrificed in a failed withdrawal.",
    })
    write_history_index(planner, history)
    planner._update_formation_loyalty("formation_black_banner_01a", at)
    after = planner.read(path)
    after_loyalty = after["military_loyalty_state"]
    assert int(after_loyalty["commander_bonds"]["char_ouki"]) < before_bond
    assert int(after_loyalty["axes"]["disaffection"]) > before_disaffection
    assert any(row.get("event_ref") == "event_test_loyalty_catastrophic_loss" for row in after_loyalty["recent_memory"])
    assert after["personnel"] == before["personnel"]
    assert after["administrative_owner"] == before["administrative_owner"]
    assert after["owner_force_ref"] == before["owner_force_ref"]


def test_crisis_allegiance_uses_immediate_officers_and_never_changes_ownership(campaign):
    planner = _planner(campaign)
    path, original = planner._load_formation("formation_black_banner_01a")
    formation = copy.deepcopy(dict(original))
    formation["commander_ref"] = "char_ouki"
    planner.put(path, formation)
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._update_formation_loyalty("formation_black_banner_01a", at)
    before = copy.deepcopy(planner.read(path))
    low = planner.evaluate_formation_allegiance(
        "formation_black_banner_01a",
        proposed_commander_ref="char_ouki",
        order_legitimacy_milli=150,
        immediate_officer_support_milli=100,
    )
    high = planner.evaluate_formation_allegiance(
        "formation_black_banner_01a",
        proposed_commander_ref="char_ouki",
        order_legitimacy_milli=150,
        immediate_officer_support_milli=900,
    )
    assert high["follow_proposed_commander_milli"] > low["follow_proposed_commander_milli"]
    assert high["administrative_ownership_changed"] == 0
    after = planner.read(path)
    assert after["administrative_owner"] == before["administrative_owner"]
    assert after["owner_force_ref"] == before["owner_force_ref"]
    assert after["personnel"] == before["personnel"]


def test_independent_command_pressure_is_reachable_for_elite_officers(campaign):
    planner = _planner(campaign)
    _path, ouki = planner._exact_person("char_ouki", active=False)
    prefs = planner._career_preferences(ouki)
    threshold = int(planner._military_rules()["career_review"]["independence_threshold_milli"])
    assert prefs["independence"] >= threshold


def test_service_entry_classifier_covers_combatant_and_staff_aspirants_without_recruiting_officials(campaign):
    from sword_runtime.military_career_loyalty import _service_entry_track

    planner = _planner(campaign)
    tracks = {}
    for ref in ("char_shin", "char_hyou", "char_karyoten", "char_kyoukai", "char_ouki", "char_ei_sei", "char_ri_shi"):
        _path, person = planner._exact_person(ref, active=False)
        tracks[ref] = _service_entry_track(person)

    # Current Hyou is dead and therefore cannot be recruited. Shin, Karyoten
    # and Kyoukai are already serving commanders/staff and likewise cannot be
    # recruited a second time. A synthetic living civilian copy below exercises
    # the generic aspirant classifier without rewinding campaign truth.
    assert tracks["char_hyou"] is None
    assert tracks["char_shin"] is None
    assert tracks["char_karyoten"] is None
    assert tracks["char_kyoukai"] is None
    assert tracks["char_ouki"] is None
    assert tracks["char_ei_sei"] is None
    assert tracks["char_ri_shi"] is None

    # Exercise the staff branch with a controlled civilian copy rather than
    # rewinding Karyoten's authoritative current command state.
    _path, hyou = planner._exact_person("char_hyou", active=False)
    combat_aspirant = _synthetic_civilian_aspirant(hyou)
    assert _service_entry_track(combat_aspirant) == "combatant"
    staff_aspirant = _synthetic_civilian_aspirant(hyou)
    staff_aspirant["goal_state"] = {"primary": "Become a strategist through disciplined study"}
    staff_aspirant["career_state"] = {
        "current_professional_path": "strategic_apprentice",
        "office_or_command": "No military office; independent strategic apprentice",
        "current_assignment_ref": None,
    }
    activity = copy.deepcopy(staff_aspirant.get("autonomous_activity_state", {}))
    activity["resolved_training_regimen_ref"] = "strategic_apprentice"
    staff_aspirant["autonomous_activity_state"] = activity
    assert _service_entry_track(staff_aspirant) == "staff"


def test_independent_service_entry_uses_current_local_state_control_and_requires_exact_location(campaign):
    planner = _planner(campaign)
    hyou_path, original = planner._exact_person("char_hyou", active=False)

    located = _synthetic_civilian_aspirant(original)
    located["state"] = "Independent"
    located["current_location"] = "loc_qin_eastern_depot"
    located.pop("location", None)
    assert planner._service_entry_target_state(located) == "state_qin"

    unlocated = copy.deepcopy(located)
    unlocated.pop("current_location", None)
    unlocated.pop("location", None)
    assert planner._service_entry_target_state(unlocated) is None

    # Settle the same civilian aspirant without exact location. Career review
    # may record interest, but it must not create a petition or teleport him
    # into state service without a physical/state access path.
    planner.put(hyou_path, unlocated)
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._settle_person_career("char_hyou", at)
    _path, after = planner._exact_person("char_hyou", active=False)
    interest = after["military_career_state"]["service_entry_interest"]
    assert interest["track"] == "combatant"
    assert interest["status"] == "awaiting_exact_location_or_state_access"
    assert not after["military_career_state"].get("active_petition_refs")


def test_staff_service_entry_reclassifies_one_conserved_body_without_granting_command(campaign):
    planner = _planner(campaign)
    aspirant_path, original = planner._exact_person("char_hyou", active=False)
    aspirant = _synthetic_civilian_aspirant(original)
    aspirant["goal_state"] = {"primary": "Become a strategist through disciplined study"}
    aspirant["career_state"] = {
        "current_professional_path": "strategic_apprentice",
        "office_or_command": "No military office; independent strategic apprentice",
        "current_assignment_ref": None,
    }
    activity = copy.deepcopy(aspirant.get("autonomous_activity_state", {}))
    activity["resolved_training_regimen_ref"] = "strategic_apprentice"
    aspirant["autonomous_activity_state"] = activity
    planner.put(aspirant_path, aspirant)

    at = str(planner.read("state/runtime.json")["world_time"])
    planner._settle_person_career("char_hyou", at)
    _path, aspirant = planner._exact_person("char_hyou", active=False)
    petition_ref = aspirant["military_career_state"]["active_petition_refs"][0]
    petition_path = planner._petition_path(petition_ref)
    petition = copy.deepcopy(planner.read(petition_path))
    assert petition["state_ref"] == "state_qin"
    assert petition["service_entry_track"] == "staff"

    population_before = copy.deepcopy(planner.read("state/population/qin.json"))
    force_before = copy.deepcopy(planner.read(planner.owner_path("force_state_qin")))
    total_before = int(population_before["population_total"])
    household_before = int(population_before["strata"]["household_and_service"])
    active_before = int(population_before["strata"]["active_military"])
    force_headcount_before = int(force_before["headcount"])

    petition["status"] = "authorized_handoff"
    planner.put(petition_path, petition)
    planner._execute_authorized_petition(petition_ref, at)

    population_after = planner.read("state/population/qin.json")
    force_after = planner.read(planner.owner_path("force_state_qin"))
    _path, aspirant_after = planner._exact_person("char_hyou", active=False)
    petition_after = planner.read(petition_path)
    assert int(population_after["population_total"]) == total_before
    assert int(population_after["strata"]["household_and_service"]) == household_before - 1
    assert int(population_after["strata"]["active_military"]) == active_before + 1
    assert int(force_after["headcount"]) == force_headcount_before + 1
    assert _materialized_personnel(force_after, "char_hyou") == 1
    assert aspirant_after["career_state"]["current_professional_path"] == "state_military_staff_candidate"
    assert "no command appointment" in aspirant_after["career_state"]["office_or_command"].lower()
    assert aspirant_after["military_rank"]["grade"] == "recruit"
    assert petition_after["status"] == "completed"
    assert petition_after["source_stratum"] == "household_and_service"


def test_combatant_service_entry_posts_same_conserved_recruit_to_real_formation(campaign):
    planner = _planner(campaign)
    aspirant_path, original = planner._exact_person("char_hyou", active=False)
    planner.put(aspirant_path, _synthetic_civilian_aspirant(original))
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._settle_person_career("char_hyou", at)
    _path, aspirant = planner._exact_person("char_hyou", active=False)
    petition_ref = aspirant["military_career_state"]["active_petition_refs"][0]
    petition_path = planner._petition_path(petition_ref)
    petition = copy.deepcopy(planner.read(petition_path))
    assert petition["service_entry_track"] == "combatant"
    petition["status"] = "authorized_handoff"
    planner.put(petition_path, petition)
    planner._execute_authorized_petition(petition_ref, at)
    petition = planner.read(petition_path)
    _path, entered = planner._exact_person("char_hyou", active=False)
    assert entered["military_rank"]["grade"] == "recruit"
    assert entered["population_provenance"]["service_stratum"] == "active_military"
    assert petition["execution_status"] in {"entered_state_military_awaiting_initial_posting", "entered_state_military_reserve"}
    if petition["execution_status"] == "entered_state_military_awaiting_initial_posting":
        order_ref = petition["initial_posting_order_ref"]
        order = planner.read(planner.owner_path(order_ref))
        assert order["officer_ref"] == "char_hyou"
        assert order["request_kind"] == "initial_posting"
        assert order["included_in_force_headcount"] is True
        assert order["source_force_ref"] == order["target_force_ref"] == "force_state_qin"
        planner._settle_transfer_order({"owner_ref": order_ref}, order["arrives_at"])
        _path, posted = planner._exact_person("char_hyou", active=False)
        assert posted.get("current_formation_id") == order["target_formation_ref"]
        force = planner.read(planner.owner_path("force_state_qin"))
        assert _materialized_personnel(force, "char_hyou") == 1


def test_exact_officer_petition_repairs_missing_pending_route_before_settlement(campaign):
    planner = _planner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    person_path, original = planner._exact_person("char_ouki", active=False)
    person = copy.deepcopy(dict(original))
    petition_ref = planner._create_petition(
        person,
        state_ref="state_qin",
        desired_commander_ref="char_tang_wei",
        request_kind="campaign_attachment",
        attraction_milli=900,
        evidence_refs=[],
        at=at,
    )
    assert petition_ref
    planner.put(person_path, person)

    index = copy.deepcopy(planner.read("state/military/career-petitions/index.json"))
    rows = index.setdefault("pending_by_state", {}).setdefault("state_qin", [])
    index["pending_by_state"]["state_qin"] = [ref for ref in rows if ref != petition_ref]
    planner.put("state/military/career-petitions/index.json", index)

    review_at = str(CampaignTime.parse(at).add_days(15))
    planner._settle_petitions("state_qin", review_at)
    petition = planner.read(planner._petition_path(petition_ref))
    assert petition["status"] == "awaiting_commander_response"
    repaired = planner.read("state/military/career-petitions/index.json")
    assert petition_ref in repaired["pending_by_state"]["state_qin"]
