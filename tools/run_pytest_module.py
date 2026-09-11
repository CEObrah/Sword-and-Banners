#!/usr/bin/env python3
"""Run pytest with repository-controlled plugin loading and exact exit status."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# The release suite must not inherit arbitrary host pytest plugins. Some host
# plugins keep shutdown threads alive after tests have completed and make a
# clean suite look hung.
os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

# pytest.main() inherits the launcher script directory as sys.path[0]. Because
# this runner lives under tools/, repository-local namespace imports such as
# ``tools.verify_release_state`` would otherwise fail even though the same test
# passes under ``python -m pytest``. Keep isolated execution import-equivalent
# to a normal repository-root pytest invocation.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


def main() -> None:
    status = int(pytest.main(sys.argv[1:]))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)


if __name__ == "__main__":
    main()
