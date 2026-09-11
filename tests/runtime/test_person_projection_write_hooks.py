from __future__ import annotations

import copy

from sword_runtime.production_planner import ProductionCampaignPlanner


def test_non_char_full_person_write_and_delete_syncs_location_and_alignment_indexes(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    person_ref = "officer.test.full_projection_hooks"
    person_path = "state/person/full-projection-hooks-test.json"
    person = copy.deepcopy(planner.read(planner.owner_path("char_han_shou")))
    person["owner_id"] = person_ref
    person["id"] = person_ref
    person["name"] = "Full Projection Hook Test"
    person["state"] = "qin"
    person["current_location"] = "loc_sai"

    planner.put(person_path, person)
    planner._register_owner(person_ref, person_path)

    locations = planner.read("state/index/person-location-index.json")
    assert locations["person_location"][person_ref] == "loc_sai"
    alignment = planner.read("state/index/faction-alignment-candidates.json")
    assert alignment["member_state"][person_ref] == "qin"
    assert person_ref in alignment["by_state"]["qin"]["person_refs"]

    person["current_location"] = "loc_kanyou"
    planner.put(person_path, person)
    locations = planner.read("state/index/person-location-index.json")
    assert locations["person_location"][person_ref] == "loc_kanyou"

    planner.delete(person_path)
    locations = planner.read("state/index/person-location-index.json")
    assert person_ref not in locations["person_location"]
    alignment = planner.read("state/index/faction-alignment-candidates.json")
    assert person_ref not in alignment["member_state"]
    assert person_ref not in alignment.get("by_state", {}).get("qin", {}).get("person_refs", [])
