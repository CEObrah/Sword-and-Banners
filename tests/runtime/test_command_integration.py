from __future__ import annotations
import ast
from pathlib import Path
from sword_runtime.command_integration import COMMAND_LAYER_METHODS
from sword_runtime.engine import RepositoryCommandPlanner
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner

def test_hosted_dispatch_has_one_explicit_router_and_one_terminal_engine_owner():
    owners=[cls for cls in ProductionCampaignPlanner.__mro__ if '_dispatch' in cls.__dict__]
    assert [cls.__module__ for cls in owners]==['sword_runtime.command_integration','sword_runtime.engine']
    assert owners[1] is RepositoryCommandPlanner

def test_every_declared_command_layer_exists_on_hosted_planner():
    assert [name for name in COMMAND_LAYER_METHODS if not callable(getattr(ProductionCampaignPlanner,name,None))]==[]

def test_no_cooperative_top_level_dispatch_chain_remains():
    root=Path(__file__).resolve().parents[2]/'runtime'/'sword_runtime'; offenders=[]; exact=[]
    for path in root.rglob('*.py'):
        text=path.read_text(encoding='utf-8')
        if 'super()._dispatch(command' in text: offenders.append(path.name)
        tree=ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name=='_dispatch': exact.append(path.name)
    assert offenders==[]
    assert sorted(exact)==['command_integration.py','engine.py']
