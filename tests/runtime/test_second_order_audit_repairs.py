import json
from pathlib import Path

import pytest

from conftest import SOURCE, execute, execute_internal
from sword_runtime.engine import (
    _append_bounded,
    _append_recent_unique_string,
    _compact_hot_state_value,
    _compact_project_rows,
)
from sword_runtime.mercenary_contracts import (
    compact_mercenary_contracts,
    mercenary_has_live_contract,
    mercenary_next_due,
)
from sword_runtime.prisoner_system import PrisonerSystemMixin


def _mercenary_rows(root: Path):
    for path in (root / "state/merc").rglob("*.json"):
        row = json.load(open(path))
        if row.get("schema") in {"mercenary", "mercenary-company", "regional-mercenary-company"} and isinstance(row.get("owner_id"), str):
            yield path, row


def test_live_accounting_mercenary_contracts_are_causally_routed(campaign):
    runtime = json.load(open(campaign / "state/runtime.json"))
    hosts = {
        str(host.get("owner_ref")): host
        for host in runtime["hosts"].values()
        if host.get("kind") == "mercenary"
    }
    live = {}
    cold = set()
    for _path, row in _mercenary_rows(campaign):
        ref = str(row["owner_id"])
        if mercenary_has_live_contract(row):
            live[ref] = row
        elif bool(row.get("accounting_only")):
            cold.add(ref)
    assert len(live) == 62
    assert set(hosts) == set(live)
    assert set(hosts).isdisjoint(cold)
    for ref, row in live.items():
        assert hosts[ref]["next_due"] == str(mercenary_next_due(row, runtime["world_time"]))


def test_direct_mercenary_offer_creates_route_and_rejects_overlap(campaign):
    ref = next(
        str(row["owner_id"])
        for _path, row in _mercenary_rows(campaign)
        if bool(row.get("accounting_only")) and row.get("status") == "available" and not mercenary_has_live_contract(row)
    )
    result = execute(campaign, "mercenary_contract", {
        "mercenary_ref": ref,
        "action": "offer",
        "contract_ref": "contract.audit.offer.1",
        "amount_silver": 250000,
        "term_days": 90,
    }).receipt.result
    assert result["status"] == "offered"
    runtime = json.load(open(campaign / "state/runtime.json"))
    routed = [host for host in runtime["hosts"].values() if host.get("kind") == "mercenary" and host.get("owner_ref") == ref]
    assert len(routed) == 1
    with pytest.raises(ValueError, match="already has a live contract obligation"):
        execute(campaign, "mercenary_contract", {
            "mercenary_ref": ref,
            "action": "offer",
            "contract_ref": "contract.audit.offer.2",
            "amount_silver": 250000,
            "term_days": 90,
        })


def test_mercenary_contract_compaction_never_drops_live_obligations():
    rows = [{"contract_ref": f"done.{i}", "status": "completed"} for i in range(50)]
    rows.insert(3, {"contract_ref": "live.offer", "status": "offered"})
    rows.insert(8, {"contract_ref": "live.active", "status": "active"})
    compacted = compact_mercenary_contracts(rows)
    refs = {row["contract_ref"] for row in compacted}
    assert {"live.offer", "live.active"}.issubset(refs)
    assert len(compacted) == 34


def test_prisoner_history_is_bounded():
    group = {"history": []}
    for i in range(90):
        PrisonerSystemMixin._custody_record_history(group, {"at": str(i), "kind": "audit"})
    assert len(group["history"]) == 64
    assert group["history"][0]["at"] == "26"


def test_generic_strategic_history_helper_is_bounded():
    record = {"history": []}
    for i in range(60):
        _append_bounded(record, "history", {"at": i, "event": "audit"}, limit=32)
    assert len(record["history"]) == 32
    assert record["history"][0]["at"] == 28




