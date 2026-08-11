from __future__ import annotations
import os, secrets
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from sword_runtime.commands import CommandEnvelope
from sword_runtime.engine import SwordRuntime, RepositoryCommandPlanner
from sword_runtime.store.repository import RepositoryStore
from sword_runtime.api.middleware import BodySizeLimitMiddleware

class StrictModel(BaseModel): model_config=ConfigDict(extra='forbid',strict=True)
class CommandRequest(StrictModel):
    campaign_id:str=Field(min_length=1,max_length=128); request_id:str=Field(min_length=1,max_length=128); actor_id:str=Field(min_length=1,max_length=128); command_type:str=Field(min_length=1,max_length=96); expected_revision:int=Field(ge=0); submitted_at:str; payload:dict[str,Any]; mode:str='gameplay'

def _safe_player_context(store:RepositoryStore)->dict[str,Any]:
    meta=store.read_json('state/meta.json'); player=store.read_json('state/player.json'); wallet=store.read_json('state/economy/player-wallet.json')
    known=[]; idx=store.read_json('state/information/index.json')
    for _,path in sorted(idx.get('claims',{}).items()):
        claim=store.read_json(path)
        if meta.get('player_id') in claim.get('knowers',[]): known.append({'information_ref':claim.get('information_ref'),'claim':claim.get('claim'),'confidence':claim.get('confidence'),'provenance':claim.get('provenance')})
    idxo=store.read_json('state/index/owner-index-gold.json').get('owners',{})
    formations=[]
    for ref,path in sorted(idxo.items()):
        if not ref.startswith('formation_'): continue
        f=store.read_json(path)
        if f.get('command_authority')==meta.get('player_id') or f.get('administrative_owner') in {meta.get('player_id'),'house_tang'}:
            formations.append({'formation_ref':ref,'name':f.get('name'),'personnel':f.get('personnel'),'location_ref':f.get('location_ref'),'status':f.get('status')})
    return {'campaign':{'campaign_id':meta['campaign_id'],'revision':meta['revision'],'world_time':meta['time']},'player':player,'wallet':wallet,'known_information':known,'controlled_formations':formations,'policy':'hidden state omitted unless lawfully known'}

def create_app(root:object, token:str)->FastAPI:
    if len(token)<32: raise ValueError('SWORD_API_TOKEN must be at least 32 characters')
    runtime=SwordRuntime(root); store=runtime.store; app=FastAPI(title='Sword & Banners Runtime',docs_url=None,redoc_url=None,openapi_url=None); app.state.sword_runtime=runtime; app.add_middleware(BodySizeLimitMiddleware,max_body_bytes=128*1024); bearer=HTTPBearer(auto_error=False)
    async def auth(c:HTTPAuthorizationCredentials|None=Depends(bearer)):
        if c is None or c.scheme.lower()!='bearer' or not secrets.compare_digest(c.credentials,token): raise HTTPException(401,detail={'code':'unauthorized'},headers={'WWW-Authenticate':'Bearer'})
    @app.get('/health')
    def health(): return {'status':'ok'}
    @app.get('/v1/play/context',dependencies=[Depends(auth)])
    def context(): return _safe_player_context(store)
    @app.get('/v1/ooc/audit',dependencies=[Depends(auth)])
    def audit():
        rt=store.read_json('state/runtime.json'); return {'campaign_id':store.campaign_id(),'revision':store.current_revision(),'world_time':rt['world_time'],'metrics':rt.get('metrics',{}),'mode':'read_only'}
    @app.post('/v1/commands/preview',dependencies=[Depends(auth)])
    def preview(req:CommandRequest):
        try: c=CommandEnvelope(**req.model_dump()); p=runtime.preview(c); return {'status':'ready','target_revision':c.expected_revision+1,'planning_reads':p.planning_reads,'writes':len(p.writes),'result':p.result}
        except Exception as e: raise HTTPException(422,detail={'code':'command_rejected','reason':type(e).__name__})
    @app.post('/v1/commands/execute',dependencies=[Depends(auth)])
    def execute(req:CommandRequest):
        if req.actor_id==RepositoryCommandPlanner.INTERNAL_ACTOR or req.mode!='gameplay': raise HTTPException(403,detail={'code':'player_surface_forbids_internal_mode'})
        try:
            c=CommandEnvelope(**req.model_dump()); x=runtime.execute(c); r=x.receipt
            return {'status':x.status,'request_id':r.request_id,'transaction_id':r.transaction_id,'campaign_id':r.campaign_id,'committed_revision':r.committed_revision,'committed_at':r.committed_at,'result':dict(r.result)}
        except Exception as e: raise HTTPException(409 if type(e).__name__=='StaleRevisionError' else 422,detail={'code':type(e).__name__})
    return app

def create_app_from_env()->FastAPI:
    root=os.environ.get('SWORD_CAMPAIGN_ROOT'); token=os.environ.get('SWORD_API_TOKEN')
    if not root or not token: raise RuntimeError('SWORD_CAMPAIGN_ROOT and SWORD_API_TOKEN are required')
    app=create_app(Path(root),token); runtime_root=os.environ.get('SWORD_RUNTIME_ROOT');
    if runtime_root:
        app.state.sword_runtime=SwordRuntime(Path(root),Path(runtime_root))
    app.state.sword_runtime.recover(); return app
