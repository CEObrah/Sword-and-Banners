"""Project the registered House Tang production owner into family field-prep reports."""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner

_HOUSE_PATH = "state/houses/house_tang.json"
_RULES_PATH = "game/data/mechanics/house-tang-production.json"
_OLD = "The ledger does not contain a House-owned monthly Tang-armor manufacturing owner, so it will not fabricate a production number: current restricted reserves are real stock, while long spears, long swords, expedition spares and any replacement mounts beyond exact reserves still require lawful issue or procurement before they are called prepared."


def project_house_production_into_field_preparation(planner: Any, event_ref: str) -> None:
    rules = planner.read(_RULES_PATH)
    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    programs = house.setdefault("administrative_programs", {})
    prep = programs.get("wei_field_preparation")
    if not isinstance(prep, MutableMapping):
        return
    production = programs.get("house_equipment_production") if isinstance(programs, Mapping) else None
    forge = int(production.get("forge_and_armory_workers", 0)) if isinstance(production, Mapping) else int(planner.read("state/population/tang-manor.json").get("strata", {}).get("forge_and_armory_workers", 0))
    stable = int(production.get("stable_remount_and_carriage_workers", 0)) if isinstance(production, Mapping) else int(planner.read("state/population/tang-manor.json").get("strata", {}).get("stable_remount_and_carriage_workers", 0))
    truth = (
        f"House Tang has a registered monthly armory/remount production owner backed by {forge} forge-and-armory workers and {stable} stable/remount workers. "
        "Output is not a free flat rate: each close is bounded by registered work shares, nearby private construction materials or horse stock, House silver and exact reserve shortages."
    )
    prep["manufacturing_truth"] = truth
    prep["production_rules_ref"] = _RULES_PATH
    if isinstance(production, Mapping):
        prep["production_last_close"] = production.get("last_close")
        prep["production_last_output"] = copy.deepcopy(production.get("last_output", {}))
    programs["wei_field_preparation"] = prep
    planner.put(_HOUSE_PATH, house)

    _path, owner = read_causal_event_owner(planner)
    event = owner.get("causal_events", {}).get(event_ref)
    if isinstance(event, MutableMapping):
        summary = str(event.get("summary", ""))
        replacement = (
            f"House Tang's armory and remount workshops are now registered against {forge} forge/armory workers and {stable} stable/remount workers. "
            "Their monthly output is resource-bounded by nearby material or horse stock, House silver, and reserve-target shortfalls; the report therefore distinguishes exact current stock from future replenishment instead of inventing instant production."
        )
        if _OLD in summary:
            summary = summary.replace(_OLD, replacement)
        elif replacement not in summary:
            summary = (summary + " " + replacement)[:4000]
        event["summary"] = summary[:4000]
        write_causal_event_owner(planner, owner)
        wake = getattr(planner, "_pending_wake_created", None)
        if isinstance(wake, MutableMapping) and wake.get("campaign_event_ref") == event_ref:
            wake["reason"] = event["summary"]


class HouseFieldPreparationProductionProjectionMixin:
    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        super()._run_due_host(host, due_text)
        if host.get("kind") == "house_field_preparation_reply":
            event_ref = str(host.get("response_event_ref", ""))
            if event_ref:
                project_house_production_into_field_preparation(self, event_ref)


__all__ = ["HouseFieldPreparationProductionProjectionMixin", "project_house_production_into_field_preparation"]
