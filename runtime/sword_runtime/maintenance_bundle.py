"""Production maintenance composition after the clean campaign rebaseline.

Legacy one-time repair bundles were intentionally retired with the baseline reset.
No repair command is admitted by this layer; maintenance must add a new explicit,
registered recipe if a future campaign repair is ever required.
"""
from __future__ import annotations

class MaintenanceRepairBundleMixin:
    """Marker mixin preserving production composition without legacy repair routes."""
    pass

__all__ = ["MaintenanceRepairBundleMixin"]
