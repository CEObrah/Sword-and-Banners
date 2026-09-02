from __future__ import annotations

import copy

import sword_runtime.api.stable_operations as stable_operations


def test_stable_operations_binds_copy_for_deepcopy_projection_paths() -> None:
    assert stable_operations.copy is copy
