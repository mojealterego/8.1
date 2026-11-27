"""RPC coordinator. All principals arrive from a trusted transport boundary."""
from __future__ import annotations
from collections.abc import Callable
import time
from .deadline import DeadlineExceeded, ExecutionBudget
from .rpc import CallerIdentity, ContractError, decode_request, SCHEMA
from .adapter import DigitalLifeAdapter
from .replay import ReplayStore, ReplayError

class Gateway:
    def __init__(self, replay: ReplayStore, adapter: DigitalLifeAdapter, *,
                 clock: Callable[[], int] = time.monotonic_ns):
        self.replay = replay
        self.adapter = adapter
        self.clock = clock

    def handle(self, raw: bytes, principal: CallerIdentity) -> dict:
        started = self.clock()
        try:
            req = decode_request(raw, principal)
        except ContractError as exc:
            return {'schema':SCHEMA, 'status':'DENY','reason':str(exc)}
        budget = ExecutionBudget.start(started, req.deadline_ms, self.clock)
        expired = {'schema':SCHEMA, 'request_id':req.request_id,
                   'status':'OFFLINE', 'reason':'deadline_exceeded'}
        try:
            budget.check()
        except DeadlineExceeded:
            return expired
        try:
            first = self.replay.admit(principal.peer_id,principal.tenant,req.request_id)
        except ReplayError as exc:
            return {'schema':SCHEMA,'request_id':req.request_id,
                    'status':'DENY','reason':str(exc)}
        except Exception:
            return {'schema':SCHEMA,'request_id':req.request_id,
                    'status':'OFFLINE','reason':'replay_store_unavailable'}
        if not first:
            return {'schema':SCHEMA,'request_id':req.request_id,
                    'status':'DENY','reason':'replay_detected'}
        try:
            budget.check()
        except DeadlineExceeded:
            # Admission remains consumed; never retry an ambiguous operation.
            return expired
        return self.adapter.handle(raw, principal, budget=budget)
