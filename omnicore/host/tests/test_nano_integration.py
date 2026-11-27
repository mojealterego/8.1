"""Exercise the original local executor and worker with the NANO policy."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

from omnicore_host.deadline import ExecutionBudget
from omnicore_host.local_executor import LocalProcessExecutor
from omnicore_host.local_services import local_handlers
from omnicore_host.nano_resources import MiB, NanoGovernor, ResourceDenied
from omnicore_host.rpc import CallerIdentity, RpcRequest

ROOT = Path(__file__).resolve().parents[1]
PRINCIPAL = CallerIdentity('peer', 'tenant', frozenset({'omnicore-home'}), frozenset({'intent.local'}))
REQUEST = RpcRequest('00000000-0000-0000-0000-000000000001', 'omnicore-home',
                     'intent.local', 1000, 'photo', 'device/local/session')


def invoke(executor):
    return executor(local_handlers()['intent.local'], REQUEST, PRINCIPAL,
                    ExecutionBudget.start(time.monotonic_ns(), 1000, time.monotonic_ns))


class IntegrationTests(unittest.TestCase):
    def test_low_memory_blocks_executor(self):
        executor = LocalProcessExecutor(governor=NanoGovernor(available=lambda: 159*MiB))
        with self.assertRaisesRegex(ResourceDenied, 'memory_pressure'):
            invoke(executor)

    def test_real_worker_with_governor(self):
        executor = LocalProcessExecutor(governor=NanoGovernor(available=lambda: 512*MiB))
        self.assertEqual(invoke(executor), {'action': 'open_gallery', 'offline': True})

    def test_default_executors_share_slot(self):
        a, b = LocalProcessExecutor(), LocalProcessExecutor()
        self.assertIs(a.governor, b.governor)
        with a.governor.admit():
            with self.assertRaisesRegex(ResourceDenied, 'worker_busy'):
                invoke(b)

    def test_production_worker_applies_kernel_caps_before_read(self):
        with subprocess.Popen([sys.executable, '-I', '-S', str(ROOT/'omnicore_host/local_worker.py')],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={}) as proc:
            try:
                end = time.monotonic()+3
                while time.monotonic()<end and proc.poll() is None:
                    limits = Path(f'/proc/{proc.pid}/limits').read_text()
                    if (any(line.startswith('Max address space') and line.split()[3:5] == ['67108864', '67108864'] for line in limits.splitlines())
                            and any(line.startswith('Max open files') and line.split()[3:5] == ['32','32'] for line in limits.splitlines())):
                        break
                    time.sleep(0.01)
                else:
                    self.fail('production child never applied address-space cap')
                self.assertTrue(any(line.startswith('Max open files') and line.split()[3:5] == ['32','32'] for line in limits.splitlines()))
                envelope = {'request': REQUEST.__dict__, 'principal': {'peer_id':'peer','tenant':'tenant','allowed_sources':['omnicore-home'],'allowed_capabilities':['intent.local']}}
                out, err = proc.communicate(json.dumps(envelope).encode(), timeout=3)
                self.assertEqual((proc.returncode, err), (0,b''))
                self.assertEqual(json.loads(out), {'action':'open_gallery','offline':True})
            finally:
                if proc.poll() is None:
                    proc.kill(); proc.communicate(timeout=3)


if __name__ == '__main__': unittest.main()
