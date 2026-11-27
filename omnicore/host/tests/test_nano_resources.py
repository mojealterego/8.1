import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest

from omnicore_host.nano_resources import NanoGovernor, ResourceDenied, read_available_bytes, apply_worker_limits, MiB


class NanoTests(unittest.TestCase):
    def test_low_memory_denied(self):
        governor = NanoGovernor(available=lambda: 159 * MiB)
        with self.assertRaises(ResourceDenied):
            with governor.admit():
                self.fail('admitted')

    def test_exact_threshold(self):
        with NanoGovernor(available=lambda: 160 * MiB).admit():
            pass

    def test_concurrent_admission_denied_and_recovery(self):
        governor = NanoGovernor(available=lambda: 512 * MiB)
        results = []
        with governor.admit():
            def other():
                try:
                    with governor.admit():
                        results.append('admitted')
                except ResourceDenied as exc:
                    results.append(str(exc))
            t = threading.Thread(target=other)
            t.start(); t.join(2)
            self.assertFalse(t.is_alive())
        self.assertEqual(results, ['worker_busy'])
        with governor.admit():
            pass

    def test_exception_releases_slot(self):
        governor = NanoGovernor(available=lambda: 512 * MiB)
        with self.assertRaises(RuntimeError):
            with governor.admit():
                raise RuntimeError('failed')
        with governor.admit():
            pass

    def test_unknown_memory_fails_closed(self):
        for value in (None, -1, True, float('nan')):
            with self.subTest(value=value):
                with self.assertRaises(ResourceDenied):
                    with NanoGovernor(available=lambda: value).admit():
                        self.fail('admitted')

    def test_proc_snapshot(self):
        self.assertGreater(read_available_bytes(), 0)

    def test_native_kernel_limits_and_allocation_denial(self):
        script = '''import json,resource
from omnicore_host.nano_resources import apply_worker_limits
apply_worker_limits()
limits=[resource.getrlimit(k) for k in (resource.RLIMIT_AS,resource.RLIMIT_CPU,resource.RLIMIT_NOFILE,resource.RLIMIT_CORE,resource.RLIMIT_FSIZE)]
try:
    bytearray(128*1024*1024)
except MemoryError:
    denied=True
else:
    denied=False
print(json.dumps([limits,denied]))'''
        p = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=5, check=True)
        limits, denied = json.loads(p.stdout)
        self.assertEqual(limits, [[64*MiB]*2,[2,2],[32,32],[0,0],[0,0]])
        self.assertTrue(denied)

    def test_native_cpu_limit(self):
        script = 'from omnicore_host.nano_resources import apply_worker_limits\napply_worker_limits()\nwhile True: pass'
        p = subprocess.run([sys.executable, '-c', script], timeout=8)
        self.assertEqual(p.returncode, -9)

if __name__ == '__main__': unittest.main()
