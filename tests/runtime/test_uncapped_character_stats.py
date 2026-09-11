from __future__ import annotations

from sword_runtime.civil_world import CivilWorldMixin


class GovernorHarness(CivilWorldMixin):
    def __init__(self, value: float):
        self.person = {
            "skills": {"Governance": value, "Law": value, "Diplomacy": value, "Leadership": value},
            "attributes": {"Presence": value},
        }

    def owner_path(self, person_ref: str) -> str:
        return person_ref

    def read(self, path: str):
        if path == "governor":
            return self.person
        raise KeyError(path)


def test_governance_stats_above_200_continue_to_matter_with_diminishing_returns():
    polity = {"governors": {"loc_test": {"person_ref": "governor"}}}
    at_200 = GovernorHarness(200)._governor_effects(polity, "loc_test")
    at_250 = GovernorHarness(250)._governor_effects(polity, "loc_test")
    at_350 = GovernorHarness(350)._governor_effects(polity, "loc_test")
    assert at_250["score"] > at_200["score"]
    assert at_250["administration_multiplier"] > at_200["administration_multiplier"]
    assert at_350["administration_multiplier"] > at_250["administration_multiplier"]
    # The increase remains organizationally bounded instead of becoming an
    # unbounded whole-polity multiplier.
    assert at_350["administration_multiplier"] < 1.60
