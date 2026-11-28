"""Application-layer signed query boundary; independent of Zenoh peer metadata."""
from __future__ import annotations
from collections.abc import Callable, Iterable
import hashlib
import json
import re
import struct
import time
from types import MappingProxyType

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from .gateway import Gateway
from .rpc import CallerIdentity, ContractError, MAX_FRAME_BYTES, decode_request

MAX_LIFETIME = 30
HEADER = 32 + 8 + 64
_SEG = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
_ROUTE = re.compile(r'omnicore/v1/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[a-z][a-z0-9_.]{0,63}\Z')


class BoundaryError(ValueError):
    pass


def _route_bytes(key: str) -> bytes:
    if not isinstance(key, str) or len(key) > 512 or not _ROUTE.fullmatch(key):
        raise BoundaryError('invalid_route')
    return key.encode('ascii')


def route(node: str, principal: CallerIdentity, capability: str) -> str:
    key = f'omnicore/v1/{node}/{principal.tenant}/{principal.peer_id}/{capability}'
    _route_bytes(key)
    return key


def _message(domain: bytes, key: str, data: bytes) -> bytes:
    encoded = _route_bytes(key)
    return domain + struct.pack('!H', len(encoded)) + encoded + data


def sign_request(private: Ed25519PrivateKey, key: str, raw: bytes, expires: int) -> bytes:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_FRAME_BYTES:
        raise BoundaryError('invalid_request_size')
    if type(expires) is not int or not 0 <= expires < 2**64:
        raise BoundaryError('invalid_expiry')
    kid = hashlib.sha256(private.public_key().public_bytes_raw()).digest()
    head = kid + struct.pack('!Q', expires)
    sig = private.sign(_message(b'OCRS-ZQ1\0', key, head + raw))
    return head + sig + raw


def verify_reply(public: Ed25519PublicKey, key: str, request: bytes, wire: bytes) -> dict:
    if type(wire) is not bytes or not 64 < len(wire) <= 64 + MAX_FRAME_BYTES:
        raise BoundaryError('invalid_reply_size')
    if type(request) is not bytes or not HEADER < len(request) <= HEADER + MAX_FRAME_BYTES:
        raise BoundaryError('invalid_request_size')
    try:
        public.verify(wire[:64], _message(b'OCRS-ZR1\0', key, hashlib.sha256(request).digest() + wire[64:]))
        data = json.loads(wire[64:].decode('utf-8'))
    except (InvalidSignature, ValueError, UnicodeError, RecursionError) as exc:
        raise BoundaryError('invalid_reply') from exc
    if type(data) is not dict:
        raise BoundaryError('invalid_reply')
    return data


class SignedIngress:
    """Immutable trusted key registry; rotate by replacing the boundary, not replay DB.

    All configured keys must be provisioned out of band. No identity from query
    metadata is trusted. Use a distinct node ID for each logical service/replay DB.
    """
    def __init__(self, node: str, gateway: Gateway,
                 grants: Iterable[tuple[Ed25519PublicKey, CallerIdentity]],
                 signer: Ed25519PrivateKey, *, clock: Callable[[], int] = lambda: int(time.time())):
        if not isinstance(node, str) or not _SEG.fullmatch(node) or gateway.replay.retention_seconds <= MAX_LIFETIME:
            raise ValueError('invalid_boundary_configuration')
        self._node, self._gate, self._signer, self._clock = node, gateway, signer, clock
        entries = {}
        routes = set()
        for public, principal in grants:
            kid = hashlib.sha256(public.public_bytes_raw()).digest()
            if kid in entries or not principal.allowed_capabilities:
                raise ValueError('invalid_key_registry')
            # Freeze grants even if a caller constructed CallerIdentity with mutable sets.
            principal = CallerIdentity(principal.peer_id, principal.tenant,
                                       frozenset(principal.allowed_sources), frozenset(principal.allowed_capabilities))
            for cap in principal.allowed_capabilities:
                routes.add(route(node, principal, cap))
            entries[kid] = (public, principal)
        if not entries:
            raise ValueError('empty_key_registry')
        self._entries = MappingProxyType(entries)
        self.routes = tuple(sorted(routes))

    def handle(self, key: str, wire: bytes) -> bytes:
        _route_bytes(key)
        if type(wire) is not bytes or not HEADER < len(wire) <= HEADER + MAX_FRAME_BYTES:
            raise BoundaryError('invalid_request_size')
        grant = self._entries.get(wire[:32])
        if grant is None:
            raise BoundaryError('untrusted_signer')
        public, principal = grant
        raw = wire[HEADER:]
        try:
            public.verify(wire[40:HEADER], _message(b'OCRS-ZQ1\0', key, wire[:40] + raw))
            request = decode_request(raw, principal)
        except (InvalidSignature, ContractError) as exc:
            raise BoundaryError('unauthorized_query') from exc
        if key != route(self._node, principal, request.capability):
            raise BoundaryError('route_denied')
        now = self._clock()
        expires, = struct.unpack('!Q', wire[32:40])
        if type(now) is not int or not 0 <= now < expires <= now + MAX_LIFETIME:
            raise BoundaryError('invalid_expiry')
        response = self._gate.handle(raw, principal)
        data = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        if not 0 < len(data) <= MAX_FRAME_BYTES:
            raise BoundaryError('invalid_reply_size')
        return self._signer.sign(_message(b'OCRS-ZR1\0', key, hashlib.sha256(wire).digest() + data)) + data


def declare_queryables(session, ingress: SignedIngress) -> tuple:
    """Register exact Zenoh queryables on a caller-owned, trusted session.

    Tested via callback contract only; no real Zenoh library required for the
    cryptographic boundary. Caller owns session and successful declarations.
    """
    def handler_for(expected: str):
        def handler(query):
            try:
                if str(query.key_expr) != expected:
                    return
                payload = query.payload
                if payload is None or not HEADER < len(payload) <= HEADER + MAX_FRAME_BYTES:
                    return
                try:
                    reply = ingress.handle(expected, payload.to_bytes())
                except BoundaryError:
                    return
                query.reply(expected, reply)
            finally:
                query.drop()
        return handler

    handles = []
    try:
        for key in ingress.routes:
            handles.append(session.declare_queryable(key, handler_for(key)))
    except Exception as original:
        failures = []
        for handle in reversed(handles):
            try:
                handle.undeclare()
            except Exception as exc:
                failures.append(exc)
        if failures:
            raise ExceptionGroup('queryable_registration_cleanup_failed', [original, *failures])
        raise
    return tuple(handles)
