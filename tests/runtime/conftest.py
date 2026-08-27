from __future__ import annotations
import collections, json, shutil, subprocess
from pathlib import Path
import pytest

SOURCE=Path(__file__).resolve().parents[2]

@pytest.fixture(scope="session")
def _campaign_repository_base(tmp_path_factory):
    """Build one pristine release repository for the pytest session.

    Every test receives a lightweight shared-object clone below. The pristine
    base objects are reused, but each test owns its *new* Git objects. Detached
    worktrees shared one object database, so deleting write-heavy test worktrees
    left large unreachable object piles that made later tests in the same module
    progressively slower. Shared clones keep the fast base reuse without that
    cross-test garbage accumulation.
    """
    base=tmp_path_factory.mktemp('sword-campaign-base')/'repo'
    shutil.copytree(
        SOURCE,
        base,
        ignore=shutil.ignore_patterns('.git', '.pytest_cache', '.pytest-tmp-*', '.release-certification.json', '__pycache__', '*.pyc'),
    )
    subprocess.run(['git','init','--quiet',str(base)],check=True)
    subprocess.run(['git','-C',str(base),'config','user.name','Sword Runtime Tests'],check=True)
    subprocess.run(['git','-C',str(base),'config','user.email','sword-tests@example.invalid'],check=True)
    subprocess.run(['git','-C',str(base),'config','gc.auto','0'],check=True)
    subprocess.run(['git','-C',str(base),'config','gc.autoPackLimit','0'],check=True)
    subprocess.run(['git','-C',str(base),'config','maintenance.auto','false'],check=True)
    subprocess.run(['git','-C',str(base),'add','-A'],check=True)
    subprocess.run(['git','-C',str(base),'commit','--quiet','-m','Sword and Banners test fixture'],check=True)
    # Pytest's basetemp owns lifecycle cleanup. Recursive in-fixture deletion of
    # full campaign repositories made write-heavy modules spend more time tearing
    # down green tests than executing them, and interrupted runs left partial trees.
    yield base

@pytest.fixture
def campaign(tmp_path, _campaign_repository_base):
    dst=tmp_path/'repo'
    base=Path(_campaign_repository_base)
    # Reuse the pristine base object store read-only while keeping every test's
    # newly written objects in that clone's own .git/objects directory. This
    # prevents write-heavy tests from polluting a session-global worktree object
    # store with unreachable commits after teardown.
    subprocess.run(['git','clone','--quiet','--shared',str(base),str(dst)],check=True)
    subprocess.run(['git','-C',str(dst),'config','user.name','Sword Runtime Tests'],check=True)
    subprocess.run(['git','-C',str(dst),'config','user.email','sword-tests@example.invalid'],check=True)
    subprocess.run(['git','-C',str(dst),'config','gc.auto','0'],check=True)
    subprocess.run(['git','-C',str(dst),'config','gc.autoPackLimit','0'],check=True)
    subprocess.run(['git','-C',str(dst),'config','maintenance.auto','false'],check=True)
    # Leave the disposable clone to the enclosing pytest basetemp. This avoids
    # synchronous recursive deletion after every test while preserving isolation.
    yield dst

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

def execute_production(root, command_type, payload, *, actor='char_tang_wei', mode='gameplay', request_id=None):
    """Execute through the domain production planner on a disposable repo."""
    from sword_runtime.engine import SwordRuntime, RepositoryCommandPlanner
    from sword_runtime.production_planner import ProductionCampaignPlanner
    from sword_runtime.commands import CommandEnvelope
    m=meta(root); request_id=request_id or f'prod-{m["revision"]}-{command_type}'
    runtime=SwordRuntime(root); runtime.planner=ProductionCampaignPlanner(root)
    c=CommandEnvelope(m['campaign_id'],request_id,actor,command_type,m['revision'],m['time'],payload,mode=mode)
    return runtime.execute(c)

def execute_production_internal(root, command_type, payload, *, request_id=None, mode='autonomous'):
    from sword_runtime.engine import RepositoryCommandPlanner
    return execute_production(root,command_type,payload,actor=RepositoryCommandPlanner.INTERNAL_ACTOR,mode=mode,request_id=request_id)

def execute_hosted_production(root, command_type, payload, *, actor='char_tang_wei', mode='gameplay', request_id=None):
    """Execute through the actual hosted production planner composition."""
    from sword_runtime.engine import SwordRuntime
    from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
    from sword_runtime.commands import CommandEnvelope
    m=meta(root); request_id=request_id or f'hosted-{m["revision"]}-{command_type}'
    runtime=SwordRuntime(root); runtime.planner=ProductionCampaignPlanner(root)
    c=CommandEnvelope(m['campaign_id'],request_id,actor,command_type,m['revision'],m['time'],payload,mode=mode)
    return runtime.execute(c)

def execute_hosted_production_internal(root, command_type, payload, *, request_id=None, mode='autonomous'):
    from sword_runtime.engine import RepositoryCommandPlanner
    return execute_hosted_production(root,command_type,payload,actor=RepositoryCommandPlanner.INTERNAL_ACTOR,mode=mode,request_id=request_id)

def route_path(root, origin, destination, *, mode=None):
    routes=json.load(open(Path(root)/'game/data/world/routes.json'))['routes']; graph=collections.defaultdict(list)
    for route in routes:
        if mode is not None and mode not in set(route.get('modes', [])):
            continue
        a,b=route['a'],route['b']; graph[a].append(b); graph[b].append(a)
    q=collections.deque([(origin,[origin])]); seen={origin}
    while q:
        node,path=q.popleft()
        if node==destination: return path
        for nxt in graph[node]:
            if nxt not in seen: seen.add(nxt); q.append((nxt,path+[nxt]))
    raise ValueError(f'no route from {origin} to {destination}')

def move_formation_internal(root, formation_ref, destination):
    idx=json.load(open(Path(root)/'state/index/owner-index.json'))['owners']; formation=json.load(open(Path(root)/idx[formation_ref])); origin=formation['location_ref']
    for nxt in route_path(root,origin,destination,mode='formation')[1:]:
        execute_internal(root,'formation_move',{'formation_ref':formation_ref,'destination_ref':nxt})

def prepare_field_formation(root, formation_ref, destination='loc_kankoku_pass'):
    idx=json.load(open(Path(root)/'state/index/owner-index.json'))['owners']; formation=json.load(open(Path(root)/idx[formation_ref])); n=int(formation['personnel'])
    logistics=formation.get('logistics',{})
    desired_arrows=int(n*4)
    arrow_request=max(0,desired_arrows-int(logistics.get('war_arrows',0)))
    execute_internal(root,'resupply',{'formation_ref':formation_ref,'war_arrows':arrow_request})
    execute_internal(root,'formation_mobilize',{'formation_ref':formation_ref})
    move_formation_internal(root,formation_ref,destination)

def activate_operation(root, operation_ref, formation_refs, location='loc_kankoku_pass'):
    execute_internal(root,'operation_create',{'operation_ref':operation_ref,'objective':'verified battlefield contact','formation_refs':list(formation_refs),'location_ref':location})
    execute_internal(root,'operation_transition',{'operation_ref':operation_ref,'status':'mobilizing'})
    execute_internal(root,'operation_transition',{'operation_ref':operation_ref,'status':'active'})
    return operation_ref
