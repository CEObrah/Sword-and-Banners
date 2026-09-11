"""Project the registered House Tang production owner into family field-prep reports."""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner

_HOUSE_PATH = "state/houses/house_tang.json"
_RULES_PATH = "game/data/mechanics/outfitting.json"

def project_house_production_into_field_preparation(planner: Any, event_ref: str) -> None:
    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    programs = house.setdefault("administrative_programs", {})
    prep = programs.get("wei_field_preparation")
    if not isinstance(prep, MutableMapping):
        return
    prep["outfitting_rules_ref"] = _RULES_PATH
    prep.pop("production_rules_ref", None); prep.pop("production_last_close", None); prep.pop("production_last_output", None)
    programs["wei_field_preparation"] = prep
    planner.put(_HOUSE_PATH, house)
    _path, owner = read_causal_event_owner(planner)
    event = owner.get("causal_events", {}).get(event_ref)
    if isinstance(event, MutableMapping):
        replacement = "House Tang's armory now reports aggregate complete outfitting reserves. Replenishment and repairs require real labor, material, silver and time; ammunition and horses remain separate exact stocks."
        summary = str(event.get("summary", ""))
        if replacement not in summary: event["summary"] = (summary + " " + replacement)[:4000]
        write_causal_event_owner(planner, owner)
        wake = getattr(planner, "_pending_wake_created", None)
        if isinstance(wake, MutableMapping) and wake.get("campaign_event_ref") == event_ref: wake["reason"] = event["summary"]


class HouseFieldPreparationOutfittingProjectionMixin:
    pass  # Due-host settlement is centrally dispatched by time_integration.py.


__all__ = ["HouseFieldPreparationOutfittingProjectionMixin", "project_house_production_into_field_preparation"]
