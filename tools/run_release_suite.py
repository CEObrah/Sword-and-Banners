#!/usr/bin/env python3
"""Resumable full Sword & Banners release certification.

Every maintained runtime test must actually pass. Modules normally run in one
fresh pytest process. Known or detected whole-module harness stalls fall back to
running every collected node separately. Each invocation owns an isolated
basetemp that is deleted immediately afterward, preventing disposable campaign
clones from accumulating gigabytes and making later tests appear hung.

``.release-certification.json`` is temporary release scaffolding used only to
resume after an external tool timeout. It is removed automatically on success
and must never be included in a packaged release.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / ".release-certification.json"
TMP_ROOT = Path("/tmp/sword-release-cert")
MODULE_TIMEOUT_SECONDS = 70
NODE_TIMEOUT_SECONDS = 90
NODE_ONLY_MODULES = {"tests/runtime/test_army_train_logistics.py"}
NODE_SPLIT_THRESHOLD = 6
NODE_PARALLELISM = 4
SERIAL_NODE_TIMEOUTS = {
    "tests/runtime/test_living_world_intelligence.py::test_current_campaign_120_day_replay_is_deterministic": 180,
}
TIMEOUT_CODES = {124, 137}


def _load_checkpoint() -> dict[str, object]:
    if not CHECKPOINT.exists():
        return {"passed_modules": [], "node_certified_modules": {}}
    try:
        data = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    except Exception:
        return {"passed_modules": [], "node_certified_modules": {}}
    if not isinstance(data, dict):
        return {"passed_modules": [], "node_certified_modules": {}}
    data.setdefault("passed_modules", [])
    data.setdefault("node_certified_modules", {})
    return data


def _save_checkpoint(data: dict[str, object]) -> None:
    CHECKPOINT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _clean_path(path: Path) -> None:
    # Native rm is materially faster than Python walking hundreds of thousands
    # of disposable campaign-clone paths after write-heavy tests.
    subprocess.run(["rm", "-rf", str(path)], cwd=ROOT, check=False)


def _ensure_tmp_root() -> None:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _pytest(target: str, *, timeout_seconds: int, label: str) -> int:
    _ensure_tmp_root()
    basetemp = TMP_ROOT / label
    _clean_path(basetemp)
    cmd = [
        "timeout", "-k", "5s", f"{timeout_seconds}s",
        sys.executable, "tools/run_pytest_module.py", "-q",
        f"--basetemp={basetemp}", target,
    ]
    print("release_gate:", " ".join(cmd[5:]), flush=True)
    try:
        result = subprocess.run(cmd, cwd=ROOT)
        return int(result.returncode)
    finally:
        _clean_path(basetemp)


def _collect_nodes(module: str) -> list[str]:
    cmd = [sys.executable, "tools/run_pytest_module.py", "--collect-only", "-q", module]
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=30)
    if result.returncode != 0:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd)
    nodes = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith(module + "::")]
    if not nodes:
        raise RuntimeError(f"no pytest nodes collected for {module}")
    return nodes


def _certify_nodes(module: str, checkpoint: dict[str, object]) -> None:
    node_map = checkpoint.setdefault("node_certified_modules", {})
    assert isinstance(node_map, dict)
    already = set(node_map.get(module, [])) if isinstance(node_map.get(module), list) else set()
    nodes = _collect_nodes(module)
    pending = [(idx, node) for idx, node in enumerate(nodes, start=1) if node not in already]

    # Performance-sensitive long-horizon acceptance nodes run alone.  Running
    # the 120-day deterministic replay beside three write-heavy Git-backed
    # clones can turn resource contention into a false timeout.
    serial = [(idx, node) for idx, node in pending if node in SERIAL_NODE_TIMEOUTS]
    parallel = [(idx, node) for idx, node in pending if node not in SERIAL_NODE_TIMEOUTS]
    for idx, node in serial:
        code = _pytest(node, timeout_seconds=SERIAL_NODE_TIMEOUTS[node], label=f"serial-node-{idx}")
        if code != 0:
            raise subprocess.CalledProcessError(code, node)
        already.add(node)
        node_map[module] = sorted(already)
        _save_checkpoint(checkpoint)

    for offset in range(0, len(parallel), NODE_PARALLELISM):
        batch = parallel[offset : offset + NODE_PARALLELISM]
        results: dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = {
                pool.submit(_pytest, node, timeout_seconds=NODE_TIMEOUT_SECONDS, label=f"node-{idx}"): node
                for idx, node in batch
            }
            for future in as_completed(futures):
                node = futures[future]
                results[node] = int(future.result())
        failed = [(node, code) for node, code in results.items() if code != 0]
        if failed:
            node, code = failed[0]
            raise subprocess.CalledProcessError(code, node)
        already.update(results)
        node_map[module] = sorted(already)
        _save_checkpoint(checkpoint)

    if not set(nodes).issubset(already):
        raise RuntimeError(f"node certification incomplete for {module}")


def _run_quick_check() -> None:
    print("release_gate: tools/quick_check.py", flush=True)
    subprocess.run([sys.executable, "tools/quick_check.py"], cwd=ROOT, check=True)


def main() -> int:
    _run_quick_check()
    modules = sorted((ROOT / "tests/runtime").glob("test_*.py"))
    checkpoint = _load_checkpoint()
    passed = set(checkpoint.get("passed_modules", [])) if isinstance(checkpoint.get("passed_modules"), list) else set()

    for index, path in enumerate(modules, start=1):
        module = path.relative_to(ROOT).as_posix()
        if module in passed:
            print(f"release_gate: resume PASS [{index}/{len(modules)}] {module}", flush=True)
            continue

        print(f"release_gate: certify [{index}/{len(modules)}] {module}", flush=True)
        nodes = _collect_nodes(module)
        if module in NODE_ONLY_MODULES or len(nodes) > NODE_SPLIT_THRESHOLD:
            reason = "known harness pathology" if module in NODE_ONLY_MODULES else f"large module ({len(nodes)} nodes)"
            print(f"release_gate: node-only harness mode ({reason}): {module}", flush=True)
            _certify_nodes(module, checkpoint)
        else:
            code = _pytest(module, timeout_seconds=MODULE_TIMEOUT_SECONDS, label="module")
            if code in TIMEOUT_CODES:
                print(f"release_gate: module harness timeout; certifying every node: {module}", flush=True)
                _certify_nodes(module, checkpoint)
            elif code != 0:
                raise subprocess.CalledProcessError(code, module)

        passed.add(module)
        checkpoint["passed_modules"] = sorted(passed)
        _save_checkpoint(checkpoint)

    expected = {p.relative_to(ROOT).as_posix() for p in modules}
    if passed != expected:
        raise RuntimeError(f"release certification incomplete: {sorted(expected - passed)[:20]}")

    print(f"release_gate: PASS ({len(modules)} runtime modules)", flush=True)
    CHECKPOINT.unlink(missing_ok=True)
    _clean_path(TMP_ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
