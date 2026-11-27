"""Capability-bound host adapter: never reports fake Digital-Life execution.

The real Digital-Life engine has REQUIRED initialization arguments. Inject
explicit action handlers once configured, not nonexistent IntegratedEngine.process().
A network queryable must construct CallerIdentity from authenticated TLS identity,
not from untrusted source/tenant fields in the request body.
"""
from __future__ import annotations
from collections.abc import Callable, Mapping
import json
import time
from .deadline import DeadlineExceeded, ExecutionBudget
from .rpc import CallerIdentity, ContractError, RpcRequest, decode_request

Handler = Callable[[RpcRequest, CallerIdentity], object]
Executor = Callable[[Handler, RpcRequest, CallerIdentity, ExecutionBudget], object]


def _direct(handler: Handler, request: RpcRequest, principal: CallerIdentity,
            budget: ExecutionBudget) -> object:
    budget.check()
    return handler(request, principal)

class DigitalLifeAdapter:
    def __init__(self, handlers: Mapping[str, Handler], *, executor: Executor = _direct,
                 clock: Callable[[], int] = time.monotonic_ns) -> None:
        self.handlers = dict(handlers)
        if not callable(executor):
            raise ValueError("non_callable_executor")
        self.executor = executor
        self.clock = clock
        if any(not callable(h) for h in self.handlers.values()):
            raise ValueError("non_callable_handler")

    def handle(self, raw: bytes, principal: CallerIdentity, *,
               budget: ExecutionBudget | None = None) -> dict:
        started = self.clock() if budget is None else 0
        try:
            request = decode_request(raw, principal)
        except ContractError as exc:
            return {"schema": "omnicore.rpc.v1", "status": "DENY", "reason": str(exc)}
        if budget is None:
            budget = ExecutionBudget.start(started, request.deadline_ms, self.clock)
        expired = {"schema": "omnicore.rpc.v1", "request_id": request.request_id,
                   "status": "OFFLINE", "reason": "deadline_exceeded"}
        try:
            budget.check()
        except DeadlineExceeded:
            return expired
        handler = self.handlers.get(request.capability)
        if handler is None:
            return {"schema": "omnicore.rpc.v1", "request_id": request.request_id,
                    "status": "OFFLINE", "reason": "handler_unavailable"}
        try:
            body = self.executor(handler, request, principal, budget)
            budget.check()
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            if len(encoded.encode("utf-8")) > 32_768:
                raise ValueError("output_limit")
            budget.check()
        except DeadlineExceeded:
            return expired
        except Exception:
            try:
                budget.check()
            except DeadlineExceeded:
                return expired
            return {"schema": "omnicore.rpc.v1", "request_id": request.request_id,
                    "status": "OFFLINE", "reason": "handler_failure"}
        return {"schema": "omnicore.rpc.v1", "request_id": request.request_id,
                "status": "OK", "body": body}
