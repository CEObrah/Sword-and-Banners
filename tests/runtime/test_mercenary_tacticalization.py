from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import activate_operation, execute_production, execute_production_internal
from sword_runtime.cohort_personnel import validate_cohort_ledger
from sword_runtime.production_planner import ProductionCampaignPlanner


def _planner(campaign: Path) -> ProductionCampaignPlanner:
    planner = ProductionCampaignPlanner(campaign)
    planner.PLAYER_ACTOR = "char_tang_wei"
    planner._reset()
    return planner


def _formation_path(ref: str) -> str:
    return f"state/formations/{ref.replace('formation_', '').replace('_', '-')}.json"


def _company_total(company: dict) -> int:
    return max(0, int(company.get("headcount", company.get("count", 0)) or 0))


def test_state_field_contracts_demand_load_normal_conserved_formations(campaign: Path) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())

    # The canonical market is allowed to evolve. Derive the employers' current
    # exact field obligations from authoritative company owners instead of
    # pinning this regression to three historical company ids.
    owner_index = planner.read("state/index/owner-index.json").get("owners", {})
    expected_owners: set[str] = set()
    for owner_ref, route in sorted(owner_index.items()):
        if not isinstance(owner_ref, str) or not isinstance(route, str) or not route.startswith("state/merc/"):
            continue
        company = planner.read(route)
        if planner._mercenary_live_contract(company, employer_ref="state_qin", field_only=True) is not None:
            expected_owners.add(owner_ref)

    assert expected_owners
    refs = planner._tactical_mercenary_formations_for_employer("state_qin", at=at)
    assert refs
    owners = {planner._load_formation(ref)[1]["owner_force_ref"] for ref in refs}
    assert owners == expected_owners

    for formation_ref in refs:
        _, formation = planner._load_formation(formation_ref)
        company = planner.read(planner.owner_path(str(formation["owner_force_ref"])))
        assert formation["schema"] == "sword-formation"
        assert formation["tactical_formation_ref"] if "tactical_formation_ref" in formation else True
        assert company["tactical_formation_ref"] == formation_ref
        assert company["accounting_only"] is False
        assert formation["personnel"] > 0
        assert formation["authorized_strength"] >= formation["personnel"]
        assert sum(int(v) for v in formation["attached_unit_command_by_role"].values()) == 1
        assert planner._combat_command_admission(formation)["aggregate_unit_post"] is True
        rows = planner._combat_cohort_snapshot(formation, company)
        assert rows
        assert sum(int(row["count"]) for row in rows) == int(formation["personnel"])
        assert all(row.get("loadout_id") for row in rows)
        validate_cohort_ledger(company)
        assert _company_total(company) == int(formation["personnel"]) + sum(
            int(v)
            for roles in company.get("external_personnel_allocations", {}).values()
            for v in roles.values()
        ) + sum(int(v) for v in company.get("available_by_role", {}).values())


