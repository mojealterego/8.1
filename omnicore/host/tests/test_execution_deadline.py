import hashlib
import json
import time
import uuid

from omnicore_host.adapter import DigitalLifeAdapter
from omnicore_host.gateway import Gateway
from omnicore_host.replay import ReplayStore
from omnicore_host.rpc import CallerIdentity


def packet(ms=1000):
    return json.dumps(dict(schema='omnicore.rpc.v1', request_id=str(uuid.UUID(int=1)),
        source='omnicore-home', capability='intent.local', deadline_ms=ms,
        payload_sha256=hashlib.sha256(b'photo').hexdigest(),
        reply_to='device/local/session', payload='photo')).encode()


PRINCIPAL = CallerIdentity('peer', 'tenant', frozenset({'omnicore-home'}),
                           frozenset({'intent.local'}))


def test_late_handler_never_returns_success(tmp_path):
    def handler(req, principal):
        time.sleep(0.03)
        return {'action': 'open_gallery'}
    gate = Gateway(ReplayStore(tmp_path/'replay.db'), DigitalLifeAdapter({'intent.local': handler}))
    result = gate.handle(packet(10), PRINCIPAL)
    assert (result['status'], result.get('reason')) == ('OFFLINE', 'deadline_exceeded')
    assert gate.handle(packet(10), PRINCIPAL)['reason'] == 'replay_detected'


class Clock:
    now = 0

    def __call__(self):
        return self.now


def test_admission_consumes_same_budget(tmp_path):
    clock = Clock()
    class SlowAdmission(ReplayStore):
        def admit(self, *args, **kwargs):
            result = super().admit(*args, **kwargs)
            clock.now += 10_000_000
            return result
    calls = []
    store = SlowAdmission(tmp_path/'replay.db')
    gate = Gateway(store, DigitalLifeAdapter({'intent.local': lambda *a: calls.append(a)}), clock=clock)
    assert gate.handle(packet(10), PRINCIPAL)['reason'] == 'deadline_exceeded'
    assert not calls and store.count() == 1
    assert gate.handle(packet(10), PRINCIPAL)['reason'] == 'replay_detected'


def test_budget_not_reset_by_adapter(tmp_path):
    clock = Clock()
    class Admission(ReplayStore):
        def admit(self, *args, **kwargs):
            result = super().admit(*args, **kwargs)
            clock.now += 7_000_000
            return result
    def handler(*args):
        clock.now += 3_000_000
        return {'ok': True}
    gate = Gateway(Admission(tmp_path/'replay.db'), DigitalLifeAdapter({'intent.local': handler}), clock=clock)
    assert gate.handle(packet(10), PRINCIPAL)['reason'] == 'deadline_exceeded'


def test_direct_adapter_uses_budget():
    clock = Clock()
    def handler(*args):
        clock.now += 10_000_000
        return {'ok': True}
    adapter = DigitalLifeAdapter({'intent.local': handler}, clock=clock)
    assert adapter.handle(packet(10), PRINCIPAL)['reason'] == 'deadline_exceeded'


def test_in_budget_success(tmp_path):
    clock = Clock()
    def handler(*args):
        clock.now += 9_000_000
        return {'ok': True}
    gate = Gateway(ReplayStore(tmp_path/'replay.db'), DigitalLifeAdapter({'intent.local': handler}), clock=clock)
    assert gate.handle(packet(10), PRINCIPAL)['status'] == 'OK'


def test_isolated_local_handler_actual_worker(tmp_path):
    from omnicore_host.local_executor import isolated_local_adapter
    gate = Gateway(ReplayStore(tmp_path/'replay.db'), isolated_local_adapter())
    result = gate.handle(packet(), PRINCIPAL)
    assert result['status'] == 'OK'
    assert result['body'] == {'action': 'open_gallery', 'offline': True}
    assert gate.handle(packet(), PRINCIPAL)['reason'] == 'replay_detected'


def test_isolated_executor_rejects_arbitrary_callable():
    from omnicore_host.local_executor import LocalProcessExecutor
    called = []
    adapter = DigitalLifeAdapter({'intent.local': lambda *a: called.append(a)}, executor=LocalProcessExecutor())
    assert adapter.handle(packet(), PRINCIPAL)['reason'] == 'handler_failure'
    assert not called


def test_worker_is_killed_and_reaped_on_timeout(tmp_path):
    import os
    import sys
    import pytest
    from omnicore_host.deadline import DeadlineExceeded, ExecutionBudget
    from omnicore_host.local_executor import _run_worker
    pidfile = tmp_path/'pid'
    marker = tmp_path/'late'
    script = ('import os,time,pathlib,sys; '
              'pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); '
              'time.sleep(1.0); pathlib.Path(sys.argv[2]).touch()')
    budget = ExecutionBudget.start(time.monotonic_ns(), 300, time.monotonic_ns)
    with pytest.raises(DeadlineExceeded):
        _run_worker([sys.executable, '-I', '-S', '-c', script, str(pidfile), str(marker)], b'', budget)
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not marker.exists()
