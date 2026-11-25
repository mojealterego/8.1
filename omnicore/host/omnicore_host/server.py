"""Host-only authenticated AF_UNIX service, single-threaded for low RSS.

Use a private directory owned by the current service account. An Android
/system init socket must instead be created and labeled by init, not this code.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import stat
import struct
import threading
from .rpc import MAX_FRAME_BYTES
from .transport import UnixRpcEndpoint


class LocalHostServer:
    def __init__(self, path: Path, endpoint: UnixRpcEndpoint, *, backlog: int = 8):
        self.path = Path(path)
        self.endpoint = endpoint
        if not 1 <= backlog <= 128:
            raise ValueError('bad_backlog')
        self.backlog = backlog

    def prepare(self) -> None:
        if not self.path.is_absolute() or len(os.fsencode(self.path)) >= 100:
            raise ValueError('invalid_socket_path')
        parent = self.path.parent
        meta = parent.lstat()
        if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.getuid() or meta.st_mode & 0o077:
            raise PermissionError('socket_parent_insecure')
        if os.path.lexists(self.path):
            raise FileExistsError(str(self.path))

    def serve_forever(self, *, stop: threading.Event, started: threading.Event | None = None) -> None:
        self.prepare()
        inode = None
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(self.path))
            os.chmod(self.path, 0o600)
            inode = self.path.lstat().st_ino
            listener.listen(self.backlog)
            listener.settimeout(0.15)
            if started is not None:
                started.set()
            try:
                while not stop.is_set():
                    try:
                        conn, _ = listener.accept()
                    except socket.timeout:
                        continue
                    with conn:
                        try:
                            self.endpoint.serve_connection(conn)
                        except (OSError, ConnectionError, BrokenPipeError):
                            # A remote close must not terminate the server loop.
                            pass
            finally:
                try:
                    meta = self.path.lstat()
                    if stat.S_ISSOCK(meta.st_mode) and meta.st_ino == inode:
                        self.path.unlink()
                except FileNotFoundError:
                    pass


def send_rpc_frame(socket_path: Path, raw: bytes, *, timeout: float = 2.0) -> dict:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_FRAME_BYTES:
        raise ValueError('invalid_request_frame')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(str(socket_path))
        conn.sendall(struct.pack('!I',len(raw))+raw)
        data = _read_exact(conn,4)
        (n,) = struct.unpack('!I',data)
        if not 0 < n <= MAX_FRAME_BYTES:
            raise ValueError('invalid_response_frame')
        response = json.loads(_read_exact(conn,n))
        if not isinstance(response,dict):
            raise ValueError('invalid_response_type')
        return response


def _read_exact(conn: socket.socket, count: int) -> bytes:
    out = bytearray()
    while len(out) < count:
        part = conn.recv(count - len(out))
        if not part:
            raise ConnectionError('truncated_response')
        out.extend(part)
    return bytes(out)