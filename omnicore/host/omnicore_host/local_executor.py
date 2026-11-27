"""Optional process lifecycle isolation for the two trusted offline handlers.

No arbitrary executable or callable supplied by a request is accepted. This is
not a privilege sandbox: the child has the service UID. NANO caps apply in the worker.
"""
from __future__ import annotations
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

from .adapter import DigitalLifeAdapter, Handler
from .deadline import DeadlineExceeded, ExecutionBudget
from .local_services import local_handlers
from .nano_resources import NanoGovernor
from .rpc import CallerIdentity, RpcRequest

_WORKER = Path(__file__).with_name('local_worker.py').resolve()
_DEFAULT_GOVERNOR = NanoGovernor()


def _run_worker(command: list[str], payload: bytes, budget: ExecutionBudget) -> bytes:
    # Only trusted workers without subprocess descendants are supported.
    budget.check()
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, env={}, close_fds=True) as proc:
        try:
            output, _ = proc.communicate(payload, timeout=budget.remaining())
            budget.check()
        except (subprocess.TimeoutExpired, DeadlineExceeded) as exc:
            proc.kill()
            proc.communicate()
            raise DeadlineExceeded('deadline_exceeded') from exc
        except BaseException:
            proc.kill()
            proc.communicate()
            raise
        if proc.returncode != 0 or len(output) > 32_768:
            raise ValueError('worker_failure')
        return output


class LocalProcessExecutor:
    def __init__(self, *, governor: NanoGovernor | None = None):
        self.governor = _DEFAULT_GOVERNOR if governor is None else governor

    def __call__(self, handler: Handler, request: RpcRequest, principal: CallerIdentity,
                 budget: ExecutionBudget) -> object:
        if local_handlers().get(request.capability) is not handler:
            raise ValueError('worker_handler_not_allowed')
        payload = json.dumps({'request': asdict(request), 'principal': {
            'peer_id': principal.peer_id, 'tenant': principal.tenant,
            'allowed_sources': sorted(principal.allowed_sources),
            'allowed_capabilities': sorted(principal.allowed_capabilities),
        }}, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(payload) > 262_144:
            raise ValueError('worker_input_limit')
        with self.governor.admit():
            output = _run_worker([sys.executable, '-I', '-S', str(_WORKER)], payload, budget)
            return json.loads(output.decode('utf-8'))


def isolated_local_adapter() -> DigitalLifeAdapter:
    return DigitalLifeAdapter(local_handlers(), executor=LocalProcessExecutor())
