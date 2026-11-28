import unittest
from concurrent.futures import ThreadPoolExecutor
from omnicore_host.neuromorphic import OmegaXNeuromorphicVArch, FrameStatus

SIGNALS = [0.35, -0.45, 0.78, 0.15, -0.25, 0.62, 0.40, -0.68,
           0.52, 0.12, -0.38, 0.85, 0.22, -0.30, 0.71, -0.18]

class Clock:
    def __init__(self, step=0): self.value, self.step = 0, step
    def __call__(self):
        self.value += self.step
        return self.value

class NeuroTests(unittest.TestCase):
    def make(self, **kw):
        return OmegaXNeuromorphicVArch(clock=Clock(), **kw)

    def test_dimensions_and_bounds(self):
        r = self.make().execute_frame(SIGNALS)
        self.assertEqual(r.status, FrameStatus.COMMITTED)
        self.assertEqual(tuple(map(len,r.outputs)), (6,6,10,8,6))
        self.assertTrue(all(-1 <= x <= 1 for v in r.outputs for x in v))

    def test_deterministic_trajectory_and_cache_equivalence(self):
        a,b = self.make(cache_capacity=12), self.make(cache_capacity=0)
        for i in range(40):
            data = [0.0]*16 if i < 3 or i % 3 == 0 else SIGNALS
            x,y = a.execute_frame(data),b.execute_frame(data)
            self.assertEqual(x.outputs,y.outputs)
            self.assertEqual(a.snapshot(),b.snapshot())
        self.assertGreater(a.cache_info().hits,0)

    def test_rollback_when_work_exhausted(self):
        a = self.make(work_limit=1)
        before,cache = a.snapshot(),a.cache_info()
        r = a.execute_frame(SIGNALS)
        self.assertEqual(r.status,FrameStatus.ABORT_WORK)
        self.assertIsNone(r.outputs)
        self.assertEqual(a.snapshot(),before)
        self.assertEqual(a.cache_info(),cache)

    def test_rollback_when_clock_exhausted(self):
        a = OmegaXNeuromorphicVArch(clock=Clock(500_000),frame_budget_ms=1)
        before = a.snapshot()
        self.assertEqual(a.execute_frame(SIGNALS).status,FrameStatus.ABORT_TIME)
        self.assertEqual(a.snapshot(),before)

    def test_clock_regression_fails_closed(self):
        values = iter([100,99])
        a = OmegaXNeuromorphicVArch(clock=lambda:next(values))
        self.assertEqual(a.execute_frame(SIGNALS).status,FrameStatus.ABORT_TIME)
        self.assertEqual(a.snapshot().tick,0)

    def test_mid_frame_abort_preserves_committed_state_and_cache(self):
        clock = Clock()
        a = OmegaXNeuromorphicVArch(clock=clock,frame_budget_ms=1)
        self.assertEqual(a.execute_frame(SIGNALS).status,FrameStatus.COMMITTED)
        before,cache = a.snapshot(),a.cache_info()
        clock.step = 20_000
        r = a.execute_frame([-x for x in SIGNALS])
        self.assertEqual(r.status,FrameStatus.ABORT_TIME)
        self.assertGreater(r.macs,0)
        self.assertIsNone(r.outputs)
        self.assertEqual(a.snapshot(),before)
        self.assertEqual(a.cache_info(),cache)
        clock.step = 0
        self.assertEqual(a.execute_frame(SIGNALS).tick,2)

    def test_bad_input_does_not_mutate(self):
        a = self.make(); before = a.snapshot()
        for data in ([0]*15,[0]*17,[float('nan')]*16,[float('inf')]*16,[9]*16,[True]*16):
            with self.subTest(data=data):
                with self.assertRaises(ValueError): a.execute_frame(data)
        self.assertEqual(a.snapshot(),before)

    def test_cache_capacity_partition(self):
        a = self.make(cache_capacity=6)
        for i in range(60): a.execute_frame([((i+j)%17-8)/8 for j in range(16)])
        info=a.cache_info()
        self.assertLessEqual(info.entries,6)
        self.assertTrue(all(n<=1 for n in info.per_layer))

    def test_feedback_affects_next_tick(self):
        a = self.make(); a.execute_frame(SIGNALS)
        self.assertTrue(any(a.snapshot().feedback))
        self.assertEqual(len(a.snapshot().feedback),16)

    def test_sparse_compute_count(self):
        a = self.make(cache_capacity=0)
        r = a.execute_frame([0]*16)
        self.assertEqual(r.macs,0)
        self.assertGreater(r.work,0)

    def test_serialized_concurrent_calls(self):
        a = self.make()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(a.execute_frame,[SIGNALS]*20))
        committed = [r for r in results if r.status is FrameStatus.COMMITTED]
        self.assertEqual(len(committed),20)
        self.assertEqual(sorted(r.tick for r in committed),list(range(1,21)))

    def test_validate_configuration(self):
        for kw in ({'cache_capacity':-1},{'cache_capacity':True},{'frame_budget_ms':float('nan')}, {'work_limit':0}):
            with self.assertRaises(ValueError): self.make(**kw)

if __name__ == '__main__': unittest.main()
