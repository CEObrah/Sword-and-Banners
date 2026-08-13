from __future__ import annotations

import pytest

from sword_runtime.api.world_reference import search_world_reference


class _Store:
    def __init__(self) -> None:
        self.data = {
            "game/data/world/locations.json": {
                "locations": [
                    {
                        "ref": "loc_kanyou",
                        "name": "Kanyou",
                        "kind": "capital",
                        "state": "qin",
                        "functions": ["politics", "market"],
                        "flavor_only": False,
                    },
                    {
                        "ref": "loc_kantan",
                        "name": "Kantan",
                        "kind": "capital",
                        "state": "zhao",
                        "functions": ["politics"],
                        "flavor_only": False,
                    },
                ]
            },
            "game/data/people/latent-identities.json": {
                "identities": {"char_ouki": {"name": "Ouki"}}
            },
            "game/data/world/noble-houses.json": {
                "houses": [
                    {"house_ref": "house_house_tang", "name": "House Tang", "state": "qin"}
                ]
            },
            "game/data/world/merchant-houses.json": {"houses": []},
            "game/data/history/canon-background.json": {
                "completed_background": [
                    {"event": "Qin institutions shape the campaign world.", "year_bce": 260}
                ]
            },
        }

    def read_json(self, path: str):
        return self.data[path]


def test_location_search_returns_exact_registered_ref() -> None:
    result = search_world_reference(_Store(), "Kanyou", category="location")
    assert result["result_count"] == 1
    assert result["results"] == [
        {
            "category": "location",
            "ref": "loc_kanyou",
            "name": "Kanyou",
            "kind": "capital",
            "state": "qin",
            "functions": ["politics", "market"],
            "flavor_only": False,
        }
    ]
    assert result["results_truncated"] is False
    assert result["next_offset"] is None


def test_reference_search_is_paginated_and_deterministic() -> None:
    result = search_world_reference(_Store(), "kan", category="location", limit=1)
    assert result["result_count"] == 2
    assert result["results"][0]["ref"] == "loc_kantan"
    assert result["results_truncated"] is True
    assert result["next_offset"] == 1

    second = search_world_reference(
        _Store(), "kan", category="location", offset=result["next_offset"], limit=1
    )
    assert second["results"][0]["ref"] == "loc_kanyou"
    assert second["results_truncated"] is False


def test_reference_search_rejects_unbounded_inputs() -> None:
    with pytest.raises(ValueError):
        search_world_reference(_Store(), "", category="location")
    with pytest.raises(ValueError):
        search_world_reference(_Store(), "Kanyou", category="secret")
    with pytest.raises(ValueError):
        search_world_reference(_Store(), "Kanyou", category="location", limit=33)
