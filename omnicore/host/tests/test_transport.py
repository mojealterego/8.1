"""Real Linux SO_PEERCRED/SO_PEERSEC authorization, not user-supplied JSON fields."""
import hashlib
import json
import os
import socket
import struct
import uuid
import pytest

from omnicore_host.transport import IdentityRegistry, PeerCredential, UnixRpcEndpoint, AuthError, get_peer_credential
from omnicore_host.rpc import CallerIdentity
from omnicore_host.gateway import Gateway
from omnicore_host.replay import ReplayStore
from omnicore_host.adapter import DigitalLifeAdapter


def packet(source='omnicore-home', cap='rag.query', text='zapis testowy', req_id=None):
    return json.dumps({
        'schema': 'omnicore.rpc.v1', 'request_id': req_id or str(uuid.uuid4()),
        'source': source, 'capability': cap, 'deadline_ms': 1500,
        'payload_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'reply_to': 'device/local/session', 'payload': text,
    }, ensure_ascii=False).encode()


def test_kernel_peer_credentials_are_observed_on_real_unix_socketpair():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        actual = get_peer_credential(a)
        assert actual.uid == os.getuid()
        assert actual.pid > 0
        assert actual.security_context
    finally:
        a.close()
        b.close()


def test_allowlisted_credentials_bound_to_capabilities():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        peer = get_peer_credential(a)
        principal = CallerIdentity('physical-peer-1', 'tenant-a', frozenset({'omnicore-home'}), frozenset({'rag.query'}))
        reg = IdentityRegistry({(peer.uid, peer.security_context): principal})
        assert reg.authenticate(peer).tenant == 'tenant-a'
        with pytest.raises(AuthError, match='peer_untrusted'):
            reg.authenticate(PeerCredential(peer.pid, peer.uid, peer.gid, 'wrong-context'))
        with pytest.raises(AuthError, match='peer_untrusted'):
            reg.authenticate(PeerCredential(peer.pid, peer.uid+1, peer.gid, peer.security_context))
    finally:
        a.close()
        b.close()


def test_socket_endpoint_rejects_unallowlisted_peer_even_if_json_claims_trust(tmp_path):
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        adapter = DigitalLifeAdapter({'rag.query': lambda req, identity: {'tenant': identity.tenant}})
        gate = Gateway(ReplayStore(tmp_path / 'r.db'), adapter)
        endpoint = UnixRpcEndpoint(gate, IdentityRegistry({}))
        b.sendall(struct.pack('!I', len(packet())) + packet())
        endpoint.serve_connection(a)
        n = struct.unpack('!I', b.recv(4))[0]
        result = json.loads(b.recv(n))
        assert result['status'] == 'DENY' and result['reason'] == 'peer_untrusted'
    finally:
        a.close(); b.close()


def test_socket_endpoint_end_to_end_valid_then_replay(tmp_path):
    adapter = DigitalLifeAdapter({'rag.query': lambda req, identity: {'tenant': identity.tenant, 'text': req.payload}})
    gate = Gateway(ReplayStore(tmp_path / 'r.db'), adapter)
    fixed_packet = packet()
    for expected_status in ('OK', 'DENY'):
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            peer = get_peer_credential(a)
            principal = CallerIdentity('physical-peer-1', 'tenant-a', frozenset({'omnicore-home'}), frozenset({'rag.query'}))
            endpoint = UnixRpcEndpoint(gate, IdentityRegistry({(peer.uid,peer.security_context):principal}))
            b.sendall(struct.pack('!I',len(fixed_packet))+fixed_packet)
            endpoint.serve_connection(a)
            n = struct.unpack('!I',b.recv(4))[0]
            result = json.loads(b.recv(n))
            assert result['status'] == expected_status
            if expected_status == 'DENY':
                assert result['reason'] == 'replay_detected'
        finally:
            a.close(); b.close()


def test_oversized_frame_rejected_before_allocating_buffer(tmp_path):
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        endpoint = UnixRpcEndpoint(Gateway(ReplayStore(tmp_path / 'r.db'), DigitalLifeAdapter({})), IdentityRegistry({}))
        b.sendall(struct.pack('!I', 9000000))
        endpoint.serve_connection(a)
        n = struct.unpack('!I', b.recv(4))[0]
        result = json.loads(b.recv(n))
        assert result['status'] == 'DENY'
    finally:
        a.close(); b.close()


def test_truncated_frame_rejected(tmp_path):
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        peer = get_peer_credential(a)
        principal = CallerIdentity('peer', 'tenant', frozenset({'omnicore-home'}), frozenset({'rag.query'}))
        endpoint = UnixRpcEndpoint(Gateway(ReplayStore(tmp_path / 'r.db'), DigitalLifeAdapter({})), IdentityRegistry({(peer.uid,peer.security_context):principal}))
        b.sendall(struct.pack('!I', 30) + b'abc')
        b.shutdown(socket.SHUT_WR)
        endpoint.serve_connection(a)
        n = struct.unpack('!I', b.recv(4))[0]
        result = json.loads(b.recv(n))
        assert result == {'schema':'omnicore.rpc.v1','status':'DENY','reason':'invalid_frame'}
    finally:
        a.close(); b.close()