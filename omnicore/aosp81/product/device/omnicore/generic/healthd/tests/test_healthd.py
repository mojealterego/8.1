"""Linux FD handoff and real AF_UNIX tests; no Android SELinux emulation."""
import os
import select
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
READY = b'OMNICORE-HEALTH/1 READY\n'


class HealthdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.build.cleanup)
        cls.bin = Path(cls.build.name) / 'healthd'
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-DOMNI_HOST_TEST',
                        str(ROOT/'healthd.c'), '-o', str(cls.bin)], check=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name)/'health.sock')
        a, b = socket.socketpair()
        with a, b:
            self.label = a.getsockopt(socket.SOL_SOCKET, 31, 1024).rstrip(b'\0').decode()

    def spawn(self, sock=None, *, fd=None, path=None, uid=None, label=None):
        if fd is None:
            fd = str(sock.fileno()) if sock is not None else ''
        env = {'ANDROID_SOCKET_omnicore_health': fd}
        proc = subprocess.Popen([str(self.bin), path or self.path,
                                 str(os.getuid() if uid is None else uid),
                                 self.label if label is None else label],
                                env=env, pass_fds=(sock.fileno(),) if sock else (),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def cleanup():
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=3)
        self.addCleanup(cleanup)
        return proc

    def bound(self, kind=socket.SOCK_STREAM):
        sock = socket.socket(socket.AF_UNIX, kind)
        self.addCleanup(sock.close)
        sock.bind(self.path)
        return sock

    def wait_ready(self, proc):
        # Startup notification is emitted only after successful listen().
        self.assertTrue(select.select([proc.stdout], [], [], 3)[0], 'startup timeout')
        self.assertEqual(proc.stdout.readline(), b'LISTENING\n')

    def exchange(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(self.path)
            data = bytearray()
            while part := client.recv(128):
                data.extend(part)
            return bytes(data)

    def failed(self, proc):
        out, err = proc.communicate(timeout=3)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(out, b'')
        self.assertEqual(err, b'')

    def test_missing_descriptor(self):
        self.failed(self.spawn())

    def test_noncanonical_descriptor(self):
        self.failed(self.spawn(fd=' 3'))

    def test_closed_descriptor(self):
        self.failed(self.spawn(fd='2147483647'))

    def test_regular_file_descriptor(self):
        with tempfile.TemporaryFile() as fd:
            self.failed(self.spawn(fd))

    def test_unbound_descriptor(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            self.failed(self.spawn(sock))

    def test_wrong_path(self):
        self.failed(self.spawn(self.bound(), path=self.path+'.wrong'))

    def test_wrong_socket_type(self):
        self.failed(self.spawn(self.bound(socket.SOCK_DGRAM)))

    def test_already_listening_rejected(self):
        sock = self.bound()
        sock.listen(1)
        self.failed(self.spawn(sock))

    def test_correct_peer_and_repeated_requests(self):
        proc = self.spawn(self.bound())
        self.wait_ready(proc)
        for _ in range(3):
            self.assertEqual(self.exchange(), READY)
        proc.terminate()
        out, err = proc.communicate(timeout=3)
        self.assertEqual((proc.returncode, out, err), (0, b'', b''))

    def test_wrong_uid(self):
        proc = self.spawn(self.bound(), uid=(os.getuid()+1) % 2**32)
        self.wait_ready(proc)
        self.assertEqual(self.exchange(), b'')

    def test_wrong_label(self):
        proc = self.spawn(self.bound(), label='not-a-kernel-label')
        self.wait_ready(proc)
        self.assertEqual(self.exchange(), b'')

    def test_configuration_fail_closed(self):
        rc = (ROOT/'omnicore_healthd.rc').read_text().splitlines()
        self.assertEqual([s.strip() for s in rc if s.strip() and not s.startswith('#')], [
            'service omnicore_healthd /system/bin/omnicore_healthd', 'class late_start',
            'user nobody', 'group nobody', 'disabled',
            'socket omnicore_health stream 0660 nobody system'])
        policy = (ROOT/'sepolicy/private/omnicore_healthd.te').read_text()
        self.assertNotIn('permissive ', policy)
        self.assertNotIn('net_domain(', policy)
        self.assertNotIn('allow untrusted_app', policy)
        self.assertIn('unix_socket_connect(system_server, omnicore_health, omnicore_healthd)', policy)
        self.assertIn('init_daemon_domain(omnicore_healthd)', policy)
        contexts = (ROOT/'sepolicy/private/file_contexts.omnicore').read_text().splitlines()
        self.assertEqual([line.split() for line in contexts], [
            ['/system/bin/omnicore_healthd', 'u:object_r:omnicore_healthd_exec:s0'],
            ['/dev/socket/omnicore_health', 'u:object_r:omnicore_health_socket:s0']])
        mk = (ROOT/'Android.mk').read_text()
        self.assertIn('LOCAL_INIT_RC := omnicore_healthd.rc', mk)
        self.assertIn('LOCAL_MODULE := omnicore_healthd', mk)
        self.assertNotIn('OMNI_HOST_TEST', mk)


if __name__ == '__main__':
    unittest.main()
