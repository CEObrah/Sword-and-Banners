"""Production planner compatibility view for sovereign campaign-entry authority.

The persisted sovereign document remains unchanged.  Reads of core-state owners
receive a bounded derived ``war_intents`` compatibility row only when an exact
state-issued active foreign campaign order already establishes equivalent entry
authority.  Existing movement, briefing, and campaign-law consumers can therefore
use their normal sovereign checks without each inventing a special exception.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.sovereign_campaign_authority import project_sovereign_document


class SovereignCampaignAuthorityMixin:
    """Augment core-state reads with exact-order-derived entry authority."""

    @staticmethod
    def _state_ref_from_path(path: str) -> str | None:
        prefix = "state/states/"
        suffix = ".json"
        if not isinstance(path, str) or not path.startswith(prefix) or not path.endswith(suffix):
            return None
        key = path[len(prefix):-len(suffix)]
        if not key or "/" in key:
            return None
        return f"state_{key}"

    def read(self, path: str) -> Any:
        parent_read = super().read
        raw = parent_read(path)
        state_ref = self._state_ref_from_path(path)
        if state_ref is None or not isinstance(raw, Mapping):
            return raw
        # Pass the raw parent reader into the projection helper.  Using self.read
        # here would recurse back through this mixin while the helper inspects
        # operations and the saved sovereign owner.
        return project_sovereign_document(parent_read, state_ref, raw)

    def read_optional(self, path: str) -> Any:
        try:
            return self.read(path)
        except (FileNotFoundError, KeyError):
            return None


__all__ = ["SovereignCampaignAuthorityMixin"]
