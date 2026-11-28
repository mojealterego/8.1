"""Actual signed ingress, gateway and SQLite behind a simulated session API."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from omnicore_host.adapter import DigitalLifeAdapter
from omnicore_host.gateway import Gateway
from omnicore_host.local_services import local_handlers
from omnicore_host.replay import ReplayStore
from omnicore_host.rpc import CallerIdentity
from omnicore_host.zenoh_boundary import SignedIngress, route, sign_request, verify_reply
from omnicore_host.zenoh_session import SessionManager


class Payload:
    def __init__(self, data): self.data = data
    def __len__(self): return len(self.data)
    def to_bytes(self): return self.data


class Query:
    def __init__(self, key, data):
        self.key_expr, self.payload = key, Payload(data)
        self.replies, self.drops = [], 0
    def reply(self, key, data): self.replies.append((key, data))
    def drop(self): self.drops += 1


class Session:
    def __init__(self):
        self.callbacks = {}
        self.closed = False
    def declare_queryable(self, key, handler):
        self.callbacks[key] = handler
        return self
    def undeclare(self): pass
    def close(self): self.closed = True
    def deliver(self, key, wire):
        q = Query(key, wire)
        # Deliberately allow stale delivery even after close to test fencing.
        self.callbacks[key](q)
        return q


class IntegrationTests(unittest.TestCase):
    def test_reconfigure_preserves_real_replay_and_signed_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            d, s = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
            p = CallerIdentity('peer', 'tenant', frozenset({'home'}), frozenset({'intent.local'}))
            store = ReplayStore(Path(tmp)/'replay.db')
            ingress = SignedIngress('node', Gateway(store, DigitalLifeAdapter(local_handlers())),
                                    [(d.public_key(), p)], s)
            key = route('node', p, 'intent.local')
            def signed(n):
                raw = json.dumps(dict(schema='omnicore.rpc.v1', request_id=str(uuid.UUID(int=n)),
                    source='home', capability='intent.local', deadline_ms=1000,
                    payload_sha256=hashlib.sha256(b'photo').hexdigest(),
                    reply_to='device/local/session', payload='photo')).encode()
                return sign_request(d, key, raw, int(time.time())+20)
            first, second = signed(1), signed(2)
            manager = SessionManager(ingress)
            self.addCleanup(manager.stop)
            old, new = Session(), Session()
            manager.start(lambda: old)
            q = old.deliver(key, first)
            self.assertEqual(q.drops, 1)
            self.assertEqual(verify_reply(s.public_key(),key,first,q.replies[0][1])['status'], 'OK')
            manager.reconfigure(lambda: new)
            self.assertTrue(old.closed)
            stale = old.deliver(key, second)
            self.assertEqual((stale.replies, stale.drops), ([], 1))
            self.assertEqual(store.count(), 1)
            duplicate = new.deliver(key, first)
            self.assertEqual(verify_reply(s.public_key(),key,first,duplicate.replies[0][1])['reason'], 'replay_detected')
            fresh = new.deliver(key, second)
            self.assertEqual(verify_reply(s.public_key(),key,second,fresh.replies[0][1])['body'],
                             {'action':'open_gallery','offline':True})
            self.assertEqual(store.count(), 2)
            manager.stop()
            self.assertTrue(new.closed)


if __name__ == '__main__': unittest.main()
