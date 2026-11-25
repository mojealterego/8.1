"""OmniCore 8.1 source gate: local override and all pinned AOSP checkouts.

Only compares on-disk sources to a resolved, revision-locked repo manifest.
It never claims AOSP builds or emulator boots and never downloads/changes code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from xml.etree import ElementTree as ET

OWNER_SHA = '4a9acdc305c27336f8ef74505800bcc541f6052e'
OWNER_NAME = 'mojealterego/8.1'
MIN_FULL_MANIFEST_PROJECTS = 100
REQUIRED_PROJECT_DIRS = (
    'frameworks/base', 'art', 'bionic', 'system/core',
    'frameworks/native', 'build', 'libcore',
)
SHA_RE = re.compile(r'[a-f0-9]{40}\Z')


class GateError(RuntimeError):
    """Fail closed when a source invariant cannot be proven."""


def _xml(path: Path) -> ET.Element:
    contents = path.read_bytes()
    if len(contents) > 8_000_000:
        raise GateError('manifest_too_large')
    if b'<!DOCTYPE' in contents.upper() or b'<!ENTITY' in contents.upper():
        raise GateError('DTD_not_allowed')
    try:
        node = ET.fromstring(contents)
    except ET.ParseError as exc:
        raise GateError('invalid_xml') from exc
    if node.tag != 'manifest':
        raise GateError('not_a_manifest')
    return node


def validate_manifest(path: Path) -> None:
    """Validate the owner fork replacement snippet, not the complete AOSP manifest."""
    root = _xml(path)
    remote = root.findall('remote')
    removal = root.findall('remove-project')
    projects = root.findall('project')
    if (len(remote) != 1 or remote[0].get('name') != 'omnicore-github'
            or remote[0].get('fetch') != 'https://github.com/'):
        raise GateError('untrusted_remote')
    if len(removal) != 1 or removal[0].get('name') != 'platform/frameworks/base':
        raise GateError('incorrect_upstream_removal')
    if len(projects) != 1:
        raise GateError('unexpected_projects')
    if len(root) != 3:
        raise GateError('unknown_manifest_items')
    project = projects[0]
    expected = ('mojealterego/8.1', 'frameworks/base', 'omnicore-github', OWNER_SHA)
    actual = tuple(project.get(x) for x in ('name', 'path', 'remote', 'revision'))
    if actual != expected or list(project):
        raise GateError('unpinned_or_untrusted_project')


def _safe_rel_path(value: str) -> bool:
    if not value or '\\' in value or '\x00' in value or value.startswith('/'):
        return False
    p = PurePosixPath(value)
    return all(c not in ('', '.', '..', '.repo', '.git') and not c.startswith('.repo') for c in value.split('/')) and str(p) == value


def validate_lock_manifest(path: Path, *, min_projects: int = MIN_FULL_MANIFEST_PROJECTS) -> dict[str, str]:
    """Require SHA-pinned *all* projects from `repo manifest -r`.

    min_projects=100 for production. A smaller threshold is solely for minimal
    synthetic unit-test fixture; it is not exposed in CLI.
    """
    root = _xml(path)
    projects = root.findall('project')
    if len(projects) < min_projects:
        raise GateError('too_few_projects:' + str(len(projects)))
    mapping: dict[str, str] = {}
    found_owner = False
    for project in projects:
        name = project.get('name', '')
        target_path = project.get('path') or name
        revision = project.get('revision', '')
        if not _safe_rel_path(target_path):
            raise GateError('unsafe_project_path:' + target_path)
        if target_path in mapping:
            raise GateError('duplicate_project_path:' + target_path)
        if not SHA_RE.fullmatch(revision):
            raise GateError('unpinned_revision:' + target_path)
        mapping[target_path] = revision
        if target_path == 'frameworks/base':
            if name != OWNER_NAME or revision != OWNER_SHA or project.get('remote') != 'omnicore-github':
                raise GateError('owner_fork_mismatch')
            found_owner = True
    if not found_owner:
        raise GateError('owner_fork_missing')
    missing = sorted(set(REQUIRED_PROJECT_DIRS) - mapping.keys())
    if missing:
        raise GateError('required_projects_missing:' + ','.join(missing))
    remotes = [p for p in root.findall('remote') if p.get('name') == 'omnicore-github']
    if len(remotes) != 1 or remotes[0].get('fetch') != 'https://github.com/':
        raise GateError('owner_remote_mismatch')
    return mapping


def _git_head(project: Path) -> str:
    try:
        return subprocess.check_output(
            ['git', '-C', str(project), 'rev-parse', '--verify', 'HEAD'],
            stderr=subprocess.DEVNULL, timeout=10, text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise GateError('git_head_unavailable:' + str(project)) from exc


def verify_checkout(root: Path, lock_path: Path | None = None, *, min_projects: int = MIN_FULL_MANIFEST_PROJECTS) -> dict:
    """Gate SOURCE_PINNED_CHECKOUT; not a build or 100%-completeness proof."""
    root = root.resolve(strict=True)
    missing = [name for name in REQUIRED_PROJECT_DIRS if not (root / name).is_dir()]
    if missing:
        raise GateError('incomplete_aosp:' + ','.join(missing))
    if lock_path is None:
        raise GateError('lock_required')
    if not (root / '.repo/manifest.xml').is_file():
        raise GateError('repo_checkout_marker_missing')
    mapping = validate_lock_manifest(lock_path, min_projects=min_projects)
    # Detect symlinks/missing directories for ALL projects before Git SHA checks.
    for relative in mapping:
        project = root / relative
        if not project.is_dir():
            raise GateError('project_missing:' + relative)
        # Reject symlinked directory components, not only symlinked final paths.
        partial = root
        for segment in relative.split('/'):
            partial = partial / segment
            if partial.is_symlink():
                raise GateError('symlink_project_path:' + relative)
        if not project.resolve().is_relative_to(root):
            raise GateError('project_escapes_checkout:' + relative)
    for relative, expected_sha in mapping.items():
        project = root / relative
        head = _git_head(project)
        if head != expected_sha:
            raise GateError('head_mismatch:' + relative + ':' + head)
    if not (root / 'frameworks/base/packages/SystemUI/Android.mk').is_file():
        raise GateError('framework_systemui_missing')
    return {
        'gate': 'F0_SOURCE_PINNED_CHECKOUT', 'result': 'PASS',
        'framework_commit': OWNER_SHA,
        'verified_projects': len(mapping),
        'lock_sha256': hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        'build_status': 'NOT_TESTED', 'emulator_status': 'NOT_TESTED',
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True, help='Owner local manifest snippet')
    p.add_argument('--aosp', type=Path, help='Full repo-sync checkout')
    p.add_argument('--lock', type=Path, help='Resolved commit-locked manifest from repo manifest -r')
    args = p.parse_args(argv)
    try:
        validate_manifest(args.manifest)
        if args.aosp is None:
            if args.lock is not None:
                raise GateError('aosp_required_with_lock')
            result = {'gate': 'F0_MANIFEST_ONLY', 'result': 'PASS',
                      'build_status': 'NOT_TESTED', 'emulator_status': 'NOT_TESTED'}
        else:
            result = verify_checkout(args.aosp, args.lock)
    except (GateError, OSError, ValueError) as exc:
        print(json.dumps({'gate': 'F0_SOURCE_PINNED_CHECKOUT', 'result': 'BLOCKED',
                          'reason': str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())