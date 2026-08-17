from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from sword_runtime.campaign_event_planner import CampaignEventPlayerGroupActionPlanner
from sword_runtime.institutional_processes import settle_institutional_process_followup, sync_institutional_process_routes


def test_current_ouki_withdrawal_arms_valid_followup(campaign: Path) -> None:
    planner = CampaignEventPlayerGroupActionPlanner(campaign)
    planner._reset()
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_institutional_process_routes(planner, runtime)
    hosts = [
        host for host in runtime["hosts"].values()
        if isinstance(host, dict) and host.get("kind") == "institutional_process"
    ]
    assert len(hosts) == 1
    host = hosts[0]
    assert host["original_due_at"] == "245-BCE-12-07T07:00:48+08:00"
    wake = settle_institutional_process_followup(planner, host, host["original_due_at"])
    assert wake["campaign_event_ref"] == "event_ouki_preliminary_review_evaluation_ready_001"
    owner = planner.read("state/event/events-messages-and-movement.json")
    schema = json.loads((campaign / "game/schemas/event-registry.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(owner)
