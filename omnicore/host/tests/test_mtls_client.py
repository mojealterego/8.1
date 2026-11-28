import datetime as dt
import hashlib
import json
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import time
import unittest
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from omnicore_host.mtls import MtlsEndpoint
from omnicore_host.mtls_client import MtlsClient, ExchangeError
from omnicore_host.rpc import CallerIdentity

RID = str(uuid.UUID(int=1))
RAW = json.dumps({'schema':'omnicore.rpc.v1','request_id':RID}).encode()
OK = {'schema':'omnicore.rpc.v1','request_id':RID,'status':'OK','body':{}}


def issue(root, name, ca=None, server=False):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,name)])
    now = dt.datetime.now(dt.timezone.utc)
    b = (x509.CertificateBuilder().subject_name(subject).issuer_name(ca[0].subject if ca else subject)
         .public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now-dt.timedelta(days=1)).not_valid_after(now+dt.timedelta(days=1))
         .add_extension(x509.BasicConstraints(ca=ca is None,path_length=0 if ca is None else None),critical=True))
    if ca:
        b = b.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH]),critical=False)
    if server:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName('omnicore.test')]),critical=False)
    cert = b.sign(ca[1] if ca else key,hashes.SHA256())
    cp,kp = root/(name+'.pem'),root/(name+'.key')
    cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    kp.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    return cert,key,cp,kp


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        root = Path(tmp.name)
        cls.ca = issue(root,'ca')
        cls.server = issue(root,'server',cls.ca,True)
        cls.device = issue(root,'device',cls.ca)
        cls.pin = cls.server[0].fingerprint(hashes.SHA256()).hex()
        principal = CallerIdentity('peer','tenant',frozenset({'home'}),frozenset({'system.status'}))
        cls.endpoint = MtlsEndpoint(cls.ca[2],cls.server[2],cls.server[3],{cls.device[0].fingerprint(hashes.SHA256()).hex():principal},timeout=1)

    def client(self, port, **kwargs):
        config = dict(address='127.0.0.1',port=port,hostname='omnicore.test',server_pin=self.pin,timeout=1)
        config.update(kwargs)
        return MtlsClient(self.ca[2],self.device[2],self.device[3],**config)

    def server_call(self, dispatch, **kwargs):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); listener.listen(1); listener.settimeout(2)
            calls=[]; errors=[]
            def wrapped(raw, principal):
                calls.append(raw)
                return dispatch(raw,principal)
            def run():
                try:
                    conn,_=listener.accept()
                    self.endpoint.serve(conn,wrapped)
                except (OSError,ValueError) as exc:
                    errors.append(exc)
            worker=threading.Thread(target=run)
            worker.start()
            try:
                try:
                    result=self.client(listener.getsockname()[1],**kwargs).exchange(RAW)
                except ExchangeError as exc:
                    result=exc
            finally:
                worker.join(3)
            self.assertFalse(worker.is_alive())
            return result,calls

    def test_actual_tls_exchange(self):
        response,calls=self.server_call(lambda *_:OK)
        self.assertEqual((response,calls),(OK,[RAW]))

    def test_bad_pin_pre_send(self):
        result,calls=self.server_call(lambda *_:OK,server_pin='0'*64)
        self.assertIsInstance(result,ExchangeError)
        self.assertFalse(result.may_have_executed)
        self.assertEqual(calls,[])

    def test_hostname_pre_send(self):
        result,calls=self.server_call(lambda *_:OK,hostname='wrong.test')
        self.assertIsInstance(result,ExchangeError)
        self.assertFalse(result.may_have_executed)
        self.assertEqual(calls,[])

    def test_response_correlation(self):
        result,calls=self.server_call(lambda *_:dict(OK,request_id=str(uuid.UUID(int=2))))
        self.assertIsInstance(result,ExchangeError)
        self.assertTrue(result.may_have_executed)
        self.assertEqual(calls,[RAW])

    def test_bad_schema(self):
        result,calls=self.server_call(lambda *_:dict(OK,schema='wrong'))
        self.assertIsInstance(result,ExchangeError)
        self.assertTrue(result.may_have_executed)
        self.assertEqual(calls,[RAW])

    def test_timeout_after_dispatch_no_retry(self):
        def slow(*_):
            time.sleep(.4)
            return OK
        result,calls=self.server_call(slow,timeout=.15)
        self.assertIsInstance(result,ExchangeError)
        self.assertTrue(result.may_have_executed)
        self.assertEqual(calls,[RAW])
        self.assertEqual(self.server_call(lambda *_:OK)[0],OK)

    def test_truncated_response(self):
        result,calls=self.server_call(lambda *_:None)
        self.assertIsInstance(result,ExchangeError)
        self.assertTrue(result.may_have_executed)
        self.assertEqual(calls,[RAW])

    def test_numeric_address_only(self):
        with self.assertRaises(ValueError):
            self.client(1234,address='localhost')

    def test_refused_connection(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            with self.assertRaises(ExchangeError) as caught:
                self.client(sock.getsockname()[1]).exchange(RAW)
        self.assertFalse(caught.exception.may_have_executed)

    def test_invalid_request_before_connect(self):
        with self.assertRaises(ValueError):
            self.client(1234).exchange(b'{}')

    def test_correlated_denial(self):
        denial={'schema':OK['schema'],'request_id':RID,'status':'DENY','reason':'replay_detected'}
        self.assertEqual(self.server_call(lambda *_:denial)[0],denial)

if __name__=='__main__': unittest.main()
