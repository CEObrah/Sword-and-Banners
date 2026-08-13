#!/usr/bin/env python3
"""Mandatory deterministic 2x1000-transaction Gold persistence soak.

Wall-clock timing on shared CI runners is noisy.  History-growth detection is
therefore evaluated on the pairwise mean of the two independent deterministic
replays, not by requiring each individual replay's clock curve to be smooth.
A real history-dependent regression should reproduce in both replays; transient
runner contention should not turn an otherwise identical deterministic release
into a random red gate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSACTIONS = 1000
MAX_GROWTH_RATIO = 1.35
MAX_WINDOW_SPREAD = 1.75


def run(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print('+', ' '.join(map(str, cmd)), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def prepare_clone(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    repo = destination / 'repo'
    subprocess.run(['git', 'clone', '--shared', '--quiet', str(ROOT), str(repo)], check=True)
    for key, value in (
        ('user.name', 'Sword Gold Soak'),
        ('user.email', 'sword-gold-soak@example.invalid'),
        ('gc.auto', '0'),
        ('gc.autoPackLimit', '0'),
        ('maintenance.auto', 'false'),
    ):
        subprocess.run(['git', '-C', str(repo), 'config', key, value], check=True)
    return repo


def run_one(label: str, base: Path) -> dict:
    repo = prepare_clone(base / label)
    metrics = base / f'{label}.jsonl'
    report = base / f'{label}.report.json'
    env = os.environ.copy()
    env['PYTHONPATH'] = str(repo / 'runtime')
    run(
        [sys.executable, 'tools/run_gold_soak.py', str(repo), str(metrics), '--count', str(TRANSACTIONS)],
        cwd=repo,
        env=env,
    )
    run(
        [sys.executable, 'tools/run_gold_soak.py', str(repo), str(metrics), '--report', str(report)],
        cwd=repo,
        env=env,
    )
    return json.loads(report.read_text())


def require_replay_integrity(label: str, report: dict) -> None:
    wal = report['wal']
    if wal != {'pending': 0, 'terminal': TRANSACTIONS, 'receipts': TRANSACTIONS}:
        raise RuntimeError(f'{label} WAL/receipt lifecycle is incomplete: {wal}')
    if any(int(value) != 0 for value in report['global_scans'].values()):
        raise RuntimeError(f'{label} performed forbidden global scans')
    if int(report['failures']) != 0:
        raise RuntimeError(f'{label} reported failures')


def require_flat_combined_latency(first: dict, second: dict) -> dict:
    first_windows = [float(value) for value in first['duration_seconds']['window_100_means']]
    second_windows = [float(value) for value in second['duration_seconds']['window_100_means']]
    if len(first_windows) != len(second_windows) or len(first_windows) < 4:
        raise RuntimeError('Gold soak latency reports have incompatible window series')

    combined_windows = [
        (left + right) / 2.0
        for left, right in zip(first_windows, second_windows)
    ]
    first_200 = sum(combined_windows[:2]) / 2.0
    last_200 = sum(combined_windows[-2:]) / 2.0
    growth = last_200 / first_200
    spread = max(combined_windows) / min(combined_windows)

    if growth > MAX_GROWTH_RATIO:
        raise RuntimeError(
            'paired soak latency regressed with history: '
            f'last/first 200 ratio {growth:.3f} > {MAX_GROWTH_RATIO:.2f}'
        )
    if spread > MAX_WINDOW_SPREAD:
        raise RuntimeError(
            'paired soak 100-transaction latency windows are unstable: '
            f'spread {spread:.3f} > {MAX_WINDOW_SPREAD:.2f}'
        )
    return {
        'pairwise_window_100_means': combined_windows,
        'growth_ratio_last_200_vs_first_200': growth,
        'window_spread': spread,
    }


def main() -> None:
    dirty = subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain'], text=True)
    if dirty.strip():
        raise RuntimeError('Gold soak gate requires a pristine source checkout')
    with tempfile.TemporaryDirectory(prefix='sword-gold-soak-gate-') as temporary:
        base = Path(temporary)
        first = run_one('replay-a', base)
        second = run_one('replay-b', base)
        require_replay_integrity('replay-a', first)
        require_replay_integrity('replay-b', second)
        paired_latency = require_flat_combined_latency(first, second)
        if first['final_root_hash'] != second['final_root_hash']:
            raise RuntimeError(
                'deterministic soak hash mismatch: %s != %s'
                % (first['final_root_hash'], second['final_root_hash'])
            )
        deterministic_fields = ('final_revision', 'planning_reads', 'writes', 'hosts_woken', 'events_processed', 'global_scans')
        for field in deterministic_fields:
            if first[field] != second[field]:
                raise RuntimeError(f'deterministic soak mismatch in {field}')
        summary = {
            'transactions_per_replay': TRANSACTIONS,
            'replays': 2,
            'final_root_hash': first['final_root_hash'],
            'replay_a_latency': first['duration_seconds'],
            'replay_b_latency': second['duration_seconds'],
            'paired_latency': paired_latency,
            'planning_reads': first['planning_reads'],
            'writes': first['writes'],
            'hosts_woken': first['hosts_woken'],
            'events_processed': first['events_processed'],
            'global_scans': first['global_scans'],
            'wal': first['wal'],
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        print('GOLD SOAK PASS: 2 x 1000 deterministic transactions, paired flat bounded recovery latency')


if __name__ == '__main__':
    main()
