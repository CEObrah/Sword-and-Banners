from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.development import age_years
from sword_runtime.sim.calendar import CampaignTime


class FamilyAutonomyMixin:
    """Evidence-gated autonomous NPC courtship without player-intent invention.

    This layer never creates attraction or scans the person population for a spouse.
    It reacts only to already-saved exact relationship evidence for the reviewing
    person.  Proposal, betrothal and marriage remain sparse family authority records.
    """

    _FAMILY_INDEX = "state/family/index.json"
    _RELATIONSHIPS = "state/relationships.json"

    def _family_autonomy_rules(self) -> Mapping[str, Any]:
        doc = self.read("game/data/mechanics/family.json")
        return doc.get("autonomous_courtship", {}) if isinstance(doc, Mapping) else {}

    def _family_index_doc(self) -> dict[str, Any]:
        raw = self.read(self._FAMILY_INDEX)
        return copy.deepcopy(dict(raw)) if isinstance(raw, Mapping) else {}

    @staticmethod
    def _family_add_person_index(idx: dict[str, Any], person_ref: str, bucket: str, record_ref: str) -> None:
        values = idx.setdefault("person_index", {}).setdefault(person_ref, {}).setdefault(bucket, [])
        if record_ref not in values:
            values.append(record_ref)

    def _family_active_union(self, idx: Mapping[str, Any], person_ref: str) -> tuple[str, str, dict[str, Any]] | None:
        refs = ((idx.get("person_index", {}) or {}).get(person_ref, {}) or {}).get("unions", [])
        for union_ref in refs if isinstance(refs, list) else []:
            path = (idx.get("unions", {}) or {}).get(str(union_ref))
            union = self.read_optional(path) if isinstance(path, str) else None
            if isinstance(union, Mapping) and str(union.get("status", "")) in {"betrothed", "married"}:
                return str(union_ref), path, copy.deepcopy(dict(union))
        return None

    def _family_close_kin(self, idx: Mapping[str, Any], a: str, b: str) -> bool:
        if a == b:
            return True
        links = self.read_optional("state/family/kinship-index.json")
        if isinstance(links, Mapping):
            alinks = ((links.get("person_links", {}) or {}).get(a, []) or [])
            blinks = set(((links.get("person_links", {}) or {}).get(b, []) or []))
            if any(str(x) in blinks for x in alinks):
                return True
        parents: dict[str, set[str]] = {}
        for path in (idx.get("parentage", {}) or {}).values():
            row = self.read_optional(path) if isinstance(path, str) else None
            if not isinstance(row, Mapping):
                continue
            child = str(row.get("child_id", ""))
            parents[child] = {str(x.get("parent_id")) for x in row.get("parent_links", []) if isinstance(x, Mapping) and x.get("parent_id")}
        if a in parents.get(b, set()) or b in parents.get(a, set()):
            return True
        if parents.get(a, set()) & parents.get(b, set()):
            return True
        return False

    def _family_relationship_to(self, source_ref: str, target_ref: str) -> Mapping[str, Any] | None:
        doc = self.read(self._RELATIONSHIPS)
        for row in doc.get("edges", []) if isinstance(doc, Mapping) else []:
            if isinstance(row, Mapping) and str(row.get("source_ref", "")) == source_ref and str(row.get("target_ref", "")) == target_ref:
                return row
        return None

    def _family_courtship_candidates(self, person_ref: str, person: Mapping[str, Any], at: CampaignTime, idx: Mapping[str, Any]) -> list[tuple[int, str, Mapping[str, Any]]]:
        rules = self._family_autonomy_rules()
        min_age = max(1, int(rules.get("minimum_age", 16)))
        if age_years(person, at) < min_age or self._family_active_union(idx, person_ref):
            return []
        allowed = set(str(x) for x in rules.get("eligible_relationship_kinds", ["friend", "companion", "courtship", "romantic_interest", "suitor", "established_relationship"]))
        min_affection = int(rules.get("minimum_affection", 55)); min_trust = int(rules.get("minimum_trust", 40))
        loc = self._person_location(person)
        if not loc:
            return []
        rels = self.read(self._RELATIONSHIPS)
        out: list[tuple[int, str, Mapping[str, Any]]] = []
        for row in rels.get("edges", []) if isinstance(rels, Mapping) else []:
            if not isinstance(row, Mapping) or str(row.get("source_ref", "")) != person_ref:
                continue
            target_ref = str(row.get("target_ref", "")); kind = str(row.get("kind", ""))
            if not target_ref or kind not in allowed or self._family_close_kin(idx, person_ref, target_ref):
                continue
            dims = row.get("dimensions", {}) if isinstance(row.get("dimensions"), Mapping) else {}
            affection = int(dims.get("affection", row.get("value", 0)) or 0); trust = int(dims.get("trust", row.get("value", 0)) or 0)
            if affection < min_affection or trust < min_trust:
                continue
            try: _tp, target = self._exact_person(target_ref, active=False)
            except (KeyError, ValueError, FileNotFoundError):
                continue
            if str(target.get("life_status", target.get("status", "active"))).lower() in {"dead", "deceased"} or age_years(target, at) < min_age:
                continue
            if self._family_active_union(idx, target_ref) or self._person_location(target) != loc:
                continue
            score = affection * 2 + trust
            out.append((score, target_ref, row))
        return sorted(out, key=lambda x: (-x[0], x[1]))

    def _family_write_event(self, idx: dict[str, Any], event_type: str, refs: list[str], source_refs: list[str], at: str) -> str:
        eid = "family.auto." + event_type + "." + hashlib.sha256((at + "|" + "|".join(sorted(refs)) + "|" + "|".join(sorted(source_refs))).encode()).hexdigest()[:16]
        path = f"state/family/events/{eid}.json"
        if self.read_optional(path) is None:
            self.put(path, {"schema":"family-event","event_id":eid,"event_type":event_type,"occurred_at":at,"authority":True,"subject_refs":refs,"source_refs":source_refs,"autonomous":True})
            idx.setdefault("events", {})[eid] = path
            for ref in refs: self._family_add_person_index(idx, ref, "events", eid)
        idx.setdefault("counts", {})["events"] = len(idx.get("events", {}))
        return eid

    def _family_create_autonomous_proposal(self, proposer_ref: str, target_ref: str, relationship_ref: str, at: str) -> str:
        idx = self._family_index_doc()
        for pref, path in (idx.get("proposals", {}) or {}).items():
            row = self.read_optional(path) if isinstance(path, str) else None
            if isinstance(row, Mapping) and str(row.get("status")) == "pending" and {str(row.get("proposer_id")), str(row.get("target_id"))} == {proposer_ref, target_ref}:
                return str(pref)
        pid = "family_auto_" + hashlib.sha256(f"{proposer_ref}|{target_ref}|{at}".encode()).hexdigest()[:18]
        path = f"state/family/proposals/{pid}.json"
        proposal = {"schema":"family-proposal","proposal_id":pid,"kind":"marriage_proposal","proposer_id":proposer_ref,"target_id":target_ref,"status":"pending","authority":True,"proposed_at":at,"player_choice_required":target_ref==self.PLAYER_ACTOR or proposer_ref==self.PLAYER_ACTOR,"relationship_evidence_ref":relationship_ref,"basis":"autonomous NPC proposal from pre-existing saved relationship evidence; no attraction or consent is invented"}
        self.put(path, proposal); self._register_owner(pid, path); idx.setdefault("proposals", {})[pid]=path
        for ref in (proposer_ref,target_ref): self._family_add_person_index(idx,ref,"proposals",pid)
        self._family_write_event(idx,"proposal_made",[proposer_ref,target_ref],[relationship_ref,path],at)
        idx.setdefault("counts", {})["proposals"] = len(idx.get("proposals", {})); self.put(self._FAMILY_INDEX,idx)
        return pid

    def _family_accept_autonomous_proposal(self, proposal_ref: str, target_ref: str, at: str) -> str | None:
        idx=self._family_index_doc(); path=(idx.get("proposals",{}) or {}).get(proposal_ref); proposal=self.read_optional(path) if isinstance(path,str) else None
        if not isinstance(proposal,Mapping) or str(proposal.get("status"))!="pending" or str(proposal.get("target_id"))!=target_ref:
            return None
        proposer_ref=str(proposal.get("proposer_id",""))
        if target_ref==self.PLAYER_ACTOR or proposer_ref==self.PLAYER_ACTOR:
            return None
        rules=self._family_autonomy_rules(); allowed=set(str(x) for x in rules.get("eligible_relationship_kinds",[]))
        relationships=self.read(self._RELATIONSHIPS)
        reverse_rows=[]
        for row in relationships.get("edges",[]) if isinstance(relationships,Mapping) else []:
            if not isinstance(row,Mapping):
                continue
            if str(row.get("source_ref",""))!=target_ref or str(row.get("target_ref",""))!=proposer_ref:
                continue
            if str(row.get("kind","")) not in allowed:
                continue
            dims=row.get("dimensions",{}) if isinstance(row.get("dimensions"),Mapping) else {}
            affection=int(dims.get("affection",row.get("value",0)) or 0); trust=int(dims.get("trust",row.get("value",0)) or 0)
            reverse_rows.append((affection*2+trust,str(row.get("edge_ref","")),row,affection,trust))
        if not reverse_rows:
            return None
        _score,_edge,reverse,affection,trust=sorted(reverse_rows,key=lambda x:(-x[0],x[1]))[0]
        if affection<int(rules.get("acceptance_affection",60)) or trust<int(rules.get("acceptance_trust",50)):
            return None
        _pp, proposer=self._exact_person(proposer_ref,active=False); _tp,target=self._exact_person(target_ref,active=False)
        if not self._person_location(proposer) or self._person_location(proposer)!=self._person_location(target): return None
        if self._family_active_union(idx,proposer_ref) or self._family_active_union(idx,target_ref) or self._family_close_kin(idx,proposer_ref,target_ref): return None
        proposal=copy.deepcopy(dict(proposal)); proposal["status"]="accepted"; proposal["accepted_at"]=at; self.put(path,proposal)
        uid="union."+"_".join(sorted([proposer_ref.replace("char_",""),target_ref.replace("char_","")]))
        up=f"state/family/unions/{uid}.json"
        union={"schema":"family-union","union_id":uid,"participants":[proposer_ref,target_ref],"status":"betrothed","authority":True,"formed_at":at,"date_precision":"exact_runtime","recognition":{"recognized":True,"basis":"autonomous mutual saved consent evidence"},"relationship_refs":[str(proposal.get("relationship_evidence_ref","")),str(reverse.get("edge_ref",""))],"proposal_ref":proposal_ref,"autonomous":True}
        self.put(up,union); self._register_owner(uid,up); idx.setdefault("unions",{})[uid]=up
        for ref in (proposer_ref,target_ref): self._family_add_person_index(idx,ref,"unions",uid)
        self._family_write_event(idx,"betrothal_formed",[proposer_ref,target_ref],[path,up],at); idx.setdefault("counts",{})["unions"]=len(idx.get("unions",{})); self.put(self._FAMILY_INDEX,idx)
        return uid

    def _family_mature_betrothal(self, person_ref: str, at: str) -> str | None:
        idx=self._family_index_doc(); active=self._family_active_union(idx,person_ref)
        if active is None: return None
        uid,up,union=active
        if str(union.get("status"))!="betrothed" or person_ref!=sorted(str(x) for x in union.get("participants",[]))[0]: return None
        participants=[str(x) for x in union.get("participants",[]) if isinstance(x,str)]
        if len(participants)!=2 or self.PLAYER_ACTOR in participants: return None
        wait=max(1,int(self._family_autonomy_rules().get("betrothal_days_before_marriage",90)))
        if CampaignTime.parse(at).seconds_since(CampaignTime.parse(str(union.get("formed_at", at)))) < wait * 86400: return None
        docs=[]
        for ref in participants:
            try: docs.append(self._exact_person(ref,active=False)[1])
            except (KeyError,ValueError,FileNotFoundError): return None
        loc=self._person_location(docs[0])
        if not loc or self._person_location(docs[1])!=loc: return None
        union["status"]="married"; union["married_at"]=at
        hid="household."+"_".join(sorted([x.replace("char_","") for x in participants])); hp=f"state/family/households/{hid}.json"
        household={"schema":"family-household","household_id":hid,"authority":True,"status":"active","member_refs":participants,"dependent_refs":[],"property_refs":[],"institution_refs":[],"residence_ref":loc,"union_refs":[uid],"autonomous":True}
        self.put(hp,household); self._register_owner(hid,hp); union["household_ref"]=hp; self.put(up,union); idx.setdefault("households",{})[hid]=hp
        for ref in participants: self._family_add_person_index(idx,ref,"households",hid)
        self._family_write_event(idx,"marriage_formed",participants,[up,hp],at); idx.setdefault("counts",{})["households"]=len(idx.get("households",{})); self.put(self._FAMILY_INDEX,idx)
        return uid

    def _autonomy_person(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_person(host, occurrences, at)
        person_ref=str(host.get("owner_ref",""))
        if not person_ref:
            return
        try: _path,person=self._exact_person(person_ref,active=False)
        except (KeyError,ValueError,FileNotFoundError): return
        if str(person.get("life_status",person.get("status","active"))).lower() in {"dead","deceased"}: return
        self._family_mature_betrothal(person_ref,at)
        idx=self._family_index_doc()
        proposals=((idx.get("person_index",{}) or {}).get(person_ref,{}) or {}).get("proposals",[])
        for proposal_ref in proposals if isinstance(proposals,list) else []:
            path=(idx.get("proposals",{}) or {}).get(str(proposal_ref)); row=self.read_optional(path) if isinstance(path,str) else None
            if isinstance(row,Mapping) and str(row.get("target_id"))==person_ref and str(row.get("status"))=="pending":
                if self._family_accept_autonomous_proposal(str(proposal_ref),person_ref,at): return
        if person_ref==self.PLAYER_ACTOR: return
        idx=self._family_index_doc(); candidates=self._family_courtship_candidates(person_ref,person,CampaignTime.parse(at),idx)
        if candidates:
            _score,target_ref,row=candidates[0]
            self._family_create_autonomous_proposal(person_ref,target_ref,str(row.get("edge_ref","")),at)
