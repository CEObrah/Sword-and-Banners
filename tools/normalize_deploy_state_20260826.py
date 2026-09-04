#!/usr/bin/env python3
"""Narrow zero-time normalization for the revision-6 deployment baseline.

This repair corrects only demonstrably stale duplicate/projection fields whose
exact owners already establish the intended truth.  It does not advance time,
change manpower, change formation ownership, or invent campaign outcomes.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REVISION = 6
EXPECTED_TIME = "244-BCE-09-16T20:22:48+08:00"
REPAIR_REF = "repair_deploy_state_normalization_20260826"
PLAYER_ORIGIN_STALE = "loc_qin_eastern_depot"
PLAYER_DESTINATION = "loc_kanyou"

COMMANDERS = [
    "char_cmd_qin_kanki_raider_host",
    "char_cmd_qin_mou_bu_shock_army",
    "char_cmd_qin_ouki_vanguard",
    "char_cmd_qin_ousen_central",
    "char_cmd_qin_tou_mobile_army",
]


def load(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def save(rel: str, doc) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def main() -> int:
    meta = load("state/meta.json")
    if int(meta.get("revision", -1)) != EXPECTED_REVISION or str(meta.get("time", "")) != EXPECTED_TIME:
        raise RuntimeError("deploy-state normalization applies only to the known revision-6 boundary")

    owner_index = load("state/index/owner-index.json").get("owners", {})

    player = load("state/player.json")
    canonical_location = str(player.get("location", ""))
    legacy_location = str(player.get("current_location", ""))
    if canonical_location != PLAYER_DESTINATION:
        raise RuntimeError(f"unexpected canonical Tang Wei location: {canonical_location}")
    if legacy_location not in {PLAYER_ORIGIN_STALE, PLAYER_DESTINATION}:
        raise RuntimeError(f"unexpected legacy Tang Wei location alias: {legacy_location}")
    player_before = legacy_location
    player["current_location"] = canonical_location
    save("state/player.json", player)

    commander_changes = []
    for person_ref in COMMANDERS:
        person_path = owner_index.get(person_ref)
        if not isinstance(person_path, str) or "#/" in person_path:
            raise RuntimeError(f"missing exact commander route: {person_ref}")
        person = load(person_path)
        assignment = person.get("command_assignment") if isinstance(person.get("command_assignment"), dict) else {}
        formation_ref = assignment.get("formation_ref")
        if not isinstance(formation_ref, str):
            raise RuntimeError(f"commander lacks exact formation assignment: {person_ref}")
        formation_path = owner_index.get(formation_ref)
        if not isinstance(formation_path, str) or "#/" in formation_path:
            raise RuntimeError(f"missing exact formation route: {formation_ref}")
        formation = load(formation_path)
        if str(formation.get("commander_ref", "")) != person_ref:
            raise RuntimeError(f"formation commander mismatch: {formation_ref}")
        expected_span = int(formation.get("personnel", 0) or 0)
        if expected_span <= 0 or int(assignment.get("current_command_span", -1) or -1) != expected_span:
            raise RuntimeError(f"command assignment is not already authoritative for {person_ref}")

        career = person.setdefault("career_state", {})
        military = person.setdefault("military_command", {})
        old_span = int(career.get("current_command_span", 0) or 0)
        old_level = str(military.get("level", ""))
        old_role = str(person.get("role", ""))
        old_office = str(career.get("office_or_command", ""))
        formation_name = str(formation.get("name") or formation_ref)
        current_label = f"{expected_span}-man Commander, {formation_name}"

        career["current_command_span"] = expected_span
        military["level"] = f"{expected_span}_commander"
        person["role"] = current_label
        career["office_or_command"] = current_label
        history = career.setdefault("assignment_history", [])
        if not any(isinstance(row, dict) and row.get("repair_ref") == REPAIR_REF for row in history):
            history.append({
                "repair_ref": REPAIR_REF,
                "kind": "command_span_metadata_reconciliation",
                "at": EXPECTED_TIME,
                "formation_ref": formation_ref,
                "prior_command_span": old_span,
                "current_command_span": expected_span,
                "prior_military_level": old_level,
                "prior_role": old_role,
                "prior_office_or_command": old_office,
            })
            del history[:-16]
        save(person_path, person)
        commander_changes.append({
            "person_ref": person_ref,
            "formation_ref": formation_ref,
            "prior_span": old_span,
            "current_span": expected_span,
        })

    repair_log = {
        "authority": False,
        "kind": "campaign_repair_provenance",
        "repair_ref": REPAIR_REF,
        "campaign_revision": EXPECTED_REVISION,
        "world_time": EXPECTED_TIME,
        "rule": "normalize only stale duplicate/projection metadata from exact current owners; do not advance chronology or change conserved bodies/authority",
        "corrected": {
            "player_location_alias": {
                "person_ref": "char_tang_wei",
                "canonical_field": "location",
                "canonical_value": canonical_location,
                "prior_current_location": player_before,
                "current_location": canonical_location,
            },
            "commander_span_metadata": commander_changes,
        },
    }
    save("state/history/repairs/deploy-state-normalization-20260826.json", repair_log)
    print(json.dumps(repair_log["corrected"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
