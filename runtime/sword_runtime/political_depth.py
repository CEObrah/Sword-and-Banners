from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any


def _band(value: float, rows: Mapping[str, Any]) -> str:
    v = float(value)
    # Mechanics files use compact textual ranges rather than executable thresholds.
    if "less_than_0" in rows and v < 0:
        return str(rows["less_than_0"])
    if "0_to_24" in rows and 0 <= v <= 24:
        return str(rows["0_to_24"])
    if "25_to_49" in rows and 25 <= v <= 49:
        return str(rows["25_to_49"])
    if "50_to_79" in rows and 50 <= v <= 79:
        return str(rows["50_to_79"])
    if "80_to_119" in rows and 80 <= v <= 119:
        return str(rows["80_to_119"])
    if "120_plus" in rows and v >= 120:
        return str(rows["120_plus"])
    if "80_plus" in rows and v >= 80:
        return str(rows["80_plus"])
    return "unclassified"


class PoliticalDepthMixin:
    """Evidence-aware sovereign courts and bounded multilateral coalition procedure.

    This layer intentionally reuses the existing information, investigation,
    diplomatic-proposal and treaty owners. It does not create a second truth
    authority for evidence and it cannot force sovereign consent.
    """

    # ------------------------------------------------------------------
    # Court evidence
    # ------------------------------------------------------------------

    def _court_evidence_claims(self, evidence_ref: str, subject_ref: str) -> list[dict[str, Any]]:
        path = self.owner_path(evidence_ref)
        doc = self.read(path)
        schema = str(doc.get("schema", "")) if isinstance(doc, Mapping) else ""
        if schema == "sword-information":
            if str(doc.get("subject_ref", "")) != subject_ref:
                raise ValueError("court evidence subject does not match the case subject")
            return [copy.deepcopy(dict(doc))]
        if schema == "sword-investigation":
            if str(doc.get("subject_ref", "")) != subject_ref:
                raise ValueError("court investigation subject does not match the case subject")
            out: list[dict[str, Any]] = []
            for claim_ref in [str(x) for x in doc.get("discovered_claim_refs", []) if isinstance(x, str)]:
                try:
                    claim = self.read(self.owner_path(claim_ref))
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                if isinstance(claim, Mapping) and str(claim.get("schema", "")) == "sword-information" and str(claim.get("subject_ref", "")) == subject_ref:
                    out.append(copy.deepcopy(dict(claim)))
            return out
        raise ValueError("court evidence must be an exact information or investigation owner")

    def _court_evidentiary_assessment(self, case: Mapping[str, Any]) -> dict[str, Any]:
        politics = self.read("game/data/mechanics/politics.json")
        refs = [str(x) for x in case.get("evidence_refs", []) if isinstance(x, str)]
        subject_ref = str(case.get("subject_ref", ""))
        claims: dict[str, dict[str, Any]] = {}
        source_refs: dict[str, list[str]] = {}
        for evidence_ref in refs:
            for claim in self._court_evidence_claims(evidence_ref, subject_ref):
                claim_ref = str(claim.get("information_ref") or claim.get("owner_id") or "")
                if not claim_ref:
                    continue
                claims[claim_ref] = claim
                source_refs.setdefault(claim_ref, []).append(evidence_ref)

        unique_count = len(claims)
        corroboration_factor = min(1.0, 0.6 + 0.2 * max(0, unique_count - 1)) if unique_count else 0.0
        items: list[dict[str, Any]] = []
        total_weight = 0.0
        for claim_ref in sorted(claims):
            claim = claims[claim_ref]
            quality = max(0.0, min(100.0, float(claim.get("confidence_milli", 0)) / 10.0))
            origin = str(claim.get("origin_authority", ""))
            status = str(claim.get("claim_status", ""))
            if origin == "runtime_established" and status == "runtime_established":
                reliability = 100.0
                custody_factor = 1.0 if claim.get("evidence_refs") else 0.85
            elif origin == "player_assertion":
                # Testimony/assertion may be admitted, but admission does not turn it
                # into objective fact and its reliability remains explicitly limited.
                reliability = 35.0
                custody_factor = 0.45
            else:
                reliability = 60.0
                custody_factor = 0.65
            contradiction_penalty = max(0.0, float(claim.get("contradiction_penalty", 0) or 0))
            # politics.json stores quality/reliability as 0..100 and custody /
            # corroboration as 0..1. Reliability therefore acts as a percentage.
            weight = max(0.0, quality * (reliability / 100.0) * custody_factor * corroboration_factor - contradiction_penalty)
            total_weight += weight
            items.append({
                "information_ref": claim_ref,
                "admitted_via_refs": sorted(set(source_refs.get(claim_ref, []))),
                "quality": round(quality, 3),
                "reliability": round(reliability, 3),
                "custody_factor": round(custody_factor, 4),
                "corroboration_factor": round(corroboration_factor, 4),
                "contradiction_penalty": round(contradiction_penalty, 3),
                "evidence_weight": round(weight, 3),
                "objective_truth_status": str(claim.get("claim_status", "unknown")),
            })

        applicable_authority = 20.0 if str(case.get("polity_ref", "")).startswith("polity_") else 0.0
        corroboration = min(20.0, max(0, unique_count - 1) * 5.0)
        contradiction = 0.0
        contamination = 0.0
        procedural_defect = 0.0
        supported_defense = 0.0
        margin = total_weight + applicable_authority + corroboration - contradiction - contamination - procedural_defect - supported_defense
        return {
            "admitted_evidence_refs": refs,
            "unique_information_refs": sorted(claims),
            "evidence_items": items,
            "admissible_evidence_weight": round(total_weight, 3),
            "evidence_strength_band": _band(total_weight, politics.get("evidence_thresholds", {})),
            "legal_components": {
                "applicable_authority": applicable_authority,
                "corroboration": corroboration,
                "contradiction": contradiction,
                "contamination": contamination,
                "procedural_defect": procedural_defect,
                "supported_defense": supported_defense,
            },
            "legal_finding_margin": round(margin, 3),
            "legal_support_band": _band(margin, politics.get("legal_margin_bands", {})),
            "finding_scope": "strength of admitted evidence relevant to the case subject; this is not a hidden objective-fact or guilt resolver",
            "objective_fact_status": "not_created_or_overwritten_by_court_assessment",
        }

    def _court_judgment_relationship(self, assessment: Mapping[str, Any], decision: str) -> dict[str, Any]:
        band = str(assessment.get("legal_support_band", "unclassified"))
        strong = band in {"strongly_supported", "overwhelmingly_supported_subject_to_scope"}
        weak = band in {"finding_not_supported", "weak_support"}
        supports_action = decision in {"uphold", "sanction"}
        dismisses = decision == "dismiss"
        divergence = (strong and dismisses) or (weak and supports_action)
        return {
            "decision": decision,
            "legal_support_band": band,
            "diverges_from_evidentiary_support": bool(divergence),
        }

    def _autonomy_polity_court(self, polity_ref: str, polity: dict[str, Any], at: str) -> None:
        super()._autonomy_polity_court(polity_ref, polity, at)
        for case_ref in [str(x) for x in polity.get("court_case_refs", []) if isinstance(x, str)]:
            try:
                case_path = self.owner_path(case_ref)
                case = copy.deepcopy(self.read(case_path))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            if str(case.get("status", "")) != "decision_required":
                continue
            assessment = self._court_evidentiary_assessment(case)
            if case.get("evidentiary_assessment") != assessment:
                case["evidentiary_assessment"] = assessment
                case.setdefault("history", []).append({"at": at, "event": "evidentiary_assessment_recorded", "legal_support_band": assessment.get("legal_support_band")})
                case["history"] = case["history"][-64:]
                self.put(case_path, case)

    # ------------------------------------------------------------------
    # Court enforcement and appeal
    # ------------------------------------------------------------------

    def _court_money_owner(self, ref: str) -> tuple[str,dict[str,Any],str]:
        ref=str(ref)
        if ref==str(self.PLAYER_ACTOR):
            p=self.owner_path(f"wallet_{ref}");d=copy.deepcopy(self.read(p));return p,d,"silver"
        if ref.startswith("state_"):
            p=self.owner_path(ref);d=copy.deepcopy(self.read(p));return p,d,"treasury_silver"
        if ref.startswith("polity_") and hasattr(self,"_sovereign_treasury"):
            return self._sovereign_treasury(ref)
        try:p,d=self.owner(ref);d=copy.deepcopy(d)
        except (ValueError,KeyError,FileNotFoundError):raise ValueError("court remedy subject lacks an exact monetary owner")
        tref=str(d.get("treasury_ref", "")) if isinstance(d,Mapping) else ""
        if tref:
            tp=self.owner_path(tref);td=copy.deepcopy(self.read(tp));key="treasury_silver" if "treasury_silver" in td else "silver";return tp,td,key
        wref=f"wallet_{ref}"
        try:wp=self.owner_path(wref);wd=copy.deepcopy(self.read(wp));return wp,wd,"silver"
        except (ValueError,KeyError,FileNotFoundError):raise ValueError("court remedy subject has no represented liquid treasury/wallet")

    def _court_transfer_silver(self, payer_ref: str, payee_ref: str, amount: int, *, at: str, case_ref: str) -> None:
        amount=max(0,int(amount))
        if not amount:return
        pp,payer,pkey=self._court_money_owner(payer_ref);qp,payee,qkey=self._court_money_owner(payee_ref)
        if pp==qp:raise ValueError("court monetary remedy cannot transfer to the same exact owner")
        if int(payer.get(pkey,0))<amount:raise ValueError("court remedy payer lacks represented liquid silver")
        payer[pkey]=int(payer.get(pkey,0))-amount;payee[qkey]=int(payee.get(qkey,0))+amount
        payer.setdefault("court_settlements",[]).append({"at":at,"case_ref":case_ref,"silver":-amount,"counterparty_ref":payee_ref});payer["court_settlements"]=payer["court_settlements"][-32:]
        payee.setdefault("court_settlements",[]).append({"at":at,"case_ref":case_ref,"silver":amount,"counterparty_ref":payer_ref});payee["court_settlements"]=payee["court_settlements"][-32:]
        self.put(pp,payer);self.put(qp,payee)

    def _court_detain_person(self, case: dict[str,Any], person_ref: str, custodian_formation_ref: str, *, at: str) -> dict[str,Any]:
        _cp,cust=self._load_formation(custodian_formation_ref);pp,person=self._exact_person(person_ref,active=False);ploc=self._person_location(person);cloc=str(cust.get("location_ref", ""))
        if not ploc or ploc!=cloc:
            warrant={"status":"outstanding","person_ref":person_ref,"custodian_formation_ref":custodian_formation_ref,"issued_at":at,"required_location_ref":cloc,"rule":"court judgment creates lawful arrest authority but cannot teleport the accused into custody"};case["arrest_warrant"]=warrant;return {"kind":"arrest_warrant_issued",**warrant}
        group_ref=self._custody_attach_named_capture(person_ref,custodian_formation_ref,str(case.get("case_ref","court_case")),at);gp,group=self._custody_group(group_ref);group["legal_status"]="court_detention";self._custody_record_history(group,{"at":at,"kind":"court_detention","case_ref":case.get("case_ref")});self.put(gp,group)
        return {"kind":"detained","person_ref":person_ref,"prisoner_group_ref":group_ref,"location_ref":cloc}

    def _court_release_person(self, person_ref: str, prisoner_group_ref: str, *, at: str, case_ref: str) -> dict[str,Any]:
        gp,group=self._custody_group(prisoner_group_ref);refs=group.get("named_prisoner_refs",[]) if isinstance(group.get("named_prisoner_refs"),list) else []
        if person_ref not in refs:raise ValueError("court release target is not held in the exact prisoner group")
        refs.remove(person_ref);group["named_prisoner_refs"]=refs;group["guard_requirement"]=(int(group.get("personnel",0))+len(refs)+4)//5;self._custody_record_history(group,{"at":at,"kind":"court_release","case_ref":case_ref,"person_ref":person_ref});self.put(gp,group);self._custody_set_active(group)
        pp,p0=self._exact_person(person_ref,active=False);person=copy.deepcopy(p0);person["custody_state"]={"status":"released_by_court","released_at":at,"former_prisoner_group_ref":prisoner_group_ref,"legal_basis_ref":case_ref,"location_ref":group.get("location_ref")};self.put(pp,person);return {"kind":"released","person_ref":person_ref,"prisoner_group_ref":prisoner_group_ref}

    def _court_remove_office(self, polity_ref: str, polity: dict[str,Any], person_ref: str, office_key: str | None, *, at: str, case_ref: str) -> dict[str,Any]:
        officeholders=polity.setdefault("officeholders",{});removed=[]
        for key,row in list(officeholders.items()):
            if (not office_key or str(key)==str(office_key)) and isinstance(row,Mapping) and str(row.get("person_ref"))==person_ref:
                removed.append(str(key));officeholders.pop(key,None)
        if office_key and not removed:raise ValueError("subject does not hold the specified polity office")
        pp,p0=self._exact_person(person_ref,active=False);person=copy.deepcopy(p0);person.setdefault("career_state",{}).setdefault("appointments",[]).append({"kind":"office_removal","office_refs":removed,"polity_ref":polity_ref,"removed_at":at,"legal_basis_ref":case_ref});person["career_state"]["appointments"]=person["career_state"]["appointments"][-32:];self.put(pp,person)
        polity.setdefault("appointment_history",[]).append({"kind":"office_removal","person_ref":person_ref,"office_refs":removed,"at":at,"legal_basis_ref":case_ref});polity["appointment_history"]=polity["appointment_history"][-128:]
        return {"kind":"office_removed","person_ref":person_ref,"office_refs":removed}

    # ------------------------------------------------------------------
    # Multilateral coalition conference
    # ------------------------------------------------------------------

    def _conference_path(self, conference_ref: str) -> str:
        token = conference_ref.removeprefix("diplomatic_conference_")
        return f"state/politics/diplomatic-conferences/{token}.json"

    def _conference_index(self) -> dict[str, Any]:
        return copy.deepcopy(self.read_optional("state/politics/diplomatic-conferences/index.json") or {
            "schema": "sword-diplomatic-conference-index", "authority": False, "conferences": {}, "active_refs": []
        })

    def _sync_diplomatic_conference(self, conference_ref: str, at: str) -> dict[str, Any]:
        path = self.owner_path(conference_ref)
        conference = copy.deepcopy(self.read(path))
        accepted: list[str] = []
        declined: list[str] = []
        pending: list[str] = []
        treaty_refs: list[str] = []
        statuses: dict[str, str] = {}
        for invitee_ref, proposal_ref in sorted((conference.get("proposal_refs") or {}).items()):
            try:
                proposal = self.read(self.owner_path(str(proposal_ref)))
            except (KeyError, ValueError, FileNotFoundError):
                statuses[str(invitee_ref)] = "missing_proposal"
                declined.append(str(invitee_ref))
                continue
            status = str(proposal.get("status", ""))
            statuses[str(invitee_ref)] = status
            if status == "accepted":
                accepted.append(str(invitee_ref))
                if proposal.get("treaty_ref"):
                    treaty_refs.append(str(proposal["treaty_ref"]))
            elif status in {"rejected", "withdrawn", "expired"}:
                declined.append(str(invitee_ref))
            else:
                pending.append(str(invitee_ref))
        member_refs = sorted(set([str(conference.get("host_ref", ""))] + accepted) - {""})
        if pending:
            status = "negotiating"
        elif len(member_refs) >= 2:
            status = "concluded"
        else:
            status = "failed"
        snapshot = {
            "proposal_statuses": statuses,
            "accepted_member_refs": member_refs,
            "declined_invitee_refs": sorted(set(declined)),
            "pending_invitee_refs": sorted(set(pending)),
            "coalition_treaty_refs": sorted(set(treaty_refs)),
            "status": status,
        }
        changed = any(conference.get(k) != v for k, v in snapshot.items())
        conference.update(snapshot)
        conference["last_review_at"] = at
        if changed:
            conference.setdefault("history", []).append({"at": at, "event": "conference_status_changed", "status": status, "accepted_member_refs": member_refs, "declined_invitee_refs": sorted(set(declined)), "pending_invitee_refs": sorted(set(pending))})
            conference["history"] = conference["history"][-64:]
        self.put(path, conference)
        idx = self._conference_index()
        idx.setdefault("conferences", {})[conference_ref] = path
        active = [str(x) for x in idx.get("active_refs", []) if isinstance(x, str) and str(x) != conference_ref]
        if status == "negotiating":
            active.append(conference_ref)
        idx["active_refs"] = sorted(set(active))
        self.put("state/politics/diplomatic-conferences/index.json", idx)
        return conference

    def _settle_diplomatic_routes(self, sovereign_ref: str, sovereign_doc: dict[str, Any], at: str) -> None:
        route_refs = [str(x) for x in sovereign_doc.get("diplomatic_route_refs", []) if isinstance(x, str)]
        conference_refs: set[str] = set()
        for proposal_ref in route_refs:
            try:
                proposal = self.read(self.owner_path(proposal_ref))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            provenance = proposal.get("provenance", {}) if isinstance(proposal.get("provenance"), Mapping) else {}
            cref = provenance.get("conference_ref")
            if isinstance(cref, str) and cref:
                conference_refs.add(cref)
        super()._settle_diplomatic_routes(sovereign_ref, sovereign_doc, at)
        for conference_ref in sorted(conference_refs):
            try:
                self._sync_diplomatic_conference(conference_ref, at)
            except (KeyError, ValueError, FileNotFoundError):
                continue

    # ------------------------------------------------------------------
    # Command surface
    # ------------------------------------------------------------------

    def _dispatch_polity_action(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", ""))
        polity_ref = str(payload.get("polity_ref", ""))
        if action == "appeal_court_case":
            now=str(self._world_time());case_ref=str(payload["case_ref"]);case_path=self.owner_path(case_ref);case=copy.deepcopy(self.read(case_path))
            if str(case.get("polity_ref"))!=polity_ref:raise PermissionError("polity may hear appeals only in its own court")
            if str(case.get("status")) not in {"decided","dismissed"}:raise ValueError("only a decided court case may be appealed")
            if isinstance(case.get("enforcement"),Mapping) and str(case["enforcement"].get("status"))=="completed":raise ValueError("completed physical sentence must use a new review/remedy case rather than retroactive appeal")
            case.setdefault("appeals",[]).append({"at":now,"filed_by_ref":command.actor_id,"prior_decision":copy.deepcopy(case.get("decision"))});case["appeals"]=case["appeals"][-16:];case["status"]="remanded";case["stage"]="appeal_review";case["next_review_at"]=str(__import__('sword_runtime.sim.calendar',fromlist=['CampaignTime']).CampaignTime.parse(now).add_seconds(30*86400));case.setdefault("history",[]).append({"at":now,"event":"appeal_filed","filed_by_ref":command.actor_id});case["history"]=case["history"][-64:];self.put(case_path,case);world_time,metrics=self._advance_seconds(3600);self._write_meta(command,world_time);return self._result(polity_ref=polity_ref,action=action,case_ref=case_ref,status=case["status"],world_time=world_time,**metrics)

        if action == "enforce_court_case":
            now=str(self._world_time());case_ref=str(payload["case_ref"]);case_path=self.owner_path(case_ref);case=copy.deepcopy(self.read(case_path));polity_path=self.owner_path(polity_ref);polity=copy.deepcopy(self.read(polity_path))
            if str(case.get("polity_ref"))!=polity_ref:raise PermissionError("polity may enforce only its own judgment")
            if str(case.get("status")) not in {"decided","dismissed"}:raise ValueError("court enforcement requires a final current judgment")
            if isinstance(case.get("enforcement"),Mapping) and str(case["enforcement"].get("status"))=="completed":raise ValueError("court case judgment is already enforced")
            remedy=str(payload.get("remedy_kind","none"));person_ref=str(payload.get("person_ref") or case.get("subject_ref") or "");effect:dict[str,Any]={"kind":"none"}
            if remedy=="office_removal":effect=self._court_remove_office(polity_ref,polity,person_ref,str(payload.get("office_key")) if payload.get("office_key") else None,at=now,case_ref=case_ref)
            elif remedy=="fine":
                amount=int(payload.get("amount_silver",0));self._court_transfer_silver(person_ref,polity_ref,amount,at=now,case_ref=case_ref);effect={"kind":"fine_paid","payer_ref":person_ref,"recipient_ref":polity_ref,"amount_silver":amount}
            elif remedy=="restitution":
                amount=int(payload.get("amount_silver",0));recipient=str(payload.get("recipient_ref",""));
                if not recipient:raise ValueError("restitution requires exact recipient_ref")
                self._court_transfer_silver(person_ref,recipient,amount,at=now,case_ref=case_ref);effect={"kind":"restitution_paid","payer_ref":person_ref,"recipient_ref":recipient,"amount_silver":amount}
            elif remedy=="detention":
                cust=str(payload.get("custodian_formation_ref",""));
                if not cust:raise ValueError("detention enforcement requires exact custodian_formation_ref")
                effect=self._court_detain_person(case,person_ref,cust,at=now)
            elif remedy=="release":
                group_ref=str(payload.get("prisoner_group_ref",""));
                if not group_ref:raise ValueError("court release requires exact prisoner_group_ref")
                effect=self._court_release_person(person_ref,group_ref,at=now,case_ref=case_ref)
            elif remedy=="execution":
                group_ref=str(payload.get("prisoner_group_ref",""));
                if not group_ref:raise ValueError("execution requires exact prisoner_group_ref")
                gp,group=self._custody_group(group_ref);refs=group.get("named_prisoner_refs",[]) if isinstance(group.get("named_prisoner_refs"),list) else []
                if person_ref not in refs:raise ValueError("execution target is not held in the exact prisoner group")
                pp,p0=self._exact_person(person_ref,active=False);person=copy.deepcopy(p0);self._settle_person_death(person_ref,pp,person,now,"court sentence execution",settle_force_body=True);refs.remove(person_ref);group["named_prisoner_refs"]=refs;group["guard_requirement"]=(int(group.get("personnel",0))+len(refs)+4)//5;self._custody_record_history(group,{"at":now,"kind":"court_execution","person_ref":person_ref,"case_ref":case_ref});self.put(gp,group);self._custody_set_active(group);effect={"kind":"execution_completed","person_ref":person_ref,"prisoner_group_ref":group_ref}
            case["enforcement"]={"status":"pending_arrest" if effect.get("kind")=="arrest_warrant_issued" else "completed","remedy_kind":remedy,"at":now,"enforced_by_ref":command.actor_id,"effect":effect};case.setdefault("history",[]).append({"at":now,"event":"judgment_enforcement","remedy_kind":remedy,"effect":effect});case["history"]=case["history"][-64:];self.put(case_path,case);self.put(polity_path,polity);world_time,metrics=self._advance_seconds(2*3600);self._write_meta(command,world_time);return self._result(polity_ref=polity_ref,action=action,case_ref=case_ref,enforcement=case["enforcement"],world_time=world_time,**metrics)

        if action == "open_coalition_conference":
            now = str(self._world_time())
            polity_path = self.owner_path(polity_ref)
            polity = copy.deepcopy(self.read(polity_path))
            target_ref = str(payload["coalition_target_ref"])
            invitees = sorted(set(str(x) for x in payload.get("invitee_refs", []) if isinstance(x, str)))
            token = hashlib.sha256(f"{polity_ref}|{target_ref}|{now}|{'|'.join(invitees)}".encode()).hexdigest()[:18]
            conference_ref = f"diplomatic_conference_{token}"
            path = self._conference_path(conference_ref)
            if self.read_optional(path) is not None:
                raise ValueError("coalition conference already exists")
            conference = {
                "schema": "sword-diplomatic-conference",
                "owner_id": conference_ref,
                "conference_ref": conference_ref,
                "kind": "coalition",
                "host_ref": polity_ref,
                "coalition_target_ref": target_ref,
                "invited_refs": invitees,
                "proposal_refs": {},
                "accepted_member_refs": [polity_ref],
                "declined_invitee_refs": [],
                "pending_invitee_refs": list(invitees),
                "coalition_treaty_refs": [],
                "status": "negotiating",
                "opened_at": now,
                "history": [{"at": now, "event": "conference_opened", "host_ref": polity_ref, "coalition_target_ref": target_ref, "invited_refs": invitees}],
                "rule": "the conference organizes exact sovereign invitations only; every invitee decides its own normal coalition proposal and no membership is created by invitation alone",
            }
            self.put(path, conference)
            self._register_owner(conference_ref, path)
            idx = self._conference_index(); idx.setdefault("conferences", {})[conference_ref] = path; idx.setdefault("active_refs", []).append(conference_ref); idx["active_refs"] = sorted(set(str(x) for x in idx["active_refs"])); self.put("state/politics/diplomatic-conferences/index.json", idx)
            proposal_refs: dict[str, str] = {}
            for invitee_ref in invitees:
                proposal = self._create_diplomatic_proposal(
                    polity_ref, invitee_ref, "coalition", "mutual", now,
                    terms={"duration_days": int(payload.get("duration_days", 720)), "coalition_target_ref": target_ref},
                    provenance={"kind": "multilateral_coalition_conference_invitation", "conference_ref": conference_ref, "host_ref": polity_ref},
                )
                proposal_refs[invitee_ref] = str(proposal["proposal_ref"])
            conference = copy.deepcopy(self.read(path)); conference["proposal_refs"] = proposal_refs; self.put(path, conference)
            polity = copy.deepcopy(self.read(polity_path)); refs = [str(x) for x in polity.setdefault("diplomatic_conference_refs", []) if isinstance(x, str)];
            if conference_ref not in refs: refs.append(conference_ref)
            polity["diplomatic_conference_refs"] = refs[-64:]; self.put(polity_path, polity)
            world_time, metrics = self._advance_seconds(4 * 3600); self._write_meta(command, world_time)
            return self._result(polity_ref=polity_ref, action=action, conference_ref=conference_ref, coalition_target_ref=target_ref, invited_refs=invitees, proposal_refs=proposal_refs, world_time=world_time, **metrics)

        if action == "submit_court_evidence":
            now = str(self._world_time()); case_ref = str(payload["case_ref"]); case_path = self.owner_path(case_ref); case = copy.deepcopy(self.read(case_path))
            if str(case.get("polity_ref", "")) != polity_ref:
                raise PermissionError("polity may admit evidence only in its own court case")
            if str(case.get("status", "")) in {"decided", "dismissed"}:
                raise ValueError("closed court case cannot admit new evidence")
            refs = [str(x) for x in payload.get("evidence_refs", []) if isinstance(x, str)]
            for evidence_ref in refs:
                self._court_evidence_claims(evidence_ref, str(case.get("subject_ref", "")))
            admitted = [str(x) for x in case.setdefault("evidence_refs", []) if isinstance(x, str)]
            admitted.extend(x for x in refs if x not in admitted)
            case["evidence_refs"] = admitted
            case["evidentiary_assessment"] = self._court_evidentiary_assessment(case)
            case.setdefault("history", []).append({"at": now, "event": "evidence_admitted", "evidence_refs": refs, "admitted_by_ref": command.actor_id})
            case["history"] = case["history"][-64:]
            self.put(case_path, case)
            world_time, metrics = self._advance_seconds(3600); self._write_meta(command, world_time)
            return self._result(polity_ref=polity_ref, action=action, case_ref=case_ref, evidence_refs=refs, evidentiary_assessment=case["evidentiary_assessment"], world_time=world_time, **metrics)

        if action == "decide_court_case":
            case_ref = str(payload["case_ref"]); case = self.read(self.owner_path(case_ref))
            if str(case.get("status", "")) != "decision_required":
                raise ValueError("court judgment requires completed investigation/hearing and decision_required status")
            result = super()._dispatch_polity_action(command, payload)
            case_path = self.owner_path(case_ref); case = copy.deepcopy(self.read(case_path))
            assessment = case.get("evidentiary_assessment") if isinstance(case.get("evidentiary_assessment"), Mapping) else self._court_evidentiary_assessment(case)
            case["evidentiary_assessment"] = copy.deepcopy(dict(assessment))
            case["judgment_evidence_relationship"] = self._court_judgment_relationship(assessment, str(payload.get("policy_value", "")))
            self.put(case_path, case)
            return result

        result = super()._dispatch_polity_action(command, payload)
        if action == "open_court_case" and result.get("case_ref"):
            case_path = self.owner_path(str(result["case_ref"])); case = copy.deepcopy(self.read(case_path))
            polity = self.read(self.owner_path(polity_ref))
            jurisdiction_ref = str(payload.get("location_ref") or self._sovereign_seat(polity_ref, polity) or "")
            case["jurisdiction_ref"] = jurisdiction_ref
            case["presiding_authority_ref"] = command.actor_id
            if payload.get("claimant_ref"): case["claimant_ref"] = str(payload["claimant_ref"])
            if payload.get("victim_refs"): case["victim_refs"] = [str(x) for x in payload["victim_refs"] if isinstance(x, str)]
            if payload.get("applicable_law_ref"): case["applicable_law_ref"] = str(payload["applicable_law_ref"])
            case["procedure"] = {"filing": True, "investigation": True, "hearing": True, "judgment_required": True, "automatic_verdict": False}
            self.put(case_path, case)
        if action in {"accept_treaty", "reject_treaty"} and result.get("proposal_ref"):
            proposal = self.read(self.owner_path(str(result["proposal_ref"])))
            provenance = proposal.get("provenance", {}) if isinstance(proposal.get("provenance"), Mapping) else {}
            conference_ref = provenance.get("conference_ref")
            if isinstance(conference_ref, str) and conference_ref:
                self._sync_diplomatic_conference(conference_ref, str(self._world_time()))
        return result
