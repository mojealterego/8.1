# RPC execution deadline and local worker lifecycle

Base main: 2a00d87fc8f99fbd3d4466e86d1432d1f89b1bc1. Environment: Linux x86_64, Python 3.13.5, pytest 9.0.2, SQLite 3.46.1, Git 2.47.3. Six reconstructed original modules matched GitHub blob IDs before modification; RPC and replay regression test sources also matched the base blobs (b15e5e75a177c2be18b0fe896e1906efde358dd6 and 079e2b50e27465c91480e88d1ad1aa003f790e12).

Run from omnicore/host:

```
python3 -m pytest -q tests/test_execution_deadline.py tests/test_rpc.py tests/test_replay.py
python3 -m compileall -q omnicore_host tests
```

RED: original gateway/adapter, focused test_late_handler_never_returns_success; exit 1, returned OK after the request deadline. GREEN: all eight new tests passed, 0.50 s. Final combined run: 27 passed, 0.53 s, no failures. compileall exit 0. Actual logs in evidence/execution-{red,green,final}.log. The final suite contains 19 existing regression tests and eight new tests. IDs of the new tests: test_late_handler_never_returns_success, test_admission_consumes_same_budget, test_budget_not_reset_by_adapter, test_direct_adapter_uses_budget, test_in_budget_success, test_isolated_local_handler_actual_worker, test_isolated_executor_rejects_arbitrary_callable, test_worker_is_killed_and_reaped_on_timeout.

Mode HYBRID: real SQLite transactions and Python child processes; four boundary scenarios use injected monotonic virtual time (fixed nanosecond advances, no random seed); native timing regression uses sleep 30 ms against a 10 ms request budget; native worker cancellation tests a 300 ms deadline against a trusted 1-second test workload, verifies PID was reaped and no late marker exists. The cancellation test exercises the same production process lifecycle helper, not an artificial success stub. Child startup/scheduling is real and can affect reproduction under extreme host load.

## Integration and limits

The budget starts when Gateway.handle begins, before decoding; it is not the AF_UNIX receive deadline. A successfully admitted replay key stays consumed even if the execution budget expires. The direct adapter checks before/after the call and serialization; an arbitrary synchronous handler cannot be forcibly cancelled and can still block or produce side effects. SQLite lock waits are not preempted. This is not an end-to-end hard realtime deadline.

For the fixed offline intent and status handlers, select `isolated_local_adapter()` explicitly in the host composition:

```python
from omnicore_host.gateway import Gateway
from omnicore_host.local_executor import isolated_local_adapter
from omnicore_host.replay import ReplayStore

gateway = Gateway(ReplayStore(path), isolated_local_adapter())
```

`path` is the configured private replay database path. The factory does not enable remote capabilities. Existing default direct-adapter call sites retain compatibility. The isolated executor only accepts the actual allowlisted local functions, invokes a fixed trusted Python worker without shell, with a clean environment and closed inherited FDs, and kills/reaps on timeout. The child has the same UID; this is lifecycle isolation, not a security sandbox, memory jail or a descendant process supervisor. Only trusted no-descendant offline handlers are supported. `communicate()` buffers the trusted worker's output; the worker enforces its own output limit. No arbitrary remote command execution, no retry, no rollback of arbitrary effects. No Android deployment, init/SELinux integration or Zenoh mTLS claim. Other host and AOSP suites, Rust compilation, NDK build and device acceptance remain open.
