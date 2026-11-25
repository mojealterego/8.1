"""Tests for safe non-destructive staged installation into a real AOSP checkout."""
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from install_overlay import OverlayError, install_overlay


class OverlayInstallationTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.aosp = Path(self.t.name)/'aosp'
        self.aosp.mkdir()
        self.overlay = Path(self.t.name)/'product'
        self.target = self.overlay/'packages/apps/OmniCoreHome'
        self.target.mkdir(parents=True)
        (self.target/'Android.mk').write_text('LOCAL_PACKAGE_NAME := OmniCoreHome\n')
        second = self.overlay/'device/omnicore/generic'
        second.mkdir(parents=True)
        (second/'AndroidProducts.mk').write_text('PRODUCT_MAKEFILES := valid\n')

    def call(self, apply=False):
        with patch('install_overlay.verify_checkout', return_value={'result':'PASS'}):
            return install_overlay(self.aosp, self.overlay, lock_path=self.aosp/'locked.xml', apply=apply)

    def test_dry_run_does_not_write(self):
        result = self.call()
        self.assertEqual(result['mode'],'DRY_RUN')
        self.assertEqual(result['actions'],['CREATE', 'CREATE'])
        self.assertFalse((self.aosp/'packages').exists())

    def test_apply_copies_two_component_directories(self):
        result = self.call(apply=True)
        self.assertEqual(result['mode'],'APPLIED')
        self.assertTrue((self.aosp/'packages/apps/OmniCoreHome/Android.mk').is_file())
        self.assertTrue((self.aosp/'device/omnicore/generic/AndroidProducts.mk').is_file())

    def test_apply_twice_is_idempotent(self):
        self.call(apply=True)
        report = self.call(apply=True)
        self.assertEqual(report['actions'],['UNCHANGED', 'UNCHANGED'])

    def test_refuses_existing_conflicting_files(self):
        self.call(apply=True)
        (self.aosp/'packages/apps/OmniCoreHome/Android.mk').write_text('NOT THE SAME\n')
        with self.assertRaisesRegex(OverlayError,'conflict'):
            self.call(apply=True)
        self.assertEqual((self.aosp/'packages/apps/OmniCoreHome/Android.mk').read_text(),'NOT THE SAME\n')

    def test_refuses_symlink_parent_directory(self):
        outside = Path(self.t.name)/'outside'
        outside.mkdir()
        (self.aosp/'packages').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(OverlayError,'symlink'):
            self.call(apply=True)
        self.assertEqual(list(outside.iterdir()),[])

    def test_fails_closed_when_source_gate_missing(self):
        with self.assertRaises(Exception):
            install_overlay(self.aosp, self.overlay, lock_path=self.aosp/'missing.lock', apply=True)
        self.assertFalse((self.aosp/'packages').exists())

if __name__=='__main__':
    unittest.main()
