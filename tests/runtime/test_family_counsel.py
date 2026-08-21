import copy

from sword_runtime.family_counsel import (
    FamilyCounselMixin,
    _classify_family_counsel,
    _counsel_positions,
    _counsel_summary,
    _counsel_topics,
    _settle_family_counsel,
)
from sword_runtime.production_planner import ProductionCampaignPlanner


def _attempt(**overrides):
    row = {
        "actor_id": "char_tang_wei",
        "target_ref": "char_tang_ling",
        "action": "ask",
        "process_ref": "event_world_arc_example.report",
        "player_statement": "We have this report. What could we do about it?",
    }
    row.update(overrides)
    return row


def test_exact_parent_report_counsel_is_classified():
    assert _classify_family_counsel(_attempt()) is True
    assert _classify_family_counsel(_attempt(target_ref="char_tang_zhu")) is True
    assert _classify_family_counsel(
        _attempt(player_statement="Do you think House Tang should declare independence from Qin or seek an alliance or treaty?")
    ) is True


def test_counsel_requires_exact_parent_exact_report_and_counsel_language():
    assert _classify_family_counsel(_attempt(target_ref="char_duan_jin")) is False
    assert _classify_family_counsel(_attempt(process_ref=None)) is False
    assert _classify_family_counsel(_attempt(player_statement="I have brought you the report.")) is False
    assert _classify_family_counsel(_attempt(actor_id="char_other")) is False


def test_counsel_topics_are_bounded_and_question_specific():
    topics = _counsel_topics(
        "What do you think of my field army doctrine, the northern Wei situation, how House Tang should grow stronger, and whether we should declare independence from Qin or negotiate an alliance or treaty?"
    )
    assert topics == (
        "field_doctrine",
        "northern_wei_situation",
        "house_growth",
        "sovereignty_and_diplomacy",
    )
    assert _counsel_topics("Advise me.") == ("general_counsel",)


def test_parent_counsel_is_advisory_role_distinct_and_does_not_echo_source():
    question = "What do you think about declaring independence from Qin or negotiating an alliance or treaty?"
    ling = _counsel_summary("char_tang_ling", "hidden source details must not be echoed", question)
    zhu = _counsel_summary("char_tang_zhu", "hidden source details must not be echoed", question)
    assert "Tang Ling" in ling
    assert "Tang Zhu" in zhu
    assert "hidden source details" not in ling
    assert "hidden source details" not in zhu
    assert "comparative troop strength alone is not sovereignty" in ling
    assert "favorable troop comparison" in zhu
    assert ling != zhu


def test_house_growth_positions_preserve_role_distinction():
    ling = _counsel_positions("char_tang_ling", ("house_growth",))
    zhu = _counsel_positions("char_tang_zhu", ("house_growth",))
    assert len(ling) == 1 and len(zhu) == 1
    assert "treasury resilience" in ling[0]
    assert "military depth before breadth" in zhu[0]


def test_family_counsel_is_in_production_mro_before_household_admin():
    assert FamilyCounselMixin in ProductionCampaignPlanner.__mro__
    assert ProductionCampaignPlanner.__mro__.index(FamilyCounselMixin) < ProductionCampaignPlanner.__mro__.index(
        __import__("sword_runtime.household_request_flow", fromlist=["HouseholdRequestFlowMixin"]).HouseholdRequestFlowMixin
    )


class _FakePlanner:
    def __init__(self):
        self.docs = {
            "state/player.json": {
                "player_id": "char_tang_wei",
                "location": "loc_tang_manor_inner_citadel_family_hall",
            },
            "state/event/events-messages-and-movement.json": {
                "schema": "event-registry",
                "owner_id": "events_messages_and_movement",
                "causal_events": {
                    "event_world_arc_example.report": {
                        "event_ref": "event_world_arc_example.report",
                        "kind": "world_arc_report",
                        "status": "triggered",
                        "triggered_at": "245-BCE-12-07T18:22:48+08:00",
                        "summary": "A major operation is being prepared; no material outcome has settled.",
                    }
                },
                "archives": [],
            },
        }

    def read(self, path):
        if path not in self.docs:
            raise FileNotFoundError(path)
        return copy.deepcopy(self.docs[path])

    def put(self, path, value):
        self.docs[path] = copy.deepcopy(value)


def test_settlement_creates_exact_typed_nonbinding_parent_advice_event_only():
    planner = _FakePlanner()
    before_player = copy.deepcopy(planner.docs["state/player.json"])
    host = {
        "request_id": "wei-ask-ling-counsel",
        "parent_ref": "char_tang_ling",
        "process_ref": "event_world_arc_example.report",
        "question_text": "Do you think House Tang should declare independence from Qin or seek an alliance or treaty?",
        "topic_tags": ["sovereignty_and_diplomacy"],
    }
    _settle_family_counsel(planner, host, "245-BCE-12-07T18:37:48+08:00")

    assert planner.docs["state/player.json"] == before_player
    events = planner.docs["state/event/events-messages-and-movement.json"]["causal_events"]
    responses = [event for ref, event in events.items() if ref.startswith("event_family_counsel_response_")]
    assert len(responses) == 1
    response = responses[0]
    assert response["actor_ref"] == "char_tang_ling"
    assert response["target_ref"] == "char_tang_wei"
    assert response["source_event_ref"] == "event_world_arc_example.report"
    assert response["process_kind"] == "house_tang_family_counsel"
    assert response["delivery"]["location_ref"] == "loc_tang_manor_inner_citadel_family_hall"
    advisory = response["advisory_record"]
    assert advisory["schema"] == "sword-nonbinding-counsel.v1"
    assert advisory["speaker_ref"] == "char_tang_ling"
    assert advisory["audience_ref"] == "char_tang_wei"
    assert "request_id" not in advisory, "request identity routes settlement but is not duplicated into the advisory payload"
    assert advisory["process_ref"] == "event_world_arc_example.report"
    assert advisory["topics"] == ["sovereignty_and_diplomacy"]
    assert advisory["positions"]
    assert advisory["binding"] is False
    assert advisory["creates_policy"] is False
    assert advisory["creates_commitment"] is False
    assert advisory["creates_authority"] is False