def test_mercenary_catastrophic_losses_preserve_source_pool_identity(campaign: Path) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    ref = planner._materialize_mercenary_tactical_formation(
        "merc.major.09", employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert ref
    before = planner._load_formation(ref)[1]
    # Leave one rank-and-file survivor plus the one conserved aggregate command
    # body. This catches reconstruction bugs where low post-battle pool counts
    # could otherwise cause the final fighting survivor to vanish.
    planner._autonomy_apply_battle_losses(
        ref,
        int(before["personnel"]) - 1,
        at,
        losing_side=True,
        opponent_state="zhao",
        seed_material="mercenary-catastrophic-loss-regression",
    )
    formation = planner._load_formation(ref)[1]
    company = planner.read(planner.owner_path("merc.major.09"))
    assert formation["personnel"] == 1
    assert company["headcount"] == 2
    assert sum(int(row["count"]) for row in company["troop_pools"]) == 2
    assert sum(int(v) for roles in company["external_personnel_allocations"].values() for v in roles.values()) == 1
    validate_cohort_ledger(company)


def test_regional_tactical_owner_retires_back_to_cold_market_without_orphan(campaign: Path) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    company_ref = "merc.regional.72"

    # This regional company is intentionally cold/aggregate in the canonical
    # save. Materialize it because a concrete field contract makes it causally
    # relevant, then prove it can return all the way to the aggregate market.
    company_path = planner._materialize_regional_mercenary(company_ref, at)
    company = json.loads(json.dumps(planner.read(company_path)))
    field_kind = sorted(str(x) for x in planner._mercenary_tactical_rules()["field_contract_kinds"])[0]
    company["contracts"] = [{
        "contract_ref": "contract.test.regional.tactical.retirement",
        "employer_ref": "state_qin",
        "status": "active",
        "engagement_kind": field_kind,
        "active_at": at,
        "deployment_location_ref": company["current_location_ref"],
    }]
    company["status"] = "contracted"
    planner.put(company_path, company)

    formation_ref = planner._materialize_mercenary_tactical_formation(
        company_ref, employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert formation_ref
    company = json.loads(json.dumps(planner.read(company_path)))
    company["contracts"][0]["status"] = "completed"
    company["contracts"][0]["completed_at"] = at
    planner.put(company_path, company)

    assert planner._retire_mercenary_tactical_formation(company_ref, at=at) is True
    retired = planner.read(company_path)
    assert retired["accounting_only"] is True
    assert retired["count"] == 1400
    assert "headcount" not in retired
    assert "cohort_ledger" not in retired
    assert "tactical_formation_ref" not in retired
    assert "equipment_and_mounts" not in retired
    assert planner.read_optional(_formation_path(formation_ref)) is None
    owners = planner.read("state/index/owner-index.json")["owners"]
    assert formation_ref not in owners

    assert planner._aggregate_idle_regional_mercenary(company_ref, at) is True
    owners = planner.read("state/index/owner-index.json")["owners"]
    assert company_ref not in owners
    regional = planner.read("state/merc/regional.json")
    entry = next(row for row in regional["entries"] if row.get("id") == company_ref)
    assert entry["materialized"] is False
    assert entry["status"] == "available"
    assert entry["count"] == 1400
    assert "path" not in entry


def test_house_tang_contract_deploy_and_complete_controls_tactical_lifecycle(campaign: Path) -> None:
    company_ref = "merc.major.11"
    contract_ref = "contract.test.mercenary.tactical.lifecycle"
    execute_production(campaign, "mercenary_contract", {
        "mercenary_ref": company_ref,
        "action": "offer",
        "contract_ref": contract_ref,
        "amount_silver": 1000,
        "term_days": 30,
    })
    execute_production_internal(campaign, "mercenary_contract", {
        "mercenary_ref": company_ref,
        "action": "accept",
        "contract_ref": contract_ref,
    })
    execute_production(campaign, "mercenary_contract", {
        "mercenary_ref": company_ref,
        "action": "pay",
        "contract_ref": contract_ref,
        "amount_silver": 1000,
    })
    deployed = execute_production(campaign, "mercenary_contract", {
        "mercenary_ref": company_ref,
        "action": "deploy",
        "contract_ref": contract_ref,
        "location_ref": "loc_qin_regional_01",
    }).receipt.result
    formation_ref = deployed.get("tactical_formation_ref")
    assert isinstance(formation_ref, str) and formation_ref

    owner_index = json.load(open(campaign / "state/index/owner-index.json"))["owners"]
    formation = json.load(open(campaign / owner_index[formation_ref]))
    company = json.load(open(campaign / owner_index[company_ref]))
    assert formation["owner_force_ref"] == company_ref
    assert company["tactical_formation_ref"] == formation_ref
    assert company["accounting_only"] is False

    completed = execute_production(campaign, "mercenary_contract", {
        "mercenary_ref": company_ref,
        "action": "complete",
        "contract_ref": contract_ref,
    }).receipt.result
    assert completed.get("tactical_formation_retired") is True
    owner_index = json.load(open(campaign / "state/index/owner-index.json"))["owners"]
    assert formation_ref not in owner_index
    company = json.load(open(campaign / owner_index[company_ref]))
    assert company["accounting_only"] is True
    assert "tactical_formation_ref" not in company
    assert "cohort_ledger" not in company
    runtime = json.load(open(campaign / "state/runtime.json"))
    merc_hosts = [
        (host_ref, host) for host_ref, host in runtime.get("hosts", {}).items()
        if host.get("kind") == "mercenary" and host.get("owner_ref") == company_ref
    ]
    assert merc_hosts == []
    canonical_host = f"host_merc_{company_ref.replace('.', '_')}"
    assert all(
        event.get("target_host") != canonical_host
        for event in runtime.get("events", [])
        if isinstance(event, dict)
    )


def test_deployed_mercenary_executes_through_normal_battle_and_syncs_casualties(campaign: Path) -> None:
    company_ref = "merc.major.11"
    contract_ref = "contract.test.mercenary.actual.battle"
    execute_production(campaign, "mercenary_contract", {
        "mercenary_ref": company_ref,
        "action": "offer",
        "contract_ref": contract_ref,
        "amount_silver": 1000,
        "term_days": 30,
    })
    execute_production_internal(campaign, "mercenary_contract", {
        "mercenary_ref": company_ref,
        "action": "accept",
        "contract_ref": contract_ref,
    })
    execute_production(campaign, "mercenary_contract", {
        "mercenary_ref": company_ref,
        "action": "pay",
        "contract_ref": contract_ref,
        "amount_silver": 1000,
    })
    deployed = execute_production(campaign, "mercenary_contract", {
        "mercenary_ref": company_ref,
        "action": "deploy",
        "contract_ref": contract_ref,
        "location_ref": "loc_qin_regional_01",
    }).receipt.result
    formation_ref = str(deployed["tactical_formation_ref"])
    opponent_ref = "formation_house_mou_family_01"
    execute_production_internal(campaign, "formation_mobilize", {"formation_ref": opponent_ref})
    operation_ref = "operation_test_mercenary_actual_battle"
    activate_operation(campaign, operation_ref, [formation_ref, opponent_ref], location="loc_qin_regional_01")

    before_owner = json.load(open(campaign / json.load(open(campaign / "state/index/owner-index.json"))["owners"][company_ref]))
    before = _company_total(before_owner)
    result = execute_production_internal(campaign, "battle_resolve", {
        "attacker_formation_refs": [formation_ref],
        "defender_formation_refs": [opponent_ref],
        "operation_ref": operation_ref,
        "objective": "mercenary production combat integration regression",
    }).receipt.result
    owner_index = json.load(open(campaign / "state/index/owner-index.json"))["owners"]
    company = json.load(open(campaign / owner_index[company_ref]))
    formation = json.load(open(campaign / owner_index[formation_ref]))
    assert result["represented_personnel"] > 0
    assert _company_total(company) <= before
    assert _company_total(company) == int(formation["personnel"]) + sum(
        int(v)
        for roles in company.get("external_personnel_allocations", {}).values()
        for v in roles.values()
    ) + sum(int(v) for v in company.get("available_by_role", {}).values())
    validate_cohort_ledger(company)


def test_deploy_fails_closed_when_tactical_formation_cannot_materialize(campaign: Path, monkeypatch) -> None:
    company_ref = "merc.major.11"
    contract_ref = "contract.test.mercenary.fail.closed"
    execute_production(campaign, "mercenary_contract", {
        "mercenary_ref": company_ref,
        "action": "offer",
        "contract_ref": contract_ref,
        "amount_silver": 1000,
        "term_days": 30,
    })
    execute_production_internal(campaign, "mercenary_contract", {
        "mercenary_ref": company_ref,
        "action": "accept",
        "contract_ref": contract_ref,
    })
    execute_production(campaign, "mercenary_contract", {
        "mercenary_ref": company_ref,
        "action": "pay",
        "contract_ref": contract_ref,
        "amount_silver": 1000,
    })
    monkeypatch.setattr(ProductionCampaignPlanner, "_materialize_mercenary_tactical_formation", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="could not materialize a conserved tactical formation"):
        execute_production(campaign, "mercenary_contract", {
            "mercenary_ref": company_ref,
            "action": "deploy",
            "contract_ref": contract_ref,
            "location_ref": "loc_qin_regional_01",
        })


def test_expired_contract_detaches_from_active_operation_and_retires_without_dangling_ref(campaign: Path) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    company_ref = "merc.major.09"
    formation_ref = planner._materialize_mercenary_tactical_formation(
        company_ref, employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert formation_ref

    operation_ref = "operation_test_expired_mercenary_withdrawal"
    operation_path = f"state/operations/{operation_ref}.json"
    operation = {
        "schema": "sword-operation",
        "operation_ref": operation_ref,
        "status": "active",
        "formation_refs": [formation_ref],
        "objective": "hold current operational assignment until contractor withdrawal is acknowledged",
        "updated_at": at,
    }
    planner.put(operation_path, operation)
    index = json.loads(json.dumps(planner.read("state/operations/index.json")))
    index.setdefault("operations", {})[operation_ref] = operation_path
    planner.put("state/operations/index.json", index)

    company_path = planner.owner_path(company_ref)
    company = json.loads(json.dumps(planner.read(company_path)))
    for contract in company.get("contracts", []):
        if contract.get("status") == "active":
            contract["status"] = "completed"
            contract["completed_at"] = at
    planner.put(company_path, company)

    assert planner._retire_mercenary_tactical_formation(company_ref, at=at) is True
    retired = planner.read(company_path)
    assert retired["status"] == "available"
    assert retired["accounting_only"] is True
    assert "tactical_retirement_pending" not in retired
    assert formation_ref not in planner.read(operation_path)["formation_refs"]
    assert planner.read_optional(_formation_path(formation_ref)) is None


def test_interstate_plan_prunes_expired_mercenary_before_tactical_retirement(campaign: Path) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    company_ref = "merc.major.09"
    formation_ref = planner._materialize_mercenary_tactical_formation(
        company_ref, employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert formation_ref

    world_path = "state/politics/interstate-history.json"
    world = json.loads(json.dumps(planner.read(world_path)))
    theater_ref = "theater_test_expired_mercenary"
    world.setdefault("theaters", {})[theater_ref] = {
        "phase": "advancing",
        "attacker_state": "qin",
        "defender_state": "zhao",
        "formation_groups": {"qin": [formation_ref], "zhao": []},
        "army_groups": {"qin": {"primary_ref": formation_ref, "formation_refs": [formation_ref]}},
        "strategic_plan": {
            "fronts": [{
                "front_ref": "front_test_expired_mercenary",
                "attacker_formation_refs": [formation_ref],
                "defender_formation_refs": [],
            }],
            "formation_objectives": {"qin": {formation_ref: "loc_test"}},
            "strategic_reserve_formation_refs": {"qin": [formation_ref]},
        },
    }
    planner.put(world_path, world)

    company_path = planner.owner_path(company_ref)
    company = json.loads(json.dumps(planner.read(company_path)))
    for contract in company.get("contracts", []):
        if contract.get("status") == "active":
            contract["status"] = "completed"
            contract["completed_at"] = at
    planner.put(company_path, company)
    assert planner._retire_mercenary_tactical_formation(company_ref, at=at) is True

    current = planner.read(world_path)["theaters"][theater_ref]
    serialized = json.dumps({
        "formation_groups": current.get("formation_groups"),
        "army_groups": current.get("army_groups"),
        "strategic_plan": current.get("strategic_plan"),
    })
    assert formation_ref not in serialized

    assert planner.read_optional(_formation_path(formation_ref)) is None


def _complete_live_mercenary_contract(planner: ProductionCampaignPlanner, company_ref: str, at: str) -> None:
    path = planner.owner_path(company_ref)
    company = json.loads(json.dumps(planner.read(path)))
    for contract in company.get("contracts", []):
        if contract.get("status") == "active":
            contract["status"] = "completed"
            contract["completed_at"] = at
    company["status"] = "available"
    planner.put(path, company)


def test_expired_mercenary_detaches_from_operation_and_operational_battlefield(campaign: Path) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    company_ref = "merc.major.09"
    formation_ref = planner._materialize_mercenary_tactical_formation(
        company_ref, employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert formation_ref
    enemy_ref = "formation_zhao_border_line"
    operation_ref = "operation_test_mercenary_expiry"
    operation_path = f"state/operations/{operation_ref}.json"
    battlefield_ref = "battlefield_test_mercenary_expiry"
    qin_sector = f"{battlefield_ref}.sector.qin"
    zhao_sector = f"{battlefield_ref}.sector.zhao"
    operation = {
        "schema": "sword-operation",
        "operation_ref": operation_ref,
        "status": "active",
        "formation_refs": [formation_ref, enemy_ref],
        "battlefields": {
            battlefield_ref: {
                "schema": "sword-operational-battlefield",
                "battlefield_ref": battlefield_ref,
                "status": "active",
                "assignments": {
                    formation_ref: {"formation_ref": formation_ref, "side_ref": "state_qin", "sector_ref": qin_sector, "status": "holding"},
                    enemy_ref: {"formation_ref": enemy_ref, "side_ref": "state_zhao", "sector_ref": zhao_sector, "status": "holding"},
                },
                "sectors": {
                    qin_sector: {"formation_refs": [formation_ref]},
                    zhao_sector: {"formation_refs": [enemy_ref]},
                },
                "command_plan": {"plan_ref": "stale_test_plan", "mission_index": {"m": {"formation_refs": [formation_ref]}}},
            }
        },
    }
    planner.put(operation_path, operation)
    op_index = json.loads(json.dumps(planner.read("state/operations/index.json")))
    op_index.setdefault("operations", {})[operation_ref] = operation_path
    op_index.setdefault("active_battlefield_operation_refs", []).append(operation_ref)
    planner.put("state/operations/index.json", op_index)

    _complete_live_mercenary_contract(planner, company_ref, at)
    assert planner._retire_mercenary_tactical_formation(company_ref, at=at) is True

    operation = planner.read(operation_path)
    battlefield = operation["battlefields"][battlefield_ref]
    assert formation_ref not in operation["formation_refs"]
    assert formation_ref not in battlefield["assignments"]
    assert formation_ref not in battlefield["sectors"][qin_sector]["formation_refs"]
    assert battlefield["status"] == "ended"
    assert operation_ref not in planner.read("state/operations/index.json")["active_battlefield_operation_refs"]
    assert formation_ref not in planner.read("state/index/owner-index.json")["owners"]


def test_expired_attacking_mercenary_lifts_its_last_siege_without_orphan(campaign: Path) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    company_ref = "merc.major.09"
    formation_ref = planner._materialize_mercenary_tactical_formation(
        company_ref, employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert formation_ref
    siege_ref = "siege_test_mercenary_attacker_expiry"
    siege_path = f"state/sieges/{siege_ref}.json"
    planner.put(siege_path, {
        "schema": "sword-siege",
        "siege_ref": siege_ref,
        "status": "active",
        "attacker_formation_refs": [formation_ref],
        "defender_formation_refs": ["formation_zhao_border_line"],
    })
    siege_index = json.loads(json.dumps(planner.read("state/sieges/index.json")))
    siege_index.setdefault("sieges", {})[siege_ref] = siege_path
    planner.put("state/sieges/index.json", siege_index)

    _complete_live_mercenary_contract(planner, company_ref, at)
    assert planner._retire_mercenary_tactical_formation(company_ref, at=at) is True
    siege = planner.read(siege_path)
    assert siege["status"] == "lifted"
    assert siege["attacker_formation_refs"] == []
    assert formation_ref not in planner.read("state/index/owner-index.json")["owners"]


def test_expired_besieged_mercenary_remains_conserved_until_siege_ends(campaign: Path) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    company_ref = "merc.major.09"
    formation_ref = planner._materialize_mercenary_tactical_formation(
        company_ref, employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert formation_ref
    siege_ref = "siege_test_mercenary_defender_holdover"
    siege_path = f"state/sieges/{siege_ref}.json"
    planner.put(siege_path, {
        "schema": "sword-siege",
        "siege_ref": siege_ref,
        "status": "active",
        "attacker_formation_refs": ["formation_zhao_border_line"],
        "defender_formation_refs": [formation_ref],
    })
    siege_index = json.loads(json.dumps(planner.read("state/sieges/index.json")))
    siege_index.setdefault("sieges", {})[siege_ref] = siege_path
    planner.put("state/sieges/index.json", siege_index)

    _complete_live_mercenary_contract(planner, company_ref, at)
    assert planner._retire_mercenary_tactical_formation(company_ref, at=at) is False
    company = planner.read(planner.owner_path(company_ref))
    formation = planner._load_formation(formation_ref)[1]
    assert company["status"] == "contract_complete_holdover"
    assert company["tactical_retirement_pending"]["formation_ref"] == formation_ref
    assert formation["status"] == "contract_complete_holdover"
    assert formation["administrative_owner"] == company_ref
    assert formation["command_authority"] == company_ref
    assert formation_ref in planner.read(siege_path)["defender_formation_refs"]

    siege = json.loads(json.dumps(planner.read(siege_path)))
    siege["status"] = "lifted"
    siege["lifted_at"] = at
    planner.put(siege_path, siege)
    assert planner._retire_mercenary_tactical_formation(company_ref, at=at) is True
    assert formation_ref not in planner.read("state/index/owner-index.json")["owners"]


def test_active_field_contract_is_a_real_independent_interstate_command_not_dead_unassigned_state(campaign: Path) -> None:
    from sword_runtime.strategic_war_planning import build_interstate_strategic_plan

    planner = _planner(campaign)
    at = str(planner._world_time())
    mercenary_ref = "merc.major.09"
    mercenary_formation = planner._materialize_mercenary_tactical_formation(
        mercenary_ref, employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert mercenary_formation
    config = planner._interstate_theater_config(planner.read("game/data/world/autonomous-theaters.json"))
    theater = next(row for row in config["theaters"] if row["theater_ref"] == "qin_zhao_gyou")
    qin_refs = list(theater["formation_ref_lists"]["qin"]) + [mercenary_formation]
    plan = build_interstate_strategic_plan(
        planner,
        theater_ref="test_mercenary_initial_war_admission",
        attacker="qin",
        defender="zhao",
        primary_target="loc_gyou",
        attacker_formation_refs=qin_refs,
        defender_formation_refs=theater["formation_ref_lists"]["zhao"],
        at=at,
    )
    tracked = set(plan["formation_objectives"]["qin"]) | set(plan["strategic_reserve_formation_refs"]["qin"])
    assert mercenary_formation in tracked
    assert mercenary_formation not in set(plan["unassigned_formation_refs"]["qin"])
    rows = list(plan["command_assignments"]["qin"]) + list(plan["strategic_reserve_commands"]["qin"])
    command = next(row for row in rows if mercenary_formation in row.get("formation_refs", []))
    assert command["independent_formation_ref"] == mercenary_formation
    assert command["context"] == "standalone_mobilized_commitment"


def test_new_field_contractor_can_enter_an_already_active_war_as_strategic_reserve(campaign: Path) -> None:
    from sword_runtime.strategic_war_planning import build_interstate_strategic_plan, integrate_reinforcement_reserves

    planner = _planner(campaign)
    at = str(planner._world_time())
    config = planner._interstate_theater_config(planner.read("game/data/world/autonomous-theaters.json"))
    theater = next(row for row in config["theaters"] if row["theater_ref"] == "qin_zhao_gyou")
    plan = build_interstate_strategic_plan(
        planner,
        theater_ref="test_mercenary_midwar_reinforcement",
        attacker="qin",
        defender="zhao",
        primary_target="loc_gyou",
        attacker_formation_refs=theater["formation_ref_lists"]["qin"],
        defender_formation_refs=theater["formation_ref_lists"]["zhao"],
        at=at,
    )
    mercenary_formation = planner._materialize_mercenary_tactical_formation(
        "merc.major.09", employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert mercenary_formation
    result = integrate_reinforcement_reserves(
        planner, plan, side="qin", formation_refs=[mercenary_formation], at=at
    )
    assert result["added_formation_refs"] == [mercenary_formation]
    assert mercenary_formation in plan["strategic_reserve_formation_refs"]["qin"]
    assert any(
        row.get("independent_formation_ref") == mercenary_formation
        for row in plan["strategic_reserve_commands"]["qin"]
    )
    # Reconciliation is idempotent and cannot duplicate the reserve command.
    again = integrate_reinforcement_reserves(
        planner, plan, side="qin", formation_refs=[mercenary_formation], at=at
    )
    assert again["added_formation_refs"] == []
    assert sum(
        1 for row in plan["strategic_reserve_commands"]["qin"]
        if row.get("independent_formation_ref") == mercenary_formation
    ) == 1


def test_active_interstate_review_discovers_and_admits_new_field_contractors(campaign: Path) -> None:
    from copy import deepcopy
    from sword_runtime.strategic_war_planning import build_interstate_strategic_plan

    planner = _planner(campaign)
    config = planner._interstate_theater_config(planner.read("game/data/world/autonomous-theaters.json"))
    theater_cfg = next(row for row in config["theaters"] if row["theater_ref"] == "qin_zhao_gyou")
    host = deepcopy(planner.read("state/runtime.json")["hosts"]["host_interstate_wars"])
    at = str(host["next_due"])
    plan = build_interstate_strategic_plan(
        planner,
        theater_ref="qin_zhao_gyou",
        attacker="qin",
        defender="zhao",
        primary_target=str(theater_cfg["target_location_ref"]),
        attacker_formation_refs=theater_cfg["formation_ref_lists"]["qin"],
        defender_formation_refs=theater_cfg["formation_ref_lists"]["zhao"],
        at=at,
    )
    selected = {
        side: sorted(set(plan["formation_objectives"][side]) | set(plan["strategic_reserve_formation_refs"][side]))
        for side in ("qin", "zhao")
    }
    world_path = planner.owner_path("interstate_warring_states")
    world = deepcopy(planner.read(world_path))
    record = world["theaters"]["qin_zhao_gyou"]
    record.update({
        "phase": "advancing",
        "cycle": max(1, int(record.get("cycle", 0))),
        "attacker_state": "qin",
        "defender_state": "zhao",
        "started_at": at,
        "battle_count": 0,
        "strategic_plan": plan,
        "formation_groups": deepcopy(selected),
        "army_groups": {
            side: {
                "primary_ref": refs[0],
                "formation_refs": list(refs),
                "reserve_refs": list(plan["strategic_reserve_formation_refs"][side]),
            }
            for side, refs in selected.items()
        },
    })
    planner.put(world_path, world)
    before = set(selected["qin"])

    planner._autonomy_interstate(host, 1, at)

    current = planner.read(world_path)["theaters"]["qin_zhao_gyou"]
    qin_group = set(current["formation_groups"]["qin"])
    added = qin_group - before
    assert added
    merc_added = []
    for ref in added:
        formation = planner._load_formation(ref)[1]
        owner = planner.read(planner.owner_path(str(formation.get("owner_force_ref", ""))))
        if owner.get("schema") in {"mercenary", "mercenary-company", "regional-mercenary-company"}:
            merc_added.append(ref)
    assert merc_added
    active_plan = current["strategic_plan"]
    for ref in merc_added:
        assert ref in set(active_plan["formation_objectives"]["qin"]) | set(active_plan["strategic_reserve_formation_refs"]["qin"])
    assert any(row.get("event") == "reinforcement_entered_strategic_reserve" for row in current.get("history", []))


def test_mercenary_casualty_sync_fails_closed_on_conservation_error(campaign: Path, monkeypatch) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    formation_ref = planner._materialize_mercenary_tactical_formation(
        "merc.major.09", employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert formation_ref

    def broken_sync(self, mercenary_ref: str) -> None:
        if mercenary_ref == "merc.major.09":
            raise ValueError("synthetic mercenary conservation failure")

    monkeypatch.setattr(ProductionCampaignPlanner, "_sync_mercenary_tactical_company", broken_sync)
    with pytest.raises(ValueError, match="synthetic mercenary conservation failure"):
        planner._autonomy_apply_battle_losses(
            formation_ref, 1, at, losing_side=True, opponent_state="zhao",
            seed_material="mercenary-fail-closed-casualty-sync",
        )


def _seed_active_qin_zhao_theater_without_mercenary(
    planner: ProductionCampaignPlanner, *, at: str
) -> tuple[dict, set[str]]:
    """Create one valid active Qin-Zhao strategic plan before a new contractor appears."""
    from copy import deepcopy
    from sword_runtime.strategic_war_planning import build_interstate_strategic_plan

    config = planner._interstate_theater_config(planner.read("game/data/world/autonomous-theaters.json"))
    theater_cfg = next(row for row in config["theaters"] if row["theater_ref"] == "qin_zhao_gyou")
    plan = build_interstate_strategic_plan(
        planner,
        theater_ref="qin_zhao_gyou",
        attacker="qin",
        defender="zhao",
        primary_target=str(theater_cfg["target_location_ref"]),
        attacker_formation_refs=theater_cfg["formation_ref_lists"]["qin"],
        defender_formation_refs=theater_cfg["formation_ref_lists"]["zhao"],
        at=at,
    )
    selected = {
        side: sorted(set(plan["formation_objectives"][side]) | set(plan["strategic_reserve_formation_refs"][side]))
        for side in ("qin", "zhao")
    }
    world_path = planner.owner_path("interstate_warring_states")
    world = deepcopy(planner.read(world_path))
    record = world["theaters"]["qin_zhao_gyou"]
    record.update({
        "phase": "advancing",
        "cycle": max(1, int(record.get("cycle", 0))),
        "attacker_state": "qin",
        "defender_state": "zhao",
        "started_at": at,
        "battle_count": 0,
        "strategic_plan": plan,
        "formation_groups": deepcopy(selected),
        "army_groups": {
            side: {
                "primary_ref": refs[0],
                "formation_refs": list(refs),
                "reserve_refs": list(plan["strategic_reserve_formation_refs"][side]),
            }
            for side, refs in selected.items()
        },
    })
    planner.put(world_path, world)
    return selected, set(selected["qin"])


def test_interstate_reinforcement_cannot_duplicate_a_formation_committed_to_another_theater(campaign: Path) -> None:
    from copy import deepcopy

    planner = _planner(campaign)
    host = deepcopy(planner.read("state/runtime.json")["hosts"]["host_interstate_wars"])
    at = str(host["next_due"])
    _selected, before = _seed_active_qin_zhao_theater_without_mercenary(planner, at=at)
    mercenary_formation = planner._materialize_mercenary_tactical_formation(
        "merc.major.09", employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert mercenary_formation and mercenary_formation not in before

    world_path = planner.owner_path("interstate_warring_states")
    world = deepcopy(planner.read(world_path))
    # This synthetic active theater is enough to represent an exact already-saved
    # commitment. It is intentionally outside the configured theater loop so the
    # reservation cannot disappear earlier in the same review.
    world["theaters"]["test_other_qin_active_theater"] = {
        "phase": "advancing",
        "cycle": 1,
        "attacker_state": "qin",
        "defender_state": "wei",
        "formation_groups": {"qin": [mercenary_formation], "wei": []},
        "history": [],
    }
    planner.put(world_path, world)

    planner._autonomy_interstate(host, 1, at)

    current = planner.read(world_path)["theaters"]["qin_zhao_gyou"]
    assert mercenary_formation not in current["formation_groups"]["qin"]
    plan = current["strategic_plan"]
    assert mercenary_formation not in set(plan["formation_objectives"]["qin"])
    assert mercenary_formation not in set(plan["strategic_reserve_formation_refs"]["qin"])


def test_interstate_reinforcement_cannot_duplicate_a_formation_in_an_active_operation(campaign: Path) -> None:
    from copy import deepcopy

    planner = _planner(campaign)
    host = deepcopy(planner.read("state/runtime.json")["hosts"]["host_interstate_wars"])
    at = str(host["next_due"])
    _selected, before = _seed_active_qin_zhao_theater_without_mercenary(planner, at=at)
    mercenary_formation = planner._materialize_mercenary_tactical_formation(
        "merc.major.09", employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert mercenary_formation and mercenary_formation not in before

    operation_ref = "operation_test_reserved_mercenary_elsewhere"
    operation_path = f"state/operations/{operation_ref}.json"
    planner.put(operation_path, {
        "schema": "sword-operation",
        "owner_id": operation_ref,
        "operation_ref": operation_ref,
        "objective": "hold a separate exact military commitment",
        "status": "active",
        "location_ref": planner._load_formation(mercenary_formation)[1]["location_ref"],
        "formation_refs": [mercenary_formation],
        "administrative_authorities": ["state_qin"],
        "administrative_authority": "state_qin",
        "contested": False,
        "created_at": at,
    })
    operation_index = deepcopy(planner.read("state/operations/index.json"))
    operation_index.setdefault("operations", {})[operation_ref] = operation_path
    planner.put("state/operations/index.json", operation_index)

    planner._autonomy_interstate(host, 1, at)

    current = planner.read(planner.owner_path("interstate_warring_states"))["theaters"]["qin_zhao_gyou"]
    assert mercenary_formation not in current["formation_groups"]["qin"]
    plan = current["strategic_plan"]
    assert mercenary_formation not in set(plan["formation_objectives"]["qin"])
    assert mercenary_formation not in set(plan["strategic_reserve_formation_refs"]["qin"])


def test_interstate_reinforcement_cannot_duplicate_a_formation_in_an_unrelated_active_siege(campaign: Path) -> None:
    from copy import deepcopy

    planner = _planner(campaign)
    host = deepcopy(planner.read("state/runtime.json")["hosts"]["host_interstate_wars"])
    at = str(host["next_due"])
    _selected, before = _seed_active_qin_zhao_theater_without_mercenary(planner, at=at)
    mercenary_formation = planner._materialize_mercenary_tactical_formation(
        "merc.major.09", employer_ref="state_qin", at=at, require_field_contract=True
    )
    assert mercenary_formation and mercenary_formation not in before

    siege_ref = "siege_test_reserved_mercenary_elsewhere"
    siege_path = f"state/sieges/{siege_ref}.json"
    planner.put(siege_path, {
        "schema": "sword-siege",
        "owner_id": siege_ref,
        "siege_ref": siege_ref,
        "status": "active",
        "attacker_formation_refs": [mercenary_formation],
        "defender_formation_refs": [],
        "strategic_theater_ref": "test_other_theater",
        "started_at": at,
    })
    siege_index = deepcopy(planner.read("state/sieges/index.json"))
    siege_index.setdefault("sieges", {})[siege_ref] = siege_path
    planner.put("state/sieges/index.json", siege_index)

    planner._autonomy_interstate(host, 1, at)

    current = planner.read(planner.owner_path("interstate_warring_states"))["theaters"]["qin_zhao_gyou"]
    assert mercenary_formation not in current["formation_groups"]["qin"]
    plan = current["strategic_plan"]
    assert mercenary_formation not in set(plan["formation_objectives"]["qin"])
    assert mercenary_formation not in set(plan["strategic_reserve_formation_refs"]["qin"])


def test_interstate_no_lawful_force_closes_through_settlement_instead_of_stranding_war_diplomacy(
    campaign: Path, monkeypatch
) -> None:
    from copy import deepcopy
    from sword_runtime.sim.calendar import CampaignTime
    import sword_runtime.engine as engine_module

    planner = _planner(campaign)
    host = deepcopy(planner.read("state/runtime.json")["hosts"]["host_interstate_wars"])
    first_due = CampaignTime.parse(str(host["next_due"]))
    recurrence = int(host["recurrence_seconds"])
    second_due = str(first_due.add_seconds(recurrence))
    theater_ref = "test_no_lawful_force_settlement"
    config = {
        "review_seconds": recurrence,
        "active_review_seconds": recurrence,
        "theaters": [{
            "theater_ref": theater_ref,
            "sides": ["qin", "zhao"],
            "target_location_ref": "loc_gyou",
            "base_pressure": 20,
            "formation_ref_lists": {"qin": [], "zhao": []},
        }],
    }
    monkeypatch.setattr(planner, "_interstate_theater_config", lambda _base, at=None: config)
    monkeypatch.setattr(engine_module, "active_levy_formations", lambda _planner, _side: [])
    monkeypatch.setattr(planner, "_tactical_mercenary_formations_for_employer", lambda _employer, at: [])

    world_path = planner.owner_path("interstate_warring_states")
    world = deepcopy(planner.read(world_path))
    world.setdefault("theaters", {})[theater_ref] = {
        "phase": "mobilizing",
        "cycle": 1,
        "pressure": 100,
        "attacker_state": "qin",
        "defender_state": "zhao",
        "started_at": str(first_due),
        "battle_count": 0,
        "war_result": None,
        "history": [],
    }
    planner.put(world_path, world)
    for side, enemy in (("qin", "zhao"), ("zhao", "qin")):
        path = f"state/states/{side}.json"
        state = deepcopy(planner.read(path))
        state.setdefault("diplomacy", {})[f"state_{enemy}"] = {
            "tension": 100,
            "status": "war",
            "theater_ref": theater_ref,
            "since": str(first_due),
        }
        planner.put(path, state)

    planner._autonomy_interstate(host, 1, str(first_due))
    interim = planner.read(world_path)["theaters"][theater_ref]
    assert interim["phase"] == "peace_settlement"
    host2 = deepcopy(host)
    host2["next_due"] = second_due
    planner._autonomy_interstate(host2, 1, second_due)

    record = planner.read(world_path)["theaters"][theater_ref]
    assert record["phase"] == "peace"
    assert record["war_result"] == "mobilization_unavailable"
    assert any(row.get("event") == "campaign_closed_no_lawful_force" for row in record["history"])
    assert any(row.get("event") == "peace_settlement" for row in record["history"])
    assert planner.read("state/states/qin.json")["diplomacy"]["state_zhao"]["status"] == "armed_peace"
    assert planner.read("state/states/zhao.json")["diplomacy"]["state_qin"]["status"] == "armed_peace"
    assert record.get("last_treaty_ref")
