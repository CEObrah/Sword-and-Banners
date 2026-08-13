import json
from pathlib import Path
import pytest
from conftest import execute, meta

class Crash(BaseException): pass

def test_normal_duplicate_and_stale(campaign):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.engine import SwordRuntime
    from sword_runtime.tx.errors import StaleRevisionError
    m=meta(campaign); r=SwordRuntime(campaign)
    c=CommandEnvelope(m['campaign_id'],'dup-1','char_tang_wei','scene_consequence',m['revision'],m['time'],{'summary':'transaction proof'})
    first=r.execute(c); assert first.status=='committed'
    assert r.execute(c).status=='duplicate'
    stale=CommandEnvelope(m['campaign_id'],'stale-1','char_tang_wei','scene_consequence',m['revision'],m['time'],{'summary':'stale'})
    with pytest.raises(StaleRevisionError): r.execute(stale)

def test_crash_after_apply_rolls_back(campaign):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.engine import SwordRuntime
    m=meta(campaign); r=SwordRuntime(campaign)
    c=CommandEnvelope(m['campaign_id'],'crash-apply','char_tang_wei','scene_consequence',m['revision'],m['time'],{'summary':'will rollback'})
    def inject(phase,manifest):
        if phase=='after_apply': raise Crash()
    with pytest.raises(Crash): r.execute(c,crash_injector=inject)
    assert meta(campaign)['revision']==m['revision']+1
    r2=SwordRuntime(campaign); decisions=r2.recover()
    assert any(d.action=='rolled_back' for d in decisions)
    assert meta(campaign)['revision']==m['revision']

def test_crash_after_commit_finalizes(campaign):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.engine import SwordRuntime
    m=meta(campaign); r=SwordRuntime(campaign)
    c=CommandEnvelope(m['campaign_id'],'crash-commit','char_tang_wei','scene_consequence',m['revision'],m['time'],{'summary':'commit survives'})
    def inject(phase,manifest):
        if phase=='after_git_commit': raise Crash()
    with pytest.raises(Crash): r.execute(c,crash_injector=inject)
    assert meta(campaign)['revision']==m['revision']+1
    r2=SwordRuntime(campaign); decisions=r2.recover()
    assert any(d.action=='finalized_commit' for d in decisions)
    assert r2.coordinator.receipts.get('crash-commit') is not None

def test_manifest_owned_atomic_temp_does_not_strand_recovery(campaign):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.engine import SwordRuntime
    m=meta(campaign); r=SwordRuntime(campaign)
    c=CommandEnvelope(m['campaign_id'],'crash-temp','char_tang_wei','scene_consequence',m['revision'],m['time'],{'summary':'temp proof'})
    def inject(phase,manifest):
        if phase=='after_apply':
            target=Path(campaign)/'state/meta.json'
            temp=target.parent/f'.{target.name}.owned.tmp'
            temp.write_bytes(target.read_bytes())
            raise Crash()
    with pytest.raises(Crash): r.execute(c,crash_injector=inject)
    SwordRuntime(campaign).recover()
    assert meta(campaign)['revision']==m['revision']
    assert not list((Path(campaign)/'state').glob('.meta.json.*.tmp'))

def test_local_commit_remains_valid_when_replication_fails(campaign):
    from sword_runtime.replication import BestEffortReplicator
    before=meta(campaign)['revision']; x=execute(campaign,'scene_consequence',{'summary':'local first'})
    assert x.status=='committed' and meta(campaign)['revision']==before+1
    rep=BestEffortReplicator(Path(campaign),Path(campaign)/'.sword-runtime','missing-remote','main')
    assert rep.replicate(x.commit_hash) is False
    status=json.loads((Path(campaign)/'.sword-runtime/replication.json').read_text())
    assert status['status']=='pending'
    assert meta(campaign)['revision']==before+1

def test_same_request_retries_after_precommit_rollback(campaign):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.engine import SwordRuntime
    from conftest import meta
    m=meta(campaign)
    command=CommandEnvelope(m['campaign_id'],'retry-after-rollback','char_tang_wei','scene_consequence',m['revision'],m['time'],{'summary':'retry-safe scene'},mode='gameplay')
    rt=SwordRuntime(campaign)
    def crash(phase, manifest):
        if phase=='after_apply':
            raise RuntimeError('injected precommit crash')
    with pytest.raises(RuntimeError):
        rt.execute(command,crash_injector=crash)
    assert meta(campaign)['revision']==m['revision']
    result=SwordRuntime(campaign).execute(command)
    assert result.status=='committed'
    assert result.receipt.committed_revision==m['revision']+1

def test_terminal_wal_history_is_not_scanned_during_recovery(campaign, monkeypatch):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.engine import SwordRuntime

    runtime = SwordRuntime(campaign)
    for index in range(12):
        m = meta(campaign)
        command = CommandEnvelope(
            m['campaign_id'],
            f'terminal-history-{index}',
            'char_tang_wei',
            'scene_consequence',
            m['revision'],
            m['time'],
            {'summary': f'terminal WAL proof {index}'},
        )
        assert runtime.execute(command).status == 'committed'

    wal = runtime.coordinator.wal
    assert not tuple(wal.pending_directory.glob('*.json'))
    assert len(tuple(wal.terminal_directory.glob('*.json'))) == 12

    original = wal._read_path
    def bounded_read(path):
        if Path(path).parent == wal.terminal_directory:
            raise AssertionError('ordinary recovery scanned terminal WAL history')
        return original(path)
    monkeypatch.setattr(wal, '_read_path', bounded_read)

    assert runtime.recover() == ()


def test_legacy_flat_wal_migrates_then_leaves_recovery_set_empty(campaign):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.engine import SwordRuntime

    m = meta(campaign)
    runtime = SwordRuntime(campaign)
    command = CommandEnvelope(
        m['campaign_id'],
        'legacy-flat-proof',
        'char_tang_wei',
        'scene_consequence',
        m['revision'],
        m['time'],
        {'summary': 'legacy flat WAL migration proof'},
    )
    assert runtime.execute(command).status == 'committed'

    wal = runtime.coordinator.wal
    terminal = next(wal.terminal_directory.glob('*.json'))
    legacy = wal.directory / terminal.name
    terminal.replace(legacy)
    assert legacy.exists()

    migrated = SwordRuntime(campaign)
    assert not tuple(migrated.coordinator.wal.directory.glob('*.json'))
    assert len(tuple(migrated.coordinator.wal.pending_directory.glob('*.json'))) == 1
    assert migrated.recover() == ()
    assert not tuple(migrated.coordinator.wal.pending_directory.glob('*.json'))
    assert len(tuple(migrated.coordinator.wal.terminal_directory.glob('*.json'))) == 1
