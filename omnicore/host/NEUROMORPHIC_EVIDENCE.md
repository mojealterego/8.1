# OMEGA-X Neuromorphic vARCH — reference host backend

Base main: 65942be866ebaadcdb6583c4a7609d4b770531f5. User provided the six-layer Python design inline. The referenced Ryzen-Core PDF was not supplied or inspected in this step. The module is an independent host library, not a replacement for the RPC/Zenoh runtime or a physical processor.

Preserved layer dimensions: 16->16 perception, 16->12 logic/scene, 28->10 graphics, 22->8 physics, 30->6 I/O, 36->16 feedback (68 stateful virtual neurons; 36 scalar outputs). Synthetic SHA256-derived weights are not trained. Q12 integers, bounded membrane potential, triangular phase modulation, refractory state, sparse weight rows, zero-input multiply skipping. Feedback feeds the next committed perception tick. The cache stores pure synaptic sums keyed by exact quantized layer inputs; it never substitutes stateful neuron updates. Six fixed capacity partitions, LRU eviction, immutable state snapshot and staged cache transaction. Aborted frame returns no outputs and does not advance tick or cache statistics. One owner under a lock; no claimed parallel execution. Budget checks are cooperative and count logical work, not hardware cycles; start is after lock acquisition, and the check immediately before commit is not a hard OS deadline. No virtual-deadline scheduler, physical cache-way partition, resonant eviction, formal Weil/Ricci verification, training, real graphics/physics/I/O execution, persistent state, Android service, RPC wiring or ARM32 port in this stage. Defaults: 2ms, 128 cache entries, 8192 work units. Inputs restricted to exactly 16 finite normalized numbers. API execute_frame is synchronous. These are deliberate deviations from the supplied example, not drop-in compatibility.

Verification: Linux x86_64, Python 3.13.5. Reconstructed local subset contained only new files. RED: missing module, exit 1. First implementation run 10/11 passed; trajectory equality passed but the test incorrectly required a cache hit from changing state. Fixture corrected to include three initial zero frames; later added mid-frame abort with previous committed state. Final unittest 12 tests in 0.085s, OK. Independent pytest 12 passed, 6 subtests passed in 0.12s. compileall exit 0. Raw logs in evidence/neuro-*.log. Fixed input sequence and injected virtual clock; actual module, not a success stub. Real threads test 20 serialized calls with unique committed ticks. No old regression suite run. No claim of MT6580 performance.

Reproduce from omnicore/host:
```
python3 -m unittest discover -s tests -p test_neuromorphic.py -v
python3 -m pytest -q tests/test_neuromorphic.py
python3 -m compileall -q omnicore_host/neuromorphic.py tests/test_neuromorphic.py
```

Exploratory native timing: 200 all-zero frames per case, sequentially, frame_budget_ms=10, cache capacities 0 and 128. Both committed all 200. Median 0.12173ms vs 0.07915ms; sorted sample index 189 (empirical p95) 0.21796ms vs 0.15718ms. Cache hits 0/1200 vs 1194/1200; zero MACs in both cases. This isolates overhead of repeated zero synaptic sums, not acceleration of nonzero neural inference or a game. Single run without warmup or statistical confidence; not an acceptance threshold. Reproduce by timing execute_frame([0.0]*16) externally using perf_counter_ns for 200 consecutive calls on fresh instances at each capacity.

SHA256:
3497e3203ee7d96d127e2b985bf276f1a401597a6d5811b44b6b6101fa49d4d3  omnicore_host/neuromorphic.py
833f1974f649ff3242113c47c3efae0e61e627236911f70c8db520f619bade27  tests/test_neuromorphic.py
0353e1eb6f8353c2580e50932570f8a93c1826ac164713b29afed3b42bcda175  evidence/neuro-cache-test.log
7159e447a58a7889c61860db7edf801ebbd1572266b9a2303d71956784d4deeb  evidence/neuro-green.log
83b4d537fe4b6428406f042e6bf6d7afe7d1553003b158eff6a09dd3c9f73312  evidence/neuro-pytest.log
b45ac794f04f38801a97434533b313a9105ecc2ac942543f6d2cef80fdb00fe5  evidence/neuro-red.log
