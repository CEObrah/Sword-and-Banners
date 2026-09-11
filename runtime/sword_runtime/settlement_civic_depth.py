from __future__ import annotations

import copy
import hashlib
import math
import re
from collections.abc import Mapping
from typing import Any

from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.person_location_index import person_location, person_refs_at_locations
from sword_runtime.tang_population import resident_support_capacity, sync_tang_private_population


JUSTICE_INDEX = "state/civic/justice/index.json"
OUTBREAK_INDEX = "state/civic/outbreaks/index.json"
OUTBREAK_REVIEW_SECONDS = 24 * 3600
OUTBREAK_HOST_PRIORITY = 82


_CIVIC_REF = re.compile(r"[A-Za-z0-9_.:-]{1,192}")


def _civic_record_path(folder: str, ref: str) -> str:
    if not isinstance(ref, str) or not _CIVIC_REF.fullmatch(ref):
        raise ValueError("invalid civic record ref")
    return f"state/civic/{folder}/{ref}.json"


def _resolve_civic_index_record(
    planner: Any,
    index: Mapping[str, Any],
    *,
    bucket: str,
    ref: str,
    folder: str,
    schema: str,
    id_field: str,
) -> tuple[str, Mapping[str, Any]] | None:
    """Resolve an exact civic owner without granting authority to its routing index."""
    canonical = _civic_record_path(folder, ref)
    routes = index.get(bucket, {}) if isinstance(index.get(bucket), Mapping) else {}
    routed = routes.get(ref) if isinstance(routes, Mapping) else None
    candidates = [routed, canonical] if isinstance(routed, str) else [canonical]
    seen: set[str] = set()
    for path in candidates:
        if not isinstance(path, str) or not path or path in seen:
            continue
        seen.add(path)
        doc = planner.read_optional(path)
        if not isinstance(doc, Mapping):
            continue
        if str(doc.get("schema", "")) != schema or str(doc.get(id_field, "")) != ref:
            continue
        return path, doc
    return None


def _registered_civic_records(
    planner: Any,
    index: Mapping[str, Any],
    *,
    bucket: str,
    route_list: str,
    folder: str,
    schema: str,
    id_field: str,
    active_status: str,
) -> list[tuple[str, str, Mapping[str, Any]]]:
    """Recover a civic route cache from exact registered owners.

    Legacy cache keys remain bounded hints. New civic owners are registered in
    the authoritative owner index, so losing both their route mapping and
    active/open list entry cannot freeze the process.
    """
    candidate_refs: set[str] = set()
    routes = index.get(bucket, {}) if isinstance(index.get(bucket), Mapping) else {}
    candidate_refs.update(str(ref) for ref in routes if isinstance(ref, str))
    routed = index.get(route_list, []) if isinstance(index.get(route_list), list) else []
    candidate_refs.update(str(ref) for ref in routed if isinstance(ref, str))
    try:
        owners_doc = planner.read("state/index/owner-index.json")
    except (FileNotFoundError, KeyError, ValueError):
        owners_doc = {}
    owners = owners_doc.get("owners", {}) if isinstance(owners_doc, Mapping) else {}
    prefix = f"state/civic/{folder}/"
    if isinstance(owners, Mapping):
        for ref, path in owners.items():
            if isinstance(ref, str) and isinstance(path, str) and path.startswith(prefix) and not path.endswith("/index.json"):
                candidate_refs.add(ref)

    rows: list[tuple[str, str, Mapping[str, Any]]] = []
    repaired_routes: dict[str, str] = {}
    active_refs: list[str] = []
    for ref in sorted(candidate_refs):
        resolved = _resolve_civic_index_record(
            planner, index, bucket=bucket, ref=ref, folder=folder,
            schema=schema, id_field=id_field,
        )
        if resolved is None:
            # A missing secondary mapping may still have an authoritative owner
            # route whose path is not the legacy canonical filename.
            try:
                exact_path = planner.owner_path(ref)
            except (FileNotFoundError, KeyError, ValueError):
                continue
            doc = planner.read_optional(exact_path)
            if not isinstance(doc, Mapping) or str(doc.get("schema", "")) != schema or str(doc.get(id_field, "")) != ref:
                continue
            resolved = (exact_path, doc)
        path, doc = resolved
        repaired_routes[ref] = path
        if str(doc.get("status", "")) == active_status:
            rows.append((ref, path, doc))
            active_refs.append(ref)

    if isinstance(index, dict):
        before_routes = index.get(bucket)
        before_active = index.get(route_list)
        if before_routes != repaired_routes or before_active != active_refs:
            index[bucket] = repaired_routes
            index[route_list] = active_refs
            path = OUTBREAK_INDEX if folder == "outbreaks" else JUSTICE_INDEX
            planner.put(path, index)
    return rows


