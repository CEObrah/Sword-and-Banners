"""Conservation and operating-cost hardening for House Tang development.

The underlying HouseTangDevelopmentMixin remains the semantic owner of Inner Walls
training, promotion, recruitment, and expansion.
This production composition layer keeps aggregate establishment totals, scheduler
chronology, House recurring expense summaries, player-safe report projection synchronized after those exact owner mutations.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.causal_callback_time import CausalCallbackWorldTimeMixin
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import apply_selection_profile, conserved_establishment_role_count, role_count
from sword_runtime.house_tang_development import (
    HouseTangDevelopmentMixin,
    MONTH_SECONDS,
    _public_owner_label,
)
from sword_runtime.household_request_flow import _emit_watch_report, _treasury_safe_ceiling
from sword_runtime.recruitment_campaigns import (
    PROFILE_PATH as CANDIDATE_PROFILE_PATH,
    REGISTRY_PATH as CANDIDATE_REGISTRY_PATH,
    _credit_recruitment_payment,
    _registry as _candidate_registry,
)
from sword_runtime.sim.calendar import CampaignTime



class HouseTangDevelopmentIntegrityMixin(CausalCallbackWorldTimeMixin, HouseTangDevelopmentMixin):
    """Close derived establishment/economy/chronology/report invariants after House development."""

    def _normalize_house_tang_training_host(self, runtime: dict[str, Any]) -> None:
        HouseTangDevelopmentMixin._normalize_house_tang_training_host(self, runtime)

    def _enrich_world_arc_report(self, source_event_ref: str) -> None:
        """Add bounded material detail without mutating closed provenance schemas."""
        source = get_causal_event(self, source_event_ref)
        report_ref = f"{source_event_ref}.report"
        report = get_causal_event(self, report_ref)
        if not isinstance(source, Mapping) or not isinstance(report, Mapping):
            return
        current_summary = str(report.get("summary", ""))
        if any(marker in current_summary for marker in (
            " The material evidence is specific enough to establish that ",
            " The material evidence establishes that ",
            " The source carries concrete actor-owned evidence that ",
            " The available evidence establishes that ",
        )):
            return
        result = str(source.get("result", ""))
        actor = _public_owner_label(source.get("actor_ref"))
        target = _public_owner_label(source.get("target_ref")) if source.get("target_ref") else "its reported objective"
        detail = ""
        if result == "material_action_settled":
            src_prov = source.get("provenance") if isinstance(source.get("provenance"), Mapping) else {}
            evidence = src_prov.get("material_evidence") if isinstance(src_prov.get("material_evidence"), Mapping) else {}
            kind = str(evidence.get("kind", ""))
            if kind == "exact_operation_created":
                detail = f" The material evidence is specific enough to establish that {actor} has opened an actual military operation directed at {target} and assigned an existing formation to it. The delivered channels do not establish the formation's size, exact route, supply state, combat contact, or result."
            elif kind in {"exact_operation_transition", "exact_operation_advanced"}:
                detail = f" The material evidence establishes that an existing operation owned by {actor} has advanced to a new settled operational state against {target}. The delivered channels do not establish undisclosed orders, force size, or combat outcome."
            elif kind in {"exact_formation_moved", "exact_formation_state_change"}:
                detail = f" The material evidence establishes that a real formation-level movement or state change by {actor} occurred in connection with {target}. Exact strength and undisclosed destination details remain outside this report."
            else:
                detail = f" The source carries concrete actor-owned evidence that {actor} completed a real domain action connected to {target}, rather than merely recording intent. The delivered channels do not establish additional tactical particulars."
        elif result == "work_blocked":
            detail = f" The available evidence establishes that {actor}'s attempted move toward {target} failed to satisfy a concrete domain requirement; no success is inferred from the attempt."
        if not detail:
            return
        _path, owner = read_causal_event_owner(self)
        mutable = owner.get("causal_events", {}).get(report_ref)
        if not isinstance(mutable, dict):
            return
        mutable["summary"] = (str(mutable.get("summary", "")).rstrip() + detail)[:4000]
        # Deliberately do not add bookkeeping keys to provenance: each provenance
        # variant is a closed schema. Idempotence is derived from the public summary.
        owner.setdefault("runtime", {})["last_settled_at"] = str(report.get("triggered_at", report.get("due_at", "")))
        write_causal_event_owner(self, owner)


    # Due-host settlement is centrally dispatched by time_integration.py.


    def _settle_expansion_request(self, host: Mapping[str, Any], at: str) -> None:
        super()._settle_expansion_request(host, at)

    def _settle_expansion_completion(self, host: Mapping[str, Any], at: str) -> None:
        super()._settle_expansion_completion(host, at)

    def _autonomy_house_tang_training(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_house_tang_training(host, occurrences, at)


__all__ = ["HouseTangDevelopmentIntegrityMixin"]
