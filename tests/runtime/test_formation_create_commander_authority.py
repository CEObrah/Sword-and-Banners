from __future__ import annotations

from pathlib import Path

import pytest

from conftest import meta
from sword_runtime.commands import CommandEnvelope
from sword_runtime.engine import RepositoryCommandPlanner


def _command(campaign: Path, commander_ref: str) -> CommandEnvelope:
    m = meta(campaign)
    return CommandEnvelope(
        m["campaign_id"],
        f"authority-{commander_ref}",
        "char_tang_wei",
        "formation_create",
        m["revision"],
        m["time"],
        {
            "state": "qin",
            "force_ref": "force_tang_wei_personal",
            "formation_ref": "formation_test_personal_authority",
            "role": "household_retainer",
            "personnel": 100,
            "authorized_strength": 100,
            "formation_class": "detachment",
            "location_ref": "loc_tang_manor_garrison_yard",
            "commander_ref": commander_ref,
        },
    )


def test_personal_formation_create_cannot_force_uncontrolled_named_commander(campaign: Path) -> None:
    planner = RepositoryCommandPlanner(campaign)
    command = _command(campaign, "char_tang_ling")
    with pytest.raises(PermissionError, match="no saved personnel authority"):
        planner._authorize_command(command, command.payload)


def test_personal_formation_create_may_name_player_as_own_commander(campaign: Path) -> None:
    planner = RepositoryCommandPlanner(campaign)
    command = _command(campaign, "char_tang_wei")
    planner._authorize_command(command, command.payload)
