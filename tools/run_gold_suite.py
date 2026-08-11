#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = [
    'tests/runtime/test_architecture_service.py',
    'tests/runtime/test_repair_projection_hardening.py',
    'tests/runtime/test_transactions.py',
    'tests/runtime/test_long_horizon.py',
    'tests/runtime/test_real_campaign_acceptance.py',
    'tests/runtime/test_semantic_surface.py',
    'tests/runtime/test_gold_hardening.py',
    'tests/runtime/test_rules_parity_adversarial.py',
    'tests/runtime/test_hostile_command_matrix.py',
    'tests/runtime/test_warfare.py',
    'tests/runtime/test_living_world_intelligence.py',
]


def run(cmd: list[str], *, env: dict[str, str]) -> None:
    print('+', ' '.join(map(str, cmd)), flush=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def main() -> None:
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT / 'runtime')
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    pyfiles = [str(p) for p in (ROOT / 'runtime').rglob('*.py')]
    pyfiles += [str(p) for p in (ROOT / 'tools').glob('*.py')]
    run([sys.executable, '-m', 'py_compile', *pyfiles], env=env)
    run([sys.executable, 'tools/audit_gold.py'], env=env)

    tests: list[str] = []
    for mod in MODULES:
        for line in (ROOT / mod).read_text().splitlines():
            if line.startswith('def test_'):
                name = line.split('def ', 1)[1].split('(', 1)[0]
                tests.append(f'{mod}::{name}')

    for index, node in enumerate(tests, start=1):
        base = Path(tempfile.mkdtemp(prefix=f'sword-gold-{index:02d}-'))
        try:
            run(
                [
                    sys.executable,
                    'tools/run_pytest_module.py',
                    '-q',
                    node,
                    '--basetemp',
                    str(base / 'tmp'),
                ],
                env=env,
            )
        finally:
            shutil.rmtree(base, ignore_errors=True)

    # Persistence performance/determinism is a release property, not an
    # optional benchmark. The gate performs two independent 1,000-command
    # replays and fails on deterministic divergence or paired history growth.
    run([sys.executable, 'tools/run_gold_soak_gate.py'], env=env)
    print(
        f'GOLD TEST SUITE PASS: {len(tests)}/{len(tests)} functional tests + '
        '2 x 1000 deterministic persistence soak transactions'
    )


if __name__ == '__main__':
    main()
