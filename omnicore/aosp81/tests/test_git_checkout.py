import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from git_checkout import CheckoutError, checked_head


class GitCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        self.git('init', '-q')
        (self.root / 'source.txt').write_text('original\n')
        self.git('add', 'source.txt')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
        self.head = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True)

    def test_clean_checkout(self):
        self.assertEqual(checked_head(self.root), self.head)

    def test_parent_repository_is_not_a_project(self):
        child = self.root / 'child'
        child.mkdir()
        with self.assertRaisesRegex(CheckoutError, 'wrong_git_root'):
            checked_head(child)

    def test_modified_tracked_file(self):
        (self.root / 'source.txt').write_text('changed\n')
        with self.assertRaisesRegex(CheckoutError, 'dirty_tracked_tree'):
            checked_head(self.root)

    def test_staged_file(self):
        (self.root / 'source.txt').write_text('changed\n')
        self.git('add', 'source.txt')
        with self.assertRaisesRegex(CheckoutError, 'dirty_tracked_tree'):
            checked_head(self.root)

    def test_deleted_tracked_file(self):
        (self.root / 'source.txt').unlink()
        with self.assertRaisesRegex(CheckoutError, 'dirty_tracked_tree'):
            checked_head(self.root)

    def test_assume_unchanged_rejected(self):
        self.git('update-index', '--assume-unchanged', 'source.txt')
        with self.assertRaisesRegex(CheckoutError, 'hidden_index_entry'):
            checked_head(self.root)

    def test_skip_worktree_rejected(self):
        self.git('update-index', '--skip-worktree', 'source.txt')
        with self.assertRaisesRegex(CheckoutError, 'hidden_index_entry'):
            checked_head(self.root)

    def test_git_dir_environment_ignored(self):
        with patch.dict(os.environ, {'GIT_DIR': '/nonexistent', 'GIT_WORK_TREE': '/nonexistent'}):
            self.assertEqual(checked_head(self.root), self.head)

    def test_untracked_overlay_allowed(self):
        (self.root / 'local-overlay.txt').write_text('overlay')
        self.assertEqual(checked_head(self.root), self.head)


if __name__ == '__main__':
    unittest.main()
