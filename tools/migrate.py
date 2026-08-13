#!/usr/bin/env python3
"""Explicit maintenance helper. This file intentionally does not implement gameplay.

Add one-off, reviewed migrations here. Never call this from an ordinary turn.
"""
import sys
if __name__=='__main__':
    print('No migration selected. Add and review an explicit maintenance migration before running.')
    sys.exit(2)
