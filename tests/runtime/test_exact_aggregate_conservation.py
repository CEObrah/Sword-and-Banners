from __future__ import annotations

import json
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

    owner_index = _read_json(campaign, "state/index/owner-index-gold.json")["owners"]
    assert person_ref in owner_index
    exact = _read_json(campaign, owner_index[person_ref])
    assert exact["owner_id"] == person_ref
    assert exact["schema"] == "sword-materialized-person"

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
