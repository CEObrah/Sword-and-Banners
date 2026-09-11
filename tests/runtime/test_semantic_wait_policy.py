from sword_runtime.downtime import DowntimeAdvanceMixin


def test_semantic_wait_clause_is_precise_across_source_and_topic():
    policy = DowntimeAdvanceMixin._normalize_wait_policy(
        {"event_kinds": ["world_arc_report"], "source_refs": ["arc_qin_frontier"], "topic_terms": ["entry authority"]}
    )

    assert DowntimeAdvanceMixin._event_matches_wait_policy(
        "event.match",
        {"kind": "world_arc_report", "arc_ref": "arc_qin_frontier", "topic": "Entry authority changes at the border."},
        policy,
    ) is True
    assert DowntimeAdvanceMixin._event_matches_wait_policy(
        "event.wrong-topic",
        {"kind": "world_arc_report", "arc_ref": "arc_qin_frontier", "topic": "Routine grain prices."},
        policy,
    ) is False
    assert DowntimeAdvanceMixin._event_matches_wait_policy(
        "event.wrong-source",
        {"kind": "world_arc_report", "arc_ref": "arc_unrelated", "topic": "Entry authority changes."},
        policy,
    ) is False


def test_semantic_wait_any_of_supports_distinct_natural_language_stop_reasons():
    policy = DowntimeAdvanceMixin._normalize_wait_policy(
        {
            "any_of": [
                {"event_kinds": ["world_arc_report"], "source_refs": ["arc_qin_frontier"], "topic_terms": ["entry authority"]},
                {"classifications": ["hard_wake"]},
            ]
        }
    )

    matching_report = {
        "kind": "world_arc_report",
        "arc_ref": "arc_qin_frontier",
        "topic": "The entry authority order changed.",
    }
    hard_contact = {
        "kind": "hostile_contact",
        "classification": "hard_wake",
        "topic": "Enemy contact at the roadblock.",
    }
    unrelated_report = {
        "kind": "world_arc_report",
        "arc_ref": "arc_merchant_prices",
        "topic": "Routine market report.",
    }

    assert DowntimeAdvanceMixin._event_matches_wait_policy("event.report", matching_report, policy) is True
    assert DowntimeAdvanceMixin._event_matches_wait_policy("event.contact", hard_contact, policy) is True
    assert DowntimeAdvanceMixin._event_matches_wait_policy("event.unrelated", unrelated_report, policy) is False
