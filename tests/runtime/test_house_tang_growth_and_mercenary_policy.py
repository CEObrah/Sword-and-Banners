from __future__ import annotations

import copy
import json
from pathlib import Path

from sword_runtime.production_planner import ProductionCampaignPlanner

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str):
    return json.loads((ROOT / rel).read_text())


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _merc_count(doc: dict) -> int:
    return max(0, int(doc.get("headcount", doc.get("count", doc.get("personnel", doc.get("strength", 0)))) or 0))


def test_house_tang_growth_policy_and_requested_training_contracts() -> None:
    policy = _read("game/data/mechanics/house-tang-force-policy.json")
    recruitment = policy["recruitment"]
    assert "monthly_maximum_intake" not in recruitment
    branches = recruitment["branches"]
    assert branches["sword_manor"]["force_ref"] == "force_sword_manor"
    assert branches["sword_manor"]["entry_role"] == "trainee"
    assert branches["sword_manor"]["outsider_instruction"] is False
    assert set(branches["four_bastion_corps"]["force_refs"]) == {
        "force_bastion_iron_wall", "force_bastion_red_thunder",
        "force_bastion_white_blade", "force_bastion_stone_spear",
    }
    assert branches["house_elite_progression"]["ladder"] == [
        "house_guard", "guardian_cavalry", "tang_champion",
    ]
    assert policy["training"]["regimen_ref"] == "house_tang_max_sustainable"
    assert policy["training"]["no_free_progress"] is True
    assert policy["force_employment"]["priority"] == [
        "single_recursive_house_tang_field_army",
        "defense_in_depth_by_subordinate_command",
        "preserve_high_quality_inner_reserves_until_operationally_required",
        "external_auxiliaries_only_when_lawfully_preferred",
    ]
    doctrine = policy["force_employment"]["home_defense_doctrine"]
    assert doctrine["root_command_ref"] == "cmdgrp.house_tang.field_army"
    assert doctrine["commander_ref"] == "char_tang_zhu"
    assert doctrine["deputy_ref"] == "char_tang_ling"
    assert doctrine["default_layers"][0]["command_ref"] == "cmdgrp.house_tang.bastions"
    assert doctrine["default_layers"][1]["command_ref"] == "cmdgrp.sword_manor.field"
    assert doctrine["default_layers"][2]["command_refs"] == [
        "cmdgrp.house_tang.house_guard",
        "cmdgrp.house_tang.guardian_cavalry",
        "cmdgrp.house_tang.champions",
    ]
    assert "not immutable restrictions" in doctrine["reassignment_rule"]
    assert "sword_manor_private_work" not in policy
    assert "outsider" in " ".join(policy["force_employment"]["constraints"]).lower()

    player = _read("state/player.json")
    assert player["activity_contract"]["training_regimen_ref"] == "house_tang_max_sustainable"
    assert player["activity_contract"]["auto_settle_standing_training"] is True

    adult_paths = [
        "state/char/tang-zhu.json", "state/char/tang-ling.json", "state/char/wei-jian.json",
        "state/char/ren-qiao.json", "state/char/duan-jin.json", "state/char/shen-rui.json",
        "state/char/qiu-ren.json", "state/char/zhao-fen.json", "state/char/gao-yun.json",
        "state/char/mu-zhen.json", "state/char/he-shan.json",
        *[f"state/char/qin-wei-unit-{i:02d}-commander.json" for i in range(1, 5)],
    ]
    for path in adult_paths:
        person = _read(path)
        contract = person["activity_contract"]
        assert contract["mode"] == "standing_role_training", path
        assert contract["training_regimen_ref"] == "house_tang_max_sustainable", path
        assert contract["autonomous_enabled"] is True, path
        assert "smart_rotation" not in contract, path

    kai = _read("state/char/tang-kai.json")
    assert kai["activity_contract"]["training_regimen_ref"] == "age_appropriate_household_development"
    assert kai["activity_contract"]["adult_regimen_prohibited"] is True


def test_mercenary_ecology_and_four_bastion_permanent_force_reconcile() -> None:
    market = _read("state/merc/market.json")
    assert market["authority"] is False
    assert market["represented_total"] == 375000
    assert sum(market["category_totals"].values()) == 375000
    assert market["category_totals"] == {
        "major_famous": 115000,
        "specialist": 40000,
        "regional_professional": 140000,
        "local_seasonal": 80000,
    }
    assert market.get("house_tang_contracted_total") in {None, 0}
    lo, hi = market["short_notice_available_target_band"]
    assert lo <= market["short_notice_available_total"] <= hi

    owners = {
        "force_bastion_iron_wall": 75000,
        "force_bastion_red_thunder": 16000,
        "force_bastion_white_blade": 10000,
        "force_bastion_stone_spear": 9000,
    }
    index = _read("state/index/owner-index.json")["owners"]
    total = 0
    for ref, expected in owners.items():
        force = _read(index[ref])
        assert force["headcount"] == expected
        assert force["administrative_owner"] == "house_tang"
        assert not str(force.get("owner_type", "")).startswith("mercenary")
        total += expected
    assert total == 110000


