"""Staged, fail-closed installation of OmniCore AOSP build overlay.

Only two known source directories are ever installed. This tool never invokes
repo sync, flashes devices, changes bootloader, or overwrites existing files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from preflight import verify_checkout, GateError

COMPONENTS = (
    ('packages/apps/OmniCoreHome', 'packages/apps/OmniCoreHome'),
    ('device/omnicore/generic', 'device/omnicore/generic'),
)


class OverlayError(RuntimeError):
    """Unsafe or conflicting overlay transaction."""


def _file_map(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for source in sorted(path.rglob('*')):
        if source.is_symlink():
            raise OverlayError('symlink_source:' + str(source))
        if source.is_file():
            result[str(source.relative_to(path))] = hashlib.sha256(source.read_bytes()).hexdigest()
    return result


def _inspect_destination(root: Path, dest: Path) -> None:
    if not dest.is_relative_to(root):
        raise OverlayError('destination_outside_aosp')
    current = root
    for piece in dest.relative_to(root).parts:
        current = current / piece
        if current.is_symlink():
            raise OverlayError('symlink_destination:' + str(current))
        if current.exists() and not current.is_dir():
            raise OverlayError('destination_not_directory:' + str(current))


def install_overlay(
    aosp_root: Path, overlay_root: Path, *, lock_path: Path, apply: bool = False,
) -> dict:
    """Require full verified AOSP pins then optionally copy approved components.

    Checks all destinations before modifying anything. On an installation error,
    removes only directories created during this transaction.
    """
    source_report = verify_checkout(aosp_root, lock_path)
    if source_report.get('result') != 'PASS':
        raise OverlayError('source_gate_did_not_pass')
    aosp = aosp_root.resolve(strict=True)
    overlay = overlay_root.resolve(strict=True)
    planned: list[tuple[Path, Path, str]] = []
    for src_name, dst_name in COMPONENTS:
        src = overlay / src_name
        dest = aosp / dst_name
        if not src.is_dir() or src.is_symlink():
            raise OverlayError('missing_or_symlink_source:' + str(src))
        src_files = _file_map(src)
        if not src_files:
            raise OverlayError('empty_source:' + str(src))
        _inspect_destination(aosp, dest)
        if dest.exists():
            if _file_map(dest) != src_files:
                raise OverlayError('conflict_existing_destination:' + str(dest))
            action = 'UNCHANGED'
        else:
            action = 'CREATE'
        planned.append((src, dest, action))
    if not apply:
        return {'mode': 'DRY_RUN', 'actions': [a for _, _, a in planned],
                'source_gate': source_report['result']}

    created: list[Path] = []
    try:
        for src, dest, action in planned:
            if action == 'UNCHANGED':
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            _inspect_destination(aosp, dest)
            staged = Path(tempfile.mkdtemp(prefix='.omnicore-stage-', dir=dest.parent))
            try:
                shutil.copytree(src, staged, dirs_exist_ok=True, symlinks=False)
                if _file_map(staged) != _file_map(src):
                    raise OverlayError('copy_integrity_failed:' + str(dest))
                os.rename(staged, dest)
                created.append(dest)
            finally:
                if staged.exists():
                    shutil.rmtree(staged)
    except Exception:
        for dest in reversed(created):
            shutil.rmtree(dest)
        raise
    return {'mode': 'APPLIED', 'actions': [a for _, _, a in planned],
            'source_gate': source_report['result']}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aosp', type=Path, required=True)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Install (default only plans)')
    args = parser.parse_args(argv)
    try:
        report = install_overlay(args.aosp, Path(__file__).parent / 'product',
                                 lock_path=args.lock, apply=args.apply)
    except (GateError, OverlayError, OSError, ValueError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({'status': 'PASS', **report}, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())