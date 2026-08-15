from __future__ import annotations

import json
import pytest
from pathlib import Path

from sword_runtime.commands import CommandEnvelope
from sword_runtime.engine import RepositoryCommandPlanner, SwordRuntime


def _read_json(root: Path, path: str):
    return json.loads((root / path).read_text(encoding="utf-8"))


def _execute_materialize(
    root: Path,
    *,
    state: str,
    role: str,
    person_ref: str,
    request_id: str,
) -> None:
    meta = _read_json(root, "state/meta.json")
    command = CommandEnvelope(
        campaign_id=str(meta["campaign_id"]),
        request_id=request_id,
        actor_id=RepositoryCommandPlanner.INTERNAL_ACTOR,
        command_type="person_materialize",
        expected_revision=int(meta["revision"]),
        submitted_at=str(meta["time"]),
        payload={
            "state": state,
            "person_ref": person_ref,
            "name": "Exact Aggregate Conservation Fixture",
            "role": role,
        },
        mode="autonomous",
    )
    SwordRuntime(root).execute(command)


def test_materialized_person_reclassifies_one_existing_force_slot(campaign: Path) -> None:
    """Exact identity and aggregate personnel remain one conserved person.

    The test derives an available state/role from the evolving campaign instead
    of assuming today's Qin counts or revision. Materialization consumes one
    anonymous available slot while total force headcount stays constant. An
    idempotent materialization of the same exact identity must not consume a
    second aggregate slot.
    """

    selected = None
    for state in ("qin", "zhao", "wei", "chu", "yan", "han", "qi"):
        path = f"state/forces/state-{state}.json"
        force = _read_json(campaign, path)
        source = str(force.get("source_location_ref", ""))
        local = force.get("available_by_location", {}).get(source, {})
        for role, count in sorted(force.get("available_by_role", {}).items()):
            if int(count) > 0 and int(local.get(role, 0)) > 0:
                selected = (state, role, path)
                break
        if selected is not None:
            break

    assert selected is not None, "campaign must expose at least one conserved available state-force slot"
    state, role, force_path = selected
    before = _read_json(campaign, force_path)
    person_ref = "char_test_exact_aggregate_conservation"

    _execute_materialize(
        campaign,
        state=state,
        role=role,
        person_ref=person_ref,
        request_id="test.exact-aggregate.materialize.first",
    )

    after_first = _read_json(campaign, force_path)
    assert int(after_first["headcount"]) == int(before["headcount"])
    assert int(after_first["available_by_role"][role]) == int(before["available_by_role"][role]) - 1
    source = str(before["source_location_ref"])
    assert int(after_first["available_by_location"][source][role]) == int(before["available_by_location"][source][role]) - 1
    assert int(after_first.get("materialized_people", {}).get(person_ref, 0)) == 1

    owner_index = _read_json(campaign, "state/index/owner-index.json")["owners"]
    assert person_ref in owner_index
    exact = _read_json(campaign, owner_index[person_ref])
    assert exact["owner_id"] == person_ref
    assert exact["schema"] == "sword-materialized-person"

    with pytest.raises(ValueError, match="person_ref already exists"):
        _execute_materialize(
            campaign,
            state=state,
            role=role,
            person_ref=person_ref,
            request_id="test.exact-aggregate.materialize.repeat",
        )

    after_repeat = _read_json(campaign, force_path)
    assert int(after_repeat["headcount"]) == int(after_first["headcount"])
    assert int(after_repeat["available_by_role"][role]) == int(after_first["available_by_role"][role])
    assert int(after_repeat["available_by_location"][source][role]) == int(after_first["available_by_location"][source][role])
    assert int(after_repeat.get("materialized_people", {}).get(person_ref, 0)) == 1


