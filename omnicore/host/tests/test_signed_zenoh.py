import hashlib
import json
import time
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from omnicore_host.adapter import DigitalLifeAdapter
from omnicore_host.gateway import Gateway
from omnicore_host.local_services import local_handlers
from omnicore_host.replay import ReplayStore
from omnicore_host.rpc import CallerIdentity
from omnicore_host.zenoh_boundary import SignedIngress, route, sign_request, verify_reply, BoundaryError


@pytest.fixture
def setup(tmp_path):
    device = Ed25519PrivateKey.generate()
    server = Ed25519PrivateKey.generate()
    identity = CallerIdentity('device1', 'tenant1', frozenset({'home'}), frozenset({'intent.local'}))
    gate = Gateway(ReplayStore(tmp_path/'replay.db'), DigitalLifeAdapter(local_handlers()))
    now = int(time.time())
    ingress = SignedIngress('node1', gate, [(device.public_key(), identity)], server, clock=lambda: now)
    key = route('node1', identity, 'intent.local')
    return device, server, identity, gate, now, ingress, key


def packet(n=1, **changes):
    data = dict(schema='omnicore.rpc.v1', request_id=str(uuid.UUID(int=n)), source='home',
                capability='intent.local', deadline_ms=1000, payload_sha256=hashlib.sha256(b'photo').hexdigest(),
                reply_to='device/local/session', payload='photo')
    data.update(changes)
    return json.dumps(data).encode()


def test_real_gateway_and_signed_reply(setup):
    d,s,_,g,n,i,k = setup
    wire = sign_request(d,k,packet(),n+10)
    reply = verify_reply(s.public_key(),k,wire,i.handle(k,wire))
    assert reply['body'] == {'action':'open_gallery','offline':True}
    assert g.replay.count() == 1


def test_replay_after_recreation_and_key_rotation(setup):
    d,s,p,g,n,i,k = setup
    first = sign_request(d,k,packet(),n+10)
    i.handle(k,first)
    new = Ed25519PrivateKey.generate()
    recreated = SignedIngress('node1',Gateway(ReplayStore(g.replay.path),DigitalLifeAdapter(local_handlers())),[(new.public_key(),p)],s,clock=lambda:n)
    with pytest.raises(BoundaryError): recreated.handle(k,first)
    second = sign_request(new,k,packet(),n+10)
    result = verify_reply(s.public_key(),k,second,recreated.handle(k,second))
    assert result['reason'] == 'replay_detected'
    assert g.replay.count() == 1


@pytest.mark.parametrize('mode',['tampered','wrong_key','wrong_tenant','wrong_peer','wrong_node','wrong_cap','wildcard','expired','far_future','forged_source','forged_capability','oversize','truncated'])
def test_denied_before_admission(setup,mode):
    d,s,p,g,n,i,k = setup
    raw = packet()
    expiry = n+10
    signer = d
    if mode == 'wrong_key': signer = Ed25519PrivateKey.generate()
    if mode == 'wrong_tenant': k = k.replace('tenant1','tenant2')
    if mode == 'wrong_peer': k = k.replace('device1','device2')
    if mode == 'wrong_node': k = k.replace('node1','node2')
    if mode == 'wrong_cap': k = k.replace('intent.local','system.status')
    if mode == 'wildcard': k = k.replace('device1','*')
    if mode == 'expired': expiry = n
    if mode == 'far_future': expiry = n+31
    if mode == 'forged_source': raw = packet(source='other')
    if mode == 'forged_capability': raw = packet(capability='system.status')
    # sign a legitimate route then change it to a wildcard, which the signing helper itself rejects.
    wire = sign_request(signer,k if mode != 'wildcard' else k.replace('*','device1'),raw,expiry)
    if mode == 'tampered': wire = wire[:-1] + bytes([wire[-1]^1])
    if mode == 'oversize': wire += b'x'*65536
    if mode == 'truncated': wire = wire[:30]
    with pytest.raises(BoundaryError): i.handle(k,wire)
    assert g.replay.count() == 0


def test_response_bound_to_original_request_and_key(setup):
    d,s,p,g,n,i,k = setup
    wire = sign_request(d,k,packet(),n+10)
    reply = i.handle(k,wire)
    for key,req,data in [(k,sign_request(d,k,packet(2),n+10),reply),(k.replace('node1','node2'),wire,reply),(k,wire,reply[:-1]+bytes([reply[-1]^1]))]:
        with pytest.raises(BoundaryError): verify_reply(s.public_key(),key,req,data)


def test_short_replay_window_rejected(setup):
    d,s,p,g,n,i,k = setup
    with pytest.raises(ValueError):
        SignedIngress('node1',Gateway(ReplayStore(g.replay.path,retention_seconds=30),DigitalLifeAdapter(local_handlers())),[(d.public_key(),p)],s)


def test_queryable_contract(setup):
    from omnicore_host.zenoh_boundary import declare_queryables
    d,s,p,g,n,i,k = setup
    wire = sign_request(d,k,packet(),n+10)
    class Payload:
        def __init__(self, data): self.data = data
        def __len__(self): return len(self.data)
        def to_bytes(self): return self.data
    class Query:
        def __init__(self,key,data):
            self.key_expr, self.payload = key, Payload(data)
            self.replies, self.drops = [], 0
        def reply(self,key,data): self.replies.append((key,data))
        def drop(self): self.drops += 1
    class Session:
        def declare_queryable(self,key,handler):
            self.key, self.handler = key, handler
            return self
        def undeclare(self): pass
    session = Session()
    assert declare_queryables(session,i) == (session,)
    assert session.key == k
    for key,data in [(k.replace('device1','*'),wire),(k,b'x'*70000),(k,b'bad')]:
        q = Query(key,data)
        session.handler(q)
        assert q.drops == 1 and not q.replies
    assert g.replay.count() == 0
    q = Query(k,wire)
    session.handler(q)
    assert q.drops == 1 and len(q.replies) == 1
    assert verify_reply(s.public_key(),k,wire,q.replies[0][1])['status'] == 'OK'


def test_declaration_rollback(setup):
    from omnicore_host.zenoh_boundary import declare_queryables
    d,s,p,g,n,_,k = setup
    other = Ed25519PrivateKey.generate()
    p2 = CallerIdentity('device2','tenant1',p.allowed_sources,p.allowed_capabilities)
    ingress = SignedIngress('node1',g,[(d.public_key(),p),(other.public_key(),p2)],s)
    class Handle:
        closed = False
        def undeclare(self): self.closed = True
    class Session:
        handle = Handle()
        calls = 0
        def declare_queryable(self,key,handler):
            self.calls += 1
            if self.calls == 2: raise OSError('network down')
            return self.handle
    session = Session()
    with pytest.raises(OSError): declare_queryables(session,ingress)
    assert session.handle.closed
