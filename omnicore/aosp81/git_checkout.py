"""Read-only Git worktree integrity check for the AOSP source gate."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess


class CheckoutError(RuntimeError):
    pass


def checked_head(project: Path) -> str:
    project = project.resolve(strict=True)
    # Do not inherit repository, index, config or worktree overrides.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0')

    def git(*args: str) -> str:
        try:
            return subprocess.check_output(
                ['git', '--no-replace-objects', '-C', str(project),
                 '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', *args],
                env=env, stderr=subprocess.DEVNULL, timeout=120,
                text=True, errors='surrogateescape',
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise CheckoutError('git_check_failed:' + args[0]) from exc

    top = git('rev-parse', '--show-toplevel').rstrip('\n')
    if Path(top).resolve(strict=True) != project:
        raise CheckoutError('wrong_git_root')
    head = git('rev-parse', '--verify', 'HEAD').strip()
    if not re.fullmatch(r'[0-9a-f]{40}', head):
        raise CheckoutError('invalid_git_head')
    entries = git('ls-files', '-v', '-z').split('\0')
    if any(entry and (entry[0] == 'S' or entry[0].islower()) for entry in entries):
        raise CheckoutError('hidden_index_entry')
    if git('status', '--porcelain=v1', '--untracked-files=no', '--ignore-submodules=none'):
        raise CheckoutError('dirty_tracked_tree')
    if git('rev-parse', '--verify', 'HEAD').strip() != head:
        raise CheckoutError('head_changed_during_check')
    return head
