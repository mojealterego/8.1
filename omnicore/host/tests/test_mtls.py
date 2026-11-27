import datetime as dt
import hashlib
import json
from pathlib import Path
import socket
import ssl
import struct
import tempfile
import threading
import unittest
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from omnicore_host.mtls import MtlsEndpoint, client_context
from omnicore_host.rpc import CallerIdentity, decode_request, ContractError
from omnicore_host.adapter import DigitalLifeAdapter
from omnicore_host.gateway import Gateway
from omnicore_host.local_services import local_handlers
from omnicore_host.replay import ReplayStore


def certificate(root, name, issuer=None, *, server=False):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(subject)
               .issuer_name(issuer[0].subject if issuer else subject).public_key(key.public_key())
               .serial_number(x509.random_serial_number()).not_valid_before(now-dt.timedelta(days=1))
               .not_valid_after(now+dt.timedelta(days=1)))
    if issuer:
        builder = builder.add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        builder = builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        if server:
            builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
    else:
        builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
    cert = builder.sign(issuer[1] if issuer else key, hashes.SHA256())
    cp, kp = root/(name+'.pem'), root/(name+'.key')
    cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    kp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert, key, cp, kp


def packet(source='omnicore-home'):
    return json.dumps(dict(schema='omnicore.rpc.v1', request_id=str(uuid.UUID(int=1)), source=source,
        capability='system.status', deadline_ms=1000, payload_sha256=hashlib.sha256(b'').hexdigest(),
        reply_to='device/local/session', payload='')).encode()


def read_exact(sock, size):
    result = bytearray()
    while len(result) < size:
        part = sock.recv(size-len(result))
        if not part:
            raise EOFError('closed')
        result.extend(part)
    return bytes(result)


class MtlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        root = Path(temp.name)
        cls.ca = certificate(root, 'ca')
        cls.other_ca = certificate(root, 'other-ca')
        cls.server = certificate(root, 'omnicore.test', cls.ca, server=True)
        cls.good = certificate(root, 'device-one', cls.ca)
        cls.unknown = certificate(root, 'device-two', cls.ca)
        cls.foreign = certificate(root, 'foreign', cls.other_ca)

    def setUp(self):
        self.principal = CallerIdentity('peer-one', 'tenant-one', frozenset({'omnicore-home'}), frozenset({'system.status'}))
        self.calls = []
        self.endpoint = MtlsEndpoint(self.ca[2], self.server[2], self.server[3],
            {self.good[0].fingerprint(hashes.SHA256()).hex(): self.principal}, timeout=0.5)

    def dispatch(self, raw, principal):
        self.calls.append(principal)
        try:
            req = decode_request(raw, principal)
        except ContractError as exc:
            return {'status':'DENY','reason':str(exc)}
        return {'status':'OK','tenant':principal.tenant,'request_id':req.request_id}

    def exchange(self, *, cert=None, hostname='omnicore.test', raw=None, context=None, frame=None, dispatch=None):
        a,b = socket.socketpair()
        results = []
        def worker():
            try:
                self.endpoint.serve(a, self.dispatch if dispatch is None else dispatch)
            except (OSError, ValueError) as exc:
                results.append(type(exc).__name__)
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            if context is None:
                cert = self.good if cert is None else cert
                context = client_context(self.ca[2], cert[2], cert[3])
            b.settimeout(2)
            with context.wrap_socket(b, server_hostname=hostname) as conn:
                raw = packet() if raw is None else raw
                conn.sendall(struct.pack('!I',len(raw))+raw if frame is None else frame)
                size, = struct.unpack('!I',read_exact(conn,4))
                return json.loads(read_exact(conn,size))
        finally:
            b.close()
            thread.join(3)
            self.assertFalse(thread.is_alive())
            a.close()

    def test_trusted_cert_maps_principal(self):
        self.assertEqual(self.exchange()['tenant'], 'tenant-one')
        self.assertEqual(self.calls, [self.principal])

    def test_unknown_cert_same_ca_denied(self):
        with self.assertRaises((OSError, EOFError)):
            self.exchange(cert=self.unknown)
        self.assertEqual(self.calls, [])

    def test_foreign_ca_denied(self):
        with self.assertRaises((OSError, EOFError)):
            self.exchange(cert=self.foreign)
        self.assertEqual(self.calls, [])

    def test_missing_client_certificate_denied(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=str(self.ca[2]))
        context.set_alpn_protocols(['omnicore-rpc/1'])
        with self.assertRaises((OSError, EOFError)):
            self.exchange(context=context)
        self.assertEqual(self.calls, [])

    def test_wrong_hostname_denied(self):
        with self.assertRaises(ssl.SSLError):
            self.exchange(hostname='wrong.test')
        self.assertEqual(self.calls, [])

    def test_source_spoof_denied(self):
        self.assertEqual(self.exchange(raw=packet('impostor'))['reason'], 'untrusted_source')

    def test_wrong_alpn_denied(self):
        context = client_context(self.ca[2], self.good[2], self.good[3])
        context.set_alpn_protocols(['other/1'])
        with self.assertRaises((OSError, EOFError)):
            self.exchange(context=context)
        self.assertEqual(self.calls, [])

    def test_oversize_denied_before_dispatch(self):
        with self.assertRaises((OSError, EOFError)):
            self.exchange(frame=struct.pack('!I',65537))
        self.assertEqual(self.calls, [])

    def test_reconnect_after_failure(self):
        with self.assertRaises((OSError, EOFError)):
            self.exchange(cert=self.unknown)
        self.assertEqual(self.exchange()['status'], 'OK')
        self.assertEqual(self.calls, [self.principal])

    def test_handshake_timeout(self):
        a,b = socket.socketpair()
        errors = []
        def run():
            try:
                self.endpoint.serve(a,self.dispatch)
            except OSError as exc:
                errors.append(exc)
        with a,b:
            thread=threading.Thread(target=run, daemon=True)
            thread.start(); thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors),1)
        self.assertIsInstance(errors[0],TimeoutError)
        self.assertEqual(self.calls,[])

    def test_actual_gateway_replay_across_tls_connections(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/'replay.db'
            gateway = Gateway(ReplayStore(db), DigitalLifeAdapter(local_handlers()))
            first = self.exchange(dispatch=gateway.handle)
            self.assertEqual(first['status'], 'OK')
            self.assertEqual(first['body']['remote_ai'], 'not_configured')
            recreated = Gateway(ReplayStore(db), DigitalLifeAdapter(local_handlers()))
            self.assertEqual(self.exchange(dispatch=recreated.handle)['reason'], 'replay_detected')
            self.assertEqual(recreated.replay.count(), 1)

    def test_certificate_rotation_replaces_registry(self):
        self.endpoint = MtlsEndpoint(self.ca[2], self.server[2], self.server[3],
            {self.unknown[0].fingerprint(hashes.SHA256()).hex(): self.principal}, timeout=0.5)
        with self.assertRaises((OSError, EOFError)):
            self.exchange()
        self.assertEqual(self.exchange(cert=self.unknown)['status'], 'OK')
        self.assertEqual(self.calls, [self.principal])

    def test_tls_1_2_compatibility(self):
        context = client_context(self.ca[2], self.good[2], self.good[3])
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        self.assertEqual(self.exchange(context=context)['status'], 'OK')
