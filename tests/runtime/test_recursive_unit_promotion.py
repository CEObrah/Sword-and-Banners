from sword_runtime.warfare_depth import build_formation_command_structure
import json


def _read(root, path):
    return json.loads((root / path).read_text())


def test_formation_promotes_to_nested_army_with_one_commander_and_conserved_successor(campaign):
    from conftest import execute_production_internal

    parent_ref = "cmdgrp.kankoku.defense_army"
    formation_ref = "formation_qin_kankoku_mobile_reserve"
    army_ref = "cmdgrp.kankoku.mobile_reserve.army"
    before_force = _read(campaign, "state/forces/state-qin.json")
    before_headcount = before_force["headcount"]
    before_form = _read(campaign, "state/formations/qin-kankoku-mobile-reserve.json")
    old_commander = before_form["commander_ref"]
    old_personnel = before_form["personnel"]
    before_internal = list(before_form["embedded_person_refs"])

    result = execute_production_internal(campaign, "command_group_action", {
        "action": "promote_formation_to_army",
        "command_group_ref": parent_ref,
        "formation_ref": formation_ref,
        "subordinate_group_ref": army_ref,
        "display_name": "Kankoku Mobile Reserve Army",
    })

    result = dict(result.receipt.result)
    assert result["promoted_army_ref"] == army_ref
    parent = _read(campaign, "state/cmd/command-groups/cmdgrp.kankoku.defense_army.json")
    assert any(row == {"kind": "nested_army", "ref": army_ref} for row in parent["units"])
    assert not any(row.get("ref") == formation_ref for row in parent["units"])

    army = _read(campaign, "state/cmd/command-groups/cmdgrp.kankoku.mobile_reserve.army.json")
    assert army["commander_ref"] == old_commander
    assert army["units"] == [{"kind": "formation", "ref": formation_ref}]

    after_form = _read(campaign, "state/formations/qin-kankoku-mobile-reserve.json")
    assert after_form["higher_command_ref"] == army_ref
    assert after_form["personnel"] == old_personnel - 1
    assert after_form["commander_ref"] != old_commander
    assert after_form["commander_ref"] != old_commander
    assert army["successor_refs"] == [after_form["commander_ref"]]
    assert result["new_formation_commander_ref"] == after_form["commander_ref"]
    assert result["replacement_embedded_officer_refs"] == ()

    rules = _read(campaign, "game/data/mechanics/warfare-organization.json")
    assert "command_structure" not in after_form
    cadre = build_formation_command_structure(after_form, rules)["officer_cadre"]
    assert sum(int(v) for v in cadre["vacant_billets"].values()) >= 1

    idx = _read(campaign, "state/index/owner-index.json")["owners"]
    ref = after_form["commander_ref"]
    route = idx[ref]
    assert "#/records/" not in route
    person = _read(campaign, route)
    assert person["schema"] == "sword-materialized-person"
    assert person["military_rank"]["durable"] is True
    assert person["military_rank"]["grade"] in {"1000_commander", "500_commander", "100_commander"}
    assert person["command_assignment"]["billet"] == "formation_commander"

    after_force = _read(campaign, "state/forces/state-qin.json")
    assert after_force["headcount"] == before_headcount
    assert after_force["allocated_to_formations"][formation_ref]["personnel"] == old_personnel - 1

