from __future__ import annotations

import copy
import json

from sword_runtime.qin_command_progression import command_scale_ceiling_from_player


def _rules(campaign):
    return json.loads((campaign / "game/data/mechanics/career-progression.json").read_text())["qin_field_command"]


def _world_time(campaign):
    return json.loads((campaign / "state/runtime.json").read_text())["world_time"]


def _candidate(campaign, person_id):
    player = json.loads((campaign / "state/player.json").read_text())
    candidate = copy.deepcopy(player)
    candidate["person_id"] = person_id
    candidate["name"] = "Synthetic Qin candidate"
    candidate["career_state"] = {}
    return candidate


def test_normal_qin_command_scale_is_candidate_wide_not_player_only(campaign):
    rules = _rules(campaign)
    at = _world_time(campaign)
    wei_like_npc = _candidate(campaign, "char_test_qin_candidate")

    assert rules["scope"] == "all_qin_field_command_candidates"
    assert command_scale_ceiling_from_player(wei_like_npc, rules, at) == 1000


def test_one_candidates_explicit_exception_does_not_raise_another_candidates_ceiling(campaign):
    rules = _rules(campaign)
    at = _world_time(campaign)
    exceptional = _candidate(campaign, "char_test_exceptional_candidate")
    ordinary = _candidate(campaign, "char_test_ordinary_candidate")

    exceptional["career_state"]["qin_command_scale_exception_personnel"] = 8000

    assert command_scale_ceiling_from_player(exceptional, rules, at) == 8000
    assert command_scale_ceiling_from_player(ordinary, rules, at) == 1000
    assert "appointment-specific" in rules["exception_policy"]
    assert "never" in rules["exception_policy"].lower()