def test_wei_personal_recruitment_is_cohort_first_and_selective_materialization_conserves_population(campaign: Path) -> None:
    """Wei's scalable personal force recruits cohorts; standouts materialize later."""
    from conftest import execute_internal

    before_pop = _read_json(campaign, "state/population/qin.json")
    before_force = _read_json(campaign, "state/forces/tang-wei-personal.json")
    campaign_ref = "recruitment.test.wei.first"

    started = execute_internal(campaign, "recruitment_campaign_start", {
        "state": "qin", "campaign_ref": campaign_ref, "applicant_count": 120,
        "destination_force_ref": "force_tang_wei_personal", "role": "household_retainer",
        "location_ref": "loc_tang_manor_garrison_yard",
    })
    assert started.receipt.result["applicants"] == 120
    execute_internal(campaign, "recruitment_campaign_stage", {
        "campaign_ref": campaign_ref, "selection_profile": "wei_basic_eligibility", "retain_count": 60,
    })
    execute_internal(campaign, "recruitment_campaign_stage", {
        "campaign_ref": campaign_ref, "selection_profile": "wei_final_retainer_screen", "retain_count": 20,
    })
    execute_internal(campaign, "recruitment_campaign_train", {"campaign_ref": campaign_ref, "hours": 12})
    finalized = execute_internal(campaign, "recruitment_campaign_finalize", {"campaign_ref": campaign_ref})
    assert finalized.receipt.result["accepted"] == 20

    after_recruit_pop = _read_json(campaign, "state/population/qin.json")
    after_recruit_force = _read_json(campaign, "state/forces/tang-wei-personal.json")
    assert int(after_recruit_pop["population_total"]) == int(before_pop["population_total"])
    assert int(after_recruit_pop["strata"]["private_household_military"]) == int(before_pop["strata"]["private_household_military"]) + 20
    assert int(after_recruit_pop["strata"].get("recruitment_candidates_reserved", 0)) == 0
    assert int(after_recruit_force["headcount"]) == int(before_force["headcount"]) + 20
    assert int(after_recruit_force["available_by_role"]["household_retainer"]) == int(before_force["available_by_role"]["household_retainer"]) + 20
    assert not after_recruit_force.get("materialized_people")

    person_ref = "char_test_wei_personal_standout"
    execute_internal(campaign, "person_materialize", {
        "state": "qin", "person_ref": person_ref, "name": "Personal Retainer Standout",
        "personal_force_ref": "force_tang_wei_personal", "role": "household_retainer",
        "representation": "person_lite", "source_location_ref": "loc_tang_manor_garrison_yard",
    })
    after_person_pop = _read_json(campaign, "state/population/qin.json")
    after_person_force = _read_json(campaign, "state/forces/tang-wei-personal.json")
    assert after_person_pop == after_recruit_pop, "materialization reclassifies an existing soldier; it cannot create another body"
    assert int(after_person_force["headcount"]) == int(after_recruit_force["headcount"])
    assert int(after_person_force["available_by_role"]["household_retainer"]) == int(after_recruit_force["available_by_role"]["household_retainer"]) - 1
    assert int(after_person_force.get("materialized_people", {}).get(person_ref, 0)) == 1
    owner_index = _read_json(campaign, "state/index/owner-index.json")["owners"]
    person = _read_json(campaign, owner_index[person_ref])
    assert person["schema"] == "person-lite"
    assert person.get("source_cohort_ref")
    assert len(person["stats"]["attributes"]) == 9
    assert len(person["stats"]["skills"]) == 35



def test_large_wei_recruitment_campaign_selects_thousands_to_three_hundred_without_individualizing(campaign: Path) -> None:
    from conftest import execute_internal

    before_pop = _read_json(campaign, "state/population/qin.json")
    before_force = _read_json(campaign, "state/forces/tang-wei-personal.json")
    before_treasury = _read_json(campaign, "state/treasury/treasury-house-tang.json")
    ref = "recruitment.test.wei.large.release"
    started = execute_internal(campaign, "recruitment_campaign_start", {
        "state":"qin", "campaign_ref":ref, "applicant_count":5000,
        "destination_force_ref":"force_tang_wei_personal", "role":"household_retainer",
        "location_ref":"loc_tang_manor_garrison_yard",
    })
    assert started.receipt.result["applicants"] == 5000
    execute_internal(campaign, "recruitment_campaign_stage", {
        "campaign_ref":ref, "selection_profile":"wei_basic_eligibility", "retain_count":1800,
    })
    execute_internal(campaign, "recruitment_campaign_stage", {
        "campaign_ref":ref, "selection_profile":"wei_physical_trial", "retain_count":800,
    })
    execute_internal(campaign, "recruitment_campaign_stage", {
        "campaign_ref":ref, "selection_profile":"wei_final_retainer_screen", "retain_count":300,
    })
    execute_internal(campaign, "recruitment_campaign_train", {"campaign_ref":ref, "hours":24})
    final = execute_internal(campaign, "recruitment_campaign_finalize", {"campaign_ref":ref})
    assert final.receipt.result["accepted"] == 300

    after_pop = _read_json(campaign, "state/population/qin.json")
    after_force = _read_json(campaign, "state/forces/tang-wei-personal.json")
    after_treasury = _read_json(campaign, "state/treasury/treasury-house-tang.json")
    registry = _read_json(campaign, "state/recruitment/candidate-pools.json")
    campaign = registry["campaigns"][ref]

    assert int(after_pop["population_total"]) == int(before_pop["population_total"])
    assert int(after_pop["strata"].get("recruitment_candidates_reserved", 0)) == 0
    assert int(after_pop["strata"]["private_household_military"]) == int(before_pop["strata"]["private_household_military"]) + 300
    assert int(after_force["headcount"]) == int(before_force["headcount"]) + 300
    assert int(after_force["available_by_role"]["household_retainer"]) == int(before_force["available_by_role"]["household_retainer"]) + 300
    assert not after_force.get("materialized_people"), "large recruitment remains cohort-first until an individual is explicitly materialized"
    assert campaign["initial_applicants"] == 5000 and campaign["accepted_count"] == 300
    assert sum(int(s["count"]) for s in campaign["slices"]) == 300
    assert len(campaign["stage_history"]) >= 4
    assert int(after_treasury["silver"]) < int(before_treasury["silver"])
    assert int(after_treasury["food_kg"]) < int(before_treasury["food_kg"])
    assert final.receipt.result["cohort_refs"]
