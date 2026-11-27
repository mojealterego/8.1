"""Native AF_UNIX tests with a Python wire peer; not Android/Zenoh integration."""
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest

PROBE = Path(__file__).resolve().parents[1] / 'unix_probe'


def read_exact(conn, n):
    data = bytearray()
    while len(data) < n:
        part = conn.recv(n - len(data))
        if not part:
            raise EOFError('truncated request')
        data.extend(part)
    return bytes(data)


class NativeUnixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'rpc.sock')
        a, b = socket.socketpair()
        with a, b:
            self.label = a.getsockopt(socket.SOL_SOCKET, 31, 1024).rstrip(b'\0').decode()

    def probe(self, payload=b'{}', *, path=None, uid=None, label=None, ms=1000, cap=65536):
        result = subprocess.run([str(PROBE), path if path is not None else self.path,
                                 str(os.getuid() if uid is None else uid),
                                 self.label if label is None else label,
                                 str(ms), str(cap)], input=payload, capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertEqual(result.stderr, b'')
        line, body = result.stdout.split(b'\n', 1)
        code, n = map(int, line.split())
        self.assertEqual(n, len(body))
        return code, body

    def exchange(self, handler, payload=b'{}', **kwargs):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(self.path)
            listener.listen(1)
            listener.settimeout(3)
            errors = []
            def worker():
                try:
                    conn, _ = listener.accept()
                    with conn:
                        conn.settimeout(3)
                        handler(conn)
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                result = self.probe(payload, **kwargs)
            finally:
                thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            return result

    def reply(self, conn, expected=b'{}', body=b'{"status":"OK"}'):
        n, = struct.unpack('!I', read_exact(conn, 4))
        self.assertEqual(read_exact(conn, n), expected)
        conn.sendall(struct.pack('!I', len(body)) + body)

    def test_nominal(self):
        self.assertEqual(self.exchange(self.reply), (0, b'{"status":"OK"}'))

    def test_maximum_frame_both_directions(self):
        payload = bytes(range(256)) * 256
        self.assertEqual(self.exchange(lambda c: self.reply(c, payload, payload), payload), (0, payload))

    def test_fragmented_response(self):
        def server(c):
            self.assertEqual(read_exact(c, 6), b'\0\0\0\2{}')
            for byte in b'\0\0\0\3xyz':
                c.sendall(bytes([byte]))
        self.assertEqual(self.exchange(server), (0, b'xyz'))

    def test_wrong_uid_no_request_sent(self):
        self.assertEqual(self.exchange(lambda c: self.assertEqual(c.recv(1), b''), uid=os.getuid()+1), (4, b''))

    def test_wrong_label_no_request_sent(self):
        self.assertEqual(self.exchange(lambda c: self.assertEqual(c.recv(1), b''), label='untrusted'), (4, b''))

    def test_zero_response_length(self):
        self.assertEqual(self.exchange(lambda c: (read_exact(c, 6), c.sendall(b'\0'*4))), (5, b''))

    def test_oversized_response_length(self):
        self.assertEqual(self.exchange(lambda c: (read_exact(c, 6), c.sendall(struct.pack('!I', 65537)))), (5, b''))

    def test_response_exceeds_capacity(self):
        self.assertEqual(self.exchange(lambda c: (read_exact(c, 6), c.sendall(struct.pack('!I', 10))), cap=5), (6, b''))

    def test_truncated_header(self):
        self.assertEqual(self.exchange(lambda c: (read_exact(c, 6), c.sendall(b'\0\0'))), (2, b''))

    def test_truncated_body(self):
        self.assertEqual(self.exchange(lambda c: (read_exact(c, 6), c.sendall(b'\0\0\0\5xy'))), (2, b''))

    def test_timeout(self):
        def server(c):
            read_exact(c, 6)
            self.assertEqual(c.recv(1), b'')
        self.assertEqual(self.exchange(server, ms=100), (3, b''))

    def test_total_deadline_across_fragments(self):
        def server(c):
            read_exact(c, 6)
            c.sendall(b'\0\0\0\4x')
            time.sleep(0.06)
            c.sendall(b'y')
            time.sleep(0.06)
            self.assertEqual(c.recv(1), b'')
        self.assertEqual(self.exchange(server, ms=100), (3, b''))

    def test_invalid_arguments(self):
        for args in ({'payload': b''}, {'payload': b'x'*65537}, {'path': 'relative'},
                     {'label': ''}, {'ms': 0}, {'ms': 5001}, {'cap': 0},
                     {'path': '/' + 'x'*108}):
            with self.subTest(args=list(args)):
                self.assertEqual(self.probe(**args), (1, b''))

    def test_missing_socket(self):
        self.assertEqual(self.probe(), (2, b''))


if __name__ == '__main__':
    unittest.main()
