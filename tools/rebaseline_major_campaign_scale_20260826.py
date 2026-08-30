#!/usr/bin/env python3
"""Narrow current-save repair for the underscaled 244 BCE Qin-Wei campaign.

This script does not script future history. It repairs already-active operation
owners so they reference the corrected current command hierarchy, then invokes
the generic standing-army mobilization rules to move already-conserved active
state personnel into those persistent armies. Total state military headcount is
unchanged. Existing formation identity, cohort training, equipment custody and
command history are preserved.
"""
from __future__ import annotations

import copy
import json
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from sword_runtime.campaign_briefing import (
    build_campaign_dossier,
    ensure_actionable_mission_packet,
    persist_campaign_briefing,
    render_campaign_briefing,
)
from sword_runtime.command_units import recursive_refs
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.store.repository import atomic_replace_bytes

REPAIR_REF = "baseline_repair_2026_08_26_major_campaign_scale"
PLAYER_OPERATION = "operation_arc_131572c4e8a2892bbc"


def _pretty_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _state_group_formations(planner: ProductionCampaignPlanner, group_ref: str, force_ref: str) -> list[str]:
    formations, _commands = recursive_refs(
        lambda ref: planner.read(f"state/cmd/command-groups/{ref}.json"),
        group_ref,
    )
    out: list[str] = []
    for formation_ref in sorted(formations):
        try:
            row = planner.read(planner.owner_path(formation_ref))
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if isinstance(row, Mapping) and str(row.get("owner_force_ref", "")) == force_ref:
            out.append(formation_ref)
    return out


def _reconcile_operation_location(planner: ProductionCampaignPlanner, operation: dict) -> None:
    opposing = {str(ref) for ref in operation.get("opposing_formation_refs", []) if isinstance(ref, str)}
    locations: set[str] = set()
    for formation_ref in operation.get("formation_refs", []) if isinstance(operation.get("formation_refs"), list) else []:
        if not isinstance(formation_ref, str) or formation_ref in opposing:
            continue
        try:
            formation = planner.read(planner.owner_path(formation_ref))
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if isinstance(formation, Mapping) and isinstance(formation.get("location_ref"), str) and formation.get("location_ref"):
            locations.add(str(formation["location_ref"]))
    operation["location_ref"] = next(iter(locations)) if len(locations) == 1 else None


def _retarget_operation_to_group(
    planner: ProductionCampaignPlanner,
    operation_ref: str,
    *,
    group_ref: str,
    force_ref: str,
) -> None:
    path = planner.owner_path(operation_ref)
    operation = copy.deepcopy(planner.read(path))
    operation["command_group_ref"] = group_ref
    operation["formation_refs"] = _state_group_formations(planner, group_ref, force_ref)
    _reconcile_operation_location(planner, operation)
    planner.put(path, operation)


def _reconcile_single_formation_operation(planner: ProductionCampaignPlanner, operation_ref: str) -> None:
    path = planner.owner_path(operation_ref)
    operation = copy.deepcopy(planner.read(path))
    _reconcile_operation_location(planner, operation)
    planner.put(path, operation)


def _mark_briefing_supersession(planner: ProductionCampaignPlanner, old_ref: str | None, new_ref: str) -> None:
    if not isinstance(old_ref, str) or not old_ref or old_ref == new_ref:
        return
    old_path = planner.owner_path(old_ref)
    new_path = planner.owner_path(new_ref)
    old = copy.deepcopy(planner.read(old_path))
    new = copy.deepcopy(planner.read(new_path))
    old["supersession_group_ref"] = "arc_ryo_fui_northern_wei_campaign"
    old["superseded_by_ref"] = new_ref
    old["assessment_status"] = "historical_assessment"
    new["supersession_group_ref"] = "arc_ryo_fui_northern_wei_campaign"
    new["supersedes_ref"] = old_ref
    new["assessment_status"] = "current_assessment"
    planner.put(old_path, old)
    planner.put(new_path, new)


def _record_repair_history(planner: ProductionCampaignPlanner, *, at: str, evidence: Mapping[str, object]) -> None:
    path = "state/history/events/index.json"
    history = copy.deepcopy(planner.read(path))
    rows = history.setdefault("events", [])
    event_id = "baseline_repair_major_campaign_scale_20260826"
    if not any(isinstance(row, Mapping) and row.get("event_id") == event_id for row in rows):
        rows.append({
            "event_id": event_id,
            "kind": "campaign_truth_repair",
            "at": at,
            "repair_ref": REPAIR_REF,
            "arc_ref": "arc_ryo_fui_northern_wei_campaign",
            "basis": "Live play exposed that already-conserved state military reserves were omitted from major-war standing-army mobilization and that nested Qin armies were represented as peer operations.",
            "material_evidence": copy.deepcopy(dict(evidence)),
        })
        planner.put(path, history)


