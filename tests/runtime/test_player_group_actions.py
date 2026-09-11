from __future__ import annotations

import pytest

from sword_runtime.api.input_guidance import COMMAND_INPUT_GUIDANCE
from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS
from sword_runtime.player_group_actions import _exact_group_refs


def test_group_reference_validation_is_bounded_and_unique() -> None:
    assert _exact_group_refs({"formation_refs": ["formation_a", "formation_b"]}) == [
        "formation_a",
        "formation_b",
    ]
    with pytest.raises(ValueError):
        _exact_group_refs({"formation_refs": []})
    with pytest.raises(ValueError):
        _exact_group_refs({"formation_refs": ["formation_a", "formation_a"]})
    with pytest.raises(ValueError):
        _exact_group_refs({"formation_refs": ["formation_a"] * 129})


def test_group_payload_contracts_are_explicit() -> None:
    assert "formation_refs" in COMMAND_PAYLOAD_KEYS["formation_mobilize"]
    assert "formation_refs" in COMMAND_PAYLOAD_KEYS["travel"]
    assert COMMAND_INPUT_GUIDANCE["formation_mobilize"]["formation_refs"]["maximum_items"] == 128
    assert COMMAND_INPUT_GUIDANCE["travel"]["formation_refs"]["maximum_items"] == 128
