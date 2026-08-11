from __future__ import annotations
import collections, json, shutil, subprocess
from pathlib import Path
import pytest

SOURCE=Path(__file__).resolve().parents[2]

@pytest.fixture
def campaign(tmp_path):
    dst=tmp_path/'repo'
    # Test campaigns need independent refs/working trees, not duplicate copies
    # of the immutable baseline object database. --shared keeps every commit
    # made by the clone local while reading baseline objects through alternates.
    subprocess.run(['git','clone','--shared','--quiet',str(SOURCE),str(dst)],check=True)
    subprocess.run(['git','-C',str(dst),'config','user.name','Sword Runtime Tests'],check=True)
    subprocess.run(['git','-C',str(dst),'config','user.email','sword-tests@example.invalid'],check=True)
    # Disposable campaign clones can create hundreds of tiny commits during
    # acceptance/soak tests. Disable Git's automatic detached maintenance so
    # no background gc/repack process inherits the pytest output pipe and
    # makes a completed module appear to hang. Production repositories retain
    # their normal Git maintenance policy.
    subprocess.run(['git','-C',str(dst),'config','gc.auto','0'],check=True)
    subprocess.run(['git','-C',str(dst),'config','gc.autoPackLimit','0'],check=True)
    subprocess.run(['git','-C',str(dst),'config','maintenance.auto','false'],check=True)
    try:
        yield dst
    finally:
        # Campaign clones contain their own object databases. Remove each one
        # immediately instead of leaving several large repositories for
        # pytest's session-level temporary-directory cleanup.
        shutil.rmtree(dst,ignore_errors=True)

def meta(root):
    return json.loads((Path(root)/'state/meta.json').read_text())

def execute(root, command_type, payload, *, actor='char_tang_wei', mode='gameplay', request_id=None):
    from sword_runtime.engine import SwordRuntime
    from sword_runtime.commands import CommandEnvelope
    m=meta(root); request_id=request_id or f'test-{m["revision"]}-{command_type}'
    c=CommandEnvelope(m['campaign_id'],request_id,actor,command_type,m['revision'],m['time'],payload,mode=mode)
    return SwordRuntime(root).execute(c)

def execute_internal(root, command_type, payload, *, request_id=None, mode='autonomous'):
    from sword_runtime.engine import RepositoryCommandPlanner
    return execute(root,command_type,payload,actor=RepositoryCommandPlanner.INTERNAL_ACTOR,mode=mode,request_id=request_id)

def route_path(root, origin, destination):
    routes=json.load(open(Path(root)/'game/data/world/routes.json'))['routes']; graph=collections.defaultdict(list)
    for route in routes:
        a,b=route['a'],route['b']; graph[a].append(b); graph[b].append(a)
    q=collections.deque([(origin,[origin])]); seen={origin}
    while q:
        node,path=q.popleft()
        if node==destination: return path
        for nxt in graph[node]:
            if nxt not in seen: seen.add(nxt); q.append((nxt,path+[nxt]))
    raise ValueError(f'no route from {origin} to {destination}')

def move_formation_internal(root, formation_ref, destination):
    idx=json.load(open(Path(root)/'state/index/owner-index-gold.json'))['owners']; formation=json.load(open(Path(root)/idx[formation_ref])); origin=formation['location_ref']
    if origin.startswith('loc_tang_manor_') and destination != origin:
        execute_internal(root,'formation_move',{'formation_ref':formation_ref,'destination_ref':'loc_kanyou'})
        origin='loc_kanyou'
        if destination == origin:
            return
    for nxt in route_path(root,origin,destination)[1:]:
        execute_internal(root,'formation_move',{'formation_ref':formation_ref,'destination_ref':nxt})

def prepare_field_formation(root, formation_ref, destination='loc_kankoku_pass', *, food_per_person=7):
    idx=json.load(open(Path(root)/'state/index/owner-index-gold.json'))['owners']; formation=json.load(open(Path(root)/idx[formation_ref])); n=int(formation['personnel'])
    mounts=sum(int(v) for v in formation.get('mounts',{}).values())
    execute_internal(root,'resupply',{'formation_ref':formation_ref,'food_kg':int(round(n*food_per_person)),'fodder_kg':int(mounts*30),'war_arrows':int(n*4)})
    execute_internal(root,'formation_mobilize',{'formation_ref':formation_ref})
    move_formation_internal(root,formation_ref,destination)

def activate_operation(root, operation_ref, formation_refs, location='loc_kankoku_pass'):
    execute_internal(root,'operation_create',{'operation_ref':operation_ref,'objective':'verified battlefield contact','formation_refs':list(formation_refs),'location_ref':location})
    execute_internal(root,'operation_transition',{'operation_ref':operation_ref,'status':'active'})
    return operation_ref
