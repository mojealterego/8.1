"""Host TLS RPC boundary. This is not a Zenoh session or an Android service."""
from __future__ import annotations
from collections.abc import Callable, Mapping
import hashlib
import json
from pathlib import Path
import re
import socket
import ssl
import struct
import time
from types import MappingProxyType

from .rpc import CallerIdentity, MAX_FRAME_BYTES

ALPN = 'omnicore-rpc/1'


def _context(role: int, ca: Path, cert: Path, key: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(role)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cafile=str(ca))
    context.load_cert_chain(str(cert), str(key))
    context.set_alpn_protocols([ALPN])
    return context


def client_context(ca: Path, cert: Path, key: Path) -> ssl.SSLContext:
    context = _context(ssl.PROTOCOL_TLS_CLIENT, ca, cert, key)
    context.check_hostname = True
    context.hostname_checks_common_name = False
    return context


def _remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError('tls_deadline_exceeded')
    return left


def _read(sock: ssl.SSLSocket, size: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < size:
        sock.settimeout(_remaining(deadline))
        part = sock.recv(size - len(data))
        if not part:
            raise OSError('tls_frame_truncated')
        data.extend(part)
    _remaining(deadline)
    return bytes(data)


class MtlsEndpoint:
    """One request per TLS connection, no automatic retry or public listener.

    The CA and leaf-certificate pins are trusted deployment configuration.
    The caller supplies an accepted connected socket; serve owns and closes it.
    Dispatch is synchronous and must enforce its own execution budget.
    """
    def __init__(self, ca: Path, cert: Path, key: Path,
                 identities: Mapping[str, CallerIdentity], *, timeout: float = 2.0):
        if not 0.05 <= timeout <= 5:
            raise ValueError('invalid_tls_timeout')
        pins = dict(identities)
        if not pins or any(not isinstance(pin, str) or not re.fullmatch(r'[0-9a-f]{64}', pin)
                           or not isinstance(identity, CallerIdentity)
                           for pin, identity in pins.items()):
            raise ValueError('invalid_tls_identity_registry')
        self._pins = MappingProxyType(pins)
        self._context = _context(ssl.PROTOCOL_TLS_SERVER, ca, cert, key)
        self._context.num_tickets = 0
        self._context.options |= ssl.OP_NO_TICKET
        self._timeout = timeout

    def serve(self, raw: socket.socket, dispatch: Callable[[bytes, CallerIdentity], dict]) -> None:
        deadline = time.monotonic() + self._timeout
        with raw:
            raw.settimeout(_remaining(deadline))
            with self._context.wrap_socket(raw, server_side=True, do_handshake_on_connect=False) as conn:
                conn.settimeout(_remaining(deadline))
                conn.do_handshake()
                if conn.selected_alpn_protocol() != ALPN:
                    raise OSError('tls_protocol_mismatch')
                peer = conn.getpeercert(binary_form=True)
                principal = self._pins.get(hashlib.sha256(peer).hexdigest()) if peer else None
                if principal is None:
                    raise OSError('tls_peer_untrusted')
                size, = struct.unpack('!I', _read(conn, 4, deadline))
                if not 0 < size <= MAX_FRAME_BYTES:
                    raise OSError('tls_frame_size')
                request = _read(conn, size, deadline)
                response = dispatch(request, principal)
                if not isinstance(response, dict):
                    raise ValueError('invalid_rpc_response')
                wire = json.dumps(response, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
                if not 0 < len(wire) <= MAX_FRAME_BYTES:
                    raise ValueError('tls_response_size')
                conn.settimeout(self._timeout)
                conn.sendall(struct.pack('!I', len(wire)) + wire)
