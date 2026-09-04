from __future__ import annotations

import copy
from types import SimpleNamespace

from sword_runtime.warfare_depth_integrity import WarfareDepthIntegrityMixin


class _DispatchBase:
    def _dispatch(self, command, payload):
        return {"delegated": True, "command_type": command.command_type}


class _DispatchHarness(WarfareDepthIntegrityMixin, _DispatchBase):
    def __init__(self):
        self.released: list[str] = []

    def _release_formation_external_personnel(self, formation_ref: str) -> None:
        self.released.append(formation_ref)


def test_merge_releases_only_secondary_external_attachments_before_delete():
    harness = _DispatchHarness()
    command = SimpleNamespace(command_type="formation_merge")
    result = harness._command_layer_warfare_depth_integrity(
        command,
        {"formation_refs": ["formation_primary", "formation_second", "formation_third"]},
        lambda: {"delegated": True, "command_type": command.command_type},
    )
    assert result["delegated"] is True
    assert harness.released == ["formation_second", "formation_third"]


class _MercenaryBase:
    def _ensure_mercenary_command_structure(self, mercenary_ref: str):
        return copy.deepcopy(self.base_structure)


class _MercenaryHarness(WarfareDepthIntegrityMixin, _MercenaryBase):
    def __init__(self, *, total: int, explicit_non_fighting: int):
        self.path = "state/merc/example.json"
        self.company = {"headcount": total}
        self.base_structure = {
            "company_headcount": total,
            "existing_non_fighting_personnel": explicit_non_fighting,
            "fighting_establishment": max(0, total - explicit_non_fighting),
            "unit_command": {"commander_billets": 1},
            "support": {
                "target_total": 0,
                "combined_command_and_support_target": 0,
                "staffing_shortfall": 0,
            },
        }
        self.writes = {}

    def owner_path(self, ref: str) -> str:
        assert ref == "merc_example"
        return self.path

    def read(self, path: str):
        assert path == self.path
        return copy.deepcopy(self.company)

    def put(self, path: str, value):
        self.writes[path] = copy.deepcopy(value)
        self.company = copy.deepcopy(value)

    def _warfare_depth_rules(self):
        return {"mercenary_command_structure": {}}


def test_mercenary_without_explicit_support_does_not_carve_fighting_headcount():
    harness = _MercenaryHarness(total=4160, explicit_non_fighting=0)
    structure = harness._ensure_mercenary_command_structure("merc_example")
    assert structure["fighting_establishment"] == 4160
    assert "routine_support_functions" not in structure
    assert structure["support"]["target_total"] == 0
    assert harness.company["headcount"] == 4160


def test_existing_mercenary_non_fighting_composition_is_descriptive_not_quota():
    harness = _MercenaryHarness(total=1259, explicit_non_fighting=363)
    structure = harness._ensure_mercenary_command_structure("merc_example")
    assert structure["fighting_establishment"] == 896
    assert structure["existing_non_fighting_personnel"] == 363
    assert "routine_support_functions" not in structure
    assert structure["support"]["target_total"] == 0
    assert structure["support"]["staffing_shortfall"] == 0
    assert harness.company["headcount"] == 1259

