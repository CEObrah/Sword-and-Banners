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
    assert recruitment["exclusive_entrypoint"] == "institution_sword_manor:trainee"
    assert recruitment["monthly_maximum_intake"] == 2000
    assert recruitment["ladder"] == [
        "trainee", "junior_disciple", "general_disciple", "senior_disciple",
        "house_guard", "guardian_cavalry", "tang_champion",
    ]
    assert policy["training"]["regimen_ref"] == "house_tang_max_sustainable"
    assert policy["training"]["no_free_progress"] is True
    assert policy["force_employment"]["priority"] == [
        "standing_contracted_mercenaries", "additional_hired_mercenaries",
        "sword_manor_mobilization", "house_tang_regulars",
    ]
    assert "outsider_training_for_fee" in policy["sword_manor_private_work"]["forbidden"]

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
        assert "smart_rotation" in contract, path

    kai = _read("state/char/tang-kai.json")
    assert kai["activity_contract"]["training_regimen_ref"] == "age_appropriate_household_development"
    assert kai["activity_contract"]["adult_regimen_prohibited"] is True


def test_mercenary_ecology_and_white_lantern_capability_reconcile() -> None:
    market = _read("state/merc/market.json")
    assert market["authority"] is False
    assert market["represented_total"] == 450000
    assert sum(market["category_totals"].values()) == 450000
    assert market["category_totals"] == {
        "major_famous": 115000,
        "specialist": 115000,
        "regional_professional": 140000,
        "local_seasonal": 80000,
    }
    assert market["house_tang_contracted_total"] == 75000
    lo, hi = market["short_notice_available_target_band"]
    assert lo <= market["short_notice_available_total"] <= hi

    contract = _read("state/contract/tang-contracted-defense.json")
    assert contract["anonymous_total"] == 75000
    assert contract["combined_total"] == 75002

    white = _read("state/merc/white-lantern.json")
    pools = {row["pool_id"]: row for row in white["troop_pools"]}
    expected = {
        "merc_white_lantern:pool_signals": 1855,
        "merc_white_lantern:pool_logistics": 1865,
    }
    for pool_id, count in expected.items():
        assert pools[pool_id]["count"] == count
        cap_path = pools[pool_id]["capability_ref"]
        cap = _read(cap_path)
        assert cap["authority"] is False
        assert cap["current_pool_count"] == count
        assert sum(int(v) for v in cap["experience_distribution"].values()) == count


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


def test_house_commercial_and_sword_manor_service_income_conserve_silver(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    host = {"owner_ref": "house_tang", "recurrence_seconds": 30 * 86400}

    treasury0 = copy.deepcopy(planner.read("state/treasury/treasury-house-tang.json"))
    economy0 = copy.deepcopy(planner.read("state/economy/private/qin.json"))
    total0 = int(treasury0["silver"]) + int(economy0["cash_silver"])
    planner._settle_house_tang_commercial_infrastructure(host, 1, at)
    treasury1 = planner.read("state/treasury/treasury-house-tang.json")
    economy1 = planner.read("state/economy/private/qin.json")
    assert int(treasury1["silver"]) > int(treasury0["silver"])
    assert int(treasury1["silver"]) + int(economy1["cash_silver"]) == total0

    total1 = int(treasury1["silver"]) + int(economy1["cash_silver"])
    planner._settle_sword_manor_private_jobs({"owner_ref": "institution_sword_manor", "recurrence_seconds": 30 * 86400}, 1, at)
    treasury2 = planner.read("state/treasury/treasury-house-tang.json")
    economy2 = planner.read("state/economy/private/qin.json")
    jobs = planner.read("state/contract/sword-manor-service-jobs.json")
    assert int(treasury2["silver"]) > int(treasury1["silver"])
    assert int(treasury2["silver"]) + int(economy2["cash_silver"]) == total1
    assert jobs["manpower_authority"]["owns_bodies"] is False
    assert jobs["outsider_training_allowed"] is False
    assert jobs["last_service"]["outsider_training"] is False
    assert 0 <= int(jobs["last_service"]["personnel"]) <= 600


def test_house_contingency_mercenary_offer_never_transfers_company_bodies(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    qin = copy.deepcopy(planner.read("state/states/qin.json"))
    qin["known_threats"] = {"test_material_threat": {"severity": 80}}
    planner.put("state/states/qin.json", qin)

    runtime = planner.read("state/runtime.json")
    refs = sorted({
        str(host["owner_ref"])
        for host in runtime.get("hosts", {}).values()
        if isinstance(host, dict) and host.get("kind") == "mercenary" and isinstance(host.get("owner_ref"), str)
    })
    standing = set(planner.read("state/contract/tang-contracted-defense.json")["member_force_ids"])
    before: dict[str, tuple[str, int]] = {}
    for ref in refs:
        if ref in standing:
            continue
        try:
            path = planner.owner_path(ref)
            doc = planner.read(path)
        except (KeyError, ValueError, FileNotFoundError):
            continue
        if doc.get("status") != "available":
            continue
        if isinstance(doc.get("market_engagement"), dict) and doc["market_engagement"].get("short_notice_available") is False:
            continue
        before[ref] = (path, _merc_count(doc))
    assert before

    planner._house_tang_contingency_mercenary_offers({"owner_ref": "house_tang", "recurrence_seconds": 30 * 86400}, 1, at)
    offered = 0
    for ref, (path, count) in before.items():
        doc = planner.read(path)
        assert _merc_count(doc) == count, ref
        contracts = doc.get("contracts", []) if isinstance(doc.get("contracts"), list) else []
        offered += sum(1 for row in contracts if isinstance(row, dict) and row.get("employer_ref") == "house_tang" and row.get("status") == "offered")
    assert offered >= 1
