"""Bounded, deterministic fixed-point SNN reference backend for OmniCore host.

Synthetic weights are not trained. Logical layers are not physical cores.
Only pure synaptic products are cached; membrane state always advances on commit.
"""
from __future__ import annotations
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import math
import threading
import time

Q = 4096
# Each row: input width, output width, threshold, leak, sparse cutoff (Q units).
LAYERS = ((16,16,2130,3482,0), (16,12,2212,3523,205),
          (28,10,2253,3441,410), (22,8,2335,3482,410),
          (30,6,2417,3604,1024), (36,16,2458,3359,614))

class FrameStatus(str, Enum):
    COMMITTED = 'committed'
    ABORT_WORK = 'abort_work'
    ABORT_TIME = 'abort_time'

@dataclass(frozen=True)
class Snapshot:
    tick: int
    membranes: tuple[tuple[tuple[int,int], ...], ...]
    feedback: tuple[int, ...]

@dataclass(frozen=True)
class CacheInfo:
    entries: int
    hits: int
    misses: int
    per_layer: tuple[int, ...]

@dataclass(frozen=True)
class FrameResult:
    status: FrameStatus
    tick: int
    outputs: tuple[tuple[float, ...], ...] | None
    work: int
    macs: int

class _Abort(Exception):
    def __init__(self, status: FrameStatus): self.status = status

class _Budget:
    def __init__(self, clock: Callable[[], int], duration: int, limit: int):
        self.clock, self.start = clock, clock()
        self.previous, self.duration, self.limit = self.start, duration, limit
        self.work = self.macs = 0

    def charge(self, cost: int = 0, macs: int = 0) -> None:
        now = self.clock()
        if now < self.previous or now - self.start >= self.duration:
            raise _Abort(FrameStatus.ABORT_TIME)
        self.previous = now
        if self.work + cost > self.limit:
            raise _Abort(FrameStatus.ABORT_WORK)
        self.work += cost
        self.macs += macs


def _clip(x: int, cap: int = Q) -> int:
    return max(-cap, min(cap, x))


