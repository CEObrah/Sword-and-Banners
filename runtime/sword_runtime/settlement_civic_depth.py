from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.sim.calendar import CampaignTime


JUSTICE_INDEX = "state/civic/justice/index.json"
OUTBREAK_INDEX = "state/civic/outbreaks/index.json"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


class SettlementCivicDepthMixin:
    """Bounded settlement justice and outbreak propagation.

    The regional population document remains the only body authority.  Local cases
    and outbreak records own only their own legal/health state; neither creates
    population, cash, named people, or duplicate settlement owners.
    """

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _settlement_civic_rules(self) -> Mapping[str, Any]:
        return self.read("game/data/mechanics/settlement-civic.json")

    def _justice_index(self) -> dict[str, Any]:
        return copy.deepcopy(self.read_optional(JUSTICE_INDEX) or {
            "schema": "sword-local-justice-index",
            "authority": False,
            "cases": {},
            "open_refs": [],
        })

    def _outbreak_index(self) -> dict[str, Any]:
        return copy.deepcopy(self.read_optional(OUTBREAK_INDEX) or {
            "schema": "sword-outbreak-index",
            "authority": False,
            "outbreaks": {},
            "active_refs": [],
        })

    @staticmethod
    def _civic_token(prefix: str, *parts: object) -> str:
        digest = hashlib.sha256(":".join(str(x) for x in parts).encode("utf-8")).hexdigest()[:16]
        return f"{prefix}_{digest}"

    def _demographic_site(self, location_ref: str) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
        native = self._native_site_state(location_ref)
        if native is None:
            raise ValueError("settlement civic state requires an exact regional population owner")
        pop_path, pop = self._ensure_local_population_ledger(native, copy.deepcopy(self.read(f"state/population/{native}.json")))
        sites = pop.get("local_population", {}).get("sites", {})
        anchor = location_ref if location_ref in sites else None
        if anchor is None:
            _pp, _pop, row = self._local_population_row(native, location_ref, pop)
            anchor = str(row.get("location_ref", ""))
        else:
            row = sites[anchor]
        if not anchor or not isinstance(row, dict):
            raise ValueError("settlement civic state could not resolve a demographic site")
        return native, pop_path, pop, row, anchor

    # ------------------------------------------------------------------
    # Local justice
    # ------------------------------------------------------------------

    def _justice_case_path(self, case_ref: str) -> str:
        idx = self._justice_index()
        path = idx.get("cases", {}).get(case_ref)
        if not isinstance(path, str):
            raise ValueError("unknown local justice case")
        return path

    def _validate_local_evidence_refs(self, refs: list[str], subject_ref: str | None = None) -> None:
        for ref in refs:
            path = self.owner_path(ref)
            doc = self.read(path)
            schema = str(doc.get("schema", "")) if isinstance(doc, Mapping) else ""
            if schema not in {"sword-information", "sword-investigation"}:
                raise ValueError("local justice evidence must be exact information or investigation owners")
            if subject_ref and str(doc.get("subject_ref", "")) not in {"", subject_ref}:
                raise ValueError("local justice evidence subject does not match the case subject")

    def _register_local_case(self, payload: Mapping[str, Any], at: str) -> dict[str, Any]:
        location_ref = str(payload["location_ref"])
        native, _pop_path, _pop, _row, anchor = self._demographic_site(location_ref)
        case_kind = str(payload.get("case_kind", "other"))
        severity = max(1, min(100, int(payload.get("severity", 25))))
        subject_ref = str(payload.get("subject_ref", "")) or None
        evidence_refs = sorted({str(x) for x in payload.get("evidence_refs", []) if isinstance(x, str)})
        self._validate_local_evidence_refs(evidence_refs, subject_ref)

        case_ref = str(payload.get("case_ref") or self._civic_token("local_case", anchor, case_kind, subject_ref or "unknown", at))
        idx = self._justice_index()
        if case_ref in idx.get("cases", {}):
            raise ValueError("local justice case already exists")
        path = f"state/civic/justice/{case_ref}.json"
        doc = {
            "schema": "sword-local-justice-case",
            "case_ref": case_ref,
            "location_ref": anchor,
            "reported_location_ref": location_ref,
            "native_state": native,
            "case_kind": case_kind,
            "severity": severity,
            "subject_ref": subject_ref,
            "evidence_refs": evidence_refs,
            "status": "open",
            "opened_at": at,
            "resolution": None,
            "history": [{"at": at, "event": "case_registered"}],
            "rule": "a local case records alleged civic/legal pressure only; registration does not establish guilt, invent evidence, or create an accused person",
        }
        idx.setdefault("cases", {})[case_ref] = path
        idx.setdefault("open_refs", []).append(case_ref)
        idx["open_refs"] = sorted(set(str(x) for x in idx["open_refs"]))
        self.put(path, doc)
        self.put(JUSTICE_INDEX, idx)
        return {"case_ref": case_ref, "location_ref": anchor, "status": "open"}

    def _resolve_local_case(self, payload: Mapping[str, Any], at: str) -> dict[str, Any]:
        case_ref = str(payload["case_ref"])
        path = self._justice_case_path(case_ref)
        case = copy.deepcopy(self.read(path))
        if str(case.get("status", "")) != "open":
            raise ValueError("local justice case is not open")
        disposition = str(payload.get("disposition", "dismissed"))
        court_case_ref = str(payload.get("court_case_ref", "")) or None
        if disposition == "escalated":
            if not court_case_ref:
                raise ValueError("escalated local justice case requires an exact sovereign court case")
            _cp, court = self.owner(court_case_ref)
            if str(court.get("schema", "")) != "sword-court-case":
                raise ValueError("court_case_ref is not an exact sovereign court case")
        case["status"] = "resolved" if disposition != "escalated" else "escalated"
        case["resolved_at"] = at
        case["resolution"] = {
            "disposition": disposition,
            "court_case_ref": court_case_ref,
            "basis": "explicit local justice disposition; does not rewrite hidden objective fact or admitted evidence",
        }
        case.setdefault("history", []).append({"at": at, "event": "case_disposition", "disposition": disposition})
        case["history"] = case["history"][-32:]
        idx = self._justice_index()
        idx["open_refs"] = [x for x in idx.get("open_refs", []) if str(x) != case_ref]
        self.put(path, case)
        self.put(JUSTICE_INDEX, idx)
        return {"case_ref": case_ref, "status": case["status"], "disposition": disposition}

    # ------------------------------------------------------------------
    # Disease/outbreaks
    # ------------------------------------------------------------------

    def _outbreak_path(self, outbreak_ref: str) -> str:
        idx = self._outbreak_index()
        path = idx.get("outbreaks", {}).get(outbreak_ref)
        if not isinstance(path, str):
            raise ValueError("unknown settlement outbreak")
        return path

    def _contact_fraction(self, margin: float) -> float:
        rows = self.read("game/data/mechanics/settlement.json").get("disease_contact_fraction_by_margin", [])
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            low = row.get("min_margin")
            high = row.get("max_margin")
            if low is not None and margin < float(low):
                continue
            if high is not None and margin > float(high):
                continue
            return max(0.0, min(1.0, float(row.get("contact_fraction", 0.0))))
        return 0.0

    def _new_outbreak_doc(
        self,
        *,
        outbreak_ref: str,
        location_ref: str,
        syndrome: str,
        transmission_route: str,
        known_cases: int,
        exposed_population: int,
        exposure_pressure: float,
        population_resistance: float,
        severity_band: str,
        incubation_hours: int,
        infectious_hours: int,
        at: str,
        parent_outbreak_ref: str | None = None,
    ) -> dict[str, Any]:
        native, _pop_path, _pop, row, anchor = self._demographic_site(location_ref)
        residents = max(0, int(row.get("civilian_population", 0)))
        known = min(max(0, int(known_cases)), residents)
        exposed = min(max(0, int(exposed_population)), max(0, residents - known))
        if known <= 0:
            raise ValueError("outbreak requires at least one supported known case")
        return {
            "schema": "sword-settlement-outbreak",
            "outbreak_ref": outbreak_ref,
            "location_ref": anchor,
            "native_state": native,
            "syndrome": syndrome,
            "etiology": "unconfirmed",
            "transmission_route": transmission_route,
            "severity_band": severity_band,
            "incubation_hours": max(1, int(incubation_hours)),
            "infectious_hours": max(1, int(infectious_hours)),
            "status": "active",
            "known_cases": known,
            "incubating_cases": 0,
            "symptomatic_cases": known,
            "recovered_cases": 0,
            "deaths": 0,
            "exposed_susceptible": exposed,
            "exposure_pressure": round(float(exposure_pressure), 3),
            "population_resistance": round(float(population_resistance), 3),
            "fractional_case_carry": 0.0,
            "quarantine": {"active": False, "strength": 0, "supply_days": 0},
            "parent_outbreak_ref": parent_outbreak_ref,
            "created_at": at,
            "last_review_at": at,
            "next_review_at": str(CampaignTime.parse(at).add_hours(24)),
            "review_history": [],
            "propagation_history": [],
            "rule": "aggregate civilian outbreak only; cases remain conserved living residents until exact recovery or death settlement; named-person illness requires its own exact health consequence",
        }

    def _start_outbreak(self, payload: Mapping[str, Any], at: str, *, parent_outbreak_ref: str | None = None) -> dict[str, Any]:
        location_ref = str(payload["location_ref"])
        syndrome = str(payload.get("syndrome", "undifferentiated febrile syndrome"))
        transmission_route = str(payload.get("transmission_route", "close_contact"))
        known_cases = int(payload.get("known_cases", 1))
        exposed_population = int(payload.get("exposed_population", max(known_cases * 10, known_cases)))
        exposure_pressure = float(payload.get("exposure_pressure", 12))
        population_resistance = float(payload.get("population_resistance", 12))
        severity_band = str(payload.get("severity_band", "moderate"))
        incubation_hours = int(payload.get("incubation_hours", 48))
        infectious_hours = int(payload.get("infectious_hours", 120))
        _native, _pp, _pop, _row, anchor = self._demographic_site(location_ref)
        outbreak_ref = str(payload.get("outbreak_ref") or self._civic_token("outbreak", anchor, syndrome, at, parent_outbreak_ref or "root"))
        idx = self._outbreak_index()
        if outbreak_ref in idx.get("outbreaks", {}):
            raise ValueError("settlement outbreak already exists")
        path = f"state/civic/outbreaks/{outbreak_ref}.json"
        doc = self._new_outbreak_doc(
            outbreak_ref=outbreak_ref,
            location_ref=location_ref,
            syndrome=syndrome,
            transmission_route=transmission_route,
            known_cases=known_cases,
            exposed_population=exposed_population,
            exposure_pressure=exposure_pressure,
            population_resistance=population_resistance,
            severity_band=severity_band,
            incubation_hours=incubation_hours,
            infectious_hours=infectious_hours,
            at=at,
            parent_outbreak_ref=parent_outbreak_ref,
        )
        idx.setdefault("outbreaks", {})[outbreak_ref] = path
        idx.setdefault("active_refs", []).append(outbreak_ref)
        idx["active_refs"] = sorted(set(str(x) for x in idx["active_refs"]))
        self.put(path, doc)
        self.put(OUTBREAK_INDEX, idx)
        return {"outbreak_ref": outbreak_ref, "location_ref": doc["location_ref"], "status": "active"}

    def _apply_outbreak_deaths(self, location_ref: str, deaths: int, at: str) -> int:
        requested = max(0, int(deaths))
        if requested <= 0:
            return 0
        native, pop_path, pop, row, _anchor = self._demographic_site(location_ref)
        civilian = row.setdefault("civilian_strata", {})
        available_total = sum(max(0, int(v)) for v in civilian.values())
        take_total = min(requested, available_total)
        if take_total <= 0:
            return 0
        # Largest-remainder partition is the same deterministic helper used by the
        # regional population model.  Exact local and parent strata are debited
        # together, so no death exists in one ledger but not the other.
        weights = [(str(k), max(0, int(v))) for k, v in civilian.items() if max(0, int(v)) > 0]
        allocation = self._weighted_integer_partition(take_total, weights)
        parent = pop.setdefault("strata", {})
        applied = 0
        for key, count in allocation.items():
            count = min(max(0, int(count)), max(0, int(civilian.get(key, 0))), max(0, int(parent.get(key, 0))))
            if count <= 0:
                continue
            civilian[key] = int(civilian.get(key, 0)) - count
            parent[key] = int(parent.get(key, 0)) - count
            applied += count
        if applied != take_total:
            raise ValueError("outbreak death settlement could not reconcile local and parent civilian strata")
        row["deaths_cumulative"] = int(row.get("deaths_cumulative", 0)) + applied
        row["last_outbreak_deaths_at"] = at
        self._sync_local_population_row(row)
        pop["population_total"] = sum(max(0, int(v)) for v in parent.values())
        self.put(pop_path, pop)
        return applied

    def _neighbor_sites(self, location_ref: str) -> list[tuple[str, str]]:
        routes = self.read("game/data/world/routes.json").get("routes", [])
        out: list[tuple[str, str]] = []
        for route in routes if isinstance(routes, list) else []:
            if not isinstance(route, Mapping) or bool(route.get("blocked", False)):
                continue
            a = str(route.get("a", route.get("from", "")))
            b = str(route.get("b", route.get("to", "")))
            if a == location_ref and b:
                out.append((str(route.get("ref", "")), b))
            elif b == location_ref and a:
                out.append((str(route.get("ref", "")), a))
        return sorted(set(out))

    def _propagate_outbreak(self, outbreak: dict[str, Any], at: str) -> list[str]:
        rules = self._settlement_civic_rules().get("outbreak", {})
        symptomatic = max(0, int(outbreak.get("symptomatic_cases", 0)))
        q = outbreak.get("quarantine", {}) if isinstance(outbreak.get("quarantine"), Mapping) else {}
        strength = _clamp(q.get("strength", 0), 0, 100) if q.get("active") else 0.0
        export_fraction = max(0.0, float(rules.get("route_export_fraction", 0.01))) * (1.0 - strength / 100.0)
        seed = min(max(0, int(rules.get("maximum_seed_cases", 50))), int(math.floor(symptomatic * export_fraction)))
        if seed < max(1, int(rules.get("minimum_seed_cases", 2))):
            return []
        existing = self._outbreak_index()
        created: list[str] = []
        already = {str(x.get("destination_ref")) for x in outbreak.get("propagation_history", []) if isinstance(x, Mapping)}
        seeded_anchors: set[str] = set()
        for route_ref, dest in self._neighbor_sites(str(outbreak.get("location_ref", ""))):
            if dest in already:
                continue
            try:
                _native, _pp, _pop, row, anchor = self._demographic_site(dest)
            except ValueError:
                continue
            residents = max(0, int(row.get("civilian_population", 0)))
            if residents <= 0 or anchor in seeded_anchors:
                continue
            duplicate = False
            for ref in existing.get("active_refs", []):
                path = existing.get("outbreaks", {}).get(ref)
                doc = self.read_optional(path) if isinstance(path, str) else None
                if isinstance(doc, Mapping) and str(doc.get("location_ref", "")) == anchor and str(doc.get("syndrome", "")) == str(outbreak.get("syndrome", "")):
                    duplicate = True
                    break
            if duplicate:
                continue
            child_payload = {
                "location_ref": anchor,
                "syndrome": str(outbreak.get("syndrome", "undifferentiated syndrome")),
                "transmission_route": str(outbreak.get("transmission_route", "close_contact")),
                "known_cases": min(seed, residents),
                "exposed_population": min(residents - min(seed, residents), max(seed * 10, seed)),
                "exposure_pressure": max(1, float(outbreak.get("exposure_pressure", 12)) * 0.7),
                "population_resistance": float(outbreak.get("population_resistance", 12)),
                "severity_band": str(outbreak.get("severity_band", "moderate")),
                "incubation_hours": int(outbreak.get("incubation_hours", 48)),
                "infectious_hours": int(outbreak.get("infectious_hours", 120)),
            }
            result = self._start_outbreak(child_payload, at, parent_outbreak_ref=str(outbreak.get("outbreak_ref", "")))
            seeded_anchors.add(anchor)
            created.append(str(result["outbreak_ref"]))
            outbreak.setdefault("propagation_history", []).append({
                "at": at,
                "route_ref": route_ref,
                "destination_ref": anchor,
                "seed_cases": min(seed, residents),
                "child_outbreak_ref": result["outbreak_ref"],
            })
            # One source review may seed several distinct neighboring sites, but never
            # the same route destination twice for the same outbreak lineage.
        outbreak["propagation_history"] = outbreak.get("propagation_history", [])[-64:]
        return created

    def _review_outbreak_once(self, outbreak_ref: str, at: str) -> dict[str, Any]:
        path = self._outbreak_path(outbreak_ref)
        outbreak = copy.deepcopy(self.read(path))
        if str(outbreak.get("status", "")) != "active":
            return {"outbreak_ref": outbreak_ref, "status": str(outbreak.get("status", ""))}
        rules = self._settlement_civic_rules().get("outbreak", {})
        q = outbreak.get("quarantine", {}) if isinstance(outbreak.get("quarantine"), Mapping) else {}
        q_strength = _clamp(q.get("strength", 0), 0, 100) if q.get("active") else 0.0
        isolation_points = q_strength * max(0.0, float(rules.get("quarantine_isolation_points_per_strength", 0.20)))
        margin = float(outbreak.get("exposure_pressure", 0)) - isolation_points - float(outbreak.get("population_resistance", 0))
        contact_fraction = self._contact_fraction(margin)
        susceptible = max(0, int(outbreak.get("exposed_susceptible", 0)))
        carry = max(0.0, float(outbreak.get("fractional_case_carry", 0.0)))
        exact_new = susceptible * contact_fraction + carry
        new_cases = min(susceptible, int(math.floor(exact_new)))
        outbreak["fractional_case_carry"] = max(0.0, exact_new - new_cases)
        outbreak["exposed_susceptible"] = susceptible - new_cases
        outbreak["incubating_cases"] = max(0, int(outbreak.get("incubating_cases", 0))) + new_cases
        outbreak["known_cases"] = int(outbreak.get("known_cases", 0)) + new_cases

        incubation_days = max(1.0, float(outbreak.get("incubation_hours", 48)) / 24.0)
        incubating = max(0, int(outbreak.get("incubating_cases", 0)))
        mature = min(incubating, max(0, int(math.ceil(incubating / incubation_days))))
        outbreak["incubating_cases"] = incubating - mature
        symptomatic = max(0, int(outbreak.get("symptomatic_cases", 0))) + mature

        severity = str(outbreak.get("severity_band", "moderate"))
        progression = rules.get("severity", {}).get(severity, rules.get("severity", {}).get("moderate", {}))
        daily_resolution = _clamp(progression.get("daily_resolution_fraction", 0.10), 0, 1)
        fatality = _clamp(progression.get("fatality_fraction_of_resolved", 0.02), 0, 1)
        medical_support = _clamp(outbreak.get("population_resistance", 0), 0, 100)
        care_reduction = _clamp(medical_support * float(rules.get("fatality_reduction_per_resistance_point", 0.003)), 0, 0.75)
        effective_fatality = fatality * (1.0 - care_reduction)
        resolved = min(symptomatic, int(math.floor(symptomatic * daily_resolution)))
        deaths_due = min(resolved, int(math.floor(resolved * effective_fatality)))
        recoveries = max(0, resolved - deaths_due)
        applied_deaths = self._apply_outbreak_deaths(str(outbreak.get("location_ref", "")), deaths_due, at)
        if applied_deaths < deaths_due:
            recoveries += deaths_due - applied_deaths
        outbreak["symptomatic_cases"] = max(0, symptomatic - resolved)
        outbreak["recovered_cases"] = int(outbreak.get("recovered_cases", 0)) + recoveries
        outbreak["deaths"] = int(outbreak.get("deaths", 0)) + applied_deaths

        spread_refs = self._propagate_outbreak(outbreak, at)
        active_cases = int(outbreak.get("incubating_cases", 0)) + int(outbreak.get("symptomatic_cases", 0))
        if active_cases <= 0:
            outbreak["status"] = "resolved"
            outbreak["resolved_at"] = at
            idx = self._outbreak_index()
            idx["active_refs"] = [x for x in idx.get("active_refs", []) if str(x) != outbreak_ref]
            self.put(OUTBREAK_INDEX, idx)
        outbreak["last_review_at"] = at
        outbreak["next_review_at"] = None if outbreak.get("status") != "active" else str(CampaignTime.parse(at).add_hours(24))
        outbreak.setdefault("review_history", []).append({
            "at": at,
            "disease_margin": round(margin, 3),
            "contact_fraction": round(contact_fraction, 6),
            "new_cases": new_cases,
            "incubating_to_symptomatic": mature,
            "resolved_cases": resolved,
            "recoveries": recoveries,
            "deaths": applied_deaths,
            "propagated_outbreak_refs": spread_refs,
        })
        outbreak["review_history"] = outbreak["review_history"][-90:]
        self.put(path, outbreak)
        return {
            "outbreak_ref": outbreak_ref,
            "status": outbreak.get("status"),
            "new_cases": new_cases,
            "recoveries": recoveries,
            "deaths": applied_deaths,
            "propagated_outbreak_refs": spread_refs,
        }

    def _set_outbreak_quarantine(self, payload: Mapping[str, Any], at: str) -> dict[str, Any]:
        outbreak_ref = str(payload["outbreak_ref"])
        path = self._outbreak_path(outbreak_ref)
        outbreak = copy.deepcopy(self.read(path))
        if str(outbreak.get("status", "")) != "active":
            raise ValueError("quarantine can change only an active outbreak")
        active = bool(payload.get("active", True))
        strength = max(0, min(100, int(payload.get("quarantine_strength", 50)))) if active else 0
        supply_days = max(0, int(payload.get("supply_days", 0))) if active else 0
        outbreak["quarantine"] = {
            "active": active,
            "strength": strength,
            "supply_days": supply_days,
            "authorized_at": at,
            "rule": "quarantine reduces contact only to the degree saved here; it does not create food, guards, immunity, or compliance",
        }
        self.put(path, outbreak)
        return {"outbreak_ref": outbreak_ref, "quarantine": outbreak["quarantine"]}

    def _settle_due_outbreaks(self, target_text: str) -> dict[str, int]:
        target = CampaignTime.parse(target_text)
        reviews = 0
        created = 0
        # Re-read the index each loop because propagation can append active refs.
        guard = 0
        while True:
            guard += 1
            if guard > 4096:
                raise ValueError("outbreak settlement exceeded bounded review guard")
            idx = self._outbreak_index()
            due: list[tuple[CampaignTime, str]] = []
            for ref in idx.get("active_refs", []):
                path = idx.get("outbreaks", {}).get(ref)
                doc = self.read_optional(path) if isinstance(path, str) else None
                if not isinstance(doc, Mapping) or str(doc.get("status", "")) != "active" or not doc.get("next_review_at"):
                    continue
                when = CampaignTime.parse(str(doc["next_review_at"]))
                if when <= target:
                    due.append((when, str(ref)))
            if not due:
                break
            when, ref = sorted(due, key=lambda x: (x[0], x[1]))[0]
            result = self._review_outbreak_once(ref, str(when))
            reviews += 1
            created += len(result.get("propagated_outbreak_refs", []))
        return {"outbreak_reviews": reviews, "outbreaks_propagated": created}

    # ------------------------------------------------------------------
    # Runtime hooks / command surface
    # ------------------------------------------------------------------

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        metrics = dict(super()._advance_runtime(target_text))
        outbreak_metrics = self._settle_due_outbreaks(target_text)
        for key, value in outbreak_metrics.items():
            metrics[key] = int(metrics.get(key, 0)) + int(value)
        return metrics

    def _dispatch_settlement_civic_action(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if str(command.actor_id) != str(self.INTERNAL_ACTOR):
            raise PermissionError("settlement civic mutation is a causal/internal consequence; player legal authority routes through sovereign/House commands")
        action = str(payload.get("action", ""))
        at = str(self._world_time())
        if action == "register_local_case":
            result = self._register_local_case(payload, at)
        elif action == "resolve_local_case":
            result = self._resolve_local_case(payload, at)
        elif action == "start_outbreak":
            result = self._start_outbreak(payload, at)
        elif action == "set_quarantine":
            result = self._set_outbreak_quarantine(payload, at)
        elif action == "review_outbreak":
            result = self._review_outbreak_once(str(payload["outbreak_ref"]), at)
        else:
            raise ValueError("unsupported settlement civic action")
        world_time, metrics = self._advance_seconds(300 if action.startswith("register") or action.startswith("resolve") else 3600)
        self._write_meta(command, world_time)
        return self._result(world_time=world_time, action=action, **result, **metrics)

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "settlement_civic_action":
            return self._dispatch_settlement_civic_action(command, payload)
        return super()._dispatch(command, payload)
