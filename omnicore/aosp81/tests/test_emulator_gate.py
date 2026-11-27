import subprocess
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_emulator import GateError, verify_emulator

HOME = 'org.omnicore.home/.HomeActivity'

class ContractTests(unittest.TestCase):
    def run_case(self, overrides=None, serial='emulator-5554'):
        replies = {
            ('get-state',): 'device',
            ('shell', 'getprop', 'ro.kernel.qemu'): '1',
            ('shell', 'getprop', 'sys.boot_completed'): '1',
            ('shell', 'getprop', 'ro.build.version.sdk'): '27',
            ('shell', 'getprop', 'ro.build.version.release'): '8.1.0',
            ('shell', 'getprop', 'ro.omnicore.profile'): 'EMULATOR',
            ('shell', 'pm', 'path', 'org.omnicore.home'): 'package:/system/app/OmniCoreHome/OmniCoreHome.apk',
            ('shell', 'cmd', 'package', 'query-activities', '--components', '--user', '0', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.HOME'): HOME,
            ('shell', 'am', 'start', '-W', '--user', '0', '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.HOME', '-n', HOME): 'Status: ok\nActivity: '+HOME+'\nComplete',
            ('shell', 'dumpsys', 'activity', 'activities'): 'mResumedActivity: ActivityRecord{1 u0 '+HOME+' t2}',
        }
        replies.update(overrides or {})
        def run(args, **kwargs):
            self.assertEqual(args[:3], ['adb', '-s', serial])
            self.assertGreater(kwargs['timeout'], 0)
            value = replies[tuple(args[3:])]
            if isinstance(value, Exception):
                raise value
            return subprocess.CompletedProcess(args, 0, value+'\n', '')
        return verify_emulator(serial, timeout=5, run=run)

    def test_nominal(self):
        self.assertEqual(self.run_case()['result'], 'PASS')

    def test_physical_device(self):
        with self.assertRaises(GateError):
            self.run_case(serial='physical-device')

    def test_not_qemu(self):
        with self.assertRaises(GateError):
            self.run_case({('shell','getprop','ro.kernel.qemu'): '0'})

    def test_wrong_sdk(self):
        with self.assertRaises(GateError):
            self.run_case({('shell','getprop','ro.build.version.sdk'): '28'})

    def test_wrong_profile(self):
        with self.assertRaises(GateError):
            self.run_case({('shell','getprop','ro.omnicore.profile'): ''})

    def test_sideloaded_home(self):
        with self.assertRaises(GateError):
            self.run_case({('shell','pm','path','org.omnicore.home'): 'package:/data/app/foo/base.apk'})

    def test_home_not_registered(self):
        key = ('shell','cmd','package','query-activities','--components','--user','0','-a','android.intent.action.MAIN','-c','android.intent.category.HOME')
        with self.assertRaises(GateError):
            self.run_case({key: 'org.other/.Home'})

    def test_launch_failure_even_with_zero_exit(self):
        key = ('shell','am','start','-W','--user','0','-a','android.intent.action.MAIN','-c','android.intent.category.HOME','-n',HOME)
        with self.assertRaises(GateError):
            self.run_case({key: 'Error type 3\nStatus: ok'})

    def test_wrong_foreground(self):
        with self.assertRaises(GateError):
            self.run_case({('shell','dumpsys','activity','activities'): 'mResumedActivity: ActivityRecord{1 u0 org.other/.Home t2}'})

    def test_transport_timeout(self):
        with self.assertRaises(GateError):
            self.run_case({('get-state',): subprocess.TimeoutExpired('adb', 1)})

if __name__ == '__main__':
    unittest.main()
