from __future__ import annotations

from sword_runtime.api.command_staff_routing_operations import RoutedCommandStaffAwareCampaignOperations


class FakeStore:
    def __init__(self) -> None:
        self.docs = {
            "state/meta.json": {"player_id": "char_tang_wei"},
            "state/player.json": {"location": "loc_kanyou"},
            "state/index/owner-index.json": {
                "owners": {"char_tang_wei": "state/people/char_tang_wei.json"}
            },
            "state/people/char_tang_wei.json": {"current_location": "loc_qin_eastern_depot"},
            "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json": {
                "schema": "command-group",
                "id": "cmdgrp.tang_wei.field_army",
                "display_name": "Tang Wei Army",
                "context": "field_army",
                "commander_ref": "char_tang_wei",
                "direct_person_refs": [],
                "units": [],
            },
        }

    def read_json(self, path: str):
        if path not in self.docs:
            raise FileNotFoundError(path)
        return self.docs[path]


def test_retinue_root_uses_authoritative_player_location_over_stale_generic_owner() -> None:
    operations = RoutedCommandStaffAwareCampaignOperations.__new__(RoutedCommandStaffAwareCampaignOperations)
    operations.store = FakeStore()

    rows, _, _ = operations._retinue_projection()

    assert len(rows) == 1
    assert rows[0]["command_group_ref"] == "cmdgrp.tang_wei.field_army"
    assert rows[0]["current_location_ref"] == "loc_kanyou"
    assert rows[0]["location_basis"] == "commander_exact_location"
