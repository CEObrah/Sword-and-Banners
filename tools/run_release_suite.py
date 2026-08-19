#!/usr/bin/env python3
"""Run the current Sword & Banners release verification suite."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    print("release_gate:", " ".join(args), flush=True)
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main() -> int:
    run("tools/quick_check.py")
    modules = sorted((ROOT / "tests/runtime").glob("test_*.py"))
    for module in modules:
        run("tools/run_pytest_module.py", "-q", module.relative_to(ROOT).as_posix())
    print(f"release_gate: PASS ({len(modules)} runtime modules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
