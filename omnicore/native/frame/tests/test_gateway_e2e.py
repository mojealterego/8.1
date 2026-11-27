"""Native client -> actual host gateway -> SQLite -> offline handler (Linux)."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1] / 'host'))
from omnicore_host.adapter import DigitalLifeAdapter
from omnicore_host.gateway import Gateway
from omnicore_host.local_services import local_handlers
from omnicore_host.replay import ReplayStore
from omnicore_host.rpc import CallerIdentity
from omnicore_host.server import LocalHostServer
from omnicore_host.transport import IdentityRegistry, UnixRpcEndpoint, get_peer_credential


class GatewayE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build = tempfile.TemporaryDirectory()
        cls.addClassCleanup(build.cleanup)
        cls.probe = Path(build.name) / 'unix_probe'
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-I' + str(ROOT / 'src'),
                        str(ROOT / 'src/frame.c'), str(ROOT / 'src/unix_client.c'),
                        str(ROOT / 'tests/unix_probe.c'), '-o', str(cls.probe)], check=True)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / 'rpc.sock'
        a, b = socket.socketpair()
        with a, b:
            self.label = get_peer_credential(a).security_context
        self.principal = CallerIdentity('peer', 'tenant', frozenset({'omnicore-home'}),
                                       frozenset({'intent.local', 'system.status', 'rag.query'}))

    @contextmanager
    def server(self, *, capacity=10):
        store = ReplayStore(self.root / 'replay.db', capacity=capacity)
        gate = Gateway(store, DigitalLifeAdapter(local_handlers()))
        endpoint = UnixRpcEndpoint(gate, IdentityRegistry({(os.getuid(), self.label): self.principal}))
        server = LocalHostServer(self.path, endpoint)
        stop, started = threading.Event(), threading.Event()
        errors = []
        def run():
            try:
                server.serve_forever(stop=stop, started=started)
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            self.assertTrue(started.wait(2), errors)
            yield store
        finally:
            stop.set()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertFalse(self.path.exists())

    def request(self, n=1, **changes):
        payload = 'proszę otwórz galerię'
        data = dict(schema='omnicore.rpc.v1', request_id=f'00000000-0000-4000-8000-{n:012x}',
                    source='omnicore-home', capability='intent.local', deadline_ms=1000,
                    payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                    reply_to='device/local/session', payload=payload)
        data.update(changes)
        return json.dumps(data, ensure_ascii=True).encode()

    def exchange(self, raw, *, uid=None, label=None):
        p = subprocess.run([str(self.probe), str(self.path), str(os.getuid() if uid is None else uid),
                            self.label if label is None else label, '2000', '65536'],
                           input=raw, capture_output=True, timeout=5)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, b'')
        line, body = p.stdout.split(b'\n', 1)
        code, length = map(int, line.split())
        self.assertEqual(length, len(body))
        return code, json.loads(body) if body else None

    def response(self, raw):
        code, body = self.exchange(raw)
        self.assertEqual(code, 0)
        self.assertEqual(body['schema'], 'omnicore.rpc.v1')
        return body

    def test_local_intent(self):
        with self.server() as store:
            body = self.response(self.request())
            self.assertEqual(body['status'], 'OK')
            self.assertEqual(body['body'], {'action': 'open_gallery', 'offline': True})
            self.assertEqual(store.count(), 1)

    def test_status_truthful(self):
        with self.server():
            body = self.response(self.request(capability='system.status'))
            self.assertEqual(body['body']['remote_ai'], 'not_configured')

    def test_replay_persists_across_server_restart(self):
        raw = self.request()
        with self.server():
            self.assertEqual(self.response(raw)['status'], 'OK')
        with self.server() as store:
            self.assertEqual(self.response(raw)['reason'], 'replay_detected')
            self.assertEqual(store.count(), 1)

    def test_policy_denies_before_admission(self):
        with self.server() as store:
            for raw, reason in [(self.request(source='impostor'), 'untrusted_source'),
                                (self.request(capability='media.offload'), 'capability_denied'),
                                (self.request(payload_sha256='0'*64), 'hash_mismatch')]:
                self.assertEqual(self.response(raw)['reason'], reason)
            self.assertEqual(store.count(), 0)

    def test_unconfigured_remote_handler(self):
        with self.server():
            body = self.response(self.request(capability='rag.query'))
            self.assertEqual((body['status'], body['reason']), ('OFFLINE', 'handler_unavailable'))

    def test_capacity_denies_new_requests(self):
        with self.server(capacity=1) as store:
            self.assertEqual(self.response(self.request())['status'], 'OK')
            self.assertEqual(self.response(self.request(2))['reason'], 'replay_capacity_exhausted')
            self.assertEqual(store.count(), 1)

    def test_wrong_server_identity_sends_no_request(self):
        with self.server() as store:
            self.assertEqual(self.exchange(self.request(), uid=os.getuid()+1), (4, None))
            self.assertEqual(self.exchange(self.request(), label='wrong-label'), (4, None))
            self.assertEqual(store.count(), 0)

    def test_surrogate_payload_denied_and_service_survives(self):
        with self.server() as store:
            body = self.response(self.request(payload='\ud800'))
            self.assertEqual((body['status'], body['reason']), ('DENY', 'invalid_payload_encoding'))
            self.assertEqual(store.count(), 0)
            self.assertEqual(self.response(self.request())['status'], 'OK')


if __name__ == '__main__':
    unittest.main()
