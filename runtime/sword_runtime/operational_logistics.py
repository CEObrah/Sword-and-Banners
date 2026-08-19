"""Physical operational movement projections for formations and recursive armies.

The world remains aggregate: no soldier coordinates.  Route geometry determines
how long a column takes to clear a bottleneck and how long a formation needs to
deploy after its tail arrives.  These are physical time costs, not caps on army
size.  Larger armies simply occupy more road and require more time/waves.
"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any, Callable
import math

from sword_runtime.strategic_crossings import crossing_operational_profile

ROUTES_PATH = "game/data/world/routes.json"


def _route_rows(read: Callable[[str], Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    doc = read(ROUTES_PATH)
    rows = list(doc.get("routes", [])) + list(doc.get("local_routes", []))
    return {str(r.get("ref")): r for r in rows if isinstance(r, Mapping) and r.get("ref")}


def route_operational_profile(read: Callable[[str], Mapping[str, Any]], route_refs: list[str]) -> dict[str, Any]:
    rows = _route_rows(read)
    selected = [rows[ref] for ref in route_refs if ref in rows]
    if not selected:
        return {
            "length_km": 0.0, "bottleneck_road_width_m": 5.0,
            "daily_troop_throughput": 30000, "daily_wagon_throughput": 1200,
            "formation_files_abreast": 4,
        }
    length = 0.0; widths=[]; troop=[]; wagons=[]; files=[]
    for row in selected:
        phy = row.get("physical_geometry") if isinstance(row.get("physical_geometry"), Mapping) else {}
        length += float(phy.get("length_km", max(1, int(row.get("hours", 1))) * 2.6))
        widths.append(float(phy.get("usable_road_width_m", 5.0)))
        road_troops=max(1, int(phy.get("daily_troop_throughput", 30000)))
        road_wagons=max(1, int(phy.get("daily_wagon_throughput", 1200)))
        crossing=crossing_operational_profile(read,row)
        if crossing is not None:
            crossing_troops=int(crossing.get("daily_troop_throughput",0))
            crossing_wagons=int(crossing.get("daily_wagon_throughput",0))
            if crossing_troops <= 0:
                raise ValueError(f"strategic crossing on {row.get('ref')} is unusable")
            road_troops=min(road_troops,crossing_troops)
            # A formation road column always carries baggage. If no wagon-equivalent
            # path remains, operational formation movement is blocked even though a
            # messenger or foot party could still cross.
            if crossing_wagons <= 0:
                raise ValueError(f"strategic crossing on {row.get('ref')} cannot pass formation baggage")
            road_wagons=min(road_wagons,crossing_wagons)
        troop.append(road_troops)
        wagons.append(road_wagons)
        files.append(max(1, int(phy.get("formation_files_abreast_baseline", 4))))
    return {
        "length_km": round(length, 3),
        "bottleneck_road_width_m": round(min(widths), 3),
        "daily_troop_throughput": min(troop),
        "daily_wagon_throughput": min(wagons),
        "formation_files_abreast": min(files),
    }


def formation_movement_profile(read: Callable[[str], Mapping[str, Any]], formation: Mapping[str, Any], route: Mapping[str, Any]) -> dict[str, Any]:
    personnel = max(0, int(formation.get("personnel", 0)))
    route_refs = [str(x) for x in route.get("route_refs", [])]
    rp = route_operational_profile(read, route_refs)
    files = max(1, int(rp["formation_files_abreast"]))
    comp = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
    # Depth consumed per body when marching in a file. Mounted/chariot/support
    # bodies impose more longitudinal space than foot troops.
    depth_m = 0.0
    for role, raw in comp.items():
        n=max(0,int(raw)); name=str(role)
        per=2.6 if "cavalry" in name else (2.2 if "chariot" in name else (1.45 if name in {"logistics","siege_engineering"} else 1.15))
        depth_m += n * per / files
    if depth_m <= 0: depth_m = personnel * 1.15 / files
    # Baggage is an operational requirement projection, not a spawned wagon owner.
    logistics_people=max(0,int(comp.get("logistics",0)))
    wagon_equiv=max(0,int(math.ceil(personnel/240.0))) + max(0,int(math.ceil(logistics_people/12.0)))
    wagon_column_m = wagon_equiv * 8.0
    column_km=(depth_m+wagon_column_m)/1000.0
    troop_clear=24.0*personnel/max(1,int(rp["daily_troop_throughput"]))
    wagon_clear=24.0*wagon_equiv/max(1,int(rp["daily_wagon_throughput"]))
    clearance=max(troop_clear,wagon_clear,column_km/max(0.5,3.0))
    base=max(0,int(route.get("duration_hours", route.get("hours", 0))))
    tail=max(base, base+clearance)
    deploy=max(0.5, math.ceil(personnel/5000.0)*0.75)
    if int(comp.get("siege_engineering",0))>0: deploy += 0.5
    if int(comp.get("chariot",0))>0: deploy += 0.5
    return {
        **rp,
        "personnel": personnel,
        "required_wagon_equivalents": wagon_equiv,
        "column_length_km": round(column_km,3),
        "base_head_travel_hours": base,
        "column_clearance_hours": round(clearance,3),
        "tail_arrival_hours": int(math.ceil(tail)),
        "deployment_hours_after_tail": round(deploy,3),
        "battle_ready_hours": int(math.ceil(tail+deploy)),
        "rule": "Route throughput never caps army size; excess personnel/wagons consume additional clearance and deployment time.",
    }


def army_ordered_formation_refs(read_group: Callable[[str], Mapping[str, Any]], group_ref: str) -> list[str]:
    from sword_runtime.command_units import unit_entries, FORMATION
    out=[]; stack=set()
    def visit(ref: str):
        if ref in stack: raise ValueError("command hierarchy contains a cycle")
        stack.add(ref); doc=read_group(ref)
        for row in unit_entries(doc):
            if row["kind"] == FORMATION: out.append(row["ref"])
            else: visit(row["ref"])
        stack.remove(ref)
    visit(group_ref); return out


def recursive_army_movement_plan(read: Callable[[str], Mapping[str, Any]], read_group: Callable[[str], Mapping[str, Any]], load_formation: Callable[[str], Mapping[str, Any]], group_ref: str, route: Mapping[str, Any]) -> dict[str, Any]:
    refs=army_ordered_formation_refs(read_group,group_ref)
    if not refs: raise ValueError("army command has no descendant formations to move")
    rp=route_operational_profile(read,[str(x) for x in route.get("route_refs",[])])
    flow_per_hour=max(1,float(rp["daily_troop_throughput"])/24.0)
    cursor=0.0; units=[]; total=0
    for ref in refs:
        f=load_formation(ref); prof=formation_movement_profile(read,f,route); n=int(f.get("personnel",0)); total+=n
        start_offset=cursor; clearance=max(prof["column_clearance_hours"], n/flow_per_hour)
        head=float(prof["base_head_travel_hours"])+start_offset
        tail=head+clearance
        ready=tail+float(prof["deployment_hours_after_tail"])
        units.append({"formation_ref":ref,"personnel":n,"required_wagon_equivalents":int(prof.get("required_wagon_equivalents",0)),"departure_offset_hours":round(start_offset,3),"head_arrival_hours":round(head,3),"tail_arrival_hours":round(tail,3),"battle_ready_hours":round(ready,3),"column_length_km":prof["column_length_km"]})
        cursor += clearance
    return {**rp,"command_group_ref":group_ref,"total_personnel":total,"formation_count":len(refs),"required_wagon_equivalents":sum(int(x.get("required_wagon_equivalents",0)) for x in units),"ordered_units":units,"whole_army_tail_arrival_hours":int(math.ceil(max(x["tail_arrival_hours"] for x in units))),"whole_army_battle_ready_hours":int(math.ceil(max(x["battle_ready_hours"] for x in units))),"rule":"Nested army structure is preserved; direct Unit order determines road-column sequence and no descendant is flattened into a new manpower owner."}
