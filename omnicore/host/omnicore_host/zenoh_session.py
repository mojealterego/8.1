"""Fail-closed lifecycle for an owned Zenoh session and its queryables.

The immutable ingress (including its replay store) survives reconfiguration.
The trusted factory owns cleanup if it raises before returning a session.
No retry, network detection, or timeout on external open/close calls is implied.
"""
from __future__ import annotations
from collections.abc import Callable
from enum import Enum
import math
import threading
from typing import Protocol


class SessionState(Enum):
    STOPPED = 'stopped'
    STARTING = 'starting'
    ACTIVE = 'active'
    DRAINING = 'draining'
    FAILED = 'failed'


class SessionError(RuntimeError):
    pass


class Query(Protocol):
    def drop(self) -> None: ...


class Session(Protocol):
    def declare_queryable(self, key: str, handler: Callable[[Query], None]) -> object: ...
    def close(self) -> None: ...


class _GuardedSession:
    def __init__(self, manager: SessionManager, session: Session, generation: int):
        self._manager, self._session, self._generation = manager, session, generation

    def declare_queryable(self, key: str, handler: Callable[[Query], None]) -> object:
        def guarded(query: Query) -> None:
            if not self._manager._enter(self._generation):
                query.drop()
                return
            try:
                handler(query)
            finally:
                self._manager._leave()
        return self._session.declare_queryable(key, guarded)


def _register(session, ingress):
    from .zenoh_boundary import declare_queryables
    return declare_queryables(session, ingress)


class SessionManager:
    """Serialize lifecycle changes; fence callbacks before draining/closing.

    A failed close retains ownership and blocks further opens until stop succeeds.
    A failed new open never restores the old configuration. Do not call lifecycle
    methods from within a query callback or a session factory.
    """
    def __init__(self, ingress, *, register=_register, max_inflight: int = 1):
        if type(max_inflight) is not int or not 1 <= max_inflight <= 32:
            raise ValueError('invalid_inflight_limit')
        self._ingress, self._register = ingress, register
        self._limit = max_inflight
        self._operation = threading.Lock()
        self._condition = threading.Condition()
        self._state = SessionState.STOPPED
        self._generation = 0
        self._inflight = 0
        self._session: Session | None = None
        self._handles: tuple = ()

    @property
    def state(self) -> SessionState:
        with self._condition:
            return self._state

    def _set_state(self, state: SessionState) -> None:
        with self._condition:
            self._state = state

    def _enter(self, generation: int) -> bool:
        with self._condition:
            if (self._state is not SessionState.ACTIVE or generation != self._generation
                    or self._inflight >= self._limit):
                return False
            self._inflight += 1
            return True

    def _leave(self) -> None:
        with self._condition:
            self._inflight -= 1
            self._condition.notify_all()

    def _start(self, factory: Callable[[], Session]) -> None:
        with self._condition:
            if self._session is not None or self._state not in (SessionState.STOPPED, SessionState.FAILED):
                raise SessionError('session_already_owned')
            self._generation += 1
            generation = self._generation
            self._state = SessionState.STARTING
        try:
            self._session = factory()
            self._handles = tuple(self._register(_GuardedSession(self, self._session, generation), self._ingress))
        except BaseException as original:
            self._set_state(SessionState.FAILED)
            if self._session is not None:
                try:
                    self._session.close()
                except BaseException as cleanup:
                    raise BaseExceptionGroup('session_start_cleanup_failed', [original, cleanup])
                self._session = None
                self._handles = ()
            raise
        self._set_state(SessionState.ACTIVE)

    def start(self, factory: Callable[[], Session]) -> None:
        with self._operation:
            self._start(factory)

    @staticmethod
    def _validate_timeout(timeout: float) -> None:
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= 60:
            raise ValueError('invalid_drain_timeout')

    def _stop(self, timeout: float) -> None:
        with self._condition:
            self._state = SessionState.DRAINING
            if not self._condition.wait_for(lambda: self._inflight == 0, timeout=timeout):
                self._state = SessionState.FAILED
                raise SessionError('session_drain_timeout')
        if self._session is not None:
            try:
                self._session.close()
            except BaseException:
                self._set_state(SessionState.FAILED)
                raise
            self._session = None
            self._handles = ()
        self._set_state(SessionState.STOPPED)

    def stop(self, *, drain_timeout: float = 5.0) -> None:
        self._validate_timeout(drain_timeout)
        with self._operation:
            self._stop(drain_timeout)

    def reconfigure(self, factory: Callable[[], Session], *, drain_timeout: float = 5.0) -> None:
        self._validate_timeout(drain_timeout)
        with self._operation:
            self._stop(drain_timeout)
            self._start(factory)
