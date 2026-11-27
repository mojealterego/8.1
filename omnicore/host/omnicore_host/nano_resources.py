"""Host-only NANO admission and kernel limits for trusted local workers."""
from __future__ import annotations
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import resource
import threading

MiB = 1024 * 1024
WORKER_ADDRESS_SPACE = 64 * MiB
SYSTEM_RESERVE = 96 * MiB


class ResourceDenied(RuntimeError):
    pass


def read_available_bytes() -> int:
    # Do not substitute MemFree or a guessed value if MemAvailable is absent.
    with open('/proc/meminfo', 'rb') as stream:
        data = stream.read(65_537)
    if len(data) > 65_536:
        raise ResourceDenied('memory_snapshot_invalid')
    rows = [row.split() for row in data.splitlines() if row.startswith(b'MemAvailable:')]
    if len(rows) != 1 or len(rows[0]) != 3 or rows[0][2] != b'kB' or not rows[0][1].isdigit():
        raise ResourceDenied('memory_snapshot_invalid')
    return int(rows[0][1]) * 1024


class NanoGovernor:
    """Single admission slot per shared governor, no queue, no retry."""
    def __init__(self, *, available: Callable[[], int] = read_available_bytes):
        self._available = available
        self._slot = threading.BoundedSemaphore(1)

    @contextmanager
    def admit(self) -> Iterator[None]:
        if not self._slot.acquire(blocking=False):
            raise ResourceDenied('worker_busy')
        try:
            try:
                available = self._available()
            except Exception as exc:
                raise ResourceDenied('memory_snapshot_unavailable') from exc
            if type(available) is not int or available < 0:
                raise ResourceDenied('memory_snapshot_invalid')
            if available < WORKER_ADDRESS_SPACE + SYSTEM_RESERVE:
                raise ResourceDenied('memory_pressure')
            yield
        finally:
            self._slot.release()


def apply_worker_limits() -> None:
    """Apply irreversible caps inside the dedicated child, never in its parent."""
    for kind, cap in ((resource.RLIMIT_AS, WORKER_ADDRESS_SPACE),
                      (resource.RLIMIT_CPU, 2), (resource.RLIMIT_NOFILE, 32),
                      (resource.RLIMIT_CORE, 0), (resource.RLIMIT_FSIZE, 0)):
        soft, hard = resource.getrlimit(kind)
        new_hard = cap if hard == resource.RLIM_INFINITY else min(hard, cap)
        new_soft = new_hard if soft == resource.RLIM_INFINITY else min(soft, new_hard)
        resource.setrlimit(kind, (new_soft, new_hard))
