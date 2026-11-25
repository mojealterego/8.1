"""One-frame local AF_UNIX gateway with kernel peer identity.

This is an independent host executable interface contract, NOT Android init/SELinux
integration. A strict UID+SO_PEERSEC allowlist is required to admit a peer.
Never derive credentials from JSON. No Abstract Unix namespace.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import socket
import struct
from typing import Mapping

from .rpc import CallerIdentity, MAX_FRAME_BYTES, SCHEMA
from .gateway import Gateway

SO_PEERSEC_LINUX = 31
SO_PEERCRED_LINUX = 17

class AuthError(PermissionError):
    pass

@dataclass(frozen=True)
class PeerCredential:
    pid: int
    uid: int
    gid: int
    security_context: str


def get_peer_credential(sock: socket.socket) -> PeerCredential:
    try:
        raw = sock.getsockopt(socket.SOL_SOCKET, SO_PEERCRED_LINUX, struct.calcsize('3i'))
        pid, uid, gid = struct.unpack('3i', raw)
        label = sock.getsockopt(socket.SOL_SOCKET, SO_PEERSEC_LINUX, 1024)
        sec = label.rstrip(b'\0').decode('utf-8', errors='strict')
    except (OSError, UnicodeError, struct.error) as exc:
        raise AuthError('peer_credentials_unavailable') from exc
    if pid <= 0 or uid < 0 or gid < 0 or not sec or len(sec) > 256:
        raise AuthError('peer_credentials_invalid')
    return PeerCredential(pid, uid, gid, sec)


class IdentityRegistry:
    def __init__(self, entries: Mapping[tuple[int, str], CallerIdentity]):
        self.entries = dict(entries)
        if any(not isinstance(k, tuple) or len(k) != 2 or not isinstance(v, CallerIdentity)
               for k,v in self.entries.items()):
            raise ValueError('bad_registry')

    def authenticate(self, cred: PeerCredential) -> CallerIdentity:
        principal = self.entries.get((cred.uid, cred.security_context))
        if principal is None:
            raise AuthError('peer_untrusted')
        return principal


def _read_exact(sock: socket.socket, length: int) -> bytes:
    out = bytearray()
    while len(out) < length:
        chunk = sock.recv(length - len(out))
        if not chunk:
            raise EOFError('truncated_frame')
        out.extend(chunk)
    return bytes(out)


class UnixRpcEndpoint:
    def __init__(self, gateway: Gateway, registry: IdentityRegistry, *, timeout_seconds: float = 2.0):
        if not 0.05 <= timeout_seconds <= 60:
            raise ValueError('bad_socket_timeout')
        self.gateway = gateway
        self.registry = registry
        self.timeout_seconds = timeout_seconds

    def serve_connection(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(self.timeout_seconds)
            cred = get_peer_credential(conn)
            principal = self.registry.authenticate(cred)
            (length,) = struct.unpack('!I', _read_exact(conn, 4))
            if not 0 < length <= MAX_FRAME_BYTES:
                raise ValueError('invalid_frame')
            raw = _read_exact(conn, length)
            response = self.gateway.handle(raw, principal)
        except AuthError as exc:
            response = {'schema':SCHEMA,'status':'DENY','reason':str(exc)}
        except (ValueError, EOFError, TimeoutError, OSError, struct.error):
            response = {'schema':SCHEMA,'status':'DENY','reason':'invalid_frame'}
        wire = json.dumps(response,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        if len(wire) > MAX_FRAME_BYTES:
            wire = b'{"schema":"omnicore.rpc.v1","status":"DENY","reason":"response_too_large"}'
        conn.sendall(struct.pack('!I', len(wire)) + wire)