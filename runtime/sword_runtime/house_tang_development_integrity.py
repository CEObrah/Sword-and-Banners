"""Conservation and operating-cost hardening for House Tang development.

The underlying HouseTangDevelopmentMixin remains the semantic owner of Sword Manor
training, promotion, recruitment, expansion, and Great Bow Guard applicant work.
This production composition layer keeps aggregate establishment totals, scheduler
chronology, House recurring expense summaries, mass Great Bow Guard screening,
and player-safe report projection synchronized after those exact owner mutations.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.causal_callback_time import CausalCallbackWorldTimeMixin
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import apply_selection_profile, role_count
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

_GBG_MASS_PRIORITY = 48
_GBG_MASS_KIND = "house_gbg_mass_screening"


class HouseTangDevelopmentIntegrityMixin(CausalCallbackWorldTimeMixin, HouseTangDevelopmentMixin):
    """Close derived establishment/economy/chronology/report invariants after House development."""

    @staticmethod
    def _gbg_mass_ids(campaign_ref: str) -> tuple[str, str]:
        digest = hashlib.sha256(("house-gbg-mass-screening|" + campaign_ref).encode("utf-8")).hexdigest()[:20]
        return f"host_house_gbg_mass_screening_{digest}", f"event_house_gbg_mass_screening_{digest}"

    def _normalize_sword_manor_host(self, runtime: dict[str, Any]) -> None:
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        now = CampaignTime.parse(str(runtime["world_time"]))
        progression = self.read("state/prog/sword-manor-progression.json")
        prog_runtime = progression.get("runtime", {}) if isinstance(progression, Mapping) else {}
        last_settled = prog_runtime.get("last_settled_at") if isinstance(prog_runtime, Mapping) else None
        desired = now.add_seconds(MONTH_SECONDS)
        if isinstance(last_settled, str) and last_settled:
            lawful_next = CampaignTime.parse(last_settled).add_seconds(MONTH_SECONDS)
            desired = now if lawful_next <= now else lawful_next
        for host_id, host in hosts.items():
            if not isinstance(host_id, str) or not isinstance(host, dict):
                continue
            if host.get("owner_ref") != "institution_sword_manor" and host_id != "host_sword_manor":
                continue
            host["kind"] = "sword_manor"
            host["recurrence_seconds"] = MONTH_SECONDS
            current_due = CampaignTime.parse(str(host["next_due"])) if isinstance(host.get("next_due"), str) else desired
            if current_due != desired:
                host["next_due"] = str(desired)
                host["safe_through"] = str(desired.add_seconds(-1))
                for event in events:
                    if isinstance(event, dict) and event.get("target_host") == host_id:
                        event["due_at"] = str(desired)
                        break
            break

    def _sync_great_bow_guard_mass_screening(self, runtime: dict[str, Any]) -> None:
        """Ensure the regional application funnel precedes the residential final trial.

        Regional application records are not population custody. The already-conserved
        candidate campaign remains the residential shortlist, so six-figure outreach
        does not pretend that every applicant moved into Sword Manor.
        """
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        house = self.read("state/houses/house_tang.json")
        programs = house.get("administrative_programs", {}) if isinstance(house, Mapping) else {}
        great = programs.get("great_bow_guard", {}) if isinstance(programs, Mapping) else {}
        campaign_ref = str(great.get("candidate_campaign_ref", "")) if isinstance(great, Mapping) else ""
        if not campaign_ref:
            return
        registry = _candidate_registry(self)
        campaign = registry.get("campaigns", {}).get(campaign_ref)
        active = (
            isinstance(campaign, Mapping)
            and str(campaign.get("status", "")) == "screening"
            and campaign.get("mass_screening_complete") is not True
        )
        host_id, event_id = self._gbg_mass_ids(campaign_ref)
        if not active:
            pending = runtime.get("pending_wake")
            if isinstance(pending, Mapping) and pending.get("target_host") == host_id:
                return
            hosts.pop(host_id, None)
            events[:] = [
                row for row in events
                if not (isinstance(row, Mapping) and row.get("target_host") == host_id)
            ]
            return

        rules = self.read("game/data/mechanics/house-tang-development.json")
        cfg = rules.get("great_bow_guard_recruitment", {}) if isinstance(rules, Mapping) else {}
        recurrence = max(86400, int(cfg.get("mass_screening_review_seconds", 7 * 86400)))
        now = CampaignTime.parse(str(runtime["world_time"]))
        host = hosts.get(host_id)
        if not isinstance(host, dict):
            host = {
                "host_id": host_id,
                "kind": _GBG_MASS_KIND,
                "owner_ref": "house_tang",
                "campaign_ref": campaign_ref,
                "recurrence_seconds": recurrence,
                "next_due": str(now),
                "resolved_through": str(now.add_seconds(-1)),
                "safe_through": str(now.add_seconds(-1)),
            }
            hosts[host_id] = host
        else:
            host["kind"] = _GBG_MASS_KIND
            host["owner_ref"] = "house_tang"
            host["campaign_ref"] = campaign_ref
            host["recurrence_seconds"] = recurrence
        event = next(
            (row for row in events if isinstance(row, dict) and row.get("event_id") == event_id),
            None,
        )
        if not isinstance(event, dict):
            events.append({
                "event_id": event_id,
                "kind": _GBG_MASS_KIND,
                "priority": _GBG_MASS_PRIORITY,
                "target_host": host_id,
                "due_at": str(host["next_due"]),
            })
        else:
            event.update({
                "kind": _GBG_MASS_KIND,
                "priority": _GBG_MASS_PRIORITY,
                "target_host": host_id,
                "due_at": str(host["next_due"]),
            })
            event.pop("suspended", None)

    def _great_bow_guard_mass_screening(self, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
        campaign_ref = str(host.get("campaign_ref", ""))
        registry = _candidate_registry(self)
        campaign = registry.get("campaigns", {}).get(campaign_ref)
        if not isinstance(campaign, MutableMapping):
            return None
        if str(campaign.get("status", "")) != "screening" or campaign.get("mass_screening_complete") is True:
            return None

        house = copy.deepcopy(self.read("state/houses/house_tang.json"))
        programs = house.get("administrative_programs", {})
        great = programs.get("great_bow_guard") if isinstance(programs, Mapping) else None
        if not isinstance(great, dict) or str(great.get("candidate_campaign_ref", "")) != campaign_ref:
            raise ValueError("Great Bow Guard mass screening lost its exact House program")

        rules = self.read("game/data/mechanics/house-tang-development.json")
        cfg = rules.get("great_bow_guard_recruitment", {}) if isinstance(rules, Mapping) else {}
        current = max(0, int(campaign.get("remaining_candidates", 0)))
        if current <= 0:
            raise ValueError("Great Bow Guard residential candidate cohort is empty")
        configured_shortlist = max(1, int(cfg.get("residential_trial_shortlist", current)))
        if current > configured_shortlist:
            raise ValueError("Great Bow Guard residential candidate cohort exceeds the registered mass-screen shortlist")

        profile_registry = self.read(CANDIDATE_PROFILE_PATH)
        source_mix = profile_registry.get("candidate_campaign_source_mix", {}) if isinstance(profile_registry, Mapping) else {}
        pop = self.read("state/population/qin.json")
        strata = pop.get("strata", {}) if isinstance(pop, Mapping) else {}
        eligible_total = current + sum(
            max(0, int(strata.get(source, 0)))
            for source in source_mix
        ) if isinstance(source_mix, Mapping) else current
        configured_target = max(current, int(cfg.get("regional_application_target", 120000)))
        regional_target = max(current, min(configured_target, eligible_total))
        selection_ref = str(cfg.get("selection_profile_ref", great.get("selection_profile", "wei_archery_trial")))

        selections = profile_registry.get("selection_profiles", {}) if isinstance(profile_registry, Mapping) else {}
        selection = selections.get(selection_ref) if isinstance(selections, Mapping) else None
        if not isinstance(selection, Mapping):
            raise ValueError("Great Bow Guard regional screening selection profile is unavailable")

        economy = self.read("game/data/mechanics/economy.json")
        constants = economy.get("recruitment_cost_constants", {}) if isinstance(economy, Mapping) else {}
        campaign_rules = economy.get("recruitment_campaign", {}) if isinstance(economy, Mapping) else {}
        contact_key = str(campaign_rules.get("default_contact_cost_key", "contacted_candidate_regional"))
        screen_key = str(campaign_rules.get("screening_cost_key", "screened_candidate_ordinary"))
        contact_rate = max(0.0, float(constants.get(contact_key, 0.1)))
        screen_rate = max(0.0, float(constants.get(screen_key, 0.1)))
        additional_records = max(0, regional_target - current)
        contact_cost = max(0, int(math.ceil(additional_records * contact_rate - 1e-9)))
        screening_cost = max(0, int(math.ceil(regional_target * screen_rate - 1e-9)))
        total_cost = contact_cost + screening_cost

        treasury = copy.deepcopy(self.read("state/treasury/treasury-house-tang.json"))
        safety = _treasury_safe_ceiling(treasury, self.read("game/data/mechanics/house-tang-programs.json"))
        if total_cost > int(treasury.get("silver", 0)) or total_cost > int(safety.get("treasury_safe_ceiling_silver", 0)):
            report_ref = _emit_watch_report(
                self,
                player_ref="char_tang_wei",
                at=at,
                key=f"gbg_mass_screening_blocked:{campaign_ref}:{regional_target}:{total_cost}",
                summary=(
                    f"House Tang reports that the Great Bow Guard regional call can examine {regional_target} applications, but the combined outreach and preliminary-screening cost of {total_cost} silver exceeds the current treasury-safe discretionary ceiling. "
                    f"The existing {current}-person residential candidate cohort remains conserved and no additional civilian population is withdrawn while the regional screening is unfunded."
                ),
            )
            report = get_causal_event(self, report_ref)
            if not isinstance(report, Mapping):
                return None
            digest = hashlib.sha256(f"{report_ref}|{at}".encode("utf-8")).hexdigest()[:20]
            return {
                "wake_ref": f"wake.house.great_bow_guard.mass.{digest}",
                "kind": "campaign_event",
                "at": at,
                "campaign_event_ref": report_ref,
                "reason": str(report.get("summary", "Great Bow Guard regional screening is blocked.")),
            }

        evidence_ref = f"house_great_bow_guard_mass_screening:{campaign_ref}:{at}"
        retain_fraction = current / max(1, regional_target)
        conditioned = 0
        for candidate_slice in campaign.get("slices", []):
            if not isinstance(candidate_slice, MutableMapping) or int(candidate_slice.get("count", 0)) <= 0:
                continue
            profile = candidate_slice.get("profile")
            if not isinstance(profile, MutableMapping):
                continue
            apply_selection_profile(profile, selection, retain_fraction=retain_fraction)
            candidate_slice.setdefault("selection_history", []).append({
                "selection_profile": selection_ref,
                "stage": "regional_mass_screening",
                "retain_fraction": round(retain_fraction, 8),
                "evidence_ref": evidence_ref,
            })
            candidate_slice["selection_history"] = candidate_slice["selection_history"][-16:]
            conditioned += int(candidate_slice.get("count", 0))
        if conditioned != current:
            raise ValueError("Great Bow Guard mass-screen conditioning does not cover the conserved residential cohort")

        treasury["silver"] = int(treasury.get("silver", 0)) - total_cost
        if contact_cost:
            contact_payee = _credit_recruitment_payment(
                self,
                "qin",
                contact_cost,
                kind="regional_application_contact",
                evidence_ref=evidence_ref,
                campaign_ref=campaign_ref,
                location_ref=str(campaign.get("location_ref", "loc_tang_manor_training_ground")),
            )
        else:
            contact_payee = None
        if screening_cost:
            screening_payee = _credit_recruitment_payment(
                self,
                "qin",
                screening_cost,
                kind="regional_candidate_screening",
                evidence_ref=evidence_ref,
                campaign_ref=campaign_ref,
                location_ref=str(campaign.get("location_ref", "loc_tang_manor_training_ground")),
            )
        else:
            screening_payee = None

        campaign["mass_screening_complete"] = True
        campaign["mass_screened_at"] = at
        campaign["regional_application_count"] = regional_target
        campaign["regional_application_records_nonresident"] = max(0, regional_target - current)
        campaign["regional_shortlist_count"] = current
        campaign["selection_profile_ref"] = selection_ref
        campaign.setdefault("stage_history", []).append({
            "kind": "regional_mass_screening",
            "before": regional_target,
            "after": current,
            "rejected": regional_target - current,
            "selection_profile": selection_ref,
            "application_records_only": True,
            "evidence_ref": evidence_ref,
        })
        campaign["stage_history"] = campaign["stage_history"][-32:]
        campaign.setdefault("economic_history", []).extend([
            {
                "kind": "regional_application_contact",
                "silver": contact_cost,
                "candidate_count": additional_records,
                "payee_ref": contact_payee,
                "evidence_ref": evidence_ref,
            },
            {
                "kind": "regional_candidate_screening",
                "silver": screening_cost,
                "candidate_count": regional_target,
                "payee_ref": screening_payee,
                "evidence_ref": evidence_ref,
            },
        ])
        campaign["economic_history"] = campaign["economic_history"][-32:]

        great["applicants_registered"] = regional_target
        great["regional_applicants_screened"] = regional_target
        great["regional_screening_rejected"] = regional_target - current
        great["screened_candidates"] = regional_target
        great["rejected_candidates"] = regional_target - current
        great["shortlisted_candidates"] = current
        great["residential_trial_candidates"] = current
        great["mass_screening_completed_at"] = at
        great["recruitment_phase"] = "residential_archery_trials"
        great["recruitment_spending_silver"] = int(great.get("recruitment_spending_silver", 0)) + total_cost
        programs["great_bow_guard"] = great

        self.put("state/treasury/treasury-house-tang.json", treasury)
        self.put(CANDIDATE_REGISTRY_PATH, registry)
        self.put("state/houses/house_tang.json", house)

        report_ref = _emit_watch_report(
            self,
            player_ref="char_tang_wei",
            at=at,
            key=f"gbg_mass_screened:{campaign_ref}",
            summary=(
                f"House Tang completes the first Great Bow Guard regional selection. The call reaches and screens {regional_target} applicant records under {selection_ref}; {regional_target - current} are eliminated before residential trials, leaving a conserved {current}-person shortlist for the final live tests at Sword Manor. "
                f"The wider applicants remained in civilian population throughout the paper, local and regional preliminary screening; only the {current} shortlisted candidates are held in the candidate pool. Outreach and preliminary screening cost {total_cost} silver. No fighter, weapon, equipment issue or formation is created by this stage."
            ),
        )
        report = get_causal_event(self, report_ref)
        if not isinstance(report, Mapping):
            return None
        digest = hashlib.sha256(f"{report_ref}|{at}".encode("utf-8")).hexdigest()[:20]
        return {
            "wake_ref": f"wake.house.great_bow_guard.mass.{digest}",
            "kind": "campaign_event",
            "at": at,
            "campaign_event_ref": report_ref,
            "reason": str(report.get("summary", "Great Bow Guard regional screening is complete.")),
        }

    def _sync_sword_manor_derived_state(self) -> None:
        sword = copy.deepcopy(self.read("state/forces/sword-manor.json"))
        authorized = sword.get("authorized_by_role", {})
        if not isinstance(authorized, Mapping):
            raise ValueError("Sword Manor authorized role registry is invalid")
        sword["authorized_strength"] = sum(max(0, int(value)) for value in authorized.values())
        self.put("state/forces/sword-manor.json", sword)

        treasury = copy.deepcopy(self.read("state/treasury/treasury-house-tang.json"))
        rules = self.read("game/data/mechanics/house-tang-development.json")
        cost_rule = rules.get("sword_manor_operating_costs", {}) if isinstance(rules, Mapping) else {}
        if not isinstance(cost_rule, Mapping):
            raise ValueError("Sword Manor operating-cost rule is invalid")
        trainees = role_count(sword, "trainee")
        cash_per_head = max(0, int(cost_rule.get("trainee_monthly_cash_per_head_silver", 40)))
        food_per_head = max(0, int(cost_rule.get("trainee_monthly_food_per_head_kg", 48)))

        components = treasury.setdefault("monthly_flow_components", {})
        cash = components.setdefault("cash", {})
        food = components.setdefault("food", {})
        if not isinstance(cash, dict) or not isinstance(food, dict):
            raise ValueError("House Tang monthly flow components are invalid")
        cash["sword_manor_trainee_program_expense_silver"] = trainees * cash_per_head
        food["trainee_population_requirement_kg"] = trainees * food_per_head

        stable = treasury.setdefault("stable_monthly_flows", {})
        if not isinstance(stable, dict):
            raise ValueError("House Tang stable monthly flow summary is invalid")
        stable["expense_silver"] = sum(max(0, int(value)) for value in cash.values())
        food_in = sum(
            max(0, int(value))
            for key, value in food.items()
            if "production" in str(key) or "delivery" in str(key)
        )
        food_out = sum(
            max(0, int(value))
            for key, value in food.items()
            if "production" not in str(key) and "delivery" not in str(key)
        )
        stable["food_net_change_kg"] = food_in - food_out
        self.put("state/treasury/treasury-house-tang.json", treasury)

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

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        runtime = copy.deepcopy(self.read("state/runtime.json"))
        self._sync_great_bow_guard_mass_screening(runtime)
        self.put("state/runtime.json", runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") == _GBG_MASS_KIND:
            wake = self._great_bow_guard_mass_screening(host, due_text)
            if isinstance(wake, dict):
                wake["target_host"] = self._active_host_id
                wake["event_id"] = self._active_event_id
            self._pending_wake_created = wake
            return
        super()._run_due_host(host, due_text)

    def _settle_expansion_request(self, host: Mapping[str, Any], at: str) -> None:
        super()._settle_expansion_request(host, at)
        self._sync_sword_manor_derived_state()

    def _settle_expansion_completion(self, host: Mapping[str, Any], at: str) -> None:
        super()._settle_expansion_completion(host, at)
        self._sync_sword_manor_derived_state()

    def _autonomy_manor(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_manor(host, occurrences, at)
        self._sync_sword_manor_derived_state()


__all__ = ["HouseTangDevelopmentIntegrityMixin"]
