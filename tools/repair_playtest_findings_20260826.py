#!/usr/bin/env python3
"""Narrow baseline repair for 2026-08-26 live-play military findings.

This is deliberately idempotent. It repairs only assignment metadata made stale by
Tang Wei's 9,500-man reorganization and leaves campaign chronology/headcount intact.
Runtime behavior fixes live in the owning modules and tests.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPAIR_REF = "baseline_repair_2026_08_26_tang_field_reassignment"


def load(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def save(rel: str, doc) -> None:
    (ROOT / rel).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def owner_path(ref: str) -> tuple[str, str | None]:
    route = str(load("state/index/owner-index.json")["owners"][ref])
    path, sep, frag = route.partition("#")
    return path, frag if sep else None


def update_person(ref: str, *, authority: str | None = None, affiliation=None, duty: str | None = None, training_regimen_ref: str | None = None) -> None:
    path, frag = owner_path(ref)
    doc = load(path)
    if frag:
        key = frag.removeprefix("/records/")
        person = doc["records"][key]
    else:
        person = doc
    career = person.setdefault("career_state", {})
    history = career.setdefault("assignment_history", [])
    if not any(isinstance(row, dict) and row.get("repair_ref") == REPAIR_REF for row in history):
        history.append({
            "repair_ref": REPAIR_REF,
            "kind": "reassignment_metadata_reconciliation",
            "prior_role": person.get("role"),
            "prior_authority": person.get("authority"),
            "current_billet": career.get("current_billet"),
            "current_command_span": career.get("current_command_span"),
        })
        del history[:-16]
    if authority is not None:
        person["authority"] = authority
    if affiliation is not None:
        person["affiliation"] = affiliation
    if training_regimen_ref is not None:
        activity = person.setdefault("activity_contract", {})
        if isinstance(activity, dict):
            activity["autonomous_enabled"] = True
            activity["mode"] = "standing_role_training"
            activity["training_regimen_ref"] = training_regimen_ref
    if duty is not None:
        goals = person.setdefault("goal_state", {})
        old = goals.get("institutional_duties", [])
        kept = []
        if isinstance(old, list):
            for row in old:
                text = str(row)
                lower = text.lower()
                if any(token in lower for token in (
                    "inner walls", "qin combined unit", "border detachment unit",
                    "house guard", "cmdgrp.tang_wei.shen_rui",
                )):
                    continue
                if text == duty:
                    continue
                kept.append(text)
        goals["institutional_duties"] = [duty, *kept]
    save(path, doc)




def _command_group_strength(group: dict) -> int:
    org = group.get("organizational_state") if isinstance(group.get("organizational_state"), dict) else {}
    return max(0, int(org.get("current_recursive_strength", 0) or 0))


def _recursive_formation_count(group_ref: str, *, seen: set[str] | None = None) -> int:
    seen = set() if seen is None else seen
    if group_ref in seen:
        raise ValueError("command hierarchy contains a cycle")
    seen.add(group_ref)
    group = load(f"state/cmd/command-groups/{group_ref}.json")
    total = 0
    for row in group.get("units", []):
        if not isinstance(row, dict) or not isinstance(row.get("ref"), str):
            continue
        if row.get("kind") == "formation":
            total += 1
        elif row.get("kind") == "nested_army":
            total += _recursive_formation_count(row["ref"], seen=seen)
    return total


def _refresh_group_organization(group_ref: str) -> None:
    path = f"state/cmd/command-groups/{group_ref}.json"
    group = load(path)
    org = group.setdefault("organizational_state", {})
    baselines = org.setdefault("baseline_unit_strengths", {})
    statuses_by_ref = {
        str(row.get("ref")): row
        for row in org.get("unit_statuses", [])
        if isinstance(row, dict) and isinstance(row.get("ref"), str)
    }
    unit_statuses = []
    recursive = 0
    direct_formation = 0
    for row in group.get("units", []):
        ref = str(row["ref"])
        if row.get("kind") == "nested_army":
            child = load(f"state/cmd/command-groups/{ref}.json")
            strength = _command_group_strength(child)
            status = str((child.get("organizational_state") or {}).get("status", "active"))
        else:
            route = load("state/index/owner-index.json")["owners"][ref]
            formation = load(route)
            strength = max(0, int(formation.get("personnel", 0) or 0))
            direct_formation += strength
            status = str(formation.get("status", "ready"))
        baselines[ref] = strength
        recursive += strength
        current = dict(statuses_by_ref.get(ref, {}))
        current.update({"current_strength": strength, "kind": row.get("kind"), "ref": ref, "status": status})
        unit_statuses.append(current)
    valid = {str(row["ref"]) for row in group.get("units", []) if isinstance(row, dict) and isinstance(row.get("ref"), str)}
    for ref in list(baselines):
        if ref not in valid:
            baselines.pop(ref, None)
    org["authorized_direct_unit_slots"] = len(group.get("units", []))
    org["authorized_strength"] = max(recursive, int(org.get("authorized_strength", 0) or 0))
    org["current_direct_formation_strength"] = direct_formation
    org["current_recursive_strength"] = recursive
    org["direct_unit_count"] = len(group.get("units", []))
    org["recursive_formation_count"] = _recursive_formation_count(group_ref)
    org["unit_statuses"] = unit_statuses
    if org.get("status") == "commander_vacant" and group.get("commander_ref"):
        org["status"] = "active"
    save(path, group)


def _set_organic_parent(child_ref: str, parent_ref: str | None, *, display_name: str | None = None) -> None:
    """Reconcile one durable parent/child relationship bidirectionally.

    This changes only current organizational truth. It does not encode any future
    succession or post-death outcome. Future promotion, succession, detachment and
    campaign attachment remain generic runtime decisions.
    """
    now = str(load("state/meta.json").get("time") or "244-BCE-09-09T20:22:48+08:00")
    child_path = f"state/cmd/command-groups/{child_ref}.json"
    child = load(child_path)
    old_parent = child.get("parent_command_group_ref")
    if isinstance(old_parent, str) and old_parent and old_parent != parent_ref:
        old_path = f"state/cmd/command-groups/{old_parent}.json"
        old = load(old_path)
        old["units"] = [
            row for row in old.get("units", [])
            if not (isinstance(row, dict) and row.get("kind") == "nested_army" and row.get("ref") == child_ref)
        ]
        old["updated_at"] = now
        save(old_path, old)
        _refresh_group_organization(old_parent)
    child["parent_command_group_ref"] = parent_ref
    if display_name:
        child["display_name"] = display_name
    child["updated_at"] = now
    save(child_path, child)
    if isinstance(parent_ref, str) and parent_ref:
        parent_path = f"state/cmd/command-groups/{parent_ref}.json"
        parent = load(parent_path)
        if not any(
            isinstance(row, dict) and row.get("kind") == "nested_army" and row.get("ref") == child_ref
            for row in parent.get("units", [])
        ):
            parent.setdefault("units", []).append({"kind": "nested_army", "ref": child_ref})
        parent["updated_at"] = now
        save(parent_path, parent)
        _refresh_group_organization(parent_ref)


def reconcile_qin_starting_command_hierarchy() -> None:
    """Correct current 244 BCE Qin organizational facts without scripting futures.

    Organic hierarchy is persistent command structure. Independent young commands
    remain parentless. Campaign attachment is intentionally not represented here.
    """
    # Tou currently serves organically inside Ouki's field command. Ouki's saved
    # successor list records a present designation, not a hard-coded death result.
    _set_organic_parent("cmdgrp.tou.field_army", "cmdgrp.ouki.field_army", display_name="Tou Army")
    tou_doc = load("state/cmd/command-groups/cmdgrp.tou.field_army.json")
    tou_doc["context"] = "state_field_army"
    save("state/cmd/command-groups/cmdgrp.tou.field_army.json", tou_doc)
    ouki_path = "state/cmd/command-groups/cmdgrp.ouki.field_army.json"
    ouki = load(ouki_path)
    if "char_tou" not in ouki.setdefault("successor_refs", []):
        ouki["successor_refs"].append("char_tou")
    save(ouki_path, ouki)
    _refresh_group_organization("cmdgrp.ouki.field_army")

    # Early Ousen and Kanki are intact subordinate armies within Mou Gou's larger
    # standing command. Their own formations/officers/history remain untouched.
    _set_organic_parent("cmdgrp.ousen.field_army", "cmdgrp.mou_gou.field_army", display_name="Ousen Army")
    _set_organic_parent("cmdgrp.kanki.field_army", "cmdgrp.mou_gou.field_army", display_name="Kanki Army")

    # Gaku Ka and Gyoku Hou are independent commands. They can be operationally
    # attached to a senior campaign commander without becoming organic children.
    _set_organic_parent("cmdgrp.mou_ten.gaku_ka", None)
    _set_organic_parent("cmdgrp.ou_hon.gyoku_hou", None)

    # Remove legacy one-sided parent listings left by the prior seed data.
    for parent_ref, child_ref in (
        ("cmdgrp.mou_gou.field_army", "cmdgrp.mou_ten.gaku_ka"),
        ("cmdgrp.ousen.field_army", "cmdgrp.ou_hon.gyoku_hou"),
    ):
        path = f"state/cmd/command-groups/{parent_ref}.json"
        parent = load(path)
        parent["units"] = [
            row for row in parent.get("units", [])
            if not (isinstance(row, dict) and row.get("kind") == "nested_army" and row.get("ref") == child_ref)
        ]
        save(path, parent)
        _refresh_group_organization(parent_ref)

    # Service-sheet projections follow current hierarchy only. No future outcome is
    # embedded here; generic succession/reassignment mechanics own later changes.
    ouki = load(ouki_path)
    ouki_span = _command_group_strength(ouki)
    opath, _ = owner_path("char_ouki")
    odoc = load(opath)
    odoc.setdefault("career_state", {}).update({
        "current_billet": "command_group_commander",
        "current_command_span": ouki_span,
        "office_or_command": "Commander, Ouki Field Army",
    })
    odoc.setdefault("command_assignment", {}).update({
        "billet": "command_group_commander",
        "command_group_ref": "cmdgrp.ouki.field_army",
        "formation_ref": "cmdgrp.ouki.field_army",
        "current_command_span": ouki_span,
        "external_to_fighting_establishment": True,
    })
    odoc.setdefault("military_command", {}).update({
        "formation_scope": "cmdgrp.ouki.field_army",
        "level": f"{ouki_span}_commander",
        "external_to_fighting_strength": True,
    })
    odoc["military_command"].pop("higher_commander_ref", None)
    save(opath, odoc)

    tou = load("state/cmd/command-groups/cmdgrp.tou.field_army.json")
    tou_span = _command_group_strength(tou)
    tpath, _ = owner_path("char_tou")
    tdoc = load(tpath)
    tdoc["role"] = "General, Ouki Army; Commander, Tou Army"
    tdoc["authority"] = "Qin general commanding the Tou Army within Ouki's field command."
    tdoc.setdefault("career_state", {}).update({
        "current_billet": "command_group_commander",
        "current_command_span": tou_span,
        "office_or_command": "Commander, Tou Army under Ouki Field Army",
    })
    tdoc.setdefault("command_assignment", {}).update({
        "billet": "command_group_commander",
        "command_group_ref": "cmdgrp.tou.field_army",
        "formation_ref": "cmdgrp.tou.field_army",
        "current_command_span": tou_span,
        "external_to_fighting_establishment": True,
    })
    tdoc.setdefault("military_command", {}).update({
        "formation_scope": "cmdgrp.tou.field_army",
        "level": f"{tou_span}_commander",
        "higher_commander_ref": "char_ouki",
        "external_to_fighting_strength": True,
    })
    save(tpath, tdoc)

    # The old live operation represented only Tou's direct body despite his actual
    # organic superior command. Reconcile only this demonstrably bad starting save.
    op_rel = "state/operations/operation_arc_1183814c96a451b510.json"
    if (ROOT / op_rel).exists():
        op = load(op_rel)
        if op.get("status") == "active" and op.get("formation_refs") == ["formation_qin_tou_mobile_army"]:
            op["command_group_ref"] = "cmdgrp.ouki.field_army"
            op["formation_refs"] = ["formation_qin_ouki_vanguard", "formation_qin_tou_mobile_army"]
        save(op_rel, op)

def main() -> None:
    inner_field = {
        "char_ren_qiao": "500-man Commander, High Guard Cavalry",
        "char_sword_manor_trainee_commander": "500-man Commander, High Guard Infantry 1",
        "char_sword_manor_trainee_training_officer": "500-man Commander, High Guard Infantry 2",
        "char_sword_manor_junior_commander": "500-man Commander, High Guard Infantry 3",
        "char_sword_manor_junior_training_officer": "500-man Commander, High Guard Infantry 4",
        "char_sword_manor_general_commander": "500-man Commander, High Guard Infantry 5",
        "char_sword_manor_general_training_officer": "500-man Commander, High Guard Infantry 6",
    }
    for ref, duty in inner_field.items():
        update_person(
            ref,
            authority="House Tang field officer under Tang Wei's active field command.",
            affiliation=["house_tang", "Tang Wei Personal Retinue"],
            duty=duty,
            training_regimen_ref="professional_officer",
        )

    black_banner = {
        "char_qin_wei_unit_01_commander": "500-man Commander, Black Banner 1A",
        "char_qin_wei_unit_02_commander": "500-man Commander, Black Banner 1B",
        "char_qin_wei_unit_03_commander": "500-man Commander, Black Banner 2A",
        "char_qin_wei_unit_04_commander": "500-man Commander, Black Banner 2B",
        "char_han_shou": "500-man Commander, Black Banner 3A",
        "char_pei_rong": "500-man Commander, Black Banner 3B",
        "char_deng_kai": "500-man Commander, Black Banner 4A",
        "char_lu_cheng": "500-man Commander, Black Banner 4B",
    }
    for ref, duty in black_banner.items():
        update_person(
            ref,
            authority="Tang Wei field officer commanding a 500-man Qin-owned Black Banner formation; Qin retains administrative troop ownership.",
            duty=duty,
            training_regimen_ref="professional_officer",
        )

    for ref, duty in {
        "char_gao_yun": "500-man Commander, High Guard Qin Reserve A",
        "char_han_qiu": "500-man Commander, High Guard Qin Reserve B",
        "char_duan_jin": "500-man Commander, Red Lance A",
        "char_shen_rui": "500-man Commander, Red Lance B",
    }.items():
        update_person(ref, duty=duty, training_regimen_ref="professional_officer")

    update_person(
        "char_lin_zhen",
        authority="Tang Wei personal retainer; Chief Strategist of Tang Wei Field Army and commander of the 4,500-man High Guard.",
        duty="Commander, High Guard; Chief Strategist, Tang Wei Army",
        training_regimen_ref="elite_command",
    )

    # The local exact commanders already exist. Pei An is the actual Inner Walls
    # command-group commander, so home formations must not route current authority
    # through officers who have left with Tang Wei's field army.
    for rel in sorted((ROOT / "state/formations").glob("house-tang-inner-walls-*.json")):
        doc = json.loads(rel.read_text(encoding="utf-8"))
        if doc.get("command_authority") in {
            "char_sword_manor_trainee_commander",
            "char_sword_manor_junior_commander",
            "char_sword_manor_general_commander",
        }:
            doc["command_authority"] = "char_pei_an"
            rel.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    reconcile_qin_starting_command_hierarchy()

    print(REPAIR_REF)


if __name__ == "__main__":
    main()