def _active_outbreak_records(planner: Any, index: Mapping[str, Any] | None = None) -> list[tuple[str, str, Mapping[str, Any]]]:
    idx = index if isinstance(index, Mapping) else (planner.read_optional(OUTBREAK_INDEX) or {"outbreaks": {}, "active_refs": []})
    return _registered_civic_records(
        planner, idx, bucket="outbreaks", route_list="active_refs", folder="outbreaks",
        schema="sword-settlement-outbreak", id_field="outbreak_ref", active_status="active",
    )


def _open_justice_records(planner: Any, index: Mapping[str, Any] | None = None) -> list[tuple[str, str, Mapping[str, Any]]]:
    idx = index if isinstance(index, Mapping) else (planner.read_optional(JUSTICE_INDEX) or {"cases": {}, "open_refs": []})
    return _registered_civic_records(
        planner, idx, bucket="cases", route_list="open_refs", folder="justice",
        schema="sword-local-justice-case", id_field="case_ref", active_status="open",
    )


def _outbreak_route_ids(outbreak_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(str(outbreak_ref).encode("utf-8")).hexdigest()[:18]
    return f"host_outbreak_review_{digest}", f"event_outbreak_review_{digest}"


def sync_outbreak_routes(planner: Any, runtime: dict[str, Any]) -> None:
    """Keep active civilian outbreaks on the one production causal clock.

    Outbreak documents own disease state; runtime hosts only route their exact
    ``next_review_at``.  This prevents long ``advance_time`` commands from
    simulating months of disease retroactively in a post-advance catch-up loop.
    """
    index = planner.read_optional(OUTBREAK_INDEX) or {"outbreaks": {}, "active_refs": []}
    active_records = _active_outbreak_records(planner, index)
    hosts = runtime.setdefault("hosts", {})
    events = runtime.setdefault("events", [])
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal registry is invalid")

    active_host_ids: set[str] = set()
    current = CampaignTime.parse(str(runtime.get("world_time")))
    event_by_id = {
        str(row.get("event_id")): row for row in events
        if isinstance(row, dict) and isinstance(row.get("event_id"), str)
    }
    for outbreak_ref, _path, doc in active_records:
        if str(doc.get("status", "")) != "active":
            continue
        due_text = doc.get("next_review_at")
        if not isinstance(due_text, str) or not due_text:
            continue
        due = CampaignTime.parse(due_text)
        # A missing legacy route may only be repaired at the current frontier.
        # Normal runtime-created outbreaks always register their first review at
        # creation time, so this branch is recovery rather than ordinary play.
        if due < current:
            due = current
            due_text = str(current)
        host_id, event_id = _outbreak_route_ids(outbreak_ref)
        active_host_ids.add(host_id)
        host = hosts.get(host_id)
        if not isinstance(host, dict):
            host = {
                "kind": "settlement_outbreak",
                "owner_ref": outbreak_ref,
                "event_id": event_id,
                "recurrence_seconds": OUTBREAK_REVIEW_SECONDS,
                "resolved_through": str(doc.get("last_review_at", doc.get("created_at", runtime.get("world_time")))),
                "next_due": due_text,
                "safe_through": str(due.add_seconds(-1)),
            }
            hosts[host_id] = host
        else:
            host.update({
                "kind": "settlement_outbreak",
                "owner_ref": outbreak_ref,
                "event_id": event_id,
                "recurrence_seconds": OUTBREAK_REVIEW_SECONDS,
                "next_due": due_text,
                "safe_through": str(due.add_seconds(-1)),
            })
        event = event_by_id.get(event_id)
        if not isinstance(event, dict):
            event = {
                "event_id": event_id,
                "kind": "settlement_outbreak",
                "priority": OUTBREAK_HOST_PRIORITY,
                "target_host": host_id,
                "due_at": due_text,
            }
            events.append(event)
            event_by_id[event_id] = event
        else:
            event.update({
                "kind": "settlement_outbreak",
                "priority": OUTBREAK_HOST_PRIORITY,
                "target_host": host_id,
                "due_at": due_text,
            })
            event.pop("suspended", None)

    stale_hosts = {
        host_id for host_id, host in hosts.items()
        if isinstance(host, Mapping) and str(host.get("kind", "")) == "settlement_outbreak" and host_id not in active_host_ids
    }
    if stale_hosts:
        stale_event_ids = {str(hosts[host_id].get("event_id", "")) for host_id in stale_hosts if isinstance(hosts.get(host_id), Mapping)}
        for host_id in stale_hosts:
            hosts.pop(host_id, None)
        runtime["events"] = [
            row for row in events
            if not (isinstance(row, Mapping) and str(row.get("event_id", "")) in stale_event_ids)
        ]


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
        resolved = _resolve_civic_index_record(
            self, idx, bucket="cases", ref=case_ref, folder="justice",
            schema="sword-local-justice-case", id_field="case_ref",
        )
        if resolved is None:
            raise ValueError("unknown local justice case")
        return resolved[0]

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
        raw_subject_ref = payload.get("subject_ref")
        subject_ref = str(raw_subject_ref) if isinstance(raw_subject_ref, str) and raw_subject_ref else None
        evidence_refs = sorted({str(x) for x in payload.get("evidence_refs", []) if isinstance(x, str)})
        self._validate_local_evidence_refs(evidence_refs, subject_ref)

        case_ref = str(payload.get("case_ref") or self._civic_token("local_case", anchor, case_kind, subject_ref or "unknown", at))
        idx = self._justice_index()
        if _resolve_civic_index_record(
            self, idx, bucket="cases", ref=case_ref, folder="justice",
            schema="sword-local-justice-case", id_field="case_ref",
        ) is not None:
            raise ValueError("local justice case already exists")
        path = _civic_record_path("justice", case_ref)
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
            "causal_basis": copy.deepcopy(payload.get("causal_basis")) if isinstance(payload.get("causal_basis"), Mapping) else None,
            "autonomous_seed": bool(payload.get("autonomous_seed", False)),
            "history": [{"at": at, "event": "case_seeded_from_pressure" if bool(payload.get("autonomous_seed", False)) else "case_registered"}],
            "rule": "a local case records alleged civic/legal pressure only; registration does not establish guilt, invent evidence, or create an accused person",
        }
        idx.setdefault("cases", {})[case_ref] = path
        idx.setdefault("open_refs", []).append(case_ref)
        idx["open_refs"] = sorted(set(str(x) for x in idx["open_refs"]))
        self.put(path, doc)
        self._register_owner(case_ref, path)
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
        resolved = _resolve_civic_index_record(
            self, idx, bucket="outbreaks", ref=outbreak_ref, folder="outbreaks",
            schema="sword-settlement-outbreak", id_field="outbreak_ref",
        )
        if resolved is None:
            raise ValueError("unknown settlement outbreak")
        return resolved[0]

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
        if _resolve_civic_index_record(
            self, idx, bucket="outbreaks", ref=outbreak_ref, folder="outbreaks",
            schema="sword-settlement-outbreak", id_field="outbreak_ref",
        ) is not None:
            raise ValueError("settlement outbreak already exists")
        path = _civic_record_path("outbreaks", outbreak_ref)
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
        self._register_owner(outbreak_ref, path)
        self.put(OUTBREAK_INDEX, idx)
        self._seed_named_outbreak_exposures(outbreak_ref, at)
        runtime = copy.deepcopy(self.read("state/runtime.json"))
        sync_outbreak_routes(self, runtime)
        self.put("state/runtime.json", runtime)
        return {"outbreak_ref": outbreak_ref, "location_ref": doc["location_ref"], "status": "active"}

    def _named_people_at_demographic_site(self, anchor: str) -> list[str]:
        index = self.read_optional("state/index/person-location-index.json") or {}
        person_locations = index.get("person_location", {}) if isinstance(index, Mapping) else {}
        matching_locations: set[str] = set()
        if isinstance(person_locations, Mapping):
            for loc in sorted({str(x) for x in person_locations.values() if isinstance(x, str)}):
                try:
                    _native, _pp, _pop, _row, resolved = self._demographic_site(loc)
                except (ValueError, KeyError, FileNotFoundError):
                    continue
                if str(resolved) == str(anchor):
                    matching_locations.add(loc)
        candidates = person_refs_at_locations(self, matching_locations)
        exact: list[str] = []
        for person_ref in candidates:
            try:
                path = self.owner_path(person_ref)
                person = self.read(path)
            except (ValueError, KeyError, FileNotFoundError):
                continue
            if not isinstance(person, Mapping) or str(person.get("schema", "")) not in {"sab_character", "sword-materialized-person", "person-lite"}:
                continue
            exact_location = person_location(person)
            if not isinstance(exact_location, str) or not exact_location:
                continue
            try:
                _native, _pp, _pop, _row, resolved = self._demographic_site(exact_location)
            except (ValueError, KeyError, FileNotFoundError):
                continue
            if str(resolved) == str(anchor):
                exact.append(person_ref)
        return exact

    def _seed_named_outbreak_exposures(self, outbreak_ref: str, at: str) -> None:
        path = self._outbreak_path(outbreak_ref)
        outbreak = copy.deepcopy(self.read(path))
        anchor = str(outbreak.get("location_ref", ""))
        rows = outbreak.setdefault("named_exposures", [])
        existing = {str(row.get("person_ref", "")) for row in rows if isinstance(row, Mapping)}
        for person_ref in self._named_people_at_demographic_site(anchor):
            if person_ref in existing:
                continue
            rows.append({
                "person_ref": person_ref,
                "first_exposed_at": at,
                "status": "exposed",
                "basis": "exact named person was physically present inside the outbreak demographic site",
            })
        outbreak["named_exposures"] = rows[-256:]
        self.put(path, outbreak)

    def _settle_named_outbreak_exposures(self, outbreak: dict[str, Any], at: str, contact_fraction: float) -> dict[str, int]:
        infected = 0
        recovered = 0
        now = CampaignTime.parse(at)
        for row in outbreak.get("named_exposures", []) if isinstance(outbreak.get("named_exposures"), list) else []:
            if not isinstance(row, dict):
                continue
            person_ref = str(row.get("person_ref", ""))
            if not person_ref:
                continue
            try:
                person_path = self.owner_path(person_ref)
                person = copy.deepcopy(self.read(person_path))
            except (ValueError, KeyError, FileNotFoundError):
                row["status"] = "unavailable"
                continue
            if not isinstance(person, Mapping) or str(person.get("schema", "")) not in {"sab_character", "sword-materialized-person", "person-lite"}:
                row["status"] = "unavailable"
                continue
            if str(row.get("status", "")) == "infected":
                infected_at = row.get("infected_at")
                if infected_at and now.seconds_since(CampaignTime.parse(str(infected_at))) >= max(24, int(outbreak.get("infectious_hours", 120))) * 3600:
                    if self._person_health(person).lower() == "ill" and str(row.get("health_consequence", "")) == "outbreak_illness":
                        self._set_person_health(person, "healthy")
                        person.setdefault("health_history", []).append({"at": at, "kind": "outbreak_recovery", "outbreak_ref": str(outbreak.get("outbreak_ref", ""))})
                        person["health_history"] = person["health_history"][-64:]
                        self.put(person_path, person)
                    row["status"] = "recovered"
                    row["recovered_at"] = at
                    recovered += 1
                continue
            if str(row.get("status", "")) != "exposed":
                continue
            # Deterministic exposure review. Resistance and contact determine the
            # threshold; the hash only chooses which already-present exact person
            # falls inside that bounded risk, so repeated previews remain identical.
            resistance = _clamp(outbreak.get("population_resistance", 12), 0, 100)
            risk_bp = int(max(1, min(8500, round(max(0.0, contact_fraction) * 10000 * (1.0 - resistance / 140.0)))))
            digest = hashlib.sha256(f"{outbreak.get('outbreak_ref')}|{person_ref}|{at}|named_exposure".encode()).hexdigest()
            if int(digest[:8], 16) % 10000 >= risk_bp:
                row["last_exposure_review_at"] = at
                continue
            if self._person_health(person).lower() in {"healthy", "fit", "well", "normal"}:
                self._set_person_health(person, "ill")
                person.setdefault("health_history", []).append({
                    "at": at, "kind": "outbreak_illness", "outbreak_ref": str(outbreak.get("outbreak_ref", "")),
                    "syndrome": str(outbreak.get("syndrome", "undifferentiated syndrome")),
                })
                person["health_history"] = person["health_history"][-64:]
                self.put(person_path, person)
                row["health_consequence"] = "outbreak_illness"
            else:
                row["health_consequence"] = "exposure_while_not_healthy"
            row["status"] = "infected"
            row["infected_at"] = at
            infected += 1
        return {"infected": infected, "recovered": recovered}

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
        if native == "qin" and str(_anchor) == "loc_tang_manor":
            sync_tang_private_population(self, at=at, reason="civilian_outbreak_deaths", evidence_ref=f"outbreak_deaths:{at}")
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
            for ref, _outbreak_path, doc in _active_outbreak_records(self, existing):
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
        self._seed_named_outbreak_exposures(outbreak_ref, at)
        # Rehydrate any just-added exposures before exact-person review.
        latest = self.read(path)
        if isinstance(latest, Mapping):
            outbreak["named_exposures"] = copy.deepcopy(latest.get("named_exposures", outbreak.get("named_exposures", [])))
        named = self._settle_named_outbreak_exposures(outbreak, at, contact_fraction)
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
            "named_infections": int(named.get("infected", 0)),
            "named_recoveries": int(named.get("recovered", 0)),
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

    def _autonomous_civic_pressure_review(self, state: str, at: str, occurrences: int = 1) -> dict[str, Any]:
        """Seed bounded civic consequences only from already-committed pressure."""
        state = str(state).lower().replace("state_", "")
        pop = self.read(f"state/population/{state}.json")
        sites = pop.get("local_population", {}).get("sites", {}) if isinstance(pop, Mapping) else {}
        infra_doc = self.read("state/infrastructure/settlements.json")
        infra_sites = infra_doc.get("sites", {}) if isinstance(infra_doc, Mapping) else {}
        territory = self.read("state/territory/control.json")
        territory_sites = territory.get("sites", {}) if isinstance(territory, Mapping) else {}
        state_doc = self.read(f"state/states/{state}.json")
        stability = max(0, min(100, int(state_doc.get("internal_stability", 60))))
        try:
            economy = self.read(f"state/economy/private/{state}.json")
            local_economy = economy.get("local_regions", {}).get("regions", {}) if isinstance(economy, Mapping) else {}
        except FileNotFoundError:
            local_economy = {}
        outbreak_idx = self._outbreak_index()
        active_sites: set[str] = set()
        for ref, _outbreak_path, doc in _active_outbreak_records(self, outbreak_idx):
            if isinstance(doc, Mapping) and str(doc.get("status", "")) == "active":
                active_sites.add(str(doc.get("location_ref", "")))
        outbreak_candidates: list[tuple[float, str, dict[str, Any]]] = []
        justice_candidates: list[tuple[float, str, str, dict[str, Any]]] = []
        open_cases = []
        jidx = self._justice_index()
        for ref, _case_path, doc in _open_justice_records(self, jidx):
            if isinstance(doc, Mapping):
                open_cases.append(doc)
        for anchor, row in sorted(sites.items()):
            if not isinstance(row, Mapping):
                continue
            civilians = max(0, int(row.get("civilian_population", 0)))
            service = max(0, int(row.get("service_population", 0)))
            residents = civilians + service
            if civilians <= 0:
                continue
            residence_ref, support_capacity = resident_support_capacity(infra_sites, str(anchor), residents)
            support = infra_sites.get(residence_ref, {}) if isinstance(infra_sites, Mapping) else {}
            physical = support.get("physical_support", {}) if isinstance(support, Mapping) else {}
            capacity = max(1, int(support_capacity or residents))
            crowd = max(0.0, residents / capacity - 1.0)
            displaced = max(0, int(row.get("displaced", 0)))
            displaced_fraction = displaced / max(1, civilians)
            water = max(0, int(physical.get("water_capacity_people", capacity))) if isinstance(physical, Mapping) else capacity
            sanitation = max(0, int(physical.get("sanitation_capacity_people", capacity))) if isinstance(physical, Mapping) else capacity
            food_support = max(0, int(physical.get("food_storage_distribution_capacity_people", capacity))) if isinstance(physical, Mapping) else capacity
            water_short = max(0.0, 1.0 - water / max(1, residents))
            sanitation_short = max(0.0, 1.0 - sanitation / max(1, residents))
            food_distribution_short = max(0.0, 1.0 - food_support / max(1, residents))
            eco = local_economy.get(anchor, {}) if isinstance(local_economy, Mapping) else {}
            feedback = eco.get("production_runtime", {}).get("economic_feedback", {}) if isinstance(eco, Mapping) else {}
            food_short = max(0.0, min(1.0, float(feedback.get("grain_shortfall_fraction", 0.0)))) if isinstance(feedback, Mapping) else 0.0
            tsite = territory_sites.get(anchor, {}) if isinstance(territory_sites, Mapping) else {}
            controller = str(tsite.get("controller", f"state_{state}")) if isinstance(tsite, Mapping) else f"state_{state}"
            occupation = 1.0 if controller and controller != f"state_{state}" else 0.0
            governance = tsite.get("governance", {}) if isinstance(tsite, Mapping) else {}
            resistance = max(0, min(100, int(governance.get("resistance", governance.get("resistance_pressure", 0))))) if isinstance(governance, Mapping) else 0
            disease_score = (crowd * 80.0 + displaced_fraction * 120.0 + water_short * 55.0 + sanitation_short * 45.0 + food_distribution_short * 25.0 + food_short * 35.0 + occupation * 8.0 + max(0, 45 - stability) * 0.35)
            disease_basis = {
                "residence_site_ref": residence_ref, "resident_load": residents, "resident_support_capacity": capacity,
                "crowding_fraction": round(crowd, 6), "displaced_fraction": round(displaced_fraction, 6),
                "water_shortfall_fraction": round(water_short, 6), "sanitation_shortfall_fraction": round(sanitation_short, 6),
                "food_distribution_shortfall_fraction": round(food_distribution_short, 6), "grain_shortfall_fraction": round(food_short, 6),
                "occupation": bool(occupation), "state_stability": stability,
            }
            if disease_score >= 20.0 and str(anchor) not in active_sites:
                outbreak_candidates.append((disease_score, str(anchor), disease_basis))
            justice_score = max(food_short * 70.0, occupation * 25.0 + resistance * 0.45, max(0, 45 - stability) * 1.2, displaced_fraction * 120.0)
            if justice_score >= 18.0:
                if occupation and resistance >= 20:
                    kind = "banditry"
                elif food_short >= 0.20:
                    kind = "property"
                elif stability < 35:
                    kind = "corruption"
                else:
                    kind = "violence"
                duplicate = any(str(case.get("location_ref", "")) == str(anchor) and str(case.get("case_kind", "")) == kind for case in open_cases)
                if not duplicate:
                    justice_candidates.append((justice_score, str(anchor), kind, {**disease_basis, "resistance_pressure": resistance, "controller": controller}))
        seeded_outbreak = None
        if outbreak_candidates:
            score, anchor, basis = sorted(outbreak_candidates, key=lambda x: (-x[0], x[1]))[0]
            dominant = max(((basis["water_shortfall_fraction"], "waterborne enteric syndrome", "water_food"), (basis["sanitation_shortfall_fraction"], "enteric febrile syndrome", "close_contact"), (basis["crowding_fraction"] + basis["displaced_fraction"], "crowded-settlement febrile syndrome", "close_contact"), (basis["grain_shortfall_fraction"], "deprivation-associated enteric syndrome", "water_food")), key=lambda x: x[0])
            severity = "severe" if score >= 60 else "moderate" if score >= 35 else "mild"
            residents = max(1, int(sites[anchor].get("civilian_population", 0)))
            rules = self._settlement_civic_rules().get("outbreak", {})
            min_seed = max(1, int(rules.get("minimum_seed_cases", 2))); max_seed = max(min_seed, int(rules.get("maximum_seed_cases", 50)))
            known = min(max_seed, max(min_seed, int(math.ceil(residents * min(0.00002, score / 5_000_000.0)))))
            result = self._start_outbreak({
                "location_ref": anchor, "syndrome": dominant[1], "transmission_route": dominant[2],
                "known_cases": known, "exposed_population": min(max(known * 20, known), max(known, residents - known)),
                "exposure_pressure": min(100.0, 10.0 + score), "population_resistance": max(5.0, min(60.0, 35.0 - score * 0.15)),
                "severity_band": severity, "incubation_hours": 48, "infectious_hours": 120,
            }, at)
            seeded_outbreak = result["outbreak_ref"]
            idx = self._outbreak_index(); idx.setdefault("autonomous_seed_history", []).append({"at": at, "outbreak_ref": seeded_outbreak, "location_ref": anchor, "risk_score": round(score, 3), "basis": basis}); idx["autonomous_seed_history"] = idx["autonomous_seed_history"][-128:]; self.put(OUTBREAK_INDEX, idx)
        seeded_case = None
        if justice_candidates:
            score, anchor, kind, basis = sorted(justice_candidates, key=lambda x: (-x[0], x[1], x[2]))[0]
            bucket = f"{CampaignTime.parse(at).bce_year:04d}-{CampaignTime.parse(at).month:02d}"
            case_ref = self._civic_token("local_case", state, anchor, kind, bucket)
            justice_idx = self._justice_index()
            if _resolve_civic_index_record(
                self, justice_idx, bucket="cases", ref=case_ref, folder="justice",
                schema="sword-local-justice-case", id_field="case_ref",
            ) is None:
                result = self._register_local_case({"case_ref": case_ref, "location_ref": anchor, "case_kind": kind, "severity": min(100, max(1, int(round(score)))), "subject_ref": None, "evidence_refs": [], "autonomous_seed": True, "causal_basis": {"pressure_score": round(score, 3), **basis}}, at)
                seeded_case = result["case_ref"]
        return {"outbreak_ref": seeded_outbreak, "case_ref": seeded_case}

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
            for ref, _outbreak_path, doc in _active_outbreak_records(self, idx):
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

    def _command_layer_settlement_civic_depth(self, command: Any, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
        if command.command_type == "settlement_civic_action":
            return self._dispatch_settlement_civic_action(command, payload)
        return next_dispatch()
