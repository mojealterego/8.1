"""Capability-bound host adapter: never reports fake Digital-Life execution.

The real Digital-Life engine has REQUIRED initialization arguments. Inject
explicit action handlers once configured, not nonexistent IntegratedEngine.process().
A network queryable must construct CallerIdentity from authenticated TLS identity,
not from untrusted source/tenant fields in the request body.
"""
from __future__ import annotations
from collections.abc import Callable, Mapping
import json
from .rpc import CallerIdentity, ContractError, RpcRequest, decode_request

Handler = Callable[[RpcRequest, CallerIdentity], object]

class DigitalLifeAdapter:
    def __init__(self, handlers: Mapping[str, Handler]) -> None:
        self.handlers = dict(handlers)
        if any(not callable(h) for h in self.handlers.values()):
            raise ValueError("non_callable_handler")

    def handle(self, raw: bytes, principal: CallerIdentity) -> dict:
        try:
            request = decode_request(raw, principal)
        except ContractError as exc:
            return {"schema": "omnicore.rpc.v1", "status": "DENY", "reason": str(exc)}
        handler = self.handlers.get(request.capability)
        if handler is None:
            return {"schema": "omnicore.rpc.v1", "request_id": request.request_id,
                    "status": "OFFLINE", "reason": "handler_unavailable"}
        try:
            body = handler(request, principal)
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            if len(encoded.encode("utf-8")) > 32_768:
                raise ValueError("output_limit")
        except Exception:
            return {"schema": "omnicore.rpc.v1", "request_id": request.request_id,
                    "status": "OFFLINE", "reason": "handler_failure"}
        return {"schema": "omnicore.rpc.v1", "request_id": request.request_id,
                "status": "OK", "body": body}
