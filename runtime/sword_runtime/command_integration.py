"""Explicit hosted command-dispatch orchestration.

Domain mixins expose ordered command-layer hooks. The hosted planner owns one
visible ``_dispatch`` entry point and the base engine remains the terminal
consequence reducer. Command order is therefore a declared contract rather than
cooperative Python MRO behavior.
"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from sword_runtime.engine import RepositoryCommandPlanner

COMMAND_LAYER_METHODS = (
    "_command_layer_time_integration",
    "_command_layer_military_reconnaissance",
    "_command_layer_qin_command_support",
    "_command_layer_production_planner",
    "_command_layer_warfare_depth_integrity",
    "_command_layer_warfare_depth",
    "_command_layer_prisoner_system",
    "_command_layer_house_field_departure_preflight",
    "_command_layer_command_staff_movement",
    "_command_layer_standing_training",
    "_command_layer_downtime",
    "_command_layer_equipment_projection",
    "_command_layer_fortified_site",
    "_command_layer_strategic_crossings",
    "_command_layer_independent_organizations",
    "_command_layer_settlement_civic_depth",
    "_command_layer_civil_world",
    "_command_layer_formation_armory_issue",
    "_command_layer_military_career_command_surface",
    "_command_layer_military_career_loyalty_politics",
    "_command_layer_player_group_actions",
    "_command_layer_production_living_world",
    "_command_layer_causal_living_world",
)

class ExplicitCommandRouterMixin:
    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        layers=[]
        for method_name in COMMAND_LAYER_METHODS:
            method=getattr(self,method_name,None)
            if callable(method): layers.append(method)
        def invoke(index:int)->dict[str,Any]:
            if index>=len(layers):
                return RepositoryCommandPlanner._dispatch(self,command,payload)
            return layers[index](command,payload,lambda: invoke(index+1))
        return invoke(0)

__all__=["COMMAND_LAYER_METHODS","ExplicitCommandRouterMixin"]
