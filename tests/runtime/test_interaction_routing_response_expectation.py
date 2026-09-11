from __future__ import annotations

from sword_runtime.interaction_routing_health import summarize_interaction_routing


class _Source:
    def read_optional(self, path: str):
        if path == "state/index/interaction-attempts.json":
            return {
                "attempts": [
                    {
                        "event_id": "interaction_attempt_no_reply_expected",
                        "actor_id": "char_tang_wei",
                        "action": "seek_contact",
                        "target_ref": "inst_wei_northern_rear_coordination",
                        "expects_response": False,
                    }
                ]
            }
        if path == "state/runtime.json":
            return {"hosts": {}}
        return None


def test_explicit_no_response_seek_contact_is_not_a_missing_response_route() -> None:
    summary = summarize_interaction_routing(_Source())
    assert summary["response_expected_attempts"] == 0
    assert summary["unrouted_attempts"] == 0
    assert "player_interaction_attempt_without_causal_response_route" not in summary["diagnostics"]