def _weights(layer: int) -> tuple[tuple[tuple[int,int], ...], ...]:
    width, count, _, _, cutoff = LAYERS[layer]
    rows = []
    for r in range(count):
        row = []
        for c in range(width):
            # Stable synthetic signed weights, about +/-0.64; no PRNG state.
            n = int.from_bytes(hashlib.sha256(f'OCRS-SNN-v1/{layer}/{r}/{c}'.encode()).digest()[:2], 'big')
            w = (n * 5243 // 65535) - 2621
            if w and abs(w) >= cutoff:
                row.append((c,w))
        rows.append(tuple(row))
    return tuple(rows)


class OmegaXNeuromorphicVArch:
    """Six stateful layers, five bounded outputs; synchronous, single-owner commit.

    Q12 inputs/weights and integer phase modulation. Cache keys are exact tuples
    of quantized inputs in a layer-specific partition. No cached membrane state.
    Deadline is cooperative (not a real-time guarantee); work counts logical
    row visits, sparse weight scans, cache-copy entries and neuron updates.
    """
    def __init__(self, *, frame_budget_ms: float = 2.0, cache_capacity: int = 128,
                 work_limit: int = 8192, clock: Callable[[], int] = time.perf_counter_ns):
        if (type(frame_budget_ms) not in (int,float) or not math.isfinite(frame_budget_ms)
                or not 0.05 <= frame_budget_ms <= 1000
                or type(cache_capacity) is not int or not 0 <= cache_capacity <= 1024
                or type(work_limit) is not int or not 1 <= work_limit <= 100_000
                or not callable(clock)):
            raise ValueError('invalid_neuromorphic_configuration')
        self._duration = int(frame_budget_ms * 1_000_000)
        self._limit, self._clock = work_limit, clock
        self._lock = threading.Lock()
        self._weights = tuple(_weights(i) for i in range(len(LAYERS)))
        self._capacities = tuple(cache_capacity//6 + int(i < cache_capacity%6) for i in range(6))
        self._state = Snapshot(0, tuple(tuple((0,0) for _ in range(layer[1])) for layer in LAYERS), (0,)*16)
        self._cache = tuple(OrderedDict() for _ in LAYERS)
        self._hits = self._misses = 0

    def snapshot(self) -> Snapshot:
        with self._lock: return self._state

    def cache_info(self) -> CacheInfo:
        with self._lock:
            counts = tuple(map(len,self._cache))
            return CacheInfo(sum(counts),self._hits,self._misses,counts)

    def execute_frame(self, signals: Sequence[float]) -> FrameResult:
        if not isinstance(signals,(list,tuple)) or len(signals) != 16:
            raise ValueError('expected_16_signals')
        data = tuple(signals)
        if any(type(x) not in (int,float) or not -1 <= x <= 1 for x in data):
            raise ValueError('invalid_signal')
        inputs = tuple(round(x*Q) for x in data)
        with self._lock:
            b = _Budget(self._clock,self._duration,self._limit)
            old = self._state
            hits = misses = 0
            states = []
            try:
                b.charge(sum(map(len,self._cache)))
                cache = tuple(c.copy() for c in self._cache)
                tick = old.tick + 1
                def forward(i: int, vec: tuple[int,...]) -> tuple[int,...]:
                    nonlocal hits, misses
                    b.charge(1)
                    width,count,threshold,leak,_ = LAYERS[i]
                    assert len(vec)==width
                    part = cache[i]
                    if vec in part:
                        dots = part[vec]; part.move_to_end(vec); hits += 1
                    else:
                        misses += 1
                        sums = []
                        for row in self._weights[i]:
                            acc = 0
                            b.charge(1+len(row))
                            for col,w in row:
                                if vec[col]:
                                    acc += vec[col]*w
                                    b.macs += 1
                            sums.append(acc//Q)
                        dots = tuple(sums)
                        if self._capacities[i]:
                            if len(part) >= self._capacities[i]: part.popitem(last=False)
                            part[vec] = dots
                    state, output = [], []
                    for j,drive in enumerate(dots):
                        b.charge(1)
                        potential, refractory = old.membranes[i][j]
                        if refractory:
                            potential = potential*leak//(2*Q); refractory -= 1; spike = 0
                        else:
                            # Fixed triangular phase modulation, not a physical oscillator.
                            phase = (tick*1843 + (j+1)*2531 + i*977) % (2*Q)
                            gain = 2867 + 1229*abs(phase-Q)//Q
                            potential = _clip(potential*leak//Q + drive*gain//Q, 5*Q//2)
                            spike = 0
                            if abs(potential) >= threshold:
                                spike = _clip(potential); potential //= 4; refractory = 1
                        state.append((potential,refractory))
                        output.append(_clip((72*spike+28*_clip(potential))//100))
                    states.append(tuple(state))
                    return tuple(output)
                perception = forward(0,tuple(_clip(x+f//8) for x,f in zip(inputs,old.feedback)))
                logic_scene = forward(1,perception)
                graphics = forward(2,perception+logic_scene)
                physics = forward(3,logic_scene+graphics)
                io = forward(4,logic_scene+graphics+physics)
                feedback = forward(5,logic_scene+graphics+physics+io)
                outputs = tuple(tuple(x/Q for x in v) for v in (logic_scene[:6],logic_scene[6:],graphics,physics,io))
                next_state = Snapshot(tick,tuple(states),feedback)
                b.charge()
            except _Abort as exc:
                return FrameResult(exc.status,old.tick,None,b.work,b.macs)
            self._state,self._cache = next_state,cache
            self._hits += hits; self._misses += misses
            return FrameResult(FrameStatus.COMMITTED,tick,outputs,b.work,b.macs)
