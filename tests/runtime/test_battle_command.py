import json
import subprocess

from conftest import activate_operation, execute_internal
from sword_runtime.battle_command import player_battle_missions
from sword_runtime.engine import RepositoryCommandPlanner

TANG_WEI_FORMATIONS = [
    "formation_red_lance_a", "formation_red_lance_b",
    "formation_high_guard_infantry_01a", "formation_high_guard_infantry_01b",
    "formation_high_guard_infantry_02a", "formation_high_guard_infantry_02b",
    "formation_high_guard_infantry_03a", "formation_high_guard_infantry_03b",
    "formation_high_guard_cavalry",
    "formation_high_guard_qin_a", "formation_high_guard_qin_b",
    "formation_black_banner_01a", "formation_black_banner_01b",
    "formation_black_banner_02a", "formation_black_banner_02b",
    "formation_black_banner_03a", "formation_black_banner_03b",
    "formation_black_banner_04a", "formation_black_banner_04b",
]


def _co_locate(campaign, formation_refs, location_ref):
    owners = json.load(open(campaign / "state/index/owner-index.json"))["owners"]
    touched = []
    for ref in formation_refs:
        path = campaign / owners[ref]
        row = json.load(open(path))
        row["location_ref"] = location_ref
        row["mobilized"] = True
        row["status"] = "ready"
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n")
        touched.append(str(path.relative_to(campaign)))
    subprocess.run(["git", "-C", str(campaign), "add", *touched], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test: co-locate battle commands"], check=True)


def _operation(campaign, operation_ref):
    index = json.load(open(campaign / "state/operations/index.json"))["operations"]
    return json.load(open(campaign / index[operation_ref]))


def test_battle_plan_groups_tang_wei_state_and_house_troops_without_transferring_ownership(campaign):
    qin_refs = TANG_WEI_FORMATIONS + ["formation_qin_ousen_central"]
    wei_refs = ["formation_wei_disciplined_line"]
    all_refs = qin_refs + wei_refs
    location = "loc_kankoku_pass"
    _co_locate(campaign, all_refs, location)
    op = activate_operation(campaign, "operation_battle_command_grouping", all_refs, location=location)
    battlefield = "battlefield_battle_command_grouping"
    execute_internal(campaign, "battlefield_control", {
        "action": "open", "operation_ref": op, "battlefield_ref": battlefield,
        "name": "Command Grouping", "side_refs": ["state_qin", "state_wei"],
        "layout_ref": "battlefield.layout.dynamic",
    })

    doc = _operation(campaign, op)
    bf = doc["battlefields"][battlefield]
    qin = bf["command_plan"]["sides"]["state_qin"]
    assert qin["supreme_commander_ref"] == "char_ousen"
    wei_missions = [row for row in qin["missions"] if row.get("recipient_ref") == "char_tang_wei"]
    assert wei_missions
    # One commander may receive several sector missions on a real battlefield.
    # Authority is preserved if the conserved leaves appear exactly once across
    # those mission blocks; forcing all nineteen into one sector would undo the
    # operational-command/echelon model.
    mission_refs = [ref for row in wei_missions for ref in row["formation_refs"]]
    assert len(mission_refs) == len(set(mission_refs))
    assert set(mission_refs) == set(TANG_WEI_FORMATIONS)
    assert sum(row["personnel"] for row in wei_missions) == 9500

    command_sectors = {}
    for ref in TANG_WEI_FORMATIONS:
        assignment = bf["assignments"][ref]
        command_sectors.setdefault(assignment["operational_command_ref"], set()).add(assignment["sector_ref"])
    assert len(command_sectors) == 3
    assert all(len(sectors) == 1 for sectors in command_sectors.values())

    owners = json.load(open(campaign / "state/index/owner-index.json"))["owners"]
    assert json.load(open(campaign / owners["formation_black_banner_01a"]))["administrative_owner"] == "state_qin"
    assert json.load(open(campaign / owners["formation_high_guard_qin_a"]))["administrative_owner"] == "state_qin"
    assert json.load(open(campaign / owners["formation_red_lance_a"]))["administrative_owner"] == "house_tang"
    assert json.load(open(campaign / owners["formation_high_guard_infantry_01a"]))["administrative_owner"] == "house_tang"


def test_player_mission_projection_contains_friendly_task_but_no_enemy_identity(campaign):
    refs = ["formation_red_lance_a", "formation_qin_ousen_central", "formation_wei_disciplined_line"]
    location = "loc_kankoku_pass"
    _co_locate(campaign, refs, location)
    op = activate_operation(campaign, "operation_battle_command_projection", refs, location=location)
    battlefield = "battlefield_battle_command_projection"
    execute_internal(campaign, "battlefield_control", {
        "action": "open", "operation_ref": op, "battlefield_ref": battlefield,
        "name": "Projection", "side_refs": ["state_qin", "state_wei"],
        "layout_ref": "battlefield.layout.line_three",
    })
    planner = RepositoryCommandPlanner(campaign)
    path = planner.read("state/operations/index.json")["operations"][op]
    bf = planner.read(path)["battlefields"][battlefield]
    views = player_battle_missions(bf, {"formation_red_lance_a"})
    assert len(views) == 1
    view = views[0]
    assert view["recipient_ref"] == "char_tang_wei"
    assert view["issuer_ref"] == "char_ousen"
    serialized = json.dumps(view, sort_keys=True)
    assert "formation_wei_disciplined_line" not in serialized
    assert "state_wei" not in serialized
    assert "enemy_formation_refs" not in serialized


def test_superior_command_directive_reaches_wei_without_auto_obedience(campaign):
    from sword_runtime.battle_command import review_battle_command_plan

    refs = ["formation_red_lance_a", "formation_qin_ousen_central", "formation_wei_disciplined_line"]
    location = "loc_kankoku_pass"
    _co_locate(campaign, refs, location)
    op = activate_operation(campaign, "operation_battle_command_update", refs, location=location)
    battlefield = "battlefield_battle_command_update"
    execute_internal(campaign, "battlefield_control", {
        "action": "open", "operation_ref": op, "battlefield_ref": battlefield,
        "name": "Changing Superior Orders", "side_refs": ["state_qin", "state_wei"],
        "layout_ref": "battlefield.layout.line_three",
    })
    planner = RepositoryCommandPlanner(campaign)
    path = planner.read("state/operations/index.json")["operations"][op]
    operation = planner.read(path)
    bf = operation["battlefields"][battlefield]
    mission = next(row for row in bf["command_plan"]["sides"]["state_qin"]["missions"] if row.get("recipient_ref") == "char_tang_wei")
    sector = bf["sectors"][mission["sector_ref"]]
    sector["pressure_milli"]["state_qin"] = 930
    sector["pressure_milli"]["state_wei"] = 300
    before_orders = {ref: bf["assignments"][ref]["order"] for ref in mission["formation_refs"]}

    changes = review_battle_command_plan(planner, operation, bf, at=str(planner._world_time()))
    directive = next(row for row in changes if row["kind"] == "player_superior_directive_queued")
    assert directive["issuer_ref"] == "char_ousen"
    assert directive["directive"] == "withdraw_or_seek_immediate_relief"
    assert directive["desired_order"] == "withdraw"
    assert {ref: bf["assignments"][ref]["order"] for ref in mission["formation_refs"]} == before_orders
    report = next(row for row in bf["reports"] if row.get("report_id") == directive["report_id"])
    assert report["level"] == "new_order"
    assert report["mission_ref"] == mission["mission_ref"]
    assert report["interrupt_player"] is True


def test_home_side_defends_and_invading_side_attacks_by_default(campaign):
    refs = ["formation_red_lance_a", "formation_wei_disciplined_line"]
    location = "loc_kankoku_pass"
    _co_locate(campaign, refs, location)
    op = activate_operation(campaign, "operation_battle_command_posture", refs, location=location)
    battlefield = "battlefield_battle_command_posture"
    execute_internal(campaign, "battlefield_control", {
        "action": "open", "operation_ref": op, "battlefield_ref": battlefield,
        "name": "Home Ground Posture", "side_refs": ["state_qin", "state_wei"],
        "layout_ref": "battlefield.layout.line_three",
    })
    bf = _operation(campaign, op)["battlefields"][battlefield]
    qin_orders = {row["order"] for row in bf["command_plan"]["sides"]["state_qin"]["missions"]}
    wei_orders = {row["order"] for row in bf["command_plan"]["sides"]["state_wei"]["missions"]}
    assert qin_orders == {"hold"}
    assert wei_orders == {"attack"}


def test_command_review_enemy_estimate_does_not_read_hidden_enemy_condition(campaign):
    from sword_runtime.battle_command import _observed_enemy_sector_strength

    refs = ["formation_red_lance_a", "formation_wei_disciplined_line"]
    location = "loc_kankoku_pass"
    _co_locate(campaign, refs, location)
    op = activate_operation(campaign, "operation_battle_command_epistemic", refs, location=location)
    battlefield = "battlefield_battle_command_epistemic"
    execute_internal(campaign, "battlefield_control", {
        "action": "open", "operation_ref": op, "battlefield_ref": battlefield,
        "name": "Epistemic Command Review", "side_refs": ["state_qin", "state_wei"],
        "layout_ref": "battlefield.layout.line_three",
    })
    planner = RepositoryCommandPlanner(campaign)
    path = planner.read("state/operations/index.json")["operations"][op]
    bf = planner.read(path)["battlefields"][battlefield]
    enemy_assignment = bf["assignments"]["formation_wei_disciplined_line"]
    sector_ref = enemy_assignment["sector_ref"]
    before = _observed_enemy_sector_strength(planner, bf, sector_ref, "state_wei", pressure_milli=350)

    owners = planner.read("state/index/owner-index.json")["owners"]
    enemy_path = campaign / owners["formation_wei_disciplined_line"]
    enemy = json.load(open(enemy_path))
    enemy["morale"] = 1
    enemy["readiness"] = 1
    enemy["cohesion"] = 1
    enemy["fatigue"] = 100
    enemy.setdefault("logistics", {})["war_arrows"] = 0
    enemy_path.write_text(json.dumps(enemy, ensure_ascii=False, indent=2) + "\n")

    after = _observed_enemy_sector_strength(planner, bf, sector_ref, "state_wei", pressure_milli=350)
    assert after == before
    assert after["basis"] == "coarse_observed_mass_plus_sector_contact_pressure"


def test_campaign_commander_field_overrides_stat_based_battle_supreme_command(campaign):
    refs = TANG_WEI_FORMATIONS + ["formation_qin_ousen_central", "formation_wei_disciplined_line"]
    location = "loc_kankoku_pass"
    _co_locate(campaign, refs, location)
    op = activate_operation(campaign, "operation_campaign_commander_override", refs, location=location)
    planner = RepositoryCommandPlanner(campaign)
    path = planner.read("state/operations/index.json")["operations"][op]
    operation_path = campaign / path
    operation = json.load(open(operation_path))
    operation["campaign_commander_ref"] = "char_tang_wei"
    operation_path.write_text(json.dumps(operation, ensure_ascii=False, indent=2) + "\n")
    subprocess.run(["git", "-C", str(campaign), "add", path], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test: appoint campaign commander"], check=True)
    execute_internal(campaign, "battlefield_control", {
        "action": "open", "operation_ref": op, "battlefield_ref": "battlefield_campaign_commander_override",
        "name": "Explicit Campaign Command", "side_refs": ["state_qin", "state_wei"],
        "layout_ref": "battlefield.layout.line_three",
    })
    doc = _operation(campaign, op)
    qin = doc["battlefields"]["battlefield_campaign_commander_override"]["command_plan"]["sides"]["state_qin"]
    assert qin["supreme_commander_ref"] == "char_tang_wei"

