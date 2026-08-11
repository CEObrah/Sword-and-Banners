#!/usr/bin/env python3
"""Run pytest and exit on pytest's exact status without host-plugin teardown."""
from __future__ import annotations
import os
import sys
import pytest

def main() -> None:
    status=int(pytest.main(sys.argv[1:]))
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(status)

if __name__=='__main__':
    main()
