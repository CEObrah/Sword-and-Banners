#!/usr/bin/env python3
"""Finalize the universal 48h/week training + command-chain delivery migration.

This repair is intentionally narrow and provenance-safe:
- it does not replay or subtract historical development;
- baseline cohorts whose current stats predate detailed training tracking receive an
  explicit tracking baseline rather than fabricated historical EDU;
- clean-baseline House Tang, Sword Manor, and Four Bastion formations receive the
  internal 1000/500/100 command billets required by their already-saved authorized
  establishment by reclassifying existing fighting bodies, never by creating people;
- Tang Wei's future standing plan is normalized to the universal 48h/week clock;
- exact/person-lite activity caches are reconciled through the normal route owner.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from sword_runtime.history_store import write_history_index
from sword_runtime.officer_cadre import _target_billets, ensure_officer_cadre
from sword_runtime.service_runtime import CommandRoutedProductionPlanner

EVENT = "repair_universal_training_hierarchy_final_244_bce_07_29"
MIGRATION = "universal_training_hierarchy_final_v1"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _is_training_hierarchy_formation(formation: Mapping[str, Any]) -> bool:
    owner = str(formation.get("owner_force_ref", "") or "")
    return owner in {"force_house_tang", "force_sword_manor"} or owner.startswith("force_bastion_")


def repair(root: Path, *, apply: bool) -> dict[str, Any]:
    planner = CommandRoutedProductionPlanner(root)
    planner._reset()
    world = str(planner.read("state/runtime.json").get("world_time"))

    # Future player schedule only. Historical hours are preserved exactly.
    player = copy.deepcopy(planner.read("state/player.json"))
    contract = player.setdefault("activity_contract", {})
    player_changed = False
    if float(contract.get("verified_hours_per_7d", 0.0) or 0.0) != 48.0:
        contract["verified_hours_per_7d"] = 48
        player_changed = True
    desired = (
        "Universal active-professional deliberate training up to 48 hours per 7 days when not interrupted by "
        "House duties, travel, command, health, fatigue, recovery, or missing physical access; the registered "
        "Tang field-senior-command program owns curriculum and trainer/facility quality rather than extra clock time"
    )
    if str(contract.get("planned_opportunity", "")) != desired:
        contract["planned_opportunity"] = desired
        player_changed = True
    if player_changed:
        planner.put("state/player.json", player)

    # Baseline cohorts: current capability is accepted as the tracking-start truth.
    # No historical hours or EDU are fabricated from service_months_mean.
    baseline_cohorts: list[dict[str, Any]] = []
    for force_path in sorted((root / "state/forces").glob("*.json")):
        rel = str(force_path.relative_to(root))
        force = copy.deepcopy(planner.read(rel))
        cohorts = force.get("cohort_ledger", {}).get("cohorts", {}) if isinstance(force, Mapping) else {}
        if not isinstance(cohorts, MutableMapping):
            continue
        changed = False
        for cohort_id, cohort in sorted(cohorts.items()):
            if not isinstance(cohort, MutableMapping):
                continue
            if "verified_training_hours_per_person" in cohort or isinstance(cohort.get("development_tracking_baseline"), Mapping):
                continue
            baseline = {
                "baseline_ref": MIGRATION,
                "recorded_at": world,
                "prior_service_months_mean": float(cohort.get("service_months_mean", 0.0) or 0.0),
                "current_saved_capability_is_tracking_start_truth": True,
                "historical_training_hours_claimed": 0.0,
                "historical_edu_backfill": False,
                "rule": (
                    "Current aggregate stats already represent pre-tracking service. Detailed verified training begins "
                    "prospectively from this baseline; prior service duration alone never mints retrospective EDU."
                ),
            }
            cohort["development_tracking_baseline"] = baseline
            cohort["verified_training_hours_per_person"] = 0.0
            cohort["verified_role_exposure_hours_per_person"] = 0.0
            baseline_cohorts.append({
                "force_ref": str(force.get("owner_id", "")),
                "cohort_ref": str(cohort_id),
                "service_months_mean": baseline["prior_service_months_mean"],
            })
            changed = True
        if changed:
            planner.put(rel, force)

    # Establishment repair: these baseline institutions are supposed to have a
    # functioning permanent command chain. Missing aggregate ranks are reclassified
    # from the same conserved fighting establishment. No personnel total changes.
    repaired_formations: list[dict[str, Any]] = []
    for formation_path in sorted((root / "state/formations").glob("*.json")):
        rel = str(formation_path.relative_to(root))
        formation = copy.deepcopy(planner.read(rel))
        if not _is_training_hierarchy_formation(formation):
            continue
        cadre = ensure_officer_cadre(formation)
        targets = _target_billets(formation)
        before_inventory = {k: int(cadre["rank_inventory"].get(k, 0) or 0) for k in targets}
        before_active = {k: int(cadre["active_billets"].get(k, 0) or 0) for k in targets}
        missing = {k: max(0, int(v) - int(before_active.get(k, 0))) for k, v in targets.items()}
        if not any(missing.values()):
            continue
        # This is a baseline correction, not an in-world promotion event. Reclassify
        # existing conserved troop bodies into the establishment ranks that the saved
        # topology already requires.
        for rank, target in targets.items():
            materialized = cadre.get("materialized_refs_by_rank", {}).get(rank, [])
            materialized_count = len(materialized) if isinstance(materialized, list) else 0
            cadre["rank_inventory"][rank] = max(int(target), materialized_count)
            cadre["active_billets"][rank] = int(target)
            cadre["cadre_reserve"][rank] = max(0, int(cadre["rank_inventory"][rank]) - int(target))
            cadre["vacant_billets"][rank] = 0
        cadre["last_reorganized_at"] = world
        cadre["last_reorganization_reason"] = "baseline_command_hierarchy_completion"
        cadre.setdefault("promotion_history", []).append({
            "at": world,
            "source": "explicit_baseline_repair",
            "reason": "baseline_command_hierarchy_completion",
            "reclassified_existing_fighting_bodies": {k: v for k, v in missing.items() if v},
            "headcount_created": 0,
            "rule": "Authorized establishment already required these internal command billets; repair changes rank classification only.",
        })
        cadre["promotion_history"] = cadre["promotion_history"][-64:]
        planner.put(rel, formation)
        repaired_formations.append({
            "formation_ref": str(formation.get("formation_ref", formation_path.stem)),
            "owner_force_ref": str(formation.get("owner_force_ref", "")),
            "personnel": int(formation.get("personnel", 0) or 0),
            "authorized_strength": int(formation.get("authorized_strength", formation.get("personnel", 0)) or 0),
            "before_inventory": before_inventory,
            "before_active": before_active,
            "target": targets,
            "reclassified": {k: v for k, v in missing.items() if v},
        })

    # Reconcile exact/person-lite activity route caches against current role/contract
    # after the universal regimen data change. No training is awarded by routing.
    planner._ensure_activity_routes()

    history = copy.deepcopy(planner.read("state/history/events/index.json"))
    events = history.setdefault("events", [])
    if not any(isinstance(row, Mapping) and row.get("event_id") == EVENT for row in events):
        events.append({
            "event_id": EVENT,
            "kind": "explicit_repair",
            "at": world,
            "path": "universal professional training clock + command-chain training delivery",
            "reason": (
                "Finalize the user-authorized 48h/week faction-neutral training law, establish provenance for pre-tracking "
                "cohort capability, and complete clean-baseline House Tang/Sword Manor/Bastion internal command chains."
            ),
            "universal_deliberate_hours_per_7d": 48.0,
            "baseline_cohorts_registered": len(baseline_cohorts),
            "formations_hierarchy_completed": len(repaired_formations),
            "headcount_created": 0,
            "historical_edu_backfilled_for_baseline_cohorts": 0,
            "rule": "Training propagates through existing command hierarchy; no Units-per-instructor cap or separate trainer manpower class exists.",
        })
        write_history_index(planner, history)

    meta = copy.deepcopy(planner.read("state/meta.json"))
    previous = meta.get("last_universal_training_hierarchy_finalization")
    # The script is idempotent: only increment revision when this finalization was not
    # already recorded. Existing writes from route reconciliation may still be emitted.
    if not isinstance(previous, Mapping) or previous.get("migration_ref") != MIGRATION:
        meta["revision"] = int(meta.get("revision", 0) or 0) + 1
    meta["last_universal_training_hierarchy_finalization"] = {
        "at": world,
        "event_ref": EVENT,
        "migration_ref": MIGRATION,
        "baseline_cohorts_registered": len(baseline_cohorts),
        "formations_hierarchy_completed": len(repaired_formations),
        "headcount_created": 0,
    }
    planner.put("state/meta.json", meta)

    summary = {
        "world_time": world,
        "baseline_cohorts_registered": len(baseline_cohorts),
        "baseline_cohorts": baseline_cohorts,
        "formations_hierarchy_completed": len(repaired_formations),
        "formations": repaired_formations,
        "player_schedule_changed": player_changed,
        "staged_files": len(planner._writes),
    }
    if apply:
        for rel, value in sorted(planner._writes.items()):
            write_json(root / rel, value)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    result = repair(Path(args.root).resolve(), apply=args.apply)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
