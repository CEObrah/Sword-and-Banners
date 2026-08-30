from sword_runtime.engine import RepositoryCommandPlanner


def test_set_person_location_synchronizes_surviving_aliases():
    person = {
        "schema": "sab_character",
        "owner_id": "char_test",
        "location": "loc_old_canonical",
        "current_location": "loc_old_legacy",
        "location_scope": "legacy_projection",
    }

    RepositoryCommandPlanner._set_person_location(person, "loc_new")

    assert person["location"] == "loc_new"
    assert person["current_location"] == "loc_new"
    assert "location_scope" not in person


def test_set_person_location_preserves_single_alias_shapes():
    canonical = {"location": "loc_old"}
    legacy = {"current_location": "loc_old"}
    empty = {}

    RepositoryCommandPlanner._set_person_location(canonical, "loc_new")
    RepositoryCommandPlanner._set_person_location(legacy, "loc_new")
    RepositoryCommandPlanner._set_person_location(empty, "loc_new")

    assert canonical == {"location": "loc_new"}
    assert legacy == {"current_location": "loc_new"}
    assert empty == {"current_location": "loc_new"}