def test_jo_is_a_conserved_minor_polity_with_real_routes() -> None:
    polity = _read("state/politics/polities/polity_jo.json")
    pop = _read("state/population/jo.json")
    force = _read("state/forces/jo.json")
    assert polity["administration_mode"] == "minor_polity"
    assert polity["population_ref"] == "population_jo"
    assert polity["military_force_refs"] == ["force_jo"]
    assert pop["population_total"] == 32000
    assert sum(int(v) for v in pop["strata"].values()) == 32000
    assert force["headcount"] == pop["strata"]["active_military"] == 1500
    assert sum(int(v) for v in force["available_by_role"].values()) == 1500
    assert pop["provenance"]["kind"] == "game_seed_noncanonical"

    routes = _read("game/data/world/routes.json")["routes"]
    jo_edges = [r for r in routes if r.get("a") in {"loc_jo_city", "loc_jo_mountain_region"} or r.get("b") in {"loc_jo_city", "loc_jo_mountain_region"}]
    assert len(jo_edges) >= 4
    foreign_edges = [r for r in jo_edges if r.get("border_crossing")]
    assert {(r["border_crossing"]["from"], r["border_crossing"]["to"]) for r in foreign_edges} == {
        ("jo", "wei"), ("jo", "zhao"), ("jo", "chu")
    }


def test_house_private_estate_income_uses_current_realized_production_and_conserves_silver(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time().add_seconds(30 * 86400))
    treasury0 = copy.deepcopy(planner.read("state/treasury/treasury-house-tang.json"))
    economy0 = copy.deepcopy(planner.read("state/economy/private/qin.json"))
    total0 = int(treasury0["silver"]) + int(economy0["cash_silver"])

    planner._settle_private_production("qin", 1, at)

    treasury1 = planner.read("state/treasury/treasury-house-tang.json")
    economy1 = planner.read("state/economy/private/qin.json")
    tang_close = economy1["local_regions"]["regions"]["loc_tang_manor"]["production_runtime"]["last_private_owner_close"]
    assert tang_close["owner_ref"] == "house_tang"
    assert tang_close["paid_silver"] > 0
    assert int(treasury1["silver"]) == int(treasury0["silver"]) + int(tang_close["paid_silver"])
    assert int(treasury1["silver"]) + int(economy1["cash_silver"]) == total0

    # Sword Manor is a permanent House military institution, not a parallel
    # private-service market subsystem.
    assert not hasattr(planner, "_settle_sword_manor_private_jobs")
    assert planner.read_optional("state/contract/sword-manor-service-jobs.json") is None
    owners = planner.read("state/index/owner-index.json")["owners"]
    assert "contract_sword_manor_private_service" not in owners


def test_current_mercenary_broker_materializes_one_available_company_without_transferring_bodies(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    for state in ("qin", "zhao", "chu", "wei", "han", "yan", "qi"):
        doc = copy.deepcopy(planner.read(f"state/states/{state}.json"))
        doc["known_threats"] = {}
        planner.put(f"state/states/{state}.json", doc)
    qin = copy.deepcopy(planner.read("state/states/qin.json"))
    qin["known_threats"] = {"test_material_threat": {"severity": 80}}
    planner.put("state/states/qin.json", qin)

    regional_before = copy.deepcopy(planner.read("state/merc/regional.json"))
    first = next(
        row for row in regional_before["entries"]
        if row.get("materialized") is not True and row.get("status", "available") == "available"
        and row.get("market_engagement", {}).get("short_notice_available") is not False
    )
    company_ref = str(first["id"])
    body_count = _merc_count(first)

    result = planner._broker_one_mercenary_offer(at)

    assert result["status"] == "offer_created"
    assert result["company_ref"] == company_ref
    assert result["employer_ref"] == "state_qin"
    regional_after = planner.read("state/merc/regional.json")
    routed = next(row for row in regional_after["entries"] if row["id"] == company_ref)
    assert routed["materialized"] is True
    exact = planner.read(routed["path"])
    assert _merc_count(exact) == body_count
    assert exact["status"] == "considering_offer"
    offers = [row for row in exact.get("contracts", []) if row.get("status") == "offered"]
    assert len(offers) == 1
    assert offers[0]["employer_ref"] == "state_qin"
    assert _merc_count(next(row for row in regional_after["entries"] if row["id"] == company_ref)) == body_count
