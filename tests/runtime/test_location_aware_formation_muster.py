from __future__ import annotations

import copy
from types import SimpleNamespace

from sword_runtime.location_aware_formation_muster import LocationAwareFormationMusterMixin
from sword_runtime.production_planner import ProductionCampaignPlanner


class _BasePlanner:
    def __init__(self) -> None:
        self.force_path = "state/forces/personal.json"
        self.docs = {
            self.force_path: {
                "source_location_ref": "loc_default",
                "available_by_role": {"house_guard": 300},
                "available_by_location": {
                    "loc_training": {"house_guard": 300},
                    "loc_default": {"house_guard": 0},
                },
            }
        }
        self.base_seen_source = None

    def owner_path(self, ref: str) -> str:
        assert ref == "force_tang_wei_personal"
        return self.force_path

    def read(self, path: str):
        return self.docs[path]

    def put(self, path: str, value) -> None:
        self.docs[path] = value

    def _dispatch(self, command, payload):
        force = copy.deepcopy(self.docs[self.force_path])
        self.base_seen_source = force.get("source_location_ref")
        location = str(payload["location_ref"])
        role = str(payload["role"])
        count = int(payload["personnel"])
        if location != str(force.get("source_location_ref")):
            raise ValueError("legacy source-location guard")
        force["available_by_role"][role] -= count
        force["available_by_location"][location][role] -= count
        self.docs[self.force_path] = force
        return {"personnel": count, "location_ref": location}


class _Planner(LocationAwareFormationMusterMixin, _BasePlanner):
    pass


def _command():
    return SimpleNamespace(command_type="formation_create")


def test_exact_location_pool_can_muster_without_changing_default_source() -> None:
    planner = _Planner()
    result = planner._dispatch(
        _command(),
        {
            "force_ref": "force_tang_wei_personal",
            "location_ref": "loc_training",
            "role": "house_guard",
            "personnel": 300,
        },
    )
    assert result["personnel"] == 300
    assert planner.base_seen_source == "loc_training"
    force = planner.docs[planner.force_path]
    assert force["source_location_ref"] == "loc_default"
    assert force["available_by_role"]["house_guard"] == 0
    assert force["available_by_location"]["loc_training"]["house_guard"] == 0


def test_location_without_enough_reserve_keeps_legacy_rejection() -> None:
    planner = _Planner()
    try:
        planner._dispatch(
            _command(),
            {
                "force_ref": "force_tang_wei_personal",
                "location_ref": "loc_empty",
                "role": "house_guard",
                "personnel": 300,
            },
        )
    except ValueError as exc:
        assert "legacy source-location guard" in str(exc)
    else:
        raise AssertionError("formation muster should not bypass an absent exact reserve")
    assert planner.docs[planner.force_path]["source_location_ref"] == "loc_default"


def test_production_planner_wires_location_aware_muster_before_base_engine() -> None:
    names = [cls.__name__ for cls in ProductionCampaignPlanner.__mro__]
    assert "LocationAwareFormationMusterMixin" in names
    assert names.index("LocationAwareFormationMusterMixin") < names.index("RepositoryCommandPlanner")
