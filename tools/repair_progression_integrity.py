#!/usr/bin/env python3
"""One-shot deterministic named-person progression integrity repair.

The repair is intentionally conservative:
- reconcile all bounded exact command routes and annual life hosts;
- record inherited cohort-development provenance on materialized people without
  re-awarding those cohort hours;
- backfill only exact people whose saved ``completed_cycles`` prove a numerical
  canonical-regimen shortfall;
- never award child/player cycles and never invent historical elapsed time.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from sword_runtime.history_store import write_history_index
from sword_runtime.progression_integrity import exact_activity_shortfall, inherited_training_baseline
from sword_runtime.service_runtime import CommandRoutedProductionPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_instructors import exact_person_drill_access
from sword_runtime.training_programs import settle_exact_program
from sword_runtime.training_rates import resolved_activity_regimen


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _cohort_index(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "state" / "forces").glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cohorts = doc.get("cohort_ledger", {}).get("cohorts", {}) if isinstance(doc, dict) else {}
        if not isinstance(cohorts, dict):
            continue
        for cohort_ref, cohort in cohorts.items():
            if isinstance(cohort, dict):
                out.setdefault(str(cohort_ref), cohort)
    return out


def repair(root: Path, *, apply: bool) -> dict[str, Any]:
    planner = CommandRoutedProductionPlanner(root)
    planner._reset()
    planner._ensure_activity_routes()
    runtime = planner.read("state/runtime.json")
    world_time = str(runtime.get("world_time"))

    command_index = planner.read("state/cmd/command-personnel.json").get("record_index", {})
    command_refs = set(command_index) if isinstance(command_index, dict) else set()
    owner_index = planner.read("state/index/owner-index.json").get("owners", {})
    routes: dict[str, str] = {}
    if isinstance(owner_index, dict):
        routes.update({str(ref): str(path) for ref, path in owner_index.items() if isinstance(path, str)})
    if isinstance(command_index, dict):
        routes.update({str(ref): str(path) for ref, path in command_index.items() if isinstance(path, str)})

    cohorts = _cohort_index(root)
    provenance_added: list[str] = []
    for person_ref, route in sorted(routes.items()):
        try:
            person = copy.deepcopy(planner.read(route))
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if not isinstance(person, dict) or person.get("schema") not in {"sab_character", "person-lite"}:
            continue
        cohort_ref = str(person.get("source_cohort_ref", "") or "")
        cohort = cohorts.get(cohort_ref)
        if not cohort_ref or not isinstance(cohort, dict):
            continue
        ds = person.setdefault("development_state", {})
        if not isinstance(ds, dict):
            continue
        if not isinstance(ds.get("inherited_training_baseline"), dict):
            ds["inherited_training_baseline"] = inherited_training_baseline(cohort, cohort_ref)
            ds["inherited_training_baseline"]["provenance_recorded_at"] = world_time
            planner.put(route, person)
            provenance_added.append(person_ref)

    tracking_baselines_added: list[str] = []
    for person_ref, route in sorted(routes.items()):
        if person_ref == planner.PLAYER_ACTOR or person_ref not in command_refs or not route.startswith("state/char/"):
            continue
        try:
            person = copy.deepcopy(planner.read(route))
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if person.get("schema") != "sab_character":
            continue
        activity = person.get("autonomous_activity_state", {})
        ds = person.setdefault("development_state", {})
        if not isinstance(activity, dict) or not isinstance(ds, dict):
            continue
        if (
            int(activity.get("completed_cycles", 0) or 0) == 0
            and int(ds.get("settled_training_hours", 0) or 0) == 0
            and not isinstance(ds.get("inherited_training_baseline"), dict)
            and not isinstance(ds.get("progression_tracking_baseline"), dict)
        ):
            ds["progression_tracking_baseline"] = {
                "tracking_started_at": str(activity.get("routed_at", world_time) or world_time),
                "baseline_kind": "current_saved_capability",
                "rule": "saved attributes and skills are authoritative at progression-tracking start; no pre-tracking EDU is invented unless completed-cycle or source-cohort provenance proves a historical settlement obligation",
            }
            planner.put(route, person)
            tracking_baselines_added.append(person_ref)

    profiles = planner.read("game/data/mil/recruitment-cohort-profiles.json")
    registry = planner.read("game/data/mil/deterministic-training-programs.json")
    training_rules = planner.read("game/data/mechanics/training.json")
    session_rules = planner.read("game/data/mechanics/training-session.json")
    repaired: list[dict[str, Any]] = []

    # Owner index is the bounded exact-person authority surface; no state/char scan.
    for person_ref, route in sorted(routes.items()):
        if not route.startswith("state/char/") or person_ref == planner.PLAYER_ACTOR:
            continue
        try:
            person = copy.deepcopy(planner.read(route))
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if person.get("schema") != "sab_character":
            continue
        contract = planner._command_activity_contract(person) if person_ref in command_refs else planner._effective_activity_contract(person)
        if not isinstance(contract, dict):
            continue
        proof = exact_activity_shortfall(person, contract, profiles)
        shortfall = int(proof["shortfall_hours"])
        if shortfall <= 0:
            continue
        if str(contract.get("mode", "")) == "age_appropriate_household_training":
            continue
        activity = person.get("autonomous_activity_state", {})
        completed_at = str(activity.get("last_completed_at", activity.get("last_cycle_at", world_time)))
        program_ref, training_ref, resolved_role = planner._activity_training_context(person, contract)
        regimen_ref, regimen = resolved_activity_regimen(person, contract, profiles)
        drill_access = exact_person_drill_access(planner, registry=registry, program_ref=program_ref, person=person)
        before_reviews = int(person.setdefault("development_state", {}).get("completed_reviews", 0) or 0)
        before_hours = int(person["development_state"].get("settled_training_hours", 0) or 0)
        verified_before = int(person["development_state"].get(
            "verified_deliberate_training_hours", before_hours
        ) or 0)
        result = settle_exact_program(
            person,
            registry=registry,
            program_ref=program_ref,
            hours=shortfall,
            at=CampaignTime.parse(completed_at),
            training_rules=training_rules,
            session_rules=session_rules,
            facility_grade=str(regimen.get("facility_grade", "adequate")),
            equipment_grade=str(regimen.get("equipment_grade", "adequate")),
            recovery_grade=str(regimen.get("recovery_grade", "adequate")),
            feedback_grade=str(regimen.get("feedback_grade", "ordinary")),
            cursor_key="autonomous_deterministic_training_cursor",
            drill_access=drill_access,
        )
        after_hours = int(person["development_state"].get("settled_training_hours", 0) or 0)
        settled_delta = after_hours - before_hours
        person["development_state"]["verified_deliberate_training_hours"] = verified_before + shortfall
        # completed_reviews historically counts causal review cycles on these records.
        # The EDU functions increment it per drill/skill call, so a repair must restore
        # the original causal-review count rather than minting extra months.
        person["development_state"]["completed_reviews"] = before_reviews
        repair_row = {
            "repair_ref": f"progression_reconciliation.244-bce-07-29.{person_ref}",
            "recorded_at": world_time,
            "completed_training_through": completed_at,
            "program_ref": program_ref,
            "training_ref": training_ref or None,
            "resolved_role": resolved_role or None,
            "canonical_cycle_hours": proof["cycle_hours"],
            "completed_cycles": proof["completed_cycles"],
            "expected_hours_before_repair": proof["expected_hours"],
            "settled_hours_before_repair": proof["settled_hours"],
            "verified_deliberate_hours_before_repair": proof["verified_deliberate_hours"],
            "reconciled_verified_hours": shortfall,
            "gain_bearing_hours": settled_delta,
            "physically_blocked_hours": max(0, shortfall - settled_delta),
            "settlement_basis": (
                "proven numerical under-settlement of already-completed saved cycles; missing hours settle through the current registered deterministic program and current physical drill-access record with the saved regimen grades; world time and causal review count are unchanged"
            ),
            "historical_instructor_claim": False,
            "historical_location_claim": False,
            "development_result": result,
        }
        person["development_state"].setdefault("progression_repair_history", []).append(repair_row)
        person["development_state"]["progression_repair_history"] = person["development_state"]["progression_repair_history"][-8:]
        planner.put(route, person)
        repaired.append({"person_ref": person_ref, "hours": shortfall, "program_ref": program_ref})

    hist = copy.deepcopy(planner.read("state/history/events/index.json"))
    event_id = "repair_progression_integrity_244_bce_07_29"
    if not any(isinstance(row, dict) and row.get("event_id") == event_id for row in hist.get("events", [])):
        hist.setdefault("events", []).append({
            "event_id": event_id,
            "kind": "explicit_repair",
            "at": world_time,
            "path": "named-person progression owners",
            "reason": "repository-wide progression-integrity reconciliation after deterministic training migration",
            "repaired_exact_people": [row["person_ref"] for row in repaired],
            "repaired_exact_hours": sum(int(row["hours"]) for row in repaired),
            "inherited_baseline_records_added": len(provenance_added),
            "tracking_baseline_records_added": len(tracking_baselines_added),
            "rule": "only proven completed-cycle hour shortfalls receive EDU; cohort-inherited or current-snapshot baselines are provenance-only and never double-awarded",
        })
        write_history_index(planner, hist)

    meta = copy.deepcopy(planner.read("state/meta.json"))
    prior_repair = meta.get("last_progression_integrity_repair")
    if not isinstance(prior_repair, dict):
        meta["revision"] = int(meta.get("revision", 0)) + 1
        meta["last_progression_integrity_repair"] = {
            "at": world_time,
            "event_ref": event_id,
            "repaired_exact_people": len(repaired),
            "repaired_exact_hours": sum(int(row["hours"]) for row in repaired),
            "inherited_baseline_records_added": len(provenance_added),
            "tracking_baseline_records_added": len(tracking_baselines_added),
        }
        planner.put("state/meta.json", meta)

    summary = {
        "world_time": world_time,
        "repaired": repaired,
        "repaired_exact_people": len(repaired),
        "repaired_exact_hours": sum(int(row["hours"]) for row in repaired),
        "inherited_baseline_records_added": len(provenance_added),
        "tracking_baseline_records_added": len(tracking_baselines_added),
        "staged_files": len(planner._writes),
    }
    if apply:
        for rel, value in sorted(planner._writes.items()):
            _json_write(root / rel, value)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    summary = repair(args.root.resolve(), apply=args.apply)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
