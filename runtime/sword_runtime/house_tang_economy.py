"""House Tang force-employment, commercial-service and Sword Manor private-work settlement.

This layer routes existing exact owners.  It never owns people, mercenaries or
money itself: House commercial receipts debit the exact Qin private economy;
Sword Manor service contracts own zero bodies; mercenary hiring creates offers
to independent exact companies and accepted contracts are paid from House Tang's
exact treasury by the ordinary mercenary autonomy cycle.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping
from typing import Any

_POLICY = "game/data/mechanics/house-tang-force-policy.json"
_PRODUCTION = "game/data/mechanics/house-tang-production.json"
_TREASURY = "state/treasury/treasury-house-tang.json"
_ECONOMY = "state/economy/private/qin.json"
_HOUSE = "state/houses/house_tang.json"
_SWORD = "state/forces/sword-manor.json"
_JOBS = "state/contract/sword-manor-service-jobs.json"
_RUNTIME = "state/runtime.json"
_OPERATION_INDEX = "state/operations/index.json"


def _months(host: Mapping[str, Any], occurrences: int) -> int:
    seconds = max(1, int(host.get("recurrence_seconds", 30 * 86400))) * max(0, int(occurrences))
    return max(1, int(round(seconds / (30 * 86400))))


def _economy_regions(economy: dict[str, Any], refs: list[str]) -> list[dict[str, Any]]:
    local = economy.get("local_regions", {})
    rows = local.get("regions", {}) if isinstance(local, Mapping) else {}
    result = []
    for ref in refs:
        row = rows.get(ref) if isinstance(rows, Mapping) else None
        if isinstance(row, dict):
            result.append(row)
    return result


def _debit_cash(regions: list[dict[str, Any]], due: int) -> int:
    remaining = max(0, int(due)); paid = 0
    for row in regions:
        if remaining <= 0:
            break
        cash = max(0, int(row.get("cash_silver", 0)))
        take = min(cash, remaining)
        if take:
            row["cash_silver"] = cash - take
            remaining -= take
            paid += take
    return paid


def _sync_economy(economy: dict[str, Any]) -> None:
    local = economy.get("local_regions", {})
    rows = local.get("regions", {}) if isinstance(local, Mapping) else {}
    if isinstance(rows, Mapping):
        economy["cash_silver"] = sum(max(0, int(row.get("cash_silver", 0))) for row in rows.values() if isinstance(row, Mapping))


class HouseTangEconomyMixin:
    def _settle_house_tang_commercial_infrastructure(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        months = _months(host, occurrences)
        rules = self.read(_PRODUCTION)
        infrastructure = rules.get("commercial_infrastructure", {}) if isinstance(rules, Mapping) else {}
        if not isinstance(infrastructure, Mapping) or not infrastructure:
            return
        population = self.read("state/population/tang-manor.json")
        strata = population.get("strata", {}) if isinstance(population, Mapping) else {}
        workforce = rules.get("workforce", {}) if isinstance(rules.get("workforce"), Mapping) else {}
        treasury = copy.deepcopy(self.read(_TREASURY))
        economy = copy.deepcopy(self.read(_ECONOMY))
        house = copy.deepcopy(self.read(_HOUSE))
        region_refs = [str(x) for x in rules.get("procurement_regions", []) if isinstance(x, str)]
        regions = _economy_regions(economy, region_refs)
        if not regions:
            raise ValueError("House Tang commercial infrastructure has no legitimate Qin market region")
        due_by_program: dict[str, int] = {}
        for key, row in infrastructure.items():
            if not isinstance(row, Mapping):
                continue
            labor_key = str(row.get("labor_owner", ""))
            current = max(0, int(strata.get(labor_key, 0))) if isinstance(strata, Mapping) else 0
            baseline_raw = workforce.get(labor_key, current) if isinstance(workforce, Mapping) else current
            baseline = max(1, int(baseline_raw)) if isinstance(baseline_raw, (int, float)) and not isinstance(baseline_raw, bool) else max(1, current)
            labor_factor = min(1.0, current / baseline)
            monthly = max(0, int(row.get("monthly_service_capacity_silver", 0)))
            due_by_program[str(key)] = max(0, int(math.floor(monthly * labor_factor * months)))
        total_due = sum(due_by_program.values())
        paid = _debit_cash(regions, total_due)
        treasury["silver"] = int(treasury.get("silver", 0)) + paid
        _sync_economy(economy)
        runtime = house.setdefault("administrative_programs", {}).setdefault("commercial_infrastructure", {})
        runtime.update({
            "schema": "house-tang-commercial-runtime.v1",
            "last_close": at,
            "months": months,
            "gross_service_receipts_due_silver": total_due,
            "gross_service_receipts_paid_silver": paid,
            "market_shortfall_silver": max(0, total_due - paid),
            "program_capacity_due_silver": due_by_program,
            "payment_source_ref": "private_economy_qin",
            "rule": "real service revenue transfers existing Qin private-economy cash to House Tang; installed labor capacity limits due receipts and no silver is minted",
        })
        hist = runtime.setdefault("history", [])
        hist.append({"at": at, "months": months, "due_silver": total_due, "paid_silver": paid})
        runtime["history"] = hist[-24:]
        self.put(_TREASURY, treasury)
        self.put(_ECONOMY, economy)
        self.put(_HOUSE, house)

    def _settle_sword_manor_private_jobs(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        months = _months(host, occurrences)
        policy = self.read(_POLICY).get("sword_manor_private_work", {})
        if not isinstance(policy, Mapping):
            return
        sword = self.read(_SWORD)
        available = sword.get("available_by_role", {}) if isinstance(sword, Mapping) else {}
        eligible_roles = [str(x) for x in policy.get("eligible_roles", []) if isinstance(x, str)]
        eligible = sum(max(0, int(available.get(role, 0))) for role in eligible_roles) if isinstance(available, Mapping) else 0
        personnel = min(max(0, int(policy.get("maximum_duty_personnel", 0))), eligible)
        fee = max(0, int(policy.get("monthly_service_fee_silver_per_person", 0)))
        due = personnel * fee * months
        treasury = copy.deepcopy(self.read(_TREASURY))
        economy = copy.deepcopy(self.read(_ECONOMY))
        regions = _economy_regions(economy, ["loc_qin_regional_01", "loc_kanyou"])
        if not regions:
            raise ValueError("Sword Manor private service has no legitimate paying market region")
        paid = _debit_cash(regions, due)
        treasury["silver"] = int(treasury.get("silver", 0)) + paid
        _sync_economy(economy)
        jobs = copy.deepcopy(self.read_optional(_JOBS) or {
            "schema": "sword-manor-service-contracts.v1",
            "owner_id": "contract_sword_manor_private_service",
            "owner_type": "service_contract_registry",
            "authority": True,
            "manpower_authority": {"owns_bodies": False, "rule": "completed private jobs reference otherwise-unallocated Sword Manor bodies for bounded duty; the contract never owns or duplicates them"},
            "outsider_training_allowed": False,
            "reviews": [],
        })
        ref = "sword_manor_service_" + hashlib.sha256(f"{at}|{months}|{personnel}".encode()).hexdigest()[:14]
        jobs["last_review"] = at
        jobs["last_service"] = {
            "service_ref": ref,
            "at": at,
            "months": months,
            "personnel": personnel,
            "eligible_roles": eligible_roles,
            "allowed_service_kinds": [str(x) for x in policy.get("allowed", [])],
            "service_area_refs": ["loc_qin_regional_01", "loc_kanyou"],
            "fee_due_silver": due,
            "fee_paid_silver": paid,
            "payer_ref": "private_economy_qin",
            "payee_ref": "treasury_house_tang",
            "outsider_training": False,
            "rule": "local completed escort/security duty only; no outsider instruction, no body transfer and no additional free training hours",
        }
        jobs.setdefault("reviews", []).append(copy.deepcopy(jobs["last_service"]))
        jobs["reviews"] = jobs["reviews"][-24:]
        self.put(_TREASURY, treasury)
        self.put(_ECONOMY, economy)
        self.put(_JOBS, jobs)
        if hasattr(self, "_register_owner"):
            try:
                self._register_owner("contract_sword_manor_private_service", _JOBS)
            except (ValueError, KeyError):
                pass

    def _house_tang_operation_location(self) -> str | None:
        index = self.read_optional(_OPERATION_INDEX)
        operations = index.get("operations", {}) if isinstance(index, Mapping) else {}
        if not isinstance(operations, Mapping):
            return None
        for _ref, path in sorted(operations.items()):
            if not isinstance(path, str):
                continue
            op = self.read_optional(path)
            if not isinstance(op, Mapping) or str(op.get("status", "")) not in {"active", "engaged", "mobilizing"}:
                continue
            for formation_ref in op.get("formation_refs", []) if isinstance(op.get("formation_refs"), list) else []:
                try:
                    _fp, formation = self._load_formation(str(formation_ref))
                except (ValueError, KeyError, FileNotFoundError):
                    continue
                source = str(formation.get("source_force_ref", formation.get("force_ref", "")))
                if source in {"force_house_tang", "force_tang_wei", "institution_sword_manor"}:
                    loc = op.get("location_ref") or formation.get("location_ref")
                    return str(loc) if isinstance(loc, str) and loc else None
        return None

    def _house_tang_contingency_mercenary_offers(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        policy = self.read(_POLICY).get("contingency_mercenary_procurement", {})
        if not isinstance(policy, Mapping):
            return
        qin = self.read("state/states/qin.json")
        threats = qin.get("known_threats", {}) if isinstance(qin, Mapping) else {}
        severity = 0
        if isinstance(threats, Mapping):
            for row in threats.values():
                try:
                    value = int(row.get("severity", 0)) if isinstance(row, Mapping) else int(row)
                except (TypeError, ValueError):
                    value = 0
                severity = max(severity, value)
        operation_location = self._house_tang_operation_location()
        if operation_location:
            severity = max(severity, 65)
        minimum = max(0, int(policy.get("minimum_threat_severity", 45)))
        if severity < minimum:
            return
        desired = 0
        for row in policy.get("desired_additional_headcount_by_severity", []) if isinstance(policy.get("desired_additional_headcount_by_severity"), list) else []:
            if isinstance(row, Mapping) and severity >= int(row.get("minimum", 101)):
                desired = max(desired, int(row.get("headcount", 0)))
        if desired <= 0:
            return

        runtime = self.read(_RUNTIME)
        hosts = runtime.get("hosts", {}) if isinstance(runtime, Mapping) else {}
        merc_refs = sorted({str(h.get("owner_ref")) for h in hosts.values() if isinstance(h, Mapping) and h.get("kind") == "mercenary" and isinstance(h.get("owner_ref"), str)})
        standing = set(self.read("state/contract/tang-contracted-defense.json").get("member_force_ids", []))
        committed = 0
        candidates: list[tuple[int, str, str, dict[str, Any]]] = []
        for ref in merc_refs:
            if ref in standing:
                continue
            try:
                path = self.owner_path(ref); company = copy.deepcopy(self.read(path))
            except (ValueError, KeyError, FileNotFoundError):
                continue
            contracts = company.get("contracts", []) if isinstance(company.get("contracts"), list) else []
            headcount = max(0, int(company.get("headcount", company.get("count", company.get("personnel", 0))) or 0))
            tang_contract = False
            for contract in contracts:
                if not isinstance(contract, Mapping) or str(contract.get("employer_ref", "")) not in {"house_tang", "institution_house_tang"}:
                    continue
                if str(contract.get("status", "")) in {"offered", "accepted_unpaid", "renewal_accepted", "active", "renewal_offered"}:
                    committed += headcount
                    tang_contract = True
                    break
            if tang_contract or headcount <= 0:
                continue
            short_notice = company.get("market_engagement", {}).get("short_notice_available") if isinstance(company.get("market_engagement"), Mapping) else None
            if str(company.get("status", "")) != "available" or short_notice is False:
                continue
            candidates.append((-headcount, ref, path, company))
        shortage = max(0, desired - committed)
        if shortage <= 0:
            return
        treasury = self.read(_TREASURY)
        protected = int(treasury.get("stable_monthly_flows", {}).get("expense_silver", 0)) * 12 if isinstance(treasury.get("stable_monthly_flows"), Mapping) else 0
        spendable = max(0, int(treasury.get("silver", 0)) - protected)
        econ = self.read("game/data/mechanics/economy.json")
        career = self.read("game/data/mechanics/career.json")
        monthly = float(econ.get("wages", {}).get("professional_soldier_monthly_silver", 7))
        factor = float(career.get("service_models", {}).get("army_model_mercenary", {}).get("cash_pay_factor_vs_common_role_baseline", 1.35))
        term = max(30, int(policy.get("term_days", 90)))
        premium = max(10000, int(policy.get("offer_premium_basis_points", 11500))) / 10000.0
        deployment = operation_location or str(policy.get("preferred_deployment_location_ref", "loc_tang_manor_defense_camp"))
        offers = 0
        offered_heads = 0
        for neg_headcount, ref, path, company in sorted(candidates):
            if shortage <= 0 or offers >= 8:
                break
            headcount = -neg_headcount
            fair = int(math.ceil(headcount * monthly * factor * term / 30.0))
            amount = int(math.ceil(fair * premium))
            if amount > spendable:
                continue
            contract_ref = "tang_contingency_" + hashlib.sha256(f"{ref}|{severity}|{at}".encode()).hexdigest()[:16]
            contracts = company.setdefault("contracts", [])
            contracts.append({
                "contract_ref": contract_ref,
                "employer_ref": "house_tang",
                "status": "offered",
                "amount_silver": amount,
                "term_days": term,
                "offered_at": at,
                "deployment_location_ref": deployment,
                "engagement_kind": "house_tang_offensive_support" if operation_location else "house_tang_defense_reinforcement",
                "threat_severity": severity,
                "basis": "House Tang mercenary-first force-employment policy, exact threat/operation need, short-notice company availability, fair-pay floor and protected treasury reserve",
            })
            company["contracts"] = contracts[-32:]
            company["status"] = "considering_offer"
            self.put(path, company)
            spendable -= amount
            shortage -= headcount
            offered_heads += headcount
            offers += 1
        if offers:
            house = copy.deepcopy(self.read(_HOUSE))
            runtime_row = house.setdefault("administrative_programs", {}).setdefault("mercenary_first_force_employment", {})
            runtime_row.update({"last_review": at, "threat_severity": severity, "desired_additional_headcount": desired, "already_committed_headcount": committed, "offered_headcount": offered_heads, "offers_created": offers, "deployment_location_ref": deployment})
            self.put(_HOUSE, house)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        super()._run_due_host(host, due_text)
        kind = host.get("kind")
        if kind == "sword_manor":
            self._settle_sword_manor_private_jobs(host, 1, due_text)
        elif kind == "house" and host.get("owner_ref") == "house_tang":
            self._settle_house_tang_commercial_infrastructure(host, 1, due_text)
            self._house_tang_contingency_mercenary_offers(host, 1, due_text)


__all__ = ["HouseTangEconomyMixin"]
