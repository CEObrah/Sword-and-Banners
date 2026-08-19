from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping
from typing import Any

from sword_runtime.sim.calendar import CampaignTime


def _slug(ref: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(ref)).strip("-")


class IndependentOrganizationMixin:
    """Generic zero-population lifecycle for persistent non-sovereign organizations.

    Organizations own institutional identity and money, never implicit people. Members
    are exact existing people and armed branches remain normal conserved force owners.
    """

    _ORG_INDEX = "state/organizations/index.json"

    def _organization_index(self) -> dict[str, Any]:
        raw = self.read_optional(self._ORG_INDEX)
        if isinstance(raw, Mapping):
            out = copy.deepcopy(dict(raw))
        else:
            out = {"schema": "sword-organization-index", "authority": False, "organizations": {}, "active_refs": []}
        out.setdefault("organizations", {})
        out.setdefault("active_refs", [])
        return out

    def _organization_path(self, organization_ref: str) -> str:
        return f"state/organizations/{_slug(organization_ref)}.json"

    def _organization_treasury_path(self, organization_ref: str) -> str:
        return f"state/treasury/treasury-{_slug(organization_ref)}.json"

    def _organization_exact(self, organization_ref: str) -> tuple[str, dict[str, Any]]:
        try:
            path = self.owner_path(organization_ref)
        except (KeyError, ValueError, FileNotFoundError):
            idx = self._organization_index()
            path = str(idx.get("organizations", {}).get(organization_ref, ""))
            if not path:
                raise ValueError("unknown independent organization")
        doc = copy.deepcopy(self.read(path))
        if str(doc.get("schema", "")) != "sword-independent-organization":
            raise ValueError("owner is not an independent organization")
        return path, doc

    def _organization_autonomy_rules(self) -> Mapping[str, Any]:
        rules = self.read("game/data/mechanics/independent-organizations.json")
        return rules.get("autonomy", {}) if isinstance(rules, Mapping) else {}

    def _organization_host_ids(self, organization_ref: str) -> tuple[str, str]:
        digest = hashlib.sha256(str(organization_ref).encode()).hexdigest()[:18]
        return f"host_org_{digest}", f"event_org_{digest}"

    def _ensure_organization_host(self, organization_ref: str, at: str) -> None:
        runtime = copy.deepcopy(self.read("state/runtime.json"))
        hosts = runtime.setdefault("hosts", {}); events = runtime.setdefault("events", [])
        host_id, event_id = self._organization_host_ids(organization_ref)
        if host_id in hosts and isinstance(hosts.get(host_id), Mapping) and hosts[host_id].get("next_due"):
            return
        review_days = max(1, int(self._organization_autonomy_rules().get("review_days", 60)))
        due = CampaignTime.parse(at).add_seconds(review_days * 86400)
        host = {"host_id":host_id,"kind":"institution","owner_ref":organization_ref,"organization_lifecycle":True,"event_id":event_id,"recurrence_seconds":review_days*86400,"next_due":str(due),"resolved_through":at,"safe_through":str(due.add_seconds(-1))}
        hosts[host_id] = host
        events[:] = [e for e in events if not (isinstance(e, Mapping) and str(e.get("event_id")) == event_id)]
        events.append({"event_id":event_id,"kind":"organization_review","priority":86,"target_host":host_id,"due_at":str(due)})
        self.put("state/runtime.json", runtime)

    def _disable_organization_host(self, organization_ref: str) -> None:
        runtime = copy.deepcopy(self.read("state/runtime.json")); hosts=runtime.setdefault("hosts",{}); events=runtime.setdefault("events",[])
        host_id,event_id=self._organization_host_ids(organization_ref)
        if isinstance(hosts.get(host_id), dict): hosts[host_id]["next_due"]=None; hosts[host_id]["disabled_reason"]="organization_dissolved"
        for e in events:
            if isinstance(e,dict) and str(e.get("event_id"))==event_id: e["suspended"]=True
        self.put("state/runtime.json",runtime)

    def _organization_person_alive(self, person_ref: str) -> bool:
        try: _p, person = self._exact_person(person_ref, active=False)
        except (KeyError, ValueError, FileNotFoundError): return False
        return str(person.get("life_status", person.get("status", "active"))).lower() not in {"dead","deceased"}

    def _autonomy_institution(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        organization_ref = str(host.get("owner_ref", ""))
        idx = self._organization_index()
        if organization_ref not in idx.get("organizations", {}):
            return super()._autonomy_institution(host, occurrences, at)
        # Let the shared institution project engine settle any due exact projects first.
        super()._autonomy_institution(host, occurrences, at)
        path, org = self._organization_exact(organization_ref)
        if str(org.get("status", "")) != "active":
            return
        rules = self._organization_autonomy_rules(); treasury_path=self.owner_path(str(org.get("treasury_ref",""))); treasury=copy.deepcopy(self.read(treasury_path))
        members=[str(x) for x in org.get("member_refs",[]) if isinstance(x,str) and self._organization_person_alive(str(x))]
        removed=sorted(set(str(x) for x in org.get("member_refs",[]) if isinstance(x,str))-set(members))
        org["member_refs"]=members
        leaders=[str(x) for x in org.get("leader_refs",[]) if isinstance(x,str) and str(x) in members]
        org["leader_refs"]=leaders
        roles=org.get("leadership_roles",{}) if isinstance(org.get("leadership_roles"),Mapping) else {}
        org["leadership_roles"]={str(k):str(v) for k,v in roles.items() if str(v) in leaders}

        # Optional autonomous admission is bounded to explicitly nominated exact people.
        admitted: list[str]=[]
        if bool((org.get("policies",{}) or {}).get("auto_admit_candidates",False)):
            queue=[str(x) for x in org.get("candidate_refs",[]) if isinstance(x,str)]
            remaining=[]
            for person_ref in queue:
                if len(members)>=max(1,int(org.get("capacity",1))): remaining.append(person_ref); continue
                if person_ref==str(getattr(self,"PLAYER_ACTOR","char_tang_wei")) or not self._organization_person_alive(person_ref):
                    remaining.append(person_ref); continue
                if person_ref in members: continue
                try: pp,p0=self._exact_person(person_ref,active=False)
                except (KeyError,ValueError,FileNotFoundError): continue
                person=copy.deepcopy(p0); affiliations=person.setdefault("institutional_affiliations",[])
                if organization_ref not in affiliations: affiliations.append(organization_ref)
                self.put(pp,person); members.append(person_ref); admitted.append(person_ref)
            org["candidate_refs"]=remaining; org["member_refs"]=members

        appointed=None
        if not org.get("leader_refs") and members:
            appointed=sorted(members)[0]; org["leader_refs"]=[appointed]; org.setdefault("leadership_roles",{})["leader"]=appointed

        base=max(0,int(rules.get("maintenance_silver_per_review",20))); per=max(0,int(rules.get("maintenance_silver_per_member",2)))
        maintenance=base+per*len(members); arrears=max(0,int(org.get("maintenance_arrears_silver",0))); due=maintenance+arrears
        available=max(0,int(treasury.get("silver",0))); paid=min(available,due); treasury["silver"]=available-paid; arrears_after=due-paid; org["maintenance_arrears_silver"]=arrears_after
        if paid:
            state=str(org.get("state","")); location=str(org.get("location_ref",""))
            try:
                ep,eco=self._private_economy(state); _site,regional=self._local_economy_region(state,eco,location); regional["cash_silver"]=int(regional.get("cash_silver",0))+paid; self._sync_local_economy_aggregate(eco); self._write_private_economy(ep,eco)
            except (KeyError,ValueError,FileNotFoundError):
                # If no local private-economy region is represented, do not destroy money.
                treasury["silver"]=int(treasury.get("silver",0))+paid; paid=0; arrears_after=due; org["maintenance_arrears_silver"]=arrears_after
        if arrears_after<=0: operational="stable"
        elif arrears_after<=max(1,maintenance*3): operational="strained"
        else: operational="dormant"
        org["operational_status"]=operational; org["last_autonomous_review_at"]=at
        org.setdefault("autonomous_reviews",[]).append({"at":at,"maintenance_due_silver":maintenance,"maintenance_paid_silver":paid,"arrears_silver":arrears_after,"removed_dead_or_missing_member_refs":removed,"admitted_candidate_refs":admitted,"appointed_successor_ref":appointed,"operational_status":operational})
        org["autonomous_reviews"]=org["autonomous_reviews"][-24:]
        self.put(treasury_path,treasury); self.put(path,org)

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        if getattr(self, "_central_scheduler_reconciliation_active", False):
            return super()._advance_runtime(target_text)
        now=str(self._world_time())
        idx=self._organization_index()
        for ref in sorted(str(x) for x in idx.get("active_refs",[]) if isinstance(x,str)):
            self._ensure_organization_host(ref,now)
        return super()._advance_runtime(target_text)

    def _validate_command_semantics(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._validate_command_semantics(command, payload)
        if command.command_type != "organization_action":
            return
        action = str(payload.get("action", ""))
        allowed = {"create", "fund", "withdraw", "join", "leave", "appoint_leader", "nominate_candidate", "remove_candidate", "link_force", "unlink_force", "set_policy", "dissolve"}
        if action not in allowed:
            raise ValueError("unsupported organization action")
        ref = str(payload.get("organization_ref", ""))
        if not ref:
            raise ValueError("organization_ref is required")
        if action == "create":
            if not str(payload.get("name", "")).strip():
                raise ValueError("organization name is required")
            if not str(payload.get("organization_class", "")).strip():
                raise ValueError("organization_class is required")
            loc = str(payload.get("location_ref", ""))
            if not loc:
                raise ValueError("organization location_ref is required")
            self._location_record(loc)
            amount = int(payload.get("amount_silver", 0))
            if amount < 0:
                raise ValueError("organization founding silver cannot be negative")
        elif action in {"fund", "withdraw"}:
            if int(payload.get("amount_silver", 0)) <= 0:
                raise ValueError("organization transfer amount_silver must be positive")
        elif action in {"join", "leave", "appoint_leader", "nominate_candidate", "remove_candidate"}:
            self._exact_person(str(payload.get("person_ref", "")))
        elif action in {"link_force", "unlink_force"}:
            force_ref = str(payload.get("force_ref", ""))
            if not force_ref:
                raise ValueError("force_ref is required")
            self.read(self.owner_path(force_ref))
        elif action == "set_policy":
            if not str(payload.get("policy_key", "")):
                raise ValueError("policy_key is required")

    def _dispatch_organization_action(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        action = str(payload["action"])
        ref = str(payload["organization_ref"])
        now = str(self._world_time())
        wallet_path = "state/economy/player-wallet.json"

        if action == "create":
            try:
                self.owner_path(ref)
            except (KeyError, ValueError, FileNotFoundError):
                pass
            else:
                raise ValueError("organization_ref already exists")
            location_ref = str(payload["location_ref"])
            state = self._native_site_state(location_ref)
            if state is None:
                row = self._location_record(location_ref)
                state = str(row.get("state", ""))
            if not state:
                raise ValueError("organization headquarters lacks a native state/economy")
            initial = max(0, int(payload.get("amount_silver", 0)))
            wallet = copy.deepcopy(self.read(wallet_path))
            if str(command.actor_id) == str(getattr(self, "PLAYER_ACTOR", "char_tang_wei")):
                if int(wallet.get("silver", 0)) < initial:
                    raise ValueError("player wallet lacks founding silver")
                wallet["silver"] = int(wallet.get("silver", 0)) - initial
                self.put(wallet_path, wallet)
            elif initial:
                raise PermissionError("non-player organization creation cannot mint founding silver")

            path = self._organization_path(ref)
            treasury_ref = f"treasury_{_slug(ref).replace('-', '_').replace('.', '_')}"
            treasury_path = self._organization_treasury_path(ref)
            capacity = max(1, int(payload.get("capacity", 20)))
            org = {
                "schema": "sword-independent-organization",
                "owner_id": ref,
                "name": str(payload["name"]),
                "organization_class": str(payload["organization_class"]),
                "state": state,
                "location_ref": location_ref,
                "status": "active",
                "capacity": capacity,
                "population_owned": 0,
                "treasury_ref": treasury_ref,
                "member_refs": [],
                "leader_refs": [],
                "linked_force_refs": [],
                "policies": {},
                "projects": [],
                "created_at": now,
                "created_by_ref": str(command.actor_id),
                "rule": "zero-population institutional owner; members are existing people and armed branches remain separate conserved force owners",
            }
            treasury = {
                "schema": "treasury",
                "owner_id": treasury_ref,
                "owner_type": "independent_organization",
                "silver": initial,
                "food_kg": 0,
                "fodder_kg": 0,
                "stable_monthly_flows": {},
                "monthly_flow_components": {},
                "runtime": {},
                "cash_close_rule": "organization treasury changes only through exact transfers, lawful project/maintenance spending, or dissolution settlement",
                "organization_ref": ref,
                "source": "exact organization treasury; funding transfers never imply population ownership",
            }
            self.put(path, org)
            self.put(treasury_path, treasury)
            self._register_owner(ref, path)
            self._register_owner(treasury_ref, treasury_path)
            idx = self._organization_index()
            idx["organizations"][ref] = path
            if ref not in idx["active_refs"]:
                idx["active_refs"].append(ref)
            idx["active_refs"] = sorted(set(str(x) for x in idx["active_refs"]))
            self.put(self._ORG_INDEX, idx)
            self._ensure_organization_host(ref, now)
            world_time, metrics = self._advance_seconds(1800)
            self._write_meta(command, world_time)
            return self._result(organization_ref=ref, treasury_ref=treasury_ref, status="active", world_time=world_time, **metrics)

        path, org = self._organization_exact(ref)
        if str(org.get("status", "")) != "active" and action != "dissolve":
            raise ValueError("organization is not active")
        treasury_ref = str(org.get("treasury_ref", ""))
        treasury_path = self.owner_path(treasury_ref)
        treasury = copy.deepcopy(self.read(treasury_path))
        result: dict[str, Any] = {"organization_ref": ref, "action": action}

        if action in {"fund", "withdraw"}:
            amount = int(payload["amount_silver"])
            wallet = copy.deepcopy(self.read(wallet_path))
            if str(command.actor_id) != str(getattr(self, "PLAYER_ACTOR", "char_tang_wei")):
                raise PermissionError("generic organization wallet transfers require the player actor")
            if action == "fund":
                if int(wallet.get("silver", 0)) < amount:
                    raise ValueError("player wallet lacks organization funding")
                wallet["silver"] = int(wallet.get("silver", 0)) - amount
                treasury["silver"] = int(treasury.get("silver", 0)) + amount
            else:
                if int(treasury.get("silver", 0)) < amount:
                    raise ValueError("organization treasury lacks withdrawal silver")
                treasury["silver"] = int(treasury.get("silver", 0)) - amount
                wallet["silver"] = int(wallet.get("silver", 0)) + amount
            self.put(wallet_path, wallet)
            self.put(treasury_path, treasury)
            result.update({"amount_silver": amount, "treasury_silver": int(treasury.get("silver", 0))})

        elif action in {"join", "leave"}:
            person_ref = str(payload["person_ref"])
            person_path, person = self._exact_person(person_ref)
            person = copy.deepcopy(person)
            members = org.setdefault("member_refs", [])
            affiliations = person.setdefault("institutional_affiliations", [])
            if action == "join":
                if person_ref not in members:
                    if len(members) >= max(1, int(org.get("capacity", 1))):
                        raise ValueError("organization membership capacity is full")
                    members.append(person_ref)
                if ref not in affiliations:
                    affiliations.append(ref)
            else:
                org["member_refs"] = [x for x in members if str(x) != person_ref]
                org["leader_refs"] = [x for x in org.get("leader_refs", []) if str(x) != person_ref]
                person["institutional_affiliations"] = [x for x in affiliations if str(x) != ref]
            self.put(person_path, person)
            result["person_ref"] = person_ref

        elif action in {"nominate_candidate", "remove_candidate"}:
            person_ref=str(payload["person_ref"]); queue=[str(x) for x in org.setdefault("candidate_refs",[]) if isinstance(x,str)]
            if action=="nominate_candidate" and person_ref not in queue: queue.append(person_ref)
            if action=="remove_candidate": queue=[x for x in queue if x!=person_ref]
            org["candidate_refs"]=queue[-128:]; result["person_ref"]=person_ref

        elif action == "appoint_leader":
            person_ref = str(payload["person_ref"])
            if person_ref not in org.setdefault("member_refs", []):
                raise ValueError("organization leader must first be an exact member")
            role = str(payload.get("role", "leader"))
            leaders = [x for x in org.setdefault("leader_refs", []) if str(x) != person_ref]
            leaders.append(person_ref)
            org["leader_refs"] = leaders[-16:]
            org.setdefault("leadership_roles", {})[role] = person_ref
            result.update({"person_ref": person_ref, "role": role})

        elif action in {"link_force", "unlink_force"}:
            force_ref = str(payload["force_ref"])
            linked = [str(x) for x in org.setdefault("linked_force_refs", [])]
            if action == "link_force" and force_ref not in linked:
                linked.append(force_ref)
            if action == "unlink_force":
                linked = [x for x in linked if x != force_ref]
            org["linked_force_refs"] = sorted(set(linked))
            result["force_ref"] = force_ref

        elif action == "set_policy":
            key = str(payload["policy_key"])
            org.setdefault("policies", {})[key] = copy.deepcopy(payload.get("policy_value"))
            result["policy_key"] = key

        elif action == "dissolve":
            if str(org.get("status", "")) == "dissolved":
                raise ValueError("organization is already dissolved")
            if any(str(x.get("status", "")) == "active" for x in org.get("projects", []) if isinstance(x, Mapping)):
                raise ValueError("organization with active physical projects cannot dissolve")
            if org.get("linked_force_refs"):
                raise ValueError("organization must unlink exact force owners before dissolution")
            remainder = max(0, int(treasury.get("silver", 0)))
            if remainder:
                wallet = copy.deepcopy(self.read(wallet_path))
                if str(command.actor_id) != str(getattr(self, "PLAYER_ACTOR", "char_tang_wei")):
                    raise PermissionError("generic dissolution settlement requires the player actor")
                wallet["silver"] = int(wallet.get("silver", 0)) + remainder
                treasury["silver"] = 0
                self.put(wallet_path, wallet)
            org["status"] = "dissolved"
            org["dissolved_at"] = now
            idx = self._organization_index()
            idx["active_refs"] = [x for x in idx.get("active_refs", []) if str(x) != ref]
            self.put(self._ORG_INDEX, idx)
            self.put(treasury_path, treasury)
            self._disable_organization_host(ref)
            result["returned_silver"] = remainder

        org.setdefault("history", []).append({"at": now, "action": action, "actor_ref": str(command.actor_id)})
        org["history"] = org["history"][-64:]
        self.put(path, org)
        world_time, metrics = self._advance_seconds(1800)
        self._write_meta(command, world_time)
        return self._result(world_time=world_time, **result, **metrics)

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "organization_action":
            return self._dispatch_organization_action(command, payload)
        return super()._dispatch(command, payload)
