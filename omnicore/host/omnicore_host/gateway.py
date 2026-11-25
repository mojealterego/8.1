"""RPC coordinator. All principals arrive from a trusted transport boundary."""
from __future__ import annotations
from .rpc import CallerIdentity, ContractError, decode_request, SCHEMA
from .adapter import DigitalLifeAdapter
from .replay import ReplayStore, ReplayError

class Gateway:
    def __init__(self, replay: ReplayStore, adapter: DigitalLifeAdapter):
        self.replay = replay
        self.adapter = adapter

    def handle(self, raw: bytes, principal: CallerIdentity) -> dict:
        try:
            req = decode_request(raw, principal)
        except ContractError as exc:
            return {'schema':SCHEMA, 'status':'DENY','reason':str(exc)}
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
        return self.adapter.handle(raw, principal)
