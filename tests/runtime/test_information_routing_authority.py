from __future__ import annotations

import copy

from sword_runtime.campaign_briefing import latest_campaign_briefing_ref
from sword_runtime.information_routing import information_claim_refs_for_subject
from sword_runtime.production_planner import ProductionCampaignPlanner


class _PlannerStore:
    def __init__(self, planner):
        self.planner = planner

    def read_json(self, path):
        return self.planner.read(path)


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def test_missing_subject_cache_does_not_hide_exact_claim(campaign):
    planner = _planner(campaign)
    index = planner.read("state/information/index.json")
    claim_ref = next(iter(index["claims"]))
    claim = planner.read(index["claims"][claim_ref])
    subject = str(claim["subject_ref"])
    empty = {"schema": "sword-information-subject-index", "authority": False, "subjects": {}}
    refs = information_claim_refs_for_subject(planner.read_optional, index, empty, subject)
    assert claim_ref in refs


def test_stale_subject_alias_cannot_inject_unrelated_exact_claim(campaign):
    planner = _planner(campaign)
    index = planner.read("state/information/index.json")
    claim_ref = next(iter(index["claims"]))
    stale = {
        "schema": "sword-information-subject-index",
        "authority": False,
        "subjects": {"subject.unrelated": [claim_ref]},
    }
    assert information_claim_refs_for_subject(
        planner.read_optional, index, stale, "subject.unrelated",
    ) == []


def test_campaign_briefing_survives_empty_subject_cache(campaign):
    planner = _planner(campaign)
    index = planner.read("state/information/index.json")
    briefing_ref = next(
        ref
        for ref, path in index["claims"].items()
        if planner.read(path).get("epistemic_kind") == "official_military_briefing"
    )
    claim = planner.read(index["claims"][briefing_ref])
    planner.put("state/information/subject-index.json", {
        "schema": "sword-information-subject-index", "authority": False, "subjects": {},
    })
    found = latest_campaign_briefing_ref(
        _PlannerStore(planner), "operation_missing_cache_probe", str(claim.get("subject_ref")),
    )
    assert found == briefing_ref