def _flush(planner: ProductionCampaignPlanner) -> list[str]:
    if planner._deletes:
        raise RuntimeError(f"campaign scale repair unexpectedly requested deletes: {sorted(planner._deletes)}")
    changed: list[str] = []
    for rel, value in sorted(planner._writes.items()):
        path = ROOT / rel
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            old = None
        if old == value:
            continue
        atomic_replace_bytes(path, _pretty_bytes(value))
        changed.append(rel)
    return changed


def main() -> int:
    planner = ProductionCampaignPlanner(ROOT)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()
    at = str(planner.read("state/meta.json")["time"])

    # Repair current organizational participation only. These exact operation refs
    # are current-save corruption targets, not named future behavior rules.
    _retarget_operation_to_group(
        planner, "operation_arc_fc2ad9d90305148fc9",
        group_ref="cmdgrp.mou_gou.field_army", force_ref="force_state_qin",
    )
    _retarget_operation_to_group(
        planner, "operation_arc_54754a3da76f03f723",
        group_ref="cmdgrp.mou_bu.field_army", force_ref="force_state_qin",
    )
    _retarget_operation_to_group(
        planner, "operation_arc_1183814c96a451b510",
        group_ref="cmdgrp.ouki.field_army", force_ref="force_state_qin",
    )

    qin_results = []
    for group_ref in (
        "cmdgrp.mou_gou.field_army",
        "cmdgrp.mou_bu.field_army",
        "cmdgrp.ouki.field_army",
    ):
        qin_results.append(planner._reinforce_state_field_army_for_mobilization(
            group_ref, state_ref="state_qin", force_ref="force_state_qin", at=at,
        ))

    # The active Wei response has two general-led independent commands. They use
    # the same generic rank-guided permanent reinforcement mechanic.
    wei_results = []
    for operation_ref, formation_ref in (
        ("operation_arc_87a653abea8db6349c", "formation_wei_mobile_reserve"),
        ("operation_arc_b4f7c0501b036cdaec", "formation_wei_reconstitution"),
    ):
        _reconcile_single_formation_operation(planner, operation_ref)
        wei_results.append(planner._reinforce_state_independent_formation_for_mobilization(
            formation_ref, state_ref="state_wei", force_ref="force_state_wei", at=at,
        ))
        _reconcile_single_formation_operation(planner, operation_ref)

    # Reinforcement changes exact formation strengths but not operation identities.
    # Refresh all repaired operation locations after the material transfer.
    for operation_ref in (
        "operation_arc_fc2ad9d90305148fc9",
        "operation_arc_54754a3da76f03f723",
        "operation_arc_1183814c96a451b510",
        "operation_arc_87a653abea8db6349c",
        "operation_arc_b4f7c0501b036cdaec",
    ):
        _reconcile_single_formation_operation(planner, operation_ref)

    player_path = planner.owner_path(PLAYER_OPERATION)
    player_operation_before = copy.deepcopy(planner.read(player_path))
    old_brief_ref = player_operation_before.get("briefing_information_ref")
    dossier = build_campaign_dossier(planner, PLAYER_OPERATION)
    mission_packet = ensure_actionable_mission_packet(planner, PLAYER_OPERATION, dossier, at=at)
    summary = render_campaign_briefing(planner, dossier, mission_packet)
    new_brief_ref = persist_campaign_briefing(planner, dossier=dossier, summary=summary, at=at)
    _mark_briefing_supersession(planner, old_brief_ref if isinstance(old_brief_ref, str) else None, new_brief_ref)

    player_operation = copy.deepcopy(planner.read(player_path))
    planner.put(player_path, player_operation)

    evidence = {
        "qin_reinforced_personnel": sum(int(row.get("assigned", 0) or 0) for row in qin_results),
        "wei_reinforced_personnel": sum(int(row.get("assigned", 0) or 0) for row in wei_results),
        "friendly_total_strength": int(dossier.get("friendly_total_strength", 0) or 0),
        "enemy_estimated_strength_low": int((dossier.get("enemy_intelligence") or {}).get("estimated_strength_low", 0) or 0),
        "enemy_estimated_strength_high": int((dossier.get("enemy_intelligence") or {}).get("estimated_strength_high", 0) or 0),
        "current_briefing_ref": new_brief_ref,
        "headcount_rule": "personnel moved only from existing force_state_qin/force_state_wei active reserves; state force headcount unchanged",
    }
    _record_repair_history(planner, at=at, evidence=evidence)

    changed = _flush(planner)
    print(f"{REPAIR_REF}: persisted {len(changed)} semantic JSON updates")
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
