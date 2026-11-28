import threading
import unittest

from omnicore_host.zenoh_session import SessionManager, SessionState, SessionError


class Query:
    def __init__(self):
        self.drops = 0
        self.replies = 0

    def drop(self):
        self.drops += 1


class Ingress:
    routes = ('omnicore/v1/node/tenant/peer/intent.local',)

    def __init__(self):
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def handle(self, query):
        try:
            self.calls += 1
            self.entered.set()
            if not self.release.wait(3):
                raise RuntimeError('test barrier timeout')
            query.replies += 1
        finally:
            query.drop()


class Session:
    def __init__(self, *, fail_declare=False, fail_close=False, early=False):
        self.fail_declare = fail_declare
        self.fail_close = fail_close
        self.early = early
        self.closed = False
        self.callback = None
        self.early_query = Query()

    def declare_queryable(self, key, handler):
        self.callback = handler
        if self.early:
            handler(self.early_query)
        if self.fail_declare:
            raise OSError('registration failed')
        return object()

    def close(self):
        if self.fail_close:
            raise OSError('close failed')
        self.closed = True

    def deliver(self):
        q = Query()
        self.callback(q)
        return q


def register(session, ingress):
    return tuple(session.declare_queryable(key, ingress.handle) for key in ingress.routes)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.ingress = Ingress()
        self.manager = SessionManager(self.ingress, register=register)
        self.addCleanup(self.manager.stop)

    def start(self, **kwargs):
        session = Session(**kwargs)
        self.manager.start(lambda: session)
        return session

    def test_nominal_and_idempotent_stop(self):
        s = self.start()
        self.assertEqual(self.manager.state, SessionState.ACTIVE)
        self.assertEqual(s.deliver().replies, 1)
        self.manager.stop()
        self.manager.stop()
        self.assertTrue(s.closed)
        self.assertEqual(self.manager.state, SessionState.STOPPED)
        self.assertEqual(s.deliver().replies, 0)

    def test_early_callback_never_executes(self):
        s = self.start(early=True)
        self.assertEqual((s.early_query.replies, s.early_query.drops), (0, 1))
        self.assertEqual(self.ingress.calls, 0)
        self.assertEqual(s.deliver().replies, 1)

    def test_reconfigure_fences_old_callback(self):
        old = self.start()
        new = Session()
        def factory():
            self.assertTrue(old.closed)
            return new
        self.manager.reconfigure(factory)
        self.assertEqual(old.deliver().replies, 0)
        self.assertEqual(new.deliver().replies, 1)
        self.assertEqual(self.ingress.calls, 1)

    def test_factory_failure_is_retryable(self):
        def fail(): raise OSError('partition')
        with self.assertRaises(OSError): self.manager.start(fail)
        self.assertEqual(self.manager.state, SessionState.FAILED)
        self.assertEqual(self.start().deliver().replies, 1)

    def test_registration_failure_closes_session(self):
        s = Session(fail_declare=True)
        with self.assertRaises(OSError): self.manager.start(lambda: s)
        self.assertTrue(s.closed)
        self.assertEqual(s.deliver().replies, 0)
        self.assertEqual(self.start().deliver().replies, 1)

    def test_cleanup_failure_blocks_new_generation(self):
        s = Session(fail_declare=True, fail_close=True)
        with self.assertRaises(ExceptionGroup): self.manager.start(lambda: s)
        with self.assertRaises(SessionError): self.manager.start(Session)
        self.assertEqual(s.deliver().replies, 0)
        s.fail_close = False
        self.manager.stop()
        self.assertTrue(s.closed)
        self.start()

    def test_close_failure_fences_and_blocks_factory(self):
        s = self.start(fail_close=True)
        called = []
        try:
            with self.assertRaises(OSError): self.manager.reconfigure(lambda: called.append(True))
            self.assertEqual(called, [])
            self.assertEqual(s.deliver().replies, 0)
            self.assertEqual(self.manager.state, SessionState.FAILED)
        finally:
            s.fail_close = False
        self.manager.stop()
        self.start()

    def test_drain_timeout_blocks_new_session(self):
        s = self.start()
        self.ingress.release.clear()
        t = threading.Thread(target=s.deliver)
        t.start()
        try:
            self.assertTrue(self.ingress.entered.wait(1))
            with self.assertRaises(SessionError): self.manager.reconfigure(Session, drain_timeout=0.01)
            self.assertFalse(s.closed)
            self.assertEqual(s.deliver().replies, 0)
            self.assertEqual(self.manager.state, SessionState.FAILED)
            with self.assertRaises(SessionError): self.manager.start(Session)
        finally:
            self.ingress.release.set()
            t.join(2)
        self.assertFalse(t.is_alive())
        self.manager.reconfigure(Session)
        self.assertTrue(s.closed)

    def test_admission_limit_and_recovery(self):
        s = self.start()
        self.ingress.release.clear()
        t = threading.Thread(target=s.deliver)
        t.start()
        try:
            self.assertTrue(self.ingress.entered.wait(1))
            q = s.deliver()
            self.assertEqual((q.replies,q.drops), (0,1))
        finally:
            self.ingress.release.set()
            t.join(2)
        self.assertFalse(t.is_alive())
        self.assertEqual(s.deliver().replies, 1)

    def test_reconfiguration_failure_does_not_restore_old_session(self):
        s = self.start()
        def fail(): raise OSError('new link unavailable')
        with self.assertRaises(OSError): self.manager.reconfigure(fail)
        self.assertTrue(s.closed)
        self.assertEqual(s.deliver().replies, 0)
        self.start()

    def test_callback_exception_releases_admission(self):
        def failing(query):
            query.drop()
            raise RuntimeError('handler failure')
        self.ingress.handle = failing
        s = self.start()
        for _ in range(2):
            with self.assertRaises(RuntimeError): s.deliver()
        self.manager.stop(drain_timeout=0.01)

    def test_invalid_lifecycle_parameters(self):
        for limit in (0, True, 33):
            with self.assertRaises(ValueError): SessionManager(self.ingress, register=register, max_inflight=limit)
        with self.assertRaises(ValueError): self.manager.stop(drain_timeout=float('nan'))
        self.start()
        with self.assertRaises(SessionError): self.manager.start(Session)


if __name__ == '__main__': unittest.main()
