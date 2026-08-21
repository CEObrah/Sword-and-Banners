"""Conserved surrender, prisoner custody, care, disposition, and escape.

Prisoner owners contain no invented bodies. Aggregate prisoners remain exact
cohort bodies of their source force, moved from a fighting formation into that
force's ``allocated_external_by_formation`` ledger under the prisoner-group ref.
Named prisoners keep their existing person owner and are linked, never cloned.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import (
    ensure_cohort_ledger,
    formation_materialized_assignments,
    transfer_between_forces,
    validate_cohort_ledger,
)
from sword_runtime.sim.calendar import CampaignTime

_INDEX = "state/custody/index.json"
_REVIEW_SECONDS = 86400


def _group_path(ref: str) -> str:
    if not isinstance(ref, str) or not ref.startswith("prisoners_") or any(x in ref for x in ("/", "\\", "..")):
        raise ValueError("invalid prisoner group ref")
    return f"state/custody/groups/{ref}.json"


def _stable_int(*parts: object, modulus: int = 10000) -> int:
    raw = "|".join(map(str, parts)).encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:16], 16) % max(1, modulus)


class PrisonerSystemMixin:
    def _custody_index(self) -> dict[str, Any]:
        row = self.read_optional(_INDEX)
        if not isinstance(row, Mapping):
            row = {"schema":"sword-prisoner-index","authority":False,"groups":{},"active_refs":[],"rule":"routing only; exact group files own aggregate custody state"}
        return copy.deepcopy(dict(row))

    def _custody_register(self, group: Mapping[str, Any], path: str) -> None:
        ref = str(group["owner_id"]); index = self._custody_index()
        index.setdefault("groups", {})[ref] = path
        active = index.setdefault("active_refs", [])
        if ref not in active: active.append(ref); active.sort()
        self.put(_INDEX, index); self._register_owner(ref, path)
        self._custody_ensure_review_host()

    def _custody_group(self, ref: str) -> tuple[str, dict[str, Any]]:
        index = self._custody_index(); path = index.get("groups", {}).get(ref)
        if not isinstance(path, str): path = _group_path(ref)
        row = self.read_optional(path)
        if not isinstance(row, Mapping): raise ValueError("unknown prisoner group")
        return path, copy.deepcopy(dict(row))

    def _custody_ensure_review_host(self) -> None:
        runtime = copy.deepcopy(self.read("state/runtime.json")); hosts=runtime.get("hosts"); events=runtime.get("events")
        if not isinstance(hosts,dict) or not isinstance(events,list): raise ValueError("runtime causal queue is invalid")
        index=self._custody_index(); refs=[str(x) for x in index.get("active_refs",[]) if isinstance(x,str)]
        host_id="host_prisoner_custody_review"; event_id="event_prisoner_custody_review"
        host=hosts.get(host_id); changed=False; now=CampaignTime.parse(str(runtime["world_time"]))
        # No prisoners means no daily custody clock. The exact custody index is the
        # wake-up authority: creating the first active group recreates this host.
        # Keeping an empty daily route makes long horizons expensive without
        # producing a single domain consequence.
        if not refs:
            if host_id in hosts:
                hosts.pop(host_id, None); changed=True
            filtered=[e for e in events if not (isinstance(e,Mapping) and (e.get("event_id")==event_id or e.get("target_host")==host_id))]
            if len(filtered)!=len(events): runtime["events"]=filtered; changed=True
            if changed:self.put("state/runtime.json",runtime)
            return
        if not isinstance(host,dict):
            due=now.add_seconds(_REVIEW_SECONDS); host={"kind":"prisoner_custody","owner_ref":"prisoner_custody_registry","routed_group_refs":refs,"recurrence_seconds":_REVIEW_SECONDS,"resolved_through":str(now),"next_due":str(due),"safe_through":str(due.add_seconds(-1))}; hosts[host_id]=host; changed=True
        elif host.get("routed_group_refs")!=refs: host["routed_group_refs"]=refs; changed=True
        if not any(isinstance(e,Mapping) and e.get("event_id")==event_id for e in events):
            events.append({"event_id":event_id,"kind":"prisoner_custody_review","priority":76,"target_host":host_id,"due_at":str(host["next_due"]) if host.get("next_due") else str(now.add_seconds(_REVIEW_SECONDS))}); changed=True
        if changed:self.put("state/runtime.json",runtime)

    @staticmethod
    def _custody_role_map(force: Mapping[str, Any], formation: Mapping[str, Any]) -> dict[str,int]:
        ledger=ensure_cohort_ledger(force); out:dict[str,int]={}
        for item in formation.get("cohort_composition",[]) if isinstance(formation,Mapping) else []:
            if not isinstance(item,Mapping):continue
            cohort=ledger.get("cohorts",{}).get(str(item.get("cohort_id")))
            if isinstance(cohort,Mapping):
                role=str(cohort.get("role","unknown")); out[role]=out.get(role,0)+max(0,int(item.get("count",0)))
        return out

    def _custody_detach_surrender(self, formation_ref: str, group_ref: str, count: int) -> tuple[str,dict[str,int],list[dict[str,Any]]]:
        fp,formation0=self._load_formation(formation_ref); formation=copy.deepcopy(formation0); force_ref=str(formation.get("owner_force_ref","")); force_path=self.owner_path(force_ref); force=copy.deepcopy(self.read(force_path)); ledger=ensure_cohort_ledger(force)
        anonymous=sum(max(0,int(x.get("count",0))) for x in formation.get("cohort_composition",[]) if isinstance(x,Mapping))
        take=min(max(0,int(count)),anonymous)
        if take<=0: raise ValueError("surrender requires anonymous fighting personnel")
        rows=[]; assigned=0
        items=[copy.deepcopy(dict(x)) for x in formation.get("cohort_composition",[]) if isinstance(x,Mapping) and int(x.get("count",0))>0]
        for item in items:
            n=int(item["count"]); exact=n*take/max(1,anonymous); base=min(n,int(math.floor(exact))); rows.append([str(item["cohort_id"]),n,base,exact-base]); assigned+=base
        rem=take-assigned; rows.sort(key=lambda r:(-r[3],_stable_int(group_ref,r[0])))
        for row in rows:
            if rem<=0:break
            if row[2]<row[1]:row[2]+=1;rem-=1
        by_role:dict[str,int]={}; slices=[]; survivors=[]
        for cid,n,moved,_frac in rows:
            cohort=ledger["cohorts"].get(cid)
            if not isinstance(cohort,MutableMapping):raise ValueError("surrender cohort route is invalid")
            held=max(0,int(cohort.setdefault("allocated_by_formation",{}).get(formation_ref,0)))
            if held<moved:raise ValueError("surrender exceeds exact formation cohort allocation")
            if moved:
                newheld=held-moved
                if newheld:cohort["allocated_by_formation"][formation_ref]=newheld
                else:cohort["allocated_by_formation"].pop(formation_ref,None)
                ext=cohort.setdefault("allocated_external_by_formation",{}); ext[group_ref]=int(ext.get(group_ref,0))+moved
                role=str(cohort.get("role","unknown")); by_role[role]=by_role.get(role,0)+moved; slices.append({"cohort_id":cid,"role":role,"count":moved})
            left=n-moved
            if left:survivors.append({"cohort_id":cid,"count":left})
        formation["cohort_composition"]=sorted(survivors,key=lambda x:x["cohort_id"]); formation["personnel"]=max(0,int(formation.get("personnel",0))-take)
        roles:dict[str,int]={}
        for item in formation["cohort_composition"]:
            cohort=ledger["cohorts"][str(item["cohort_id"])]; role=str(cohort.get("role","unknown"));roles[role]=roles.get(role,0)+int(item["count"])
        for a in formation_materialized_assignments(force,formation_ref).values():
            role=str(a.get("role","unknown"));roles[role]=roles.get(role,0)+max(1,int(a.get("personnel",1)))
        formation["composition"]={k:v for k,v in roles.items() if v>0}
        force.setdefault("allocated_to_formations",{})[formation_ref]={"personnel":int(formation["personnel"]),"composition":copy.deepcopy(formation["composition"])}
        force.setdefault("external_personnel_allocations",{})[group_ref]=copy.deepcopy(by_role)
        validate_cohort_ledger(force); self.put(fp,formation); self.put(force_path,force)
        return force_ref,by_role,slices

    def _custody_release_aggregate(self, group: MutableMapping[str,Any], *, status: str, at: str) -> int:
        n=max(0,int(group.get("personnel",0)))
        if n<=0:return 0
        force_ref=str(group.get("source_force_ref","")); fp=self.owner_path(force_ref); force=copy.deepcopy(self.read(fp)); ledger=ensure_cohort_ledger(force); loc=str(group.get("location_ref","")); released=0
        for row in group.get("cohort_slices",[]) if isinstance(group.get("cohort_slices"),list) else []:
            if not isinstance(row,Mapping):continue
            cid=str(row.get("cohort_id","")); requested=max(0,int(row.get("count",0))); cohort=ledger.get("cohorts",{}).get(cid)
            if not isinstance(cohort,MutableMapping):continue
            ext=cohort.setdefault("allocated_external_by_formation",{}); held=max(0,int(ext.get(str(group["owner_id"]),0))); give=min(requested,held)
            if not give:continue
            if held==give:ext.pop(str(group["owner_id"]),None)
            else:ext[str(group["owner_id"])]=held-give
            reserve=cohort.setdefault("reserve_by_location",{});reserve[loc]=int(reserve.get(loc,0))+give
            role=str(cohort.get("role","unknown"));force.setdefault("available_by_role",{})[role]=int(force.setdefault("available_by_role",{}).get(role,0))+give; local=force.setdefault("available_by_location",{}).setdefault(loc,{});local[role]=int(local.get(role,0))+give;released+=give
        force.setdefault("external_personnel_allocations",{}).pop(str(group["owner_id"]),None);validate_cohort_ledger(force);self.put(fp,force)
        group["personnel"]=max(0,n-released);group["status"]=status;group["released_at"]=at;group["legal_status"]=status
        return released

    def _custody_debit_population_deaths(self, force_ref: str, count: int) -> None:
        count=max(0,int(count))
        if not count:return
        force=self.read(self.owner_path(force_ref)); admin=str(force.get("administrative_owner","")) if isinstance(force,Mapping) else ""
        if force_ref.startswith("force_state_"):
            state=str(force.get("state", "")) if str(force.get("service_class", ""))=="state_levy" else force_ref.replace("force_state_","")
            state=state.replace("state_", "", 1)
            path=f"state/population/{state}.json"; pop=copy.deepcopy(self.read(path)); pop["strata"]["active_military"]=max(0,int(pop["strata"].get("active_military",0))-count); pop["population_total"]=max(0,int(pop.get("population_total",0))-count);self.put(path,pop)
        elif admin==self.PLAYER_ACTOR or admin.startswith("house_"):
            state="qin"
            if admin.startswith("house_"):
                h=self.read_optional(self.owner_path(admin));
                if isinstance(h,Mapping):state=self._state_key(h.get("state"))
            path=f"state/population/{state}.json";pop=copy.deepcopy(self.read(path));key="private_household_military";pop["strata"][key]=max(0,int(pop["strata"].get(key,0))-count);pop["population_total"]=max(0,int(pop.get("population_total",0))-count);self.put(path,pop)

    def _custody_kill_aggregate(self, group: MutableMapping[str,Any], count: int, *, at: str, reason: str) -> int:
        requested=min(max(0,int(count)),max(0,int(group.get("personnel",0))))
        if not requested:return 0
        force_ref=str(group.get("source_force_ref",""));fp=self.owner_path(force_ref);force=copy.deepcopy(self.read(fp)); remaining=requested;killed=0
        by_role=group.get("by_role",{}) if isinstance(group.get("by_role"),Mapping) else {}
        for role,held in sorted(by_role.items(),key=lambda x:(-int(x[1]),str(x[0]))):
            if remaining<=0:break
            take=min(remaining,max(0,int(held))); actual=self._kill_external_role_allocation(force,formation_ref=str(group["owner_id"]),role=str(role),losses=take,evidence_ref=f"{group['owner_id']}:{reason}:{at}");by_role[role]=max(0,int(held)-actual);remaining-=actual;killed+=actual
        group["by_role"]={k:int(v) for k,v in by_role.items() if int(v)>0};group["personnel"]=max(0,int(group.get("personnel",0))-killed);group.setdefault("death_history",[]).append({"at":at,"count":killed,"reason":reason});group["death_history"]=group["death_history"][-24:];self.put(fp,force);self._custody_debit_population_deaths(force_ref,killed);return killed

    def _custody_new_group(self, *, source_formation_ref: str, custodian_formation_ref: str, count: int, at: str, terms: str = "unconditional_surrender") -> dict[str,Any]:
        _cp,custodian=self._load_formation(custodian_formation_ref); sp,source0=self._load_formation(source_formation_ref); source=copy.deepcopy(source0)
        if str(source.get("location_ref"))!=str(custodian.get("location_ref")):raise ValueError("surrender requires exact co-location")
        if str(source.get("owner_force_ref","")) == str(custodian.get("owner_force_ref","")):
            raise ValueError("a formation cannot surrender into custody of its own force")
        offer=source.get("surrender_state") if isinstance(source.get("surrender_state"),Mapping) else {}
        if str(offer.get("status",""))!="offered" or str(offer.get("offered_to_formation_ref",""))!=custodian_formation_ref:
            raise ValueError("aggregate surrender requires an exact active surrender offer")
        offered=max(0,int(offer.get("offered_personnel",0)))
        if int(count)>offered:raise ValueError("accepted surrender exceeds offered personnel")
        ref="prisoners_"+hashlib.sha256(f"{source_formation_ref}|{custodian_formation_ref}|{at}|{count}".encode()).hexdigest()[:16]
        source_force,by_role,slices=self._custody_detach_surrender(source_formation_ref,ref,count)
        n=sum(by_role.values()); req=(n+4)//5
        group={"schema":"sword-prisoner-group","owner_id":ref,"source_formation_ref":source_formation_ref,"source_force_ref":source_force,"custodian_formation_ref":custodian_formation_ref,"captor_authority_ref":str(custodian.get("administrative_owner") or custodian.get("command_authority") or custodian.get("owner_force_ref")),"location_ref":str(source.get("location_ref")),"personnel":n,"by_role":by_role,"cohort_slices":slices,"named_prisoner_refs":[],"guards_allocated":0,"guard_requirement":req,"restraint_condition_milli":700,"enclosure_condition_milli":650,"health_milli":900,"food_kg":0,"water_person_days":0,"legal_status":"prisoner_of_war","status":"held","surrender_terms":terms,"captured_at":at,"history":[{"at":at,"kind":"aggregate_surrender","personnel":n,"source_formation_ref":source_formation_ref}]}
        path=_group_path(ref);self.put(path,group);self._custody_register(group,path)
        # The source formation offered these exact bodies before the custody transfer.
        sp2,source_after=self._load_formation(source_formation_ref);source_after=copy.deepcopy(source_after);state=source_after.setdefault("surrender_state",{});state["status"]="accepted";state["accepted_personnel"]=n;state["accepted_at"]=at;state["prisoner_group_ref"]=ref;self.put(sp2,source_after)
        return group

    def _custody_attach_named_capture(self, person_ref: str, custodian_formation_ref: str, battle_ref: str, at: str) -> str:
        _cp,custodian=self._load_formation(custodian_formation_ref); loc=str(custodian.get("location_ref","")); authority=str(custodian.get("administrative_owner") or custodian.get("command_authority") or custodian.get("owner_force_ref"))
        ref="prisoners_named_"+hashlib.sha256(f"{battle_ref}|{custodian_formation_ref}".encode()).hexdigest()[:16]; path=_group_path(ref); existing=self.read_optional(path)
        group=copy.deepcopy(dict(existing)) if isinstance(existing,Mapping) else {"schema":"sword-prisoner-group","owner_id":ref,"source_formation_ref":None,"source_force_ref":None,"custodian_formation_ref":custodian_formation_ref,"captor_authority_ref":authority,"location_ref":loc,"personnel":0,"by_role":{},"cohort_slices":[],"named_prisoner_refs":[],"guards_allocated":0,"guard_requirement":0,"restraint_condition_milli":650,"enclosure_condition_milli":650,"health_milli":900,"food_kg":0,"water_person_days":0,"legal_status":"prisoner_of_war","status":"held","captured_at":at,"history":[]}
        refs=group.setdefault("named_prisoner_refs",[])
        if person_ref not in refs:refs.append(person_ref);refs.sort();group["guard_requirement"]=(int(group.get("personnel",0))+len(refs)+4)//5;group.setdefault("history",[]).append({"at":at,"kind":"named_capture","person_ref":person_ref,"battle_ref":battle_ref})
        pp,person0=self._exact_person(person_ref,active=False);person=copy.deepcopy(person0);person["custody_state"]={"status":"prisoner","prisoner_group_ref":ref,"captured_at":at,"captured_by":authority,"location_ref":loc,"battle_ref":battle_ref};self.put(pp,person);self.put(path,group);self._custody_register(group,path);return ref

    def _custody_mark_surrender_opportunity(self, loser_ref: str, winner_ref: str, battle_ref: str, at: str) -> dict[str,Any] | None:
        fp,formation0=self._load_formation(loser_ref);formation=copy.deepcopy(formation0);anonymous=sum(max(0,int(x.get("count",0))) for x in formation.get("cohort_composition",[]) if isinstance(x,Mapping))
        if anonymous<=0:return None
        morale=max(0,int(formation.get("morale",50)));cohesion=max(0,int(formation.get("cohesion",50)))
        if morale>28 and cohesion>22:return None
        collapse=max(0,60-min(morale,cohesion));fraction=min(1.0,max(0.25,collapse/60.0));offered=max(1,min(anonymous,int(math.floor(anonymous*fraction))))
        state={"status":"offered","offered_to_formation_ref":winner_ref,"offered_personnel":offered,"battle_ref":battle_ref,"offered_at":at,"terms":"request_terms","rule":"offer is an autonomous losing-formation decision; accepting it transfers only the exact offered living bodies"};formation["surrender_state"]=state;self.put(fp,formation);return {"formation_ref":loser_ref,**state}

    def _custody_force_authority(self, force_ref: str) -> str:
        force=self.read(self.owner_path(force_ref))
        return str(force.get("administrative_owner") or force.get("command_authority") or force_ref)

    def _custody_authority_treasury(self, authority_ref: str) -> tuple[str,dict[str,Any],str]:
        authority_ref=str(authority_ref)
        if authority_ref.startswith("state_"):
            p=self.owner_path(authority_ref);d=copy.deepcopy(self.read(p));return p,d,"treasury_silver"
        if authority_ref=="house_tang":
            p=self.owner_path("treasury_house_tang");d=copy.deepcopy(self.read(p));return p,d,"silver"
        if authority_ref==str(self.PLAYER_ACTOR):
            p=self.owner_path(f"wallet_{self.PLAYER_ACTOR}");d=copy.deepcopy(self.read(p));return p,d,"silver"
        if authority_ref.startswith("polity_") and hasattr(self,"_sovereign_treasury"):
            return self._sovereign_treasury(authority_ref)
        try:
            p,d=self.owner(authority_ref);d=copy.deepcopy(d)
        except (ValueError,KeyError,FileNotFoundError):
            raise ValueError("custody authority lacks an exact treasury")
        tref=str(d.get("treasury_ref", "")) if isinstance(d,Mapping) else ""
        if tref:
            tp=self.owner_path(tref);td=copy.deepcopy(self.read(tp));key="treasury_silver" if "treasury_silver" in td else "silver";return tp,td,key
        raise ValueError("custody authority lacks an exact treasury")

    def _custody_transfer_silver(self, payer_ref: str, payee_ref: str, amount: int, *, at: str, reason: str) -> None:
        amount=max(0,int(amount))
        if not amount:return
        pp,payer,pkey=self._custody_authority_treasury(payer_ref);qp,payee,qkey=self._custody_authority_treasury(payee_ref)
        if pp==qp:raise ValueError("custody settlement payer and payee cannot be the same treasury")
        if int(payer.get(pkey,0))<amount:raise ValueError("custody settlement payer has insufficient silver")
        payer[pkey]=int(payer.get(pkey,0))-amount;payee[qkey]=int(payee.get(qkey,0))+amount
        payer.setdefault("custody_settlements",[]).append({"at":at,"reason":reason,"counterparty_ref":payee_ref,"silver":-amount});payer["custody_settlements"]=payer["custody_settlements"][-32:]
        payee.setdefault("custody_settlements",[]).append({"at":at,"reason":reason,"counterparty_ref":payer_ref,"silver":amount});payee["custody_settlements"]=payee["custody_settlements"][-32:]
        self.put(pp,payer);self.put(qp,payee)

    def _custody_population_binding(self, force_ref: str) -> tuple[str,str]:
        force=self.read(self.owner_path(force_ref));admin=str(force.get("administrative_owner", ""))
        if force_ref.startswith("force_state_"):
            if str(force.get("service_class", "")) == "state_levy":
                return str(force.get("state", "")).removeprefix("state_"),"active_military"
            return force_ref.removeprefix("force_state_"),"active_military"
        if admin.startswith("state_"):
            return admin.removeprefix("state_"),"active_military"
        # House Tang and Wei's personal military establishment are physically part
        # of the Qin demographic ledger while remaining separate military owners.
        if admin=="house_tang" or admin==str(self.PLAYER_ACTOR) or force_ref.startswith("force_house_tang") or force_ref.startswith("force_tang_wei"):
            return "qin","private_household_military"
        raise ValueError("force lacks a demographic binding for prisoner recruitment")

    def _custody_transfer_population_affiliation(self, source_force_ref: str, destination_force_ref: str, count: int) -> None:
        count=max(0,int(count))
        if not count:return
        src_state,src_key=self._custody_population_binding(source_force_ref);dst_state,dst_key=self._custody_population_binding(destination_force_ref)
        sp=f"state/population/{src_state}.json";dp=f"state/population/{dst_state}.json";src=copy.deepcopy(self.read(sp));dst=src if sp==dp else copy.deepcopy(self.read(dp))
        if int(src.get("strata",{}).get(src_key,0))<count:raise ValueError("source demographic military stratum lacks recruited prisoner bodies")
        src.setdefault("strata",{})[src_key]=int(src["strata"].get(src_key,0))-count
        dst.setdefault("strata",{})[dst_key]=int(dst["strata"].get(dst_key,0))+count
        if sp!=dp:
            src["population_total"]=max(0,int(src.get("population_total",0))-count);dst["population_total"]=int(dst.get("population_total",0))+count;self.put(dp,dst)
        self.put(sp,src)

    def _custody_finalize_recruitment(self, group: MutableMapping[str,Any], destination_force_ref: str, *, at: str) -> int:
        if str((group.get("recruitment_offer") or {}).get("status"))!="accepted":raise ValueError("prisoner recruitment requires an autonomous accepted offer")
        total=max(0,int(group.get("personnel",0)))
        if total<=0:raise ValueError("prisoner group has no aggregate personnel to recruit")
        loc=str(group.get("location_ref",""));source_force_ref=str(group.get("source_force_ref",""));roles=copy.deepcopy(dict(group.get("by_role",{})))
        released=self._custody_release_aggregate(group,status="recruitment_transfer",at=at)
        if released!=total:raise ValueError("prisoner recruitment release did not conserve the full aggregate group")
        sp=self.owner_path(source_force_ref);dp=self.owner_path(destination_force_ref);source=copy.deepcopy(self.read(sp));dest=copy.deepcopy(self.read(dp));moved=0
        for role,count in sorted(roles.items()):
            n=max(0,int(count))
            if not n:continue
            moved+=transfer_between_forces(source,dest,source_role=str(role),destination_role=str(role),count=n,source_location_ref=loc,destination_location_ref=loc,evidence_ref=f"{group['owner_id']}:voluntary_recruitment:{at}")
        if moved!=total:raise ValueError("cross-force prisoner recruitment failed exact role conservation")
        self._custody_transfer_population_affiliation(source_force_ref,destination_force_ref,total)
        self.put(sp,source);self.put(dp,dest);group["status"]="recruited";group["legal_status"]="voluntary_new_service";group["recruited_at"]=at;group["recruitment_destination_force_ref"]=destination_force_ref;group["personnel"]=0;group["by_role"]={};group["cohort_slices"]=[];self._custody_clear_guard_duty(group);group["guards_allocated"]=0
        return moved

    def _custody_testimony(self, group: Mapping[str,Any], topic_ref: str, statement: str, *, at: str, knower_ref: str) -> str:
        topic_ref=str(topic_ref);statement=str(statement or f"Prisoner testimony concerning {topic_ref}")[:2000]
        # Topic must be an exact owner or location. Testimony itself is never world truth.
        try:self.owner(topic_ref)
        except (ValueError,KeyError,FileNotFoundError):self._location_record(topic_ref)
        ref="info_prisoner_testimony_"+hashlib.sha256(f"{group.get('owner_id')}|{topic_ref}|{at}|{statement}".encode()).hexdigest()[:16];path=f"state/information/{ref}.json";idx=copy.deepcopy(self.read("state/information/index.json"));confidence=max(150,min(650,250+int(group.get("health_milli",500))//5-int(group.get("escape_risk_milli",0))//10))
        doc={"schema":"sword-information","owner_id":ref,"information_ref":ref,"subject_ref":topic_ref,"fact":statement,"claim":statement,"epistemic_kind":"prisoner_testimony","confidence_milli":confidence,"confidence":f"{confidence/1000:.3f}","provenance":str(group.get("owner_id")),"evidence_refs":[str(group.get("owner_id"))],"classification":"custody_intelligence","location_ref":group.get("location_ref"),"discoverability_milli":400,"investigation_discoverable":True,"origin_authority":"runtime_testimony","world_truth_authority":False,"claim_status":"unverified_prisoner_testimony","knowers":[knower_ref],"holder_states":{knower_ref:{"epistemic_kind":"testimony","confidence_milli":confidence,"source_ref":str(group.get("owner_id")),"learned_at":at}},"deliveries":[],"created_at":at}
        self.put(path,doc);idx.setdefault("claims",{})[ref]=path;refs=idx.setdefault("by_holder",{}).setdefault(knower_ref,[])
        if ref not in refs:refs.append(ref)
        self.put("state/information/index.json",idx);self._register_owner(ref,path);return ref

    def _custody_set_active(self, group: Mapping[str,Any]) -> None:
        index=self._custody_index();active=index.setdefault("active_refs",[]);ref=str(group.get("owner_id",""));is_active=str(group.get("status","")) in {"held","in_transit"} and (int(group.get("personnel",0))>0 or bool(group.get("named_prisoner_refs")))
        if is_active and ref not in active:active.append(ref);active.sort()
        if not is_active and ref in active:active.remove(ref)
        self.put(_INDEX,index)

    def _battle(self, command: Any, payload: Mapping[str,Any], *, context: Mapping[str,Any] | None = None) -> dict[str,Any]:
        result=super()._battle(command,payload,context=context)
        outcomes=result.get("named_person_outcomes",{}) if isinstance(result,Mapping) else {}; attackers=[str(x) for x in payload.get("attacker_formation_refs",[])];defenders=[str(x) for x in payload.get("defender_formation_refs",[])]
        result_time = str(result.get("world_time")) if isinstance(result, Mapping) and result.get("world_time") else str(self._world_time())
        attacker_won=str(result.get("winner"))=="attacker";custodian=(attackers[0] if attacker_won else defenders[0]) if attackers and defenders else None; groups=[]
        if custodian:
            for person_ref,row in outcomes.items():
                if isinstance(row,Mapping) and row.get("outcome")=="captured":groups.append(self._custody_attach_named_capture(str(person_ref),custodian,str(result.get("battle_event","battle")),result_time))
        offers=[]
        losers=defenders if attacker_won else attackers
        if custodian:
            for loser_ref in losers:
                offer=self._custody_mark_surrender_opportunity(loser_ref,custodian,str(result.get("battle_event","battle")),result_time)
                if offer:offers.append(offer)
        if groups or offers:result=dict(result)
        if groups:result["prisoner_group_refs"]=sorted(set(groups))
        if offers:result["surrender_offers"]=offers
        return result

    def _custody_set_guard_duty(self, group: Mapping[str,Any], guards: int) -> int:
        custodian_ref=str(group.get("custodian_formation_ref",""));fp,f0=self._load_formation(custodian_ref);formation=copy.deepcopy(f0);guards=min(max(0,int(guards)),max(0,int(formation.get("personnel",0))))
        duties=formation.setdefault("custody_guard_allocations",{});ref=str(group.get("owner_id",""))
        if guards:duties[ref]=guards
        else:duties.pop(ref,None)
        formation["custody_guard_duty_personnel"]=sum(max(0,int(v)) for v in duties.values());formation["custody_guard_rule"]="existing formation personnel on guard duty; these bodies are not additional troops";self.put(fp,formation);return guards

    def _custody_clear_guard_duty(self, group: Mapping[str,Any]) -> None:
        try:self._custody_set_guard_duty(group,0)
        except (ValueError,FileNotFoundError):pass

    def _custody_daily_review(self, group_ref: str, at: str) -> None:
        path,group=self._custody_group(group_ref)
        if str(group.get("status")) not in {"held","in_transit"}:return
        total=max(0,int(group.get("personnel",0)))+len(group.get("named_prisoner_refs",[]) if isinstance(group.get("named_prisoner_refs"),list) else [])
        if total<=0:group["status"]="empty";self.put(path,group);return
        food_need=2*total;water_need=total;food=min(food_need,max(0,int(group.get("food_kg",0))));water=min(water_need,max(0,int(group.get("water_person_days",0))));group["food_kg"]=max(0,int(group.get("food_kg",0))-food);group["water_person_days"]=max(0,int(group.get("water_person_days",0))-water)
        guard=max(0,int(group.get("guards_allocated",0)));required=max(1,(total+4)//5);group["guard_requirement"]=required
        shortage=max((food_need-food)/max(1,food_need),(water_need-water)/max(1,water_need));health=max(0,int(group.get("health_milli",900))-int(round(shortage*90)));group["health_milli"]=health
        deaths=0
        if shortage>0.5 and int(group.get("personnel",0))>0:deaths=max(0,int(math.floor(int(group["personnel"])*min(0.02,0.002+shortage*0.006))))
        if deaths:self._custody_kill_aggregate(group,deaths,at=at,reason="custody_deprivation")
        escape_pressure=max(0,required-guard)*120+max(0,500-int(group.get("restraint_condition_milli",650)))+max(0,500-int(group.get("enclosure_condition_milli",650)))
        group["escape_risk_milli"]=min(1000,escape_pressure);group.setdefault("care_history",[]).append({"at":at,"food_consumed_kg":food,"water_person_days_consumed":water,"guards":guard,"required_guards":required,"health_milli":health,"deaths":deaths});group["care_history"]=group["care_history"][-30:]
        offer=group.get("recruitment_offer") if isinstance(group.get("recruitment_offer"),Mapping) else None
        if isinstance(offer,dict) and str(offer.get("status"))=="offered" and CampaignTime.parse(at)>=CampaignTime.parse(str(offer.get("review_at",at))):
            try:_fp,source=self._load_formation(str(group.get("source_formation_ref","")))
            except (ValueError,FileNotFoundError):source={}
            morale=max(0,int(source.get("morale",30))) if isinstance(source,Mapping) else 30;cohesion=max(0,int(source.get("cohesion",30))) if isinstance(source,Mapping) else 30;loyalty=source.get("military_loyalty_state") if isinstance(source,Mapping) and isinstance(source.get("military_loyalty_state"),Mapping) else {};axes=loyalty.get("axes",{}) if isinstance(loyalty,Mapping) else {};identity=max(0,int(axes.get("formation_identity",500)));disaffection=max(0,int(axes.get("disaffection",180)));willing=max(20,min(780,120+max(0,35-morale)*9+max(0,35-cohesion)*7+disaffection//2-identity//3+(80 if health>=750 else -80)));roll=_stable_int(group.get("owner_id"),offer.get("destination_force_ref"),offer.get("offered_at"),"recruitment",modulus=1000);offer["decision_roll_milli"]=roll;offer["willingness_milli"]=willing;offer["decided_at"]=at;offer["status"]="accepted" if roll<willing else "refused";offer["decision_rule"]="aggregate prisoner cohort decides from saved surrender/custody conditions and source formation loyalty; captor cannot force acceptance"
        self.put(path,group)

    def _run_due_host(self, host: Mapping[str,Any], due_text: str) -> None:
        if host.get("kind")=="prisoner_custody":
            for ref in host.get("routed_group_refs",[]) if isinstance(host.get("routed_group_refs"),list) else []:
                if isinstance(ref,str):self._custody_daily_review(ref,due_text)
            self._pending_wake_created=None;return
        super()._run_due_host(host,due_text)

    def _advance_runtime(self,target_text:str)->dict[str,Any]:
        if getattr(self, "_central_scheduler_reconciliation_active", False):
            return super()._advance_runtime(target_text)
        if self.read_optional(_INDEX):self._custody_ensure_review_host()
        return super()._advance_runtime(target_text)

    def _validate_command_semantics(self, command: Any, payload: Mapping[str,Any]) -> None:
        super()._validate_command_semantics(command,payload)
        if command.command_type=="siege_action" and str(payload.get("action","")) in {"offer_surrender","accept_surrender_terms"}:
            ref=str(payload.get("siege_ref",""));idx=self.read("state/sieges/index.json");path=idx.get("sieges",{}).get(ref)
            if not path:raise ValueError("unknown siege")
            siege=self.read(path)
            if str(siege.get("status"))!="active":raise ValueError("siege surrender negotiation requires an active siege")
            if str(payload.get("action"))=="offer_surrender":
                source=str(payload.get("source_formation_ref",""));self._load_formation(source)
                if source not in [str(x) for x in siege.get("defender_formation_refs",[])]:raise ValueError("siege surrender offer must come from an exact defender formation")
            return
        if command.command_type!="custody_action":return
        action=str(payload.get("action",""));allowed={"accept_surrender","allocate_guards","provision","transfer_custodian","release","parole","execute","escape_attempt","set_ransom","accept_ransom","propose_exchange","accept_exchange","interrogate","offer_recruitment","finalize_recruitment"}
        if action not in allowed:raise ValueError("unsupported custody action")
        if action=="accept_surrender":
            src=str(payload.get("source_formation_ref",""));dst=str(payload.get("custodian_formation_ref",""));self._load_formation(src);self._load_formation(dst);count=int(payload.get("personnel",0));
            if count<=0:raise ValueError("surrender personnel must be positive")
        else:
            self._custody_group(str(payload.get("prisoner_group_ref","")))
            if action in {"set_ransom"} and int(payload.get("amount_silver",0))<=0:raise ValueError("ransom amount must be positive")
            if action in {"propose_exchange","accept_exchange"}:self._custody_group(str(payload.get("other_prisoner_group_ref","")))
            if action=="interrogate" and not str(payload.get("topic_ref","")):raise ValueError("interrogation requires exact topic_ref")
            if action in {"offer_recruitment","finalize_recruitment"}:self.read(self.owner_path(str(payload.get("destination_force_ref",""))))

    def _authorize_command(self, command: Any, payload: Mapping[str,Any]) -> None:
        super()._authorize_command(command,payload)
        if command.command_type=="siege_action" and str(payload.get("action","")) in {"offer_surrender","accept_surrender_terms"}:
            if command.actor_id==self.INTERNAL_ACTOR:return
            ref=str(payload.get("siege_ref",""));path=self.read("state/sieges/index.json").get("sieges",{}).get(ref);siege=self.read(path) if path else {}
            if str(payload.get("action"))=="offer_surrender":self._require_formation_authority(command.actor_id,str(payload.get("source_formation_ref","")))
            else:
                attackers=[str(x) for x in siege.get("attacker_formation_refs",[])]
                if not any(self._has_formation_authority(command.actor_id,x) for x in attackers):raise PermissionError("only an exact attacking authority may accept siege surrender terms")
            return
        if command.command_type!="custody_action" or command.actor_id==self.INTERNAL_ACTOR:return
        action=str(payload.get("action",""))
        if action=="accept_surrender":self._require_formation_authority(command.actor_id,str(payload.get("custodian_formation_ref","")))
        else:
            _p,g=self._custody_group(str(payload.get("prisoner_group_ref","")));cust=str(g.get("custodian_formation_ref",""))
            if action=="accept_ransom":
                source_auth=self._custody_force_authority(str(g.get("source_force_ref","")))
                if command.actor_id!=source_auth and not (source_auth=="house_tang" and command.actor_id==self.PLAYER_ACTOR):raise PermissionError("only the source authority may accept its prisoners' ransom")
            elif action=="accept_exchange":
                _op,other=self._custody_group(str(payload.get("other_prisoner_group_ref","")));self._require_formation_authority(command.actor_id,str(other.get("custodian_formation_ref","")))
            else:self._require_formation_authority(command.actor_id,cust)
            if action=="provision":
                depot_ref=str(payload.get("depot_ref",""));depot=self.read(self.owner_path(depot_ref));state=str(depot.get("state","")) if isinstance(depot,Mapping) else ""
                if command.actor_id==self.PLAYER_ACTOR and state not in {"house_tang",str(self.PLAYER_ACTOR)}:
                    raise PermissionError("player custody provisioning may draw only from an exact House/player depot")

    def _dispatch(self, command: Any, payload: Mapping[str,Any]) -> dict[str,Any]:
        if command.command_type=="siege_action" and str(payload.get("action","")) in {"offer_surrender","accept_surrender_terms"}:
            action=str(payload.get("action"));ref=str(payload.get("siege_ref",""));idxp="state/sieges/index.json";idx=copy.deepcopy(self.read(idxp));path=idx.get("sieges",{}).get(ref)
            if not path:raise ValueError("unknown siege")
            siege=copy.deepcopy(self.read(path));now=str(self._world_time())
            if action=="offer_surrender":
                source_ref=str(payload.get("source_formation_ref",""));_sp,source=self._load_formation(source_ref);attackers=[str(x) for x in siege.get("attacker_formation_refs",[])]
                if not attackers:raise ValueError("siege has no exact attacking formation to receive surrender")
                custodian=attackers[0];anonymous=sum(max(0,int(x.get("count",0))) for x in source.get("cohort_composition",[]) if isinstance(x,Mapping))
                if anonymous<=0:raise ValueError("defender formation has no anonymous garrison personnel to surrender")
                terms=str(payload.get("terms","prisoner_of_war"));offer={"status":"offered","source_formation_ref":source_ref,"custodian_formation_ref":custodian,"personnel":anonymous,"terms":terms,"offered_at":now,"offered_by_ref":command.actor_id};siege["surrender_offer"]=offer
                sp,source2=self._load_formation(source_ref);source2=copy.deepcopy(source2);source2["surrender_state"]={"status":"offered","offered_to_formation_ref":custodian,"offered_personnel":anonymous,"battle_ref":ref,"offered_at":now,"terms":terms,"rule":"siege defender offers exact surviving anonymous garrison bodies; acceptance is a separate attacker decision"};self.put(sp,source2);self.put(path,siege);world,metrics=self._advance_seconds(1800);self._write_meta(command,world);return self._result(siege_ref=ref,status=siege.get("status"),surrender_offer=offer,world_time=world,**metrics)
            offer=siege.get("surrender_offer") if isinstance(siege.get("surrender_offer"),Mapping) else {}
            if str(offer.get("status"))!="offered":raise ValueError("siege has no active surrender offer")
            group=self._custody_new_group(source_formation_ref=str(offer["source_formation_ref"]),custodian_formation_ref=str(offer["custodian_formation_ref"]),count=int(offer["personnel"]),at=now,terms=str(offer.get("terms","prisoner_of_war")))
            if str(offer.get("terms")) in {"parole","safe_conduct_parole"}:
                self._custody_release_aggregate(group,status="paroled",at=now);gp=_group_path(str(group["owner_id"]));self.put(gp,group);self._custody_set_active(group)
            sp,source=self._load_formation(str(offer["source_formation_ref"]));source=copy.deepcopy(source);source["status"]="surrendered";source["mobilized"]=False;source.setdefault("surrender_state",{})["status"]="accepted";self.put(sp,source)
            offer=dict(offer);offer["status"]="accepted";offer["accepted_at"]=now;offer["prisoner_group_ref"]=group["owner_id"];siege["surrender_offer"]=offer;siege.setdefault("surrendered_defender_refs",[]).append(str(offer["source_formation_ref"]));siege["surrendered_defender_refs"]=sorted(set(siege["surrendered_defender_refs"]))
            remaining=[]
            for dref in siege.get("defender_formation_refs",[]):
                try:_fp,df=self._load_formation(str(dref))
                except ValueError:continue
                if str(df.get("status"))!="surrendered" and int(df.get("personnel",0))>0:remaining.append(str(dref))
            if not remaining:siege["status"]="captured";siege["outcome"]="attacker_control_by_surrender";siege["captured_at"]=now
            self.put(path,siege);world,metrics=self._advance_seconds(1800);self._write_meta(command,world);return self._result(siege_ref=ref,status=siege.get("status"),prisoner_group_ref=group["owner_id"],surrender_terms=offer.get("terms"),world_time=world,**metrics)
        if command.command_type!="custody_action":
            result=super()._dispatch(command,payload)
            moved_refs:set[str]=set()
            if command.command_type=="formation_move" and isinstance(payload.get("formation_ref"),str):moved_refs.add(str(payload["formation_ref"]))
            if command.command_type=="command_group_action" and str(payload.get("action",""))=="move_army":
                # Exact active custody groups are few and explicitly routed; only sync
                # groups whose custodian formation actually changed location.
                moved_refs=set(str(x) for x in self._custody_index().get("active_refs",[]))  # sentinel to enter bounded sync below
            if moved_refs:
                index=self._custody_index()
                for ref in list(index.get("active_refs",[])):
                    try:path,g=self._custody_group(str(ref));cust_ref=str(g.get("custodian_formation_ref",""));_fp,cust=self._load_formation(cust_ref)
                    except (ValueError,FileNotFoundError):continue
                    if command.command_type=="formation_move" and cust_ref not in moved_refs:continue
                    loc=str(cust.get("location_ref",""))
                    if loc and loc!=str(g.get("location_ref","")):
                        g["location_ref"]=loc;g.setdefault("history",[]).append({"at":str(self._world_time()),"kind":"custodian_movement","custodian_formation_ref":cust_ref,"location_ref":loc});self.put(path,g)
            return result
        action=str(payload["action"]);now=str(self._world_time())
        if action=="accept_surrender":
            group=self._custody_new_group(source_formation_ref=str(payload["source_formation_ref"]),custodian_formation_ref=str(payload["custodian_formation_ref"]),count=int(payload["personnel"]),at=now,terms=str(payload.get("terms","unconditional_surrender")));world,metrics=self._advance_seconds(1800);self._write_meta(command,world);return self._result(prisoner_group_ref=group["owner_id"],personnel=group["personnel"],world_time=world,**metrics)
        path,group=self._custody_group(str(payload["prisoner_group_ref"]))
        if action=="allocate_guards":
            n=self._custody_set_guard_duty(group,max(0,int(payload.get("guards",0))));group["guards_allocated"]=n;group["guard_allocation_rule"]="duty allocation from existing custodian formation personnel; no extra guards created"
        elif action=="provision":
            depot_ref=str(payload.get("depot_ref") or "");dp=self.owner_path(depot_ref);depot=copy.deepcopy(self.read(dp));stocks=depot.setdefault("stocks",{});food=min(max(0,int(payload.get("food_kg",0))),max(0,int(stocks.get("grain_kg",0))))
            water_request=max(0,int(payload.get("water_person_days",0)));water_state=depot.get("water_reserve") if isinstance(depot.get("water_reserve"),Mapping) else None
            if isinstance(water_state,Mapping):
                water_state=dict(water_state);available_water=max(0,int(water_state.get("current_person_days",0)));water=min(water_request,available_water);water_state["current_person_days"]=available_water-water;depot["water_reserve"]=water_state
            else:
                available_water=max(0,int(depot.get("water_reserve_person_days",0)));water=min(water_request,available_water);depot["water_reserve_person_days"]=available_water-water
            stocks["grain_kg"]=int(stocks.get("grain_kg",0))-food;group["food_kg"]=int(group.get("food_kg",0))+food;group["water_person_days"]=int(group.get("water_person_days",0))+water;self.put(dp,depot)
        elif action=="transfer_custodian":
            new_ref=str(payload.get("custodian_formation_ref",""));_nfp,new_cust=self._load_formation(new_ref);old_ref=str(group.get("custodian_formation_ref",""));_ofp,old_cust=self._load_formation(old_ref)
            if str(new_cust.get("location_ref",""))!=str(group.get("location_ref","")) or str(old_cust.get("location_ref",""))!=str(group.get("location_ref","")):
                raise ValueError("custody transfer requires both custodian formations and prisoners co-located")
            if str(new_cust.get("administrative_owner") or new_cust.get("owner_force_ref"))!=str(old_cust.get("administrative_owner") or old_cust.get("owner_force_ref")):
                raise ValueError("custody transfer requires the same lawful captor authority")
            group["custodian_formation_ref"]=new_ref;group.setdefault("history",[]).append({"at":now,"kind":"custodian_transfer","from_formation_ref":old_ref,"to_formation_ref":new_ref})
        elif action in {"release","parole"}:
            self._custody_release_aggregate(group,status="paroled" if action=="parole" else "released",at=now)
            for pref in group.get("named_prisoner_refs",[]) if isinstance(group.get("named_prisoner_refs"),list) else []:
                try:pp,p0=self._exact_person(str(pref),active=False);p=copy.deepcopy(p0);p["custody_state"]={"status":"paroled" if action=="parole" else "released","released_at":now,"location_ref":group.get("location_ref"),"former_prisoner_group_ref":group["owner_id"]};self.put(pp,p)
                except ValueError:pass
            group["named_prisoner_refs"]=[]
            self._custody_clear_guard_duty(group);group["guards_allocated"]=0
        elif action=="execute":
            person_ref=str(payload.get("person_ref", ""));killed=0
            if person_ref:
                refs=group.get("named_prisoner_refs",[]) if isinstance(group.get("named_prisoner_refs"),list) else []
                if person_ref not in refs:raise ValueError("named execution target is not held in this prisoner group")
                pp,p0=self._exact_person(person_ref,active=False);person=copy.deepcopy(p0);self._settle_person_death(person_ref,pp,person,now,"lawful custody execution");refs.remove(person_ref);group["named_prisoner_refs"]=refs;group["guard_requirement"]=(int(group.get("personnel",0))+len(refs)+4)//5;group.setdefault("history",[]).append({"at":now,"kind":"named_execution","person_ref":person_ref,"authority_ref":command.actor_id,"legal_basis_ref":payload.get("legal_basis_ref")})
            else:
                killed=self._custody_kill_aggregate(group,int(payload.get("personnel",group.get("personnel",0))),at=now,reason="execution");group.setdefault("history",[]).append({"at":now,"kind":"execution","personnel":killed,"authority_ref":command.actor_id,"legal_basis_ref":payload.get("legal_basis_ref")})
            if int(group.get("personnel",0))<=0 and not group.get("named_prisoner_refs"):group["status"]="closed";self._custody_clear_guard_duty(group);group["guards_allocated"]=0
        elif action=="set_ransom":
            amount=max(1,int(payload.get("amount_silver",0)));group["ransom_offer"]={"status":"offered","amount_silver":amount,"offered_at":now,"payee_authority_ref":group.get("captor_authority_ref"),"payer_authority_ref":self._custody_force_authority(str(group.get("source_force_ref","")))};group.setdefault("history",[]).append({"at":now,"kind":"ransom_offered","amount_silver":amount})
        elif action=="accept_ransom":
            offer=group.get("ransom_offer") if isinstance(group.get("ransom_offer"),Mapping) else {};amount=max(0,int(offer.get("amount_silver",0)))
            if str(offer.get("status"))!="offered" or amount<=0:raise ValueError("prisoner group has no active ransom offer")
            payer=self._custody_force_authority(str(group.get("source_force_ref","")));payee=str(group.get("captor_authority_ref",""));self._custody_transfer_silver(payer,payee,amount,at=now,reason=f"ransom:{group['owner_id']}");self._custody_release_aggregate(group,status="ransomed",at=now)
            for pref in list(group.get("named_prisoner_refs",[])):
                try:pp,p0=self._exact_person(str(pref),active=False);p=copy.deepcopy(p0);p["custody_state"]={"status":"ransomed","released_at":now,"former_prisoner_group_ref":group["owner_id"],"location_ref":group.get("location_ref")};self.put(pp,p)
                except ValueError:pass
            group["named_prisoner_refs"]=[];offer=dict(offer);offer["status"]="paid_and_released";offer["accepted_at"]=now;group["ransom_offer"]=offer;self._custody_clear_guard_duty(group);group["guards_allocated"]=0
        elif action=="propose_exchange":
            other_ref=str(payload.get("other_prisoner_group_ref",""));_op,other=self._custody_group(other_ref)
            if str(group.get("status"))!="held" or str(other.get("status"))!="held":raise ValueError("exchange requires two held prisoner groups")
            if str(group.get("location_ref"))!=str(other.get("location_ref")):raise ValueError("prisoner exchange requires exact exchange-point co-location")
            group["exchange_offer"]={"status":"offered","other_prisoner_group_ref":other_ref,"offered_at":now,"offered_by_ref":command.actor_id};group.setdefault("history",[]).append({"at":now,"kind":"exchange_offered","other_prisoner_group_ref":other_ref})
        elif action=="accept_exchange":
            other_ref=str(payload.get("other_prisoner_group_ref",""));op,other=self._custody_group(other_ref);offer=group.get("exchange_offer") if isinstance(group.get("exchange_offer"),Mapping) else {}
            if str(offer.get("status"))!="offered" or str(offer.get("other_prisoner_group_ref"))!=other_ref:raise ValueError("no matching active prisoner exchange offer")
            if str(group.get("location_ref"))!=str(other.get("location_ref")):raise ValueError("prisoner exchange requires exact exchange-point co-location")
            self._custody_release_aggregate(group,status="exchanged",at=now);self._custody_release_aggregate(other,status="exchanged",at=now);self._custody_clear_guard_duty(group);self._custody_clear_guard_duty(other);group["guards_allocated"]=0;other["guards_allocated"]=0;offer=dict(offer);offer["status"]="accepted";offer["accepted_at"]=now;group["exchange_offer"]=offer;other.setdefault("history",[]).append({"at":now,"kind":"exchange_completed","other_prisoner_group_ref":group["owner_id"]});self.put(op,other);self._custody_set_active(other)
        elif action=="interrogate":
            info_ref=self._custody_testimony(group,str(payload.get("topic_ref","")),str(payload.get("statement","")),at=now,knower_ref=command.actor_id);group.setdefault("interrogations",[]).append({"at":now,"topic_ref":str(payload.get("topic_ref","")),"information_ref":info_ref,"interrogator_ref":command.actor_id,"rule":"testimony is saved as an unverified claim, never direct world truth"});group["interrogations"]=group["interrogations"][-24:]
        elif action=="offer_recruitment":
            dest_ref=str(payload.get("destination_force_ref",""));dest=self.read(self.owner_path(dest_ref));dest_auth=str(dest.get("administrative_owner") or dest.get("command_authority") or dest_ref)
            if dest_auth!=str(group.get("captor_authority_ref")) and not (str(group.get("captor_authority_ref"))==str(self.PLAYER_ACTOR) and dest_auth=="house_tang"):raise PermissionError("prisoner recruitment destination must belong to the captor authority")
            group["recruitment_offer"]={"status":"offered","destination_force_ref":dest_ref,"offered_at":now,"review_at":str(CampaignTime.parse(now).add_seconds(7*86400)),"rule":"captor offers service; prisoners decide autonomously after a cooling period"};group.setdefault("history",[]).append({"at":now,"kind":"recruitment_offered","destination_force_ref":dest_ref})
        elif action=="finalize_recruitment":
            dest_ref=str(payload.get("destination_force_ref",""));moved=self._custody_finalize_recruitment(group,dest_ref,at=now);group.setdefault("history",[]).append({"at":now,"kind":"voluntary_recruitment_finalized","destination_force_ref":dest_ref,"personnel":moved})
        elif action=="escape_attempt":
            total=max(0,int(group.get("personnel",0)));risk=max(0,int(group.get("escape_risk_milli",0)));roll=_stable_int(group["owner_id"],now,"escape",modulus=1000);escaped=0
            if total and roll<risk:escaped=max(1,int(math.floor(total*min(0.35,max(0.02,risk/3000.0)))));group["escape_progress_personnel"]=int(group.get("escape_progress_personnel",0))+escaped;group.setdefault("history",[]).append({"at":now,"kind":"escape_attempt","roll_milli":roll,"risk_milli":risk,"escaped_perimeter":escaped,"rule":"escape progress clears the immediate enclosure but does not teleport escapees to friendly territory"})
        self.put(path,group);self._custody_set_active(group);world,metrics=self._advance_seconds(1800);self._write_meta(command,world);return self._result(prisoner_group_ref=group["owner_id"],status=group.get("status"),personnel=group.get("personnel"),world_time=world,**metrics)
