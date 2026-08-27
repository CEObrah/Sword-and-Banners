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

import fcntl
import hashlib
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / ".release-certification.json"
TMP_ROOT = Path("/tmp/sword-release-cert")
LOCK_PATH = Path("/tmp/sword-release-cert.lock")
MODULE_TIMEOUT_SECONDS = 70
NODE_TIMEOUT_SECONDS = 90
NODE_ONLY_MODULES = {"tests/runtime/test_army_train_logistics.py", "tests/runtime/test_causal_connections.py", "tests/runtime/test_hosted_horizon_performance.py", "tests/runtime/test_personal_combat_multi_actor.py", "tests/runtime/test_real_campaign_acceptance.py", "tests/runtime/test_rules_parity_adversarial.py", "tests/runtime/test_warfare.py"}
NODE_PARALLELISM = 2
MODULE_PARALLELISM = 2
SERIAL_MODULES = {"tests/runtime/test_living_world_intelligence.py", "tests/runtime/test_long_horizon.py"}
SERIAL_NODE_TIMEOUTS = {
    "tests/runtime/test_living_world_intelligence.py::test_current_campaign_120_day_replay_is_stable_for_same_saved_seed": 180,
}
TIMEOUT_CODES = {124, 137}
RUN_TOKEN = str(__import__("os").getpid())
CERTIFIED_ROOTS = (
    "runtime",
    "game",
    "state",
    "tests/runtime",
    "tools",
    "plugins/sword-and-banners/skills/sword-and-banners-game-master",
)
CERTIFIED_TOP_LEVEL_FILES = (
    "pyproject.toml",
    "requirements.txt",
    "Dockerfile",
    "railway.toml",
)


