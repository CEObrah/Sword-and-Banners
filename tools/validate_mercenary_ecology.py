#!/usr/bin/env python3
"""Focused exact-owner validation for the living mercenary ecology."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def _j(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    market = _j(root / "state/merc/market.json")
    local = _j(root / "state/merc/local.json")
    if market.get("authority") is not False:
        errors.append("mercenary market index must remain authority:false")
    standing: set[str] = set()

    major_total = 0
    independent_specialist_total = 0
    standing_total = 0
    exact_company_total = 0
    company_paths = sorted((root / "state/merc").glob("*.json")) + sorted((root / "state/merc/regional").glob("*.json"))
    for path in company_paths:
        doc = _j(path)
        schema = str(doc.get("schema", ""))
        if schema not in {"mercenary", "mercenary-company", "regional-mercenary-company"}:
            continue
        owner = str(doc.get("owner_id", doc.get("id", "")))
        count = max(0, int(doc.get("headcount", doc.get("count", 0)) or 0))
        exact_company_total += count
        if path.name.startswith("major-"):
            major_total += count
        elif owner in standing:
            standing_total += count
        elif schema == "mercenary-company":
            independent_specialist_total += count

        pools = doc.get("troop_pools", [])
        if not isinstance(pools, list):
            continue
        for pool in pools:
            if not isinstance(pool, dict):
                continue
            pool_count = max(0, int(pool.get("count", 0)))
            cap_ref = pool.get("capability_ref")
            if not isinstance(cap_ref, str) or not cap_ref:
                continue
            cap_path = root / cap_ref
            if not cap_path.is_file():
                errors.append(f"{owner}:{pool.get('pool_id')} missing capability {cap_ref}")
                continue
            cap = _j(cap_path)
            if str(cap.get("source_owner", "")) != owner:
                errors.append(f"{cap_ref} source_owner does not match {owner}")
            dist = cap.get("experience_distribution", {})
            dist_total = sum(max(0, int(v)) for v in dist.values()) if isinstance(dist, dict) else -1
            current = cap.get("current_pool_count")
            if current is not None and int(current) != pool_count:
                errors.append(f"{cap_ref} current_pool_count {current} != exact pool {pool_count}")
            if dist_total != pool_count:
                errors.append(f"{cap_ref} experience_distribution {dist_total} != exact pool {pool_count}")

    regional_total = sum(max(0, int(_j(p).get("count", 0))) for p in (root / "state/merc/regional").glob("*.json"))
    local_total = max(0, int(local.get("armed_total", 0)))
    class_total = sum(max(0, int(r.get("count", 0))) for r in local.get("classes", []) if isinstance(r, dict))
    regional_dist_total = sum(max(0, int(v)) for v in local.get("regional_distribution", {}).values()) if isinstance(local.get("regional_distribution"), dict) else -1
    short_local = max(0, int(local.get("short_notice_available_total", 0)))
    short_by_loc = sum(max(0, int(v)) for v in local.get("short_notice_available_by_location", {}).values()) if isinstance(local.get("short_notice_available_by_location"), dict) else -1

    expected = market.get("category_totals", {})
    actual = {
        "major_famous": major_total,
        "specialist": independent_specialist_total,
        "regional_professional": regional_total,
        "local_seasonal": local_total,
    }
    for key, value in actual.items():
        if int(expected.get(key, -1)) != value:
            errors.append(f"market category {key}: index={expected.get(key)} exact={value}")
    represented = sum(actual.values())
    if represented != int(market.get("represented_total", -1)) or represented != 375000:
        errors.append(f"represented mercenary total must be exactly 375,000 after permanent Bastion separation; got {represented}")
    if standing_total != 0:
        errors.append(f"permanent Bastion forces leaked into mercenary market: {standing_total}")
    if class_total != local_total or regional_dist_total != local_total:
        errors.append("local mercenary class/geographic partitions do not conserve armed_total")
    if short_by_loc != short_local:
        errors.append("local short-notice geographic partition does not reconcile")
    short_market = max(0, int(market.get("short_notice_available_total", 0)))
    band = market.get("short_notice_available_target_band", [0, 0])
    if not isinstance(band, list) or len(band) != 2 or not int(band[0]) <= short_market <= int(band[1]):
        errors.append(f"mercenary short-notice availability {short_market} outside declared band {band}")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate(root)
    if errors:
        for error in errors:
            print("FAIL", error)
        return 1
    print("validate_mercenary_ecology: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