def test_terminal_projects_are_bounded_but_active_obligations_are_preserved():
    rows = [
        {"project_ref": f"done.{i}", "status": "completed", "resolved_at": str(i)}
        for i in range(40)
    ]
    rows.insert(5, {"project_ref": "active.1", "status": "active"})
    rows.insert(17, {"project_ref": "scheduled.1", "status": "scheduled"})
    compacted = _compact_project_rows(rows, terminal_limit=16)
    refs = [row["project_ref"] for row in compacted]
    assert "active.1" in refs
    assert "scheduled.1" in refs
    assert len([row for row in compacted if row.get("status") == "completed"]) == 16
    assert "done.39" in refs
    assert "done.0" not in refs


def test_house_and_institution_hot_state_drop_explanatory_project_prose():
    owner = {
        "schema": "sword-institution",
        "owner_id": "inst.audit",
        "projects": [
            {"project_ref": f"done.{i}", "status": "completed", "resolution_basis": "debug explanation"}
            for i in range(25)
        ] + [{"project_ref": "active.1", "status": "active", "cancellation_basis": "should also disappear"}],
    }
    compacted = _compact_hot_state_value(owner)
    assert len(compacted["projects"]) == 17
    assert any(row["project_ref"] == "active.1" for row in compacted["projects"])
    assert all("resolution_basis" not in row and "cancellation_basis" not in row for row in compacted["projects"])


def test_repeated_strategic_goals_are_unique_and_bounded():
    owner = {"strategic_goals": []}
    for i in range(30):
        _append_recent_unique_string(owner, "strategic_goals", f"goal.{i}", limit=16)
    _append_recent_unique_string(owner, "strategic_goals", "goal.20", limit=16)
    assert len(owner["strategic_goals"]) == 16
    assert owner["strategic_goals"][-1] == "goal.20"
    assert owner["strategic_goals"].count("goal.20") == 1
    assert "goal.0" not in owner["strategic_goals"]


def test_duplicate_career_affiliation_add_is_rejected(campaign):
    execute_internal(campaign, "career_event", {
        "person_ref": "char_tang_wei",
        "kind": "affiliation_add",
        "affiliation_ref": "faction_audit_affiliation",
    })
    with pytest.raises(ValueError, match="affiliation is already active"):
        execute_internal(campaign, "career_event", {
            "person_ref": "char_tang_wei",
            "kind": "affiliation_add",
            "affiliation_ref": "faction_audit_affiliation",
        })


def test_combat_training_isolation_does_not_recreate_aggregate_unit_command_for_named_commander():
    from copy import deepcopy
    from sword_runtime.engine import RepositoryCommandPlanner
    from sword_runtime.cohort_personnel import ensure_formation_composition, validate_cohort_ledger

    planner = RepositoryCommandPlanner(SOURCE)
    formation_ref = "formation_qin_mou_gou_central"
    _path, formation0 = planner._load_formation(formation_ref)
    formation = deepcopy(formation0)
    force = deepcopy(planner.read(planner.owner_path(str(formation["owner_force_ref"]))))
    ensure_formation_composition(force, formation)
    validate_cohort_ledger(force)

    cohorts = force["cohort_ledger"]["cohorts"]
    before_external = sum(
        int(cohort.get("allocated_external_by_formation", {}).get(formation_ref, 0))
        for cohort in cohorts.values()
    )
    # Current 500+ formations use an exact named commander as the external
    # Unit-command billet, so there must be no duplicate aggregate command body.
    assert formation.get("commander_ref")
    assert before_external == 0

    planner._ct_isolate_training(force, formation, "audit.combat.isolation")
    validate_cohort_ledger(force)

    cohorts = force["cohort_ledger"]["cohorts"]
    after_external = sum(
        int(cohort.get("allocated_external_by_formation", {}).get(formation_ref, 0))
        for cohort in cohorts.values()
    )
    assert after_external == before_external
    for row in formation["cohort_composition"]:
        cohort = cohorts[row["cohort_id"]]
        assert "development_branches" not in cohort
        if row["cohort_id"] not in {item["cohort_id"] for item in formation0.get("cohort_composition", [])}:
            assert not cohort.get("allocated_external_by_formation")
