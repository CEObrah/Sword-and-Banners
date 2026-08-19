"""Best-effort local-first Git replication.

A valid local campaign commit is canonical immediately. Remote delivery is a
separate retryable durability concern and never rolls a committed transaction
back when the network is unavailable.
"""
from __future__ import annotations
import json, os, subprocess
from pathlib import Path
from typing import Mapping

class ReplicationStatus:
    def __init__(self, runtime_root: Path): self.path=Path(runtime_root)/"replication.json"
    def write(self, record: Mapping[str, object]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp=self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(dict(record),sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
        os.replace(tmp,self.path)

class BestEffortReplicator:
    def __init__(self, repo: Path, runtime_root: Path, remote='origin', branch='main'):
        self.repo=Path(repo); self.remote=remote; self.branch=branch; self.status=ReplicationStatus(Path(runtime_root))
    def replicate(self, commit_hash: str) -> bool:
        env=dict(os.environ); env['GIT_TERMINAL_PROMPT']='0'
        try:
            cp=subprocess.run(['git','-C',str(self.repo),'push',self.remote,f'{commit_hash}:refs/heads/{self.branch}'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env,timeout=30,check=False)
            ok=cp.returncode==0
        except (OSError,subprocess.TimeoutExpired): ok=False
        self.status.write({'commit_hash':commit_hash,'remote':self.remote,'branch':self.branch,'status':'replicated' if ok else 'pending'})
        return ok
