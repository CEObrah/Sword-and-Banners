from __future__ import annotations

from sword_runtime.engine import RepositoryCommandPlanner


def test_person_lite_reputation_subject_is_a_person_and_schema_valid(campaign):
    planner = RepositoryCommandPlanner(campaign)
    person_ref = "officer.qin.kankoku.army.chief_of_staff"
    assert planner.owner(person_ref)[1]["schema"] == "person-lite"

    planner._record_reputation_signal(
        person_ref,
        "state_qin",
        1,
        "battle_command",
        "event.person-lite-reputation",
        str(planner.read("state/runtime.json")["world_time"]),
        "focused person-lite reputation regression",
    )

    index = planner._writes["state/reputation/index.json"]
    subject_path = index["subjects"][person_ref]
    subject = planner._writes[subject_path]
    assert subject["subject_type"] == "person"
    planner.schema_validator.validators["reputation-subject"].validate(subject)


def test_non_person_reputation_subject_never_uses_unregistered_organization_type(campaign):
    planner = RepositoryCommandPlanner(campaign)
    planner._record_reputation_signal(
        "state_qin",
        "state_zhao",
        1,
        "political_attention",
        "event.state-reputation",
        str(planner.read("state/runtime.json")["world_time"]),
        "focused state reputation regression",
    )
    index = planner._writes["state/reputation/index.json"]
    subject_path = index["subjects"]["state_qin"]
    subject = planner._writes[subject_path]
    assert subject["subject_type"] in {"faction", "other"}
    assert subject["subject_type"] != "organization"
    planner.schema_validator.validators["reputation-subject"].validate(subject)
