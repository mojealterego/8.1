"""Stdlib unittest: deterministic checks for F0 source gate."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from preflight import GateError, validate_manifest, verify_checkout

class SourceGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.good = Path(__file__).resolve().parent.parent/'omnicore.xml'

    def replace(self,old,new):
        dest=Path(self.tmp.name)/'omnicore.xml'
        dest.write_text(self.good.read_text().replace(old,new))
        return dest

    def test_pinned_manifest_valid(self):
        validate_manifest(self.good)

    def test_moving_branch_rejected(self):
        with self.assertRaisesRegex(GateError,'unpinned_or_untrusted_project'):
            validate_manifest(self.replace('4a9acdc305c27336f8ef74505800bcc541f6052e','main'))

    def test_remote_not_https_rejected(self):
        with self.assertRaisesRegex(GateError,'untrusted_remote'):
            validate_manifest(self.replace('https://github.com/','http://github.com/'))

    def test_duplicated_project_rejected(self):
        with self.assertRaisesRegex(GateError,'unexpected_projects'):
            validate_manifest(self.replace('</manifest>', '<project name="evil"/></manifest>'))

    def test_missing_complete_tree_blocked(self):
        with self.assertRaisesRegex(GateError,'incomplete_aosp'):
            verify_checkout(Path(self.tmp.name))

    def test_dtd_disallowed(self):
        dest=Path(self.tmp.name)/'omnicore.xml'
        dest.write_text('<!DOCTYPE manifest [<!ENTITY x SYSTEM "file:///etc/passwd">]><manifest>&x;</manifest>')
        with self.assertRaisesRegex(GateError,'DTD_not_allowed'):
            validate_manifest(dest)

if __name__=='__main__':
    unittest.main()
