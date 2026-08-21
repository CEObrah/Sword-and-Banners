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
    prep["manufacturing_truth"] = (
        "House Tang does not receive a monthly item-factory tick. Existing unissued equipment is held as aggregate complete role-outfitting sets; "
        "new sets and repairs require real craft labor, construction materials, silver and elapsed work, while ammunition and living mounts remain separate physical stocks."
    )
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
    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        super()._run_due_host(host, due_text)
        if host.get("kind") == "house_field_preparation_reply":
            event_ref = str(host.get("response_event_ref", ""))
            if event_ref:
                project_house_production_into_field_preparation(self, event_ref)


__all__ = ["HouseFieldPreparationOutfittingProjectionMixin", "project_house_production_into_field_preparation"]
