"""Small deterministic interleavings at the actual read and planner boundary."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from sword_runtime.api.operations import CampaignOperations
from sword_runtime.commands import CommandEnvelope
from sword_runtime.engine import SwordRuntime
from sword_runtime.store.repository import RepositoryStore
from sword_runtime.tx.locking import CampaignLock, SingleWriterLock
from sword_runtime.tx.errors import LockUnavailableError


def runtime_stub(tmp_path, planner):
    return SimpleNamespace(
        store=RepositoryStore(tmp_path), planner=planner,
        coordinator=SimpleNamespace(
            lock_path=tmp_path / 'campaign.lock', lock_timeout=1,
            _recover_locked=lambda: None,
            git=SimpleNamespace(assert_pristine=lambda: None),
        ),
    )


def test_nested_campaign_lock_excludes_other_threads(tmp_path):
    path = tmp_path / 'campaign.lock'
    with CampaignLock(path) as outer:
        with CampaignLock(path) as inner:
            assert outer.outermost and not inner.outermost
        with ThreadPoolExecutor(1) as pool:
            def contender():
                with pytest.raises(LockUnavailableError):
                    with SingleWriterLock(path, timeout=0):
                        pass
            pool.submit(contender).result(timeout=2)
    with SingleWriterLock(path, timeout=0):
        pass


def test_final_subclass_context_cannot_read_half_applied_files(tmp_path):
    for name in ('first', 'second'):
        (tmp_path / f'{name}.json').write_text('0')
    entered = threading.Event()
    attempted = threading.Event()
    runtime = runtime_stub(tmp_path, SimpleNamespace(_reset=lambda: None))

    class Base(CampaignOperations):
        def play_context(self):
            entered.set()
            return {'first': self.store.read_json('first.json')}

    class Complete(Base):
        def play_context(self):
            result = super().play_context()
            result['second'] = self.store.read_json('second.json')
            return result

    operations = Complete(runtime)
    with ThreadPoolExecutor(1) as pool:
        with CampaignLock(runtime.coordinator.lock_path):
            (tmp_path / 'first.json').write_text('1')
            def read():
                attempted.set()
                return operations.play_context()
            future = pool.submit(read)
            assert attempted.wait(1)
            assert not entered.wait(.05)
            (tmp_path / 'second.json').write_text('1')
        assert future.result(timeout=2) == {'first': 1, 'second': 1}


def test_shared_planner_isolated_for_whole_preview(tmp_path):
    first_planning = threading.Event()
    release_first = threading.Event()
    second_attempted = threading.Event()

    class Planner:
        def _reset(self):
            self.current = None

        def preview(self, command):
            self.current = command.request_id
            if command.request_id == 'first':
                first_planning.set()
                assert release_first.wait(2)
            return self.current

    runtime = runtime_stub(tmp_path, Planner())
    def command(name):
        return CommandEnvelope('campaign', name, 'char_tang_wei', 'scene_consequence', 1, 'now', {})
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(SwordRuntime.preview, runtime, command('first'))
        assert first_planning.wait(1)
        def second():
            second_attempted.set()
            return SwordRuntime.preview(runtime, command('second'))
        later = pool.submit(second)
        assert second_attempted.wait(1)
        assert not later.done()
        release_first.set()
        assert first.result(timeout=2) == 'first'
        assert later.result(timeout=2) == 'second'
