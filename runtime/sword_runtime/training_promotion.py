"""Promotion-aware training hooks.

House Tang troop species no longer form a prestige evolution ladder. Durable military
rank and command-billet progression are owned by the career/command systems. This
hook therefore contributes no troop-role promotion thresholds.
"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any

def exact_promotion_facts(runtime: Any, person: Mapping[str, Any]) -> Mapping[str, Any]:
    return {}

__all__ = ["exact_promotion_facts"]
