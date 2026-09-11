from __future__ import annotations
import ast
import json
from pathlib import Path
from sword_runtime.time_integration import HOST_KIND_SPECS, SUPPORTED_HOST_KINDS

def _literal_created_host_kinds(root: Path) -> set[str]:
    kinds:set[str]=set()
    for path in root.rglob('*.py'):
        tree=ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node,ast.Dict): continue
            values={}
            for key,value in zip(node.keys,node.values):
                if isinstance(key,ast.Constant) and isinstance(key.value,str): values[key.value]=value
            if not {'host_id','kind','next_due'}.issubset(values): continue
            kind=values['kind']
            if isinstance(kind,ast.Constant) and isinstance(kind.value,str): kinds.add(kind.value)
    return kinds

def test_scheduler_host_registry_is_self_consistent():
    assert SUPPORTED_HOST_KINDS==frozenset(HOST_KIND_SPECS)
    assert all(spec.get('owner') and spec.get('wake') for spec in HOST_KIND_SPECS.values())

def test_literal_host_creators_and_current_runtime_are_registered():
    repo=Path(__file__).resolve().parents[2]
    created=_literal_created_host_kinds(repo/'runtime'/'sword_runtime')
    runtime=json.loads((repo/'state'/'runtime.json').read_text(encoding='utf-8'))
    current={str(host.get('kind')) for host in runtime.get('hosts',{}).values() if isinstance(host,dict)}
    assert created | current <= SUPPORTED_HOST_KINDS
