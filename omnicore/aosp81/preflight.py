"""OmniCore 8.1 F0/G01: verify local manifest and *complete* AOSP checkout.

This tool does not download, compile, flash, or claim SOURCE_VERIFIED
unless a complete tree exists and the pinned checkout is present.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import json
import subprocess
import sys

from xml.etree import ElementTree as ET

EXPECTED_FORK_SHA = '4a9acdc305c27336f8ef74505800bcc541f6052e'
REQUIRED_PROJECT_DIRS = ('frameworks/base', 'art', 'bionic', 'system/core',
                         'frameworks/native', 'build', 'libcore')

class GateError(RuntimeError):
    pass


def validate_manifest(path: Path) -> None:
    contents = path.read_text(encoding='utf-8')
    if '<!DOCTYPE' in contents.upper() or '<!ENTITY' in contents.upper():
        raise GateError('DTD_not_allowed')
    try:
        root = ET.fromstring(contents)
    except ET.ParseError as exc:
        raise GateError('invalid_xml') from exc
    if root.tag != 'manifest':
        raise GateError('not_a_manifest')
    remotes = root.findall('remote')
    removals = root.findall('remove-project')
    projects = root.findall('project')
    if (len(remotes) != 1 or remotes[0].get('name') != 'omnicore-github'
            or remotes[0].get('fetch') != 'https://github.com/'):
        raise GateError('untrusted_remote')
    if len(removals) != 1 or removals[0].get('name') != 'platform/frameworks/base':
        raise GateError('incorrect_upstream_removal')
    if len(projects) != 1:
        raise GateError('unexpected_projects')
    p = projects[0]
    if (p.get('name'), p.get('path'), p.get('remote'), p.get('revision')) != (
        'mojealterego/8.1', 'frameworks/base', 'omnicore-github', EXPECTED_FORK_SHA
    ):
        raise GateError('unpinned_or_untrusted_project')
    if len(root) != 3:
        raise GateError('unknown_manifest_items')


def verify_checkout(root: Path) -> dict:
    root = root.resolve()
    missing = [name for name in REQUIRED_PROJECT_DIRS if not (root / name).is_dir()]
    if missing:
        raise GateError('incomplete_aosp:' + ','.join(missing))
    try:
        head = subprocess.check_output(
            ['git', '-C', str(root/'frameworks/base'), 'rev-parse', 'HEAD'],
            stderr=subprocess.DEVNULL, timeout=10, text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise GateError('framework_head_unavailable') from exc
    if head != EXPECTED_FORK_SHA:
        raise GateError('framework_head_mismatch:' + head)
    if not (root/'frameworks/base/packages/SystemUI/Android.mk').is_file():
        raise GateError('framework_systemui_missing')
    return {'gate':'F0_SOURCE_PRECHECK','result':'PASS',
            'framework_commit':head,'checked_directories':list(REQUIRED_PROJECT_DIRS),
            'build_status':'NOT_TESTED', 'emulator_status':'NOT_TESTED'}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--aosp', type=Path)
    args = p.parse_args(argv)
    try:
        validate_manifest(args.manifest)
        report = ({'gate':'F0_MANIFEST_ONLY','result':'PASS',
                   'build_status':'NOT_TESTED', 'emulator_status':'NOT_TESTED'}
                  if args.aosp is None else verify_checkout(args.aosp))
    except (GateError, OSError) as exc:
        print(json.dumps({'gate':'F0_SOURCE_PRECHECK','result':'BLOCKED',
                          'reason':str(exc)},sort_keys=True))
        return 2
    print(json.dumps(report,sort_keys=True))
    return 0


if __name__=='__main__':
    sys.exit(main())
