#!/usr/bin/env python3
"""Run pytest with repository-controlled plugin loading and exact exit status."""
from __future__ import annotations

import os
import sys

# The release suite must not inherit arbitrary host pytest plugins. Some host
# plugins keep shutdown threads alive after tests have completed and make a
# clean suite look hung.
os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

import pytest


def main() -> None:
    status = int(pytest.main(sys.argv[1:]))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)


if __name__ == "__main__":
    main()