def _certification_fingerprint(root: Path = ROOT) -> str:
    """Bind resumable certification to the exact maintained release tree.

    A timeout checkpoint is only evidence for the tree that produced it. Source,
    current campaign state, maintained tests/tools, and Skill changes must reset
    certification rather than inheriting stale green modules. Generated caches, Git
    metadata, and the checkpoint itself are deliberately excluded.
    """
    digest = hashlib.sha256()
    files: list[Path] = []
    for rel in CERTIFIED_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        files.extend(path for path in base.rglob("*") if path.is_file())
    for name in CERTIFIED_TOP_LEVEL_FILES:
        path = root / name
        if path.is_file():
            files.append(path)
    for path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
        rel = path.relative_to(root)
        if any(part in {".git", ".pytest_cache", "__pycache__"} for part in rel.parts):
            continue
        if path.suffix in {".pyc", ".pyo"} or path.name == CHECKPOINT.name:
            continue
        digest.update(rel.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _fresh_checkpoint(source_fingerprint: str) -> dict[str, object]:
    return {
        "source_fingerprint": source_fingerprint,
        "passed_modules": [],
        "node_certified_modules": {},
    }


def _load_checkpoint(source_fingerprint: str) -> dict[str, object]:
    if not CHECKPOINT.exists():
        return _fresh_checkpoint(source_fingerprint)
    try:
        data = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    except Exception:
        return _fresh_checkpoint(source_fingerprint)
    if not isinstance(data, dict) or data.get("source_fingerprint") != source_fingerprint:
        return _fresh_checkpoint(source_fingerprint)
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
    basetemp = TMP_ROOT / f"{RUN_TOKEN}-{label}"
    cmd = [
        "timeout", "-k", "5s", f"{timeout_seconds}s",
        sys.executable, "tools/run_pytest_module.py", "-q",
        f"--basetemp={basetemp}", target,
    ]
    print("release_gate:", " ".join(cmd[5:]), flush=True)
    # Each invocation owns disposable campaign clones. Remove them immediately
    # after pytest exits so interrupted certification cannot accumulate tens of
    # gigabytes of stale basetemps and turn later modules into false timeouts.
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
    module_token = hashlib.sha256(module.encode("utf-8")).hexdigest()[:10]
    for idx, node in serial:
        code = _pytest(node, timeout_seconds=SERIAL_NODE_TIMEOUTS[node], label=f"serial-node-{module_token}-{idx}")
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
                pool.submit(_pytest, node, timeout_seconds=NODE_TIMEOUT_SECONDS, label=f"node-{module_token}-{idx}"): node
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
    # Certification progress lives in CHECKPOINT, not in pytest basetemps. A
    # resumed run may therefore discard every stale disposable clone safely.
    _clean_path(TMP_ROOT)
    _ensure_tmp_root()
    modules = sorted((ROOT / "tests/runtime").glob("test_*.py"))
    source_fingerprint = _certification_fingerprint()
    checkpoint = _load_checkpoint(source_fingerprint)
    if checkpoint.get("quick_check_passed") is not True:
        _run_quick_check()
        checkpoint["quick_check_passed"] = True
        _save_checkpoint(checkpoint)
    else:
        print("release_gate: resume PASS quick_check", flush=True)
    passed = set(checkpoint.get("passed_modules", [])) if isinstance(checkpoint.get("passed_modules"), list) else set()

    def mark_passed(module: str) -> None:
        passed.add(module)
        checkpoint["passed_modules"] = sorted(passed)
        _save_checkpoint(checkpoint)

    normal_batch: list[tuple[int, str]] = []

    def flush_normal_batch() -> None:
        nonlocal normal_batch
        if not normal_batch:
            return
        results: dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=len(normal_batch)) as pool:
            futures = {
                pool.submit(
                    _pytest, module, timeout_seconds=MODULE_TIMEOUT_SECONDS,
                    label=f"module-{index:03d}",
                ): module
                for index, module in normal_batch
            }
            for future in as_completed(futures):
                module = futures[future]
                results[module] = int(future.result())
        for _index, module in normal_batch:
            code = results[module]
            if code in TIMEOUT_CODES:
                print(f"release_gate: module harness timeout; certifying every node: {module}", flush=True)
                _certify_nodes(module, checkpoint)
            elif code != 0:
                raise subprocess.CalledProcessError(code, module)
            mark_passed(module)
        normal_batch = []

    for index, path in enumerate(modules, start=1):
        module = path.relative_to(ROOT).as_posix()
        if module in passed:
            print(f"release_gate: resume PASS [{index}/{len(modules)}] {module}", flush=True)
            continue
        if module in NODE_ONLY_MODULES or module in SERIAL_MODULES:
            flush_normal_batch()
            print(f"release_gate: certify [{index}/{len(modules)}] {module}", flush=True)
            if module in NODE_ONLY_MODULES:
                print(f"release_gate: node-only harness mode (known harness pathology): {module}", flush=True)
                _certify_nodes(module, checkpoint)
            else:
                code = _pytest(module, timeout_seconds=max(MODULE_TIMEOUT_SECONDS, 110), label=f"serial-module-{index:03d}")
                if code in TIMEOUT_CODES:
                    print(f"release_gate: serial module timeout; certifying every node: {module}", flush=True)
                    _certify_nodes(module, checkpoint)
                elif code != 0:
                    raise subprocess.CalledProcessError(code, module)
            mark_passed(module)
            continue
        print(f"release_gate: certify [{index}/{len(modules)}] {module}", flush=True)
        normal_batch.append((index, module))
        if len(normal_batch) >= MODULE_PARALLELISM:
            flush_normal_batch()
    flush_normal_batch()

    expected = {p.relative_to(ROOT).as_posix() for p in modules}
    if passed != expected:
        raise RuntimeError(f"release certification incomplete: {sorted(expected - passed)[:20]}")

    print(f"release_gate: PASS ({len(modules)} runtime modules)", flush=True)
    CHECKPOINT.unlink(missing_ok=True)
    _clean_path(TMP_ROOT)
    return 0


if __name__ == "__main__":
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("release_gate: another certification process already owns the release lock", file=sys.stderr, flush=True)
            raise SystemExit(75)
        raise SystemExit(main())
