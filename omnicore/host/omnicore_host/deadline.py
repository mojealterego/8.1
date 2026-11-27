"""Monotonic execution budget, distinct from the socket receive deadline."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
import time


class DeadlineExceeded(TimeoutError):
    pass


@dataclass(frozen=True)
class ExecutionBudget:
    expires_ns: int
    clock: Callable[[], int] = time.monotonic_ns

    @classmethod
    def start(cls, started_ns: int, deadline_ms: int, clock: Callable[[], int]) -> ExecutionBudget:
        return cls(started_ns + deadline_ms * 1_000_000, clock)

    def remaining(self) -> float:
        ns = self.expires_ns - self.clock()
        if ns <= 0:
            raise DeadlineExceeded('deadline_exceeded')
        return ns / 1_000_000_000

    def check(self) -> None:
        self.remaining()
