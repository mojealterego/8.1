"""One-shot host mTLS client; not a Zenoh transport. No automatic retry."""
from __future__ import annotations
import hashlib
import hmac
import ipaddress
import json
from pathlib import Path
import re
import socket
import struct
import time
import uuid

from .mtls import ALPN, client_context, _read, _remaining
from .rpc import SCHEMA, MAX_FRAME_BYTES, _no_duplicate_keys, _invalid_constant


class ExchangeError(OSError):
    def __init__(self, stage: str, *, may_have_executed: bool):
        super().__init__('tls_exchange_failed:' + stage)
        self.stage = stage
        self.may_have_executed = may_have_executed


def _document(raw: bytes) -> dict:
    data = json.loads(raw.decode('utf-8'), object_pairs_hook=_no_duplicate_keys,
                      parse_constant=_invalid_constant)
    if type(data) is not dict or data.get('schema') != SCHEMA:
        raise ValueError('invalid_schema')
    return data


class MtlsClient:
    """Trusted static endpoint configuration; numeric IP avoids unbounded DNS.

    CA validation, SAN hostname matching, ALPN and exact leaf pin are required.
    Every call opens a fresh connection. Once transmission begins, failures are
    ambiguous: never infer that the remote operation did not execute.
    """
    def __init__(self, ca: Path, cert: Path, key: Path, *, address: str,
                 port: int, hostname: str, server_pin: str, timeout: float = 2.0):
        ip = ipaddress.ip_address(address)
        if (getattr(ip, 'scope_id', None) is not None or type(port) is not int
                or not 1 <= port <= 65535 or not hostname or '\0' in hostname
                or not re.fullmatch(r'[0-9a-f]{64}', server_pin)
                or not 0.05 <= timeout <= 5):
            raise ValueError('invalid_tls_client_configuration')
        self._family = socket.AF_INET if ip.version == 4 else socket.AF_INET6
        self._address = (str(ip), port) if ip.version == 4 else (str(ip), port, 0, 0)
        self._hostname = hostname
        self._pin = server_pin
        self._timeout = timeout
        self._context = client_context(ca, cert, key)

    def exchange(self, request: bytes) -> dict:
        if type(request) is not bytes or not 0 < len(request) <= MAX_FRAME_BYTES:
            raise ValueError('invalid_request_frame')
        try:
            rid = _document(request).get('request_id')
            if type(rid) is not str or str(uuid.UUID(rid)) != rid:
                raise ValueError('invalid_request_id')
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError('invalid_request_envelope') from exc
        stage = 'connect'
        sent = False
        deadline = time.monotonic() + self._timeout
        try:
            with socket.socket(self._family, socket.SOCK_STREAM) as raw:
                raw.settimeout(_remaining(deadline))
                raw.connect(self._address)
                stage = 'handshake'
                with self._context.wrap_socket(raw, server_hostname=self._hostname,
                                               do_handshake_on_connect=False) as conn:
                    conn.settimeout(_remaining(deadline))
                    conn.do_handshake()
                    stage = 'identity'
                    peer = conn.getpeercert(binary_form=True)
                    if (conn.selected_alpn_protocol() != ALPN or not peer
                            or not hmac.compare_digest(hashlib.sha256(peer).hexdigest(), self._pin)):
                        raise OSError('untrusted_tls_server')
                    stage = 'send'
                    conn.settimeout(_remaining(deadline))
                    sent = True  # sendall failure may still mean partial or full delivery
                    conn.sendall(struct.pack('!I', len(request)) + request)
                    stage = 'receive'
                    size, = struct.unpack('!I', _read(conn, 4, deadline))
                    if not 0 < size <= MAX_FRAME_BYTES:
                        raise ValueError('invalid_response_frame')
                    stage = 'response'
                    response = _document(_read(conn, size, deadline))
                    if response.get('request_id') != rid:
                        raise ValueError('uncorrelated_response')
                    status = response.get('status')
                    if status == 'OK':
                        if set(response) != {'schema', 'request_id', 'status', 'body'}:
                            raise ValueError('invalid_success_response')
                    elif status in ('DENY', 'OFFLINE'):
                        if (set(response) != {'schema', 'request_id', 'status', 'reason'}
                                or not isinstance(response['reason'], str)):
                            raise ValueError('invalid_failure_response')
                    else:
                        raise ValueError('invalid_response_status')
                    _remaining(deadline)
                    return response
        except (OSError, ValueError, UnicodeError, RecursionError) as exc:
            raise ExchangeError(stage, may_have_executed=sent) from exc
