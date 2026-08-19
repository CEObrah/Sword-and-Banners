"""Generic, evidence-bounded intrigue scheme engine.

Schemes own no people and no implied access. Sponsors assign existing agents,
spend exact silver, and work through saved access refs. Progress and exposure
are independent numerical tracks derived from saved character/target state.
Terminal scheme results create only effects the existing physical systems can
support; assassination/kidnapping/defection never become automatic outcomes.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.sim.calendar import CampaignTime

_INDEX="state/politics/schemes/index.json"
_REVIEW=7*86400
_OBJECTIVES=frozenset({"bribery","blackmail","forgery","defection","sabotage","gate_opening","assassination","kidnapping","theft","misinformation","discrediting","prisoner_escape","revolt"})
_DIFFICULTY={"bribery":38,"blackmail":50,"forgery":48,"defection":70,"sabotage":58,"gate_opening":72,"assassination":82,"kidnapping":86,"theft":48,"misinformation":44,"discrediting":50,"prisoner_escape":68,"revolt":84}
_TRACE={"bribery":22,"blackmail":24,"forgery":30,"defection":36,"sabotage":44,"gate_opening":48,"assassination":62,"kidnapping":65,"theft":38,"misinformation":26,"discrediting":32,"prisoner_escape":46,"revolt":58}


def _path(ref:str)->str:
    if not ref.startswith("scheme_") or any(x in ref for x in ("/","\\","..")):raise ValueError("invalid scheme ref")
    return f"state/politics/schemes/{ref}.json"

def _clamp(v:float,lo:int=0,hi:int=100)->int:return max(lo,min(hi,int(round(v))))

class IntrigueSchemeMixin:
    def _scheme_index(self)->dict[str,Any]:
        row=self.read_optional(_INDEX)
        if not isinstance(row,Mapping):row={"schema":"sword-scheme-index","authority":False,"schemes":{},"active_refs":[]}
        return copy.deepcopy(dict(row))

    def _scheme(self,ref:str)->tuple[str,dict[str,Any]]:
        idx=self._scheme_index();p=idx.get("schemes",{}).get(ref)
        if not isinstance(p,str):p=_path(ref)
        row=self.read_optional(p)
        if not isinstance(row,Mapping):raise ValueError("unknown scheme")
        return p,copy.deepcopy(dict(row))

    def _scheme_register(self,row:Mapping[str,Any],p:str)->None:
        idx=self._scheme_index();ref=str(row["owner_id"]);idx.setdefault("schemes",{})[ref]=p;active=idx.setdefault("active_refs",[])
        if ref not in active:active.append(ref);active.sort()
        self.put(_INDEX,idx);self._register_owner(ref,p);self._scheme_ensure_host()

    def _scheme_funding_source(self,sponsor_ref:str)->tuple[str,dict[str,Any],str]:
        sponsor_ref=str(sponsor_ref)
        if sponsor_ref==str(self.PLAYER_ACTOR):
            path=self.owner_path(f"wallet_{sponsor_ref}")
            return path,copy.deepcopy(self.read(path)),"silver"
        if sponsor_ref=="house_tang":
            path=self.owner_path("treasury_house_tang")
            return path,copy.deepcopy(self.read(path)),"silver"
        if sponsor_ref.startswith("state_"):
            path=self.owner_path(sponsor_ref);doc=copy.deepcopy(self.read(path))
            return path,doc,"treasury_silver"
        if sponsor_ref.startswith("polity_") and hasattr(self,"_sovereign_treasury"):
            return self._sovereign_treasury(sponsor_ref)
        try:
            sp,sponsor=self.owner(sponsor_ref)
        except (ValueError,KeyError,FileNotFoundError):
            sp=sponsor=None
        if isinstance(sponsor,Mapping):
            tref=str(sponsor.get("treasury_ref", ""))
            if tref:
                path=self.owner_path(tref);doc=copy.deepcopy(self.read(path));key="treasury_silver" if "treasury_silver" in doc else "silver"
                return path,doc,key
        wallet_ref=f"wallet_{sponsor_ref}"
        try:
            path=self.owner_path(wallet_ref);doc=copy.deepcopy(self.read(path));return path,doc,"silver"
        except (ValueError,KeyError,FileNotFoundError):
            raise ValueError("scheme sponsor lacks an exact spendable treasury or wallet")

    def _scheme_reserve_funds(self,sponsor_ref:str,amount:int)->str:
        amount=max(0,int(amount))
        path,doc,key=self._scheme_funding_source(sponsor_ref)
        balance=max(0,int(doc.get(key,0)))
        if amount>balance:raise ValueError("scheme sponsor has insufficient exact silver")
        if amount:
            doc[key]=balance-amount;self.put(path,doc)
        return str(doc.get("owner_id",path))

    def _scheme_refund_funds(self,row:dict[str,Any],amount:int)->int:
        amount=max(0,min(int(amount),int(row.get("remaining_budget_silver",0))))
        if not amount:return 0
        path,doc,key=self._scheme_funding_source(str(row.get("sponsor_ref","")))
        doc[key]=max(0,int(doc.get(key,0)))+amount;self.put(path,doc);row["remaining_budget_silver"]=int(row.get("remaining_budget_silver",0))-amount
        row["refunded_silver"]=int(row.get("refunded_silver",0))+amount
        return amount

    def _validate_scheme_reference(self,ref:str,*,allow_route:bool=True)->None:
        ref=str(ref)
        if not ref:raise ValueError("empty scheme reference")
        try:
            self.owner(ref);return
        except (ValueError,KeyError,FileNotFoundError):pass
        if ref.startswith("loc_"):
            self._location_record(ref);return
        if allow_route and ref.startswith("route_"):
            # Any exact strategic route is valid access; water crossings are a subset.
            doc=self.read("game/data/world/routes.json")
            if any(isinstance(x,Mapping) and str(x.get("ref"))==ref for x in list(doc.get("routes",[]))+list(doc.get("local_routes",[]))):return
        raise ValueError("scheme reference must resolve to an exact owner, location, or strategic route")

    def _scheme_set_active(self,row:Mapping[str,Any])->None:
        idx=self._scheme_index();active=idx.setdefault("active_refs",[]);ref=str(row.get("owner_id",""));is_active=str(row.get("status")) in {"active","exposed"}
        if is_active and ref not in active:active.append(ref);active.sort()
        if not is_active and ref in active:active.remove(ref)
        self.put(_INDEX,idx)

    def _scheme_ensure_host(self)->None:
        runtime=copy.deepcopy(self.read("state/runtime.json"));hosts=runtime.get("hosts");events=runtime.get("events")
        if not isinstance(hosts,dict) or not isinstance(events,list):raise ValueError("runtime causal queue is invalid")
        refs=[str(x) for x in self._scheme_index().get("active_refs",[]) if isinstance(x,str)];hid="host_intrigue_schemes";eid="event_intrigue_schemes";host=hosts.get(hid);changed=False;now=CampaignTime.parse(str(runtime["world_time"]))
        if not isinstance(host,dict):
            due=now.add_seconds(_REVIEW);host={"kind":"intrigue_scheme","owner_ref":"scheme_registry","routed_scheme_refs":refs,"recurrence_seconds":_REVIEW,"resolved_through":str(now),"next_due":str(due),"safe_through":str(due.add_seconds(-1))};hosts[hid]=host;changed=True
        elif host.get("routed_scheme_refs")!=refs:host["routed_scheme_refs"]=refs;changed=True
        if not any(isinstance(e,Mapping) and e.get("event_id")==eid for e in events):events.append({"event_id":eid,"kind":"intrigue_scheme_review","priority":74,"target_host":hid,"due_at":str(host["next_due"])});changed=True
        if changed:self.put("state/runtime.json",runtime)

    def _scheme_person_score(self,ref:str)->dict[str,int]:
        _p,person=self._exact_person(ref,active=False);skills=person.get("skills",{}) if isinstance(person.get("skills"),Mapping) else {};attrs=person.get("attributes",{}) if isinstance(person.get("attributes"),Mapping) else {}
        return {"intrigue":_clamp(float(skills.get("Intrigue",0))),"stealth":_clamp(float(skills.get("Stealth",0))),"diplomacy":_clamp(float(skills.get("Diplomacy",0))),"engineering":_clamp(float(skills.get("Engineering",0))),"intelligence":_clamp(float(skills.get("Intelligence Operations",0))),"cunning":_clamp(float(attrs.get("Intelligence",attrs.get("Wits",50))))}

    def _scheme_target_security(self,target_ref:str)->int:
        try:
            _p,row=self.owner(target_ref)
            if isinstance(row,Mapping):
                for key in ("security_milli","counterintelligence_milli","security","defense","readiness"):
                    if key in row:
                        value=float(row.get(key,0));return _clamp(value/10 if value>100 else value)
        except (ValueError,FileNotFoundError):pass
        try:
            loc=self._location_record(target_ref)
            if isinstance(loc,Mapping):return _clamp(35+(20 if "fort" in str(loc.get("kind","")).lower() else 0))
        except Exception:pass
        return 40

    def _scheme_components(self,row:Mapping[str,Any])->tuple[dict[str,int],dict[str,int]]:
        agents=[str(x) for x in row.get("agent_refs",[]) if isinstance(x,str)];scores=[self._scheme_person_score(x) for x in agents]
        objective=str(row.get("objective"));relevant="intrigue"
        if objective in {"sabotage","gate_opening"}:relevant="engineering"
        elif objective in {"assassination","kidnapping","theft","prisoner_escape"}:relevant="stealth"
        elif objective in {"defection","bribery","blackmail","discrediting","revolt"}:relevant="diplomacy"
        capability=_clamp(sum((s.get("intrigue",0)+s.get(relevant,0))/2 for s in scores)/max(1,len(scores))) if scores else 0
        access_refs=row.get("access_refs",[]) if isinstance(row.get("access_refs"),list) else [];access=_clamp(15+18*len(access_refs));budget=max(0,int(row.get("remaining_budget_silver",0)));resources=_clamp(min(100,20+budget/500));security=self._scheme_target_security(str(row.get("target_ref","")));prep=_clamp(row.get("preparation",0));difficulty=_DIFFICULTY.get(objective,60);opposition=security
        progress={"access":access,"agent_capability":capability,"resources":resources,"target_vulnerability":_clamp(100-security),"preparation":prep,"difficulty":difficulty,"opposition":opposition}
        mean_intrigue=sum(s.get("intrigue",0) for s in scores)/max(1,len(scores)) if scores else 0
        exposure={"traces":_TRACE.get(objective,40),"witnesses":_clamp(20+5*len(agents)),"communication_risk":_clamp(10+8*max(0,len(agents)-1)),"suspicious_access":_clamp(70-access),"counterintelligence":security,"compartmentation":_clamp(70-10*max(0,len(agents)-1)),"cover":_clamp(mean_intrigue),"cleanup":_clamp(row.get("cleanup",0))}
        return progress,exposure

    @staticmethod
    def _scheme_scores(progress:Mapping[str,int],exposure:Mapping[str,int])->tuple[int,int]:
        ps=int(progress["access"]+progress["agent_capability"]+progress["resources"]+progress["target_vulnerability"]+progress["preparation"]-progress["difficulty"]-progress["opposition"])
        es=int(exposure["traces"]+exposure["witnesses"]+exposure["communication_risk"]+exposure["suspicious_access"]+exposure["counterintelligence"]-exposure["compartmentation"]-exposure["cover"]-exposure["cleanup"])
        return ps,es

    def _scheme_discovery(self,row:dict[str,Any],old:int,new:int,at:str)->None:
        for threshold,label in ((15,"investigable_trace"),(30,"probable_hostile_activity"),(50,"strong_exposure")):
            if old<threshold<=new and not any(isinstance(x,Mapping) and x.get("threshold")==threshold for x in row.setdefault("discoveries",[])):
                row["discoveries"].append({"at":at,"threshold":threshold,"scope":label,"known_by_ref":row.get("target_ref"),"rule":"exposure reveals only a bounded anomaly/method/agent link supported by this threshold, not omniscient sponsor truth"})
        if new>=30 and str(row.get("status"))=="active":row["status"]="exposed"

    def _scheme_terminal_effect(self,row:dict[str,Any],at:str)->dict[str,Any]:
        objective=str(row.get("objective"));target=str(row.get("target_ref",""));ref=str(row["owner_id"]);effect:dict[str,Any]={"kind":"opportunity_created","target_ref":target}
        if objective=="sabotage":
            if target.startswith("route_") and hasattr(self,"_mutate_crossing"):
                try:
                    self._mutate_crossing({"route_ref":target,"action":"damage_bridge","amount":25},at);effect={"kind":"strategic_crossing_damage","route_ref":target,"damage_percent":25}
                except ValueError:
                    effect={"kind":"sabotage_opportunity","target_ref":target,"rule":"route has no materialized bridge target; no damage invented"}
            elif target.startswith("loc_") and hasattr(self,"_siege_damage_fortified_site"):
                self._ensure_hot_fortified_site_resources(target,at=at,authority_ref=self._fortified_site_authority(target));self._siege_damage_fortified_site({"site_ref":target},damage_percent=15.0,target="magazine",at=at,cause=f"intrigue scheme {ref}");effect={"kind":"fortified_site_damage","site_ref":target,"damage_percent":15}
        elif objective=="prisoner_escape" and target.startswith("prisoners_"):
            try:p,g=self._custody_group(target);g["escape_risk_milli"]=min(1000,int(g.get("escape_risk_milli",0))+300);g.setdefault("history",[]).append({"at":at,"kind":"external_escape_scheme_completed","scheme_ref":ref});self.put(p,g);effect={"kind":"prisoner_escape_opening","prisoner_group_ref":target,"escape_risk_added_milli":300}
            except ValueError:pass
        elif objective in {"assassination","kidnapping"}:
            effect={"kind":"physical_contact_opportunity","target_ref":target,"required_next_resolution":"personal_combat_or_custody_action","rule":"scheme completion establishes access only; it never auto-kills or auto-kidnaps"}
        elif objective in {"defection","revolt","bribery","blackmail"}:
            effect={"kind":"decision_pressure_opportunity","target_ref":target,"required_next_resolution":"target_authority_decision","rule":"scheme pressure does not override agency or allegiance"}
        elif objective in {"forgery","misinformation","discrediting"}:
            effect={"kind":"claim_injection_opportunity","target_ref":target,"claim_status":"unverified_or_forged","rule":"scheme output may circulate a claim but never rewrites world truth"}
        elif objective=="gate_opening":
            effect={"kind":"gate_access_window","site_ref":target,"access_window_hours":6,"rule":"window must still be used by a physically present force before it expires"}
            try:
                depot_ref=self._ensure_hot_fortified_site_resources(target,at=at).get("depot_ref");dp=self.owner_path(str(depot_ref));depot=copy.deepcopy(self.read(dp));depot.setdefault("security_state",{})["gate_compromised_until"]=str(CampaignTime.parse(at).add_seconds(6*3600));depot["security_state"]["scheme_ref"]=ref;self.put(dp,depot)
            except Exception:pass
        row["terminal_effect"]=effect;return effect

    def _scheme_work(self,ref:str,*,at:str,hours:int=24)->dict[str,Any]:
        p,row=self._scheme(ref)
        if str(row.get("status")) not in {"active","exposed"}:raise ValueError("scheme is not active")
        progress,exposure=self._scheme_components(row);ps,es=self._scheme_scores(progress,exposure);old_exp=max(0,int(row.get("exposure_progress",0)));delta_p=max(0,min(30,ps//10 if ps>0 else 0));delta_e=max(0,min(25,es//12 if es>0 else 0));row["completed_progress"]=min(int(row.get("required_progress",100)),max(0,int(row.get("completed_progress",0)))+delta_p);row["exposure_progress"]=min(100,old_exp+delta_e);row["preparation"]=_clamp(int(row.get("preparation",0))+max(1,hours//8));row["last_step_components"]={"progress":progress,"exposure":exposure};row["last_progress_score"]=ps;row["last_exposure_score"]=es
        spend=min(max(0,int(row.get("remaining_budget_silver",0))),max(0,int(hours))*2)
        row["remaining_budget_silver"]=max(0,int(row.get("remaining_budget_silver",0))-spend);row["disbursed_silver"]=int(row.get("disbursed_silver",0))+spend
        row.setdefault("history",[]).append({"at":at,"kind":"work","hours":hours,"progress_delta":delta_p,"exposure_delta":delta_e,"progress_score":ps,"exposure_score":es,"disbursed_silver":spend});row["history"]=row["history"][-40:];self._scheme_discovery(row,old_exp,int(row["exposure_progress"]),at)
        if int(row["completed_progress"])>=int(row.get("required_progress",100)):
            row["status"]="completed";row["completed_at"]=at;self._scheme_terminal_effect(row,at)
        self.put(p,row);self._scheme_set_active(row);return row

    def _run_due_host(self,host:Mapping[str,Any],due_text:str)->None:
        if host.get("kind")=="intrigue_scheme":
            for ref in host.get("routed_scheme_refs",[]) if isinstance(host.get("routed_scheme_refs"),list) else []:
                try:_p,row=self._scheme(str(ref))
                except ValueError:continue
                if row.get("standing_work") is True and row.get("sponsor_ref")!=self.PLAYER_ACTOR and str(row.get("status")) in {"active","exposed"}:self._scheme_work(str(ref),at=due_text,hours=24)
            self._pending_wake_created=None;return
        super()._run_due_host(host,due_text)

    def _advance_runtime(self,target_text:str)->dict[str,Any]:
        if getattr(self, "_central_scheduler_reconciliation_active", False):
            return super()._advance_runtime(target_text)
        if self.read_optional(_INDEX):self._scheme_ensure_host()
        return super()._advance_runtime(target_text)

    def _validate_command_semantics(self,command:Any,payload:Mapping[str,Any])->None:
        super()._validate_command_semantics(command,payload)
        if command.command_type!="scheme_action":return
        action=str(payload.get("action",""))
        if action not in {"start","work","fund","cleanup","cancel"}:raise ValueError("unsupported scheme action")
        if action=="start":
            objective=str(payload.get("objective",""));
            if objective not in _OBJECTIVES:raise ValueError("unsupported scheme objective")
            agents=payload.get("agent_refs");
            if not isinstance(agents,list) or not agents or len(agents)>8:raise ValueError("scheme requires 1-8 exact agents")
            for ref in agents:self._exact_person(str(ref),active=False)
            target=str(payload.get("target_ref",""));
            if not target:raise ValueError("scheme requires target_ref")
            # Exact owner or exact location only.
            self._validate_scheme_reference(target)
            for ref in payload.get("access_refs",[]) if isinstance(payload.get("access_refs"),list) else []:self._validate_scheme_reference(str(ref))
            for ref in payload.get("tool_refs",[]) if isinstance(payload.get("tool_refs"),list) else []:self._validate_scheme_reference(str(ref),allow_route=False)
            budget=int(payload.get("budget_silver",0))
            if budget<0:raise ValueError("scheme budget cannot be negative")
        elif action=="fund":
            self._scheme(str(payload.get("scheme_ref","")))
            if int(payload.get("amount_silver",0))<=0:raise ValueError("scheme funding must be positive")
        else:self._scheme(str(payload.get("scheme_ref","")))

    def _authorize_command(self,command:Any,payload:Mapping[str,Any])->None:
        super()._authorize_command(command,payload)
        if command.command_type!="scheme_action" or command.actor_id==self.INTERNAL_ACTOR:return
        if str(payload.get("action"))=="start":
            agents=[str(x) for x in payload.get("agent_refs",[])];
            for ref in agents:self._require_interaction_authority(command.actor_id,ref) if hasattr(self,"_require_interaction_authority") else None
        else:
            _p,row=self._scheme(str(payload.get("scheme_ref","")))
            if str(row.get("sponsor_ref"))!=command.actor_id:raise PermissionError("only the exact scheme sponsor may direct this scheme")

    def _dispatch(self,command:Any,payload:Mapping[str,Any])->dict[str,Any]:
        if command.command_type!="scheme_action":return super()._dispatch(command,payload)
        action=str(payload["action"]);now=str(self._world_time())
        if action=="start":
            objective=str(payload["objective"]);target=str(payload["target_ref"]);agents=sorted(set(str(x) for x in payload["agent_refs"]));access=sorted(set(str(x) for x in payload.get("access_refs",[]) if isinstance(x,str)));budget=max(0,int(payload.get("budget_silver",0)));ref=str(payload.get("scheme_ref") or "scheme_"+hashlib.sha256(f"{command.actor_id}|{objective}|{target}|{now}".encode()).hexdigest()[:16]);p=_path(ref)
            if self.read_optional(p):raise ValueError("scheme_ref already exists")
            funding_source_ref=self._scheme_reserve_funds(str(command.actor_id),budget)
            row={"schema":"sword-intrigue-scheme","owner_id":ref,"objective":objective,"sponsor_ref":command.actor_id,"agent_refs":agents,"target_ref":target,"access_refs":access,"tool_refs":[str(x) for x in payload.get("tool_refs",[]) if isinstance(x,str)],"funding_source_ref":funding_source_ref,"remaining_budget_silver":budget,"disbursed_silver":0,"refunded_silver":0,"required_progress":100,"completed_progress":0,"exposure_progress":0,"preparation":10,"cleanup":0,"standing_work":bool(payload.get("standing_work",False)),"status":"active","created_at":now,"discoveries":[],"history":[{"at":now,"kind":"scheme_started","reserved_silver":budget,"funding_source_ref":funding_source_ref}],"rule":"progress, exposure, physical access, evidence and terminal effects are separate; scheme silver is exact reserved escrow until disbursed or refunded"};self.put(p,row);self._scheme_register(row,p);world,metrics=self._advance_seconds(3600);self._write_meta(command,world);return self._result(scheme_ref=ref,status="active",reserved_silver=budget,funding_source_ref=funding_source_ref,world_time=world,**metrics)
        p,row=self._scheme(str(payload["scheme_ref"]))
        if action=="work":row=self._scheme_work(str(row["owner_id"]),at=now,hours=max(1,min(168,int(payload.get("hours",24)))));p=_path(str(row["owner_id"]))
        elif action=="fund":
            amount=max(1,int(payload.get("amount_silver",0)));funding_source_ref=self._scheme_reserve_funds(str(row.get("sponsor_ref","")),amount);row["remaining_budget_silver"]=int(row.get("remaining_budget_silver",0))+amount;row.setdefault("history",[]).append({"at":now,"kind":"funded","amount_silver":amount,"funding_source_ref":funding_source_ref})
        elif action=="cleanup":row["cleanup"]=_clamp(int(row.get("cleanup",0))+max(1,int(payload.get("hours",8))));row.setdefault("history",[]).append({"at":now,"kind":"cleanup","hours":int(payload.get("hours",8))})
        elif action=="cancel":
            refunded=self._scheme_refund_funds(row,int(row.get("remaining_budget_silver",0)));row["status"]="cancelled";row["cancelled_at"]=now;row.setdefault("history",[]).append({"at":now,"kind":"cancelled","refunded_silver":refunded});self._scheme_set_active(row)
        self.put(p,row);world,metrics=self._advance_seconds(3600);self._write_meta(command,world);return self._result(scheme_ref=row["owner_id"],status=row.get("status"),completed_progress=row.get("completed_progress"),exposure_progress=row.get("exposure_progress"),terminal_effect=row.get("terminal_effect"),world_time=world,**metrics)
