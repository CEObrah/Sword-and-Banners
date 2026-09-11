from __future__ import annotations

import copy

from sword_runtime.engine import RepositoryCommandPlanner


def test_stale_reputation_subject_index_cannot_substitute_another_subject(campaign):
    planner = RepositoryCommandPlanner(campaign)
    idx_path = "state/reputation/index.json"
    idx = copy.deepcopy(planner.read(idx_path))
    wei_ref = "char_tang_wei"
    other_ref = "faction.tang_household"
    wei_path = idx["subjects"][wei_ref]
    other_path = idx["subjects"][other_ref]
    other_before = copy.deepcopy(planner.read(other_path))

    # authority:false routing is deliberately corrupted. The exact subject_id
    # must win, so Wei's signal cannot mutate the household subject.
    idx["subjects"][wei_ref] = other_path
    planner.put(idx_path, idx)
    planner._record_reputation_signal(
        wei_ref,
        "state_qin",
        3,
        "battle_command",
        "event.reputation-routing-substitution",
        str(planner.read("state/runtime.json")["world_time"]),
        "routing authority regression",
    )

    repaired_idx = planner.read(idx_path)
    assert repaired_idx["subjects"][wei_ref] == wei_path
    wei = planner.read(wei_path)
    assert wei["subject_id"] == wei_ref
    assert "state_qin" in wei["audience_profiles"]
    assert planner.read(other_path) == other_before


def test_missing_reputation_subject_route_cannot_suppress_exact_subject(campaign):
    planner = RepositoryCommandPlanner(campaign)
    idx_path = "state/reputation/index.json"
    idx = copy.deepcopy(planner.read(idx_path))
    wei_path = idx["subjects"].pop("char_tang_wei")
    planner.put(idx_path, idx)

    planner._record_reputation_signal(
        "char_tang_wei",
        "state_qin",
        2,
        "reliability",
        "event.reputation-routing-missing",
        str(planner.read("state/runtime.json")["world_time"]),
        "missing route must fall back to exact subject",
    )
    repaired_idx = planner.read(idx_path)
    assert repaired_idx["subjects"]["char_tang_wei"] == wei_path
    assert planner.read(wei_path)["subject_id"] == "char_tang_wei"


def test_stale_reputation_profile_route_cannot_swap_audiences(campaign):
    planner = RepositoryCommandPlanner(campaign)
    at = str(planner.read("state/runtime.json")["world_time"])
    planner._record_reputation_signal(
        "char_tang_wei", "state_qin", 1, "general", "event.profile-qin-1", at, "fixture"
    )
    planner._record_reputation_signal(
        "char_tang_wei", "state_zhao", 1, "general", "event.profile-zhao-1", at, "fixture"
    )
    idx = planner.read("state/reputation/index.json")
    subject_path = idx["subjects"]["char_tang_wei"]
    subject = copy.deepcopy(planner.read(subject_path))
    qin_path = subject["audience_profiles"]["state_qin"]
    zhao_path = subject["audience_profiles"]["state_zhao"]
    qin_before = copy.deepcopy(planner.read(qin_path))
    zhao_before = copy.deepcopy(planner.read(zhao_path))

    subject["audience_profiles"]["state_qin"] = zhao_path
    planner.put(subject_path, subject)
    planner._record_reputation_signal(
        "char_tang_wei", "state_qin", 2, "general", "event.profile-qin-2", at, "fixture"
    )

    repaired_subject = planner.read(subject_path)
    assert repaired_subject["audience_profiles"]["state_qin"] == qin_path
    assert planner.read(qin_path)["standing"]["overall"] == qin_before["standing"]["overall"] + 2
    assert planner.read(zhao_path) == zhao_before
