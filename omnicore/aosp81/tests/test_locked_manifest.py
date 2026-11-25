"""Red/green contract tests: a lockfile must describe all pinned projects."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from preflight import GateError, verify_checkout, validate_lock_manifest

PIN = '4a9acdc305c27336f8ef74505800bcc541f6052e'
DUMMY = 'a' * 40
NAMES = ('frameworks/base', 'art', 'bionic', 'system/core', 'frameworks/native', 'build', 'libcore')


def xml_for(paths: tuple[str, ...] = NAMES, *, revision: str = DUMMY) -> str:
    projects = [f'<project name="platform/{p}" path="{p}" revision="{revision}"/>' for p in paths]
    projects[0] = '<project name="mojealterego/8.1" path="frameworks/base" remote="omnicore-github" revision="' + PIN + '"/>'
    return '<manifest><remote name="omnicore-github" fetch="https://github.com/"/>' + ''.join(projects) + '</manifest>'


class LockedManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / '.repo').mkdir()
        (self.root / '.repo' / 'manifest.xml').write_text('<manifest/>')
        for path in NAMES:
            (self.root / path).mkdir(parents=True, exist_ok=True)
        (self.root / 'frameworks/base/packages/SystemUI').mkdir(parents=True)
        (self.root / 'frameworks/base/packages/SystemUI/Android.mk').touch()
        self.lock = self.root / 'manifest.lock.xml'
        self.lock.write_text(xml_for())

    def test_locked_manifest_tracks_all_required_projects(self):
        self.assertEqual(len(validate_lock_manifest(self.lock, min_projects=7)), 7)

    def test_rejects_floating_revision(self):
        self.lock.write_text(xml_for(revision='main'))
        with self.assertRaisesRegex(GateError, 'unpinned'):
            validate_lock_manifest(self.lock, min_projects=7)

    def test_rejects_duplicate_project_path(self):
        self.lock.write_text(xml_for() .replace('</manifest>', '<project name="evil" path="art" revision="' + DUMMY + '"/></manifest>'))
        with self.assertRaisesRegex(GateError, 'duplicate'):
            validate_lock_manifest(self.lock, min_projects=7)

    def test_rejects_absolute_project_path(self):
        self.lock.write_text(xml_for(paths=NAMES[:-1] + ('/tmp/escape',)))
        with self.assertRaisesRegex(GateError, 'unsafe'):
            validate_lock_manifest(self.lock, min_projects=7)

    def test_rejects_symlink_project_directory(self):
        (self.root / 'art').rmdir()
        (self.root / 'art').symlink_to(self.root / 'libcore', target_is_directory=True)
        with patch('preflight._git_head', return_value=DUMMY):
            with self.assertRaisesRegex(GateError, 'symlink'):
                verify_checkout(self.root, self.lock, min_projects=7)

    def test_rejects_mismatched_revision(self):
        with patch('preflight._git_head', return_value='b' * 40):
            with self.assertRaisesRegex(GateError, 'head_mismatch'):
                verify_checkout(self.root, self.lock, min_projects=7)

    def test_checks_every_project_head(self):
        with patch('preflight._git_head', side_effect=lambda p: PIN if p.name == 'base' else DUMMY) as head:
            result = verify_checkout(self.root, self.lock, min_projects=7)
        self.assertEqual(result['verified_projects'], 7)
        self.assertEqual(head.call_count, 7)
        self.assertEqual(result['build_status'], 'NOT_TESTED')

    def test_no_lockfile_is_never_source_verified(self):
        with self.assertRaisesRegex(GateError, 'lock_required'):
            verify_checkout(self.root, None, min_projects=7)

    def test_rejects_small_lock_at_default_threshold(self):
        with self.assertRaisesRegex(GateError, 'too_few_projects'):
            validate_lock_manifest(self.lock)


if __name__ == '__main__':
    unittest.main()
