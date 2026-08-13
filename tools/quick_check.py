#!/usr/bin/env python3
"""Fast structural and syntax gate for ordinary Sword development."""
from __future__ import annotations

import compileall
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    subprocess.run(list(args), cwd=ROOT, check=True)


def main() -> int:
    if not compileall.compile_dir(ROOT / "runtime" / "sword_runtime", quiet=1):
        raise SystemExit("runtime syntax compilation failed")
    run(sys.executable, "tools/audit_gold.py")
    print("quick_check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
