"""Public API application factories without eager service imports.

Keeping these imports lazy prevents narrow runtime modules (for example the
interaction surface) from importing the entire hosted planner graph merely by
being under ``sword_runtime.api``.
"""

from __future__ import annotations

from typing import Any


def create_app(*args: Any, **kwargs: Any):
    from sword_runtime.api.app import create_app as _create_app
    return _create_app(*args, **kwargs)


def create_app_from_env(*args: Any, **kwargs: Any):
    from sword_runtime.api.app import create_app_from_env as _create_app_from_env
    return _create_app_from_env(*args, **kwargs)


__all__ = ["create_app", "create_app_from_env"]
