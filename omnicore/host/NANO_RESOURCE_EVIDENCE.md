# NANO resource governor — host acceptance

Base main: 7375ec229e3e2c1267bd68f20b0640d6d7064c8f. Linux x86_64, Python 3.13.5, pytest 9.0.2, Git 2.47.3. Mode HYBRID: fixed memory snapshots (159, 160, 512 MiB and invalid values), real Linux threads, subprocesses, /proc and resource limits. No random seed. Six reconstructed base files matched the GitHub blob IDs before modification: adapter bc8db0fa974d1351d1dcf7f88c25792d3bd6e324, deadline 4b5695521bc9cc46010d1a1d7eaeb4b3d80bb31b, executor 7b76eb7f0d37574319bb723709f4d541a794deb3, worker d95588cca7b57e6bd2045c090776345b5262033a, local_services e6e1d9429c9c560c5ac48b0cf084d236f46fc167, rpc 8698e73677e862749427ffbf1db2e95dbc782c2a.

From omnicore/host:
```
python3 -m pytest -q tests/test_nano_resources.py tests/test_nano_integration.py
python3 -m compileall -q omnicore_host tests
```
Local checkout contained the two new test files and six base source files plus the new module. Actual final command was python3 -m pytest -q tests, exit 0, 12 passed and 4 subtests passed in 2.62 s. compileall exit 0. RED: absent new module (exit 1; evidence/nano-red.log). Integration RED against unchanged executor/worker: 4 test methods, 1 failure and 3 errors (no governor, missing caps); final integration polling was strengthened to observe both AS and FD caps before continuing, to avoid sampling between setrlimit calls. GREEN: actual worker executes the offline intent. CPU test spins a dedicated child and verifies SIGKILL at the hard CPU limit; allocation test verifies MemoryError at a 128 MiB allocation under a 64 MiB address-space cap. The memory snapshot is simulated only for admission decisions. No full device, cgroup or whole-OS memory simulation.

Tests: test_low_memory_denied, test_exact_threshold, test_concurrent_admission_denied_and_recovery, test_exception_releases_slot, test_unknown_memory_fails_closed, test_proc_snapshot, test_native_kernel_limits_and_allocation_denial, test_native_cpu_limit, test_low_memory_blocks_executor, test_real_worker_with_governor, test_default_executors_share_slot, test_production_worker_applies_kernel_caps_before_read. Native timing depends on host scheduler. Prior host and AOSP suites not rerun.

Proposed host profile: 64 MiB virtual address space per worker (NOT physical RSS), 96 MiB admission reserve, minimum host MemAvailable 160 MiB, 2 CPU seconds per worker, 32 descriptors, no core dump, regular-file write size limit 0. Existing stricter rlimits are not raised. Default executors share one nonblocking admission slot within one Python process. Separately injected governors and separate processes are not globally coordinated. The MemAvailable snapshot is not an atomic reservation or cgroup accounting and does not prevent memory pressure from other processes. Limits apply after interpreter startup and before request reading/handler imports. No privilege isolation, syscall sandbox, temperature control, bandwidth quota, aggregate CPU throttling or full-device memory guarantee. ResourceDenied currently maps to existing adapter handler_failure and does not bypass replay admission. Direct adapters are not governed; use the existing isolated_local_adapter factory for the governed local worker. These budgets are engineering defaults for NANO validation, not measured limits on MT6580. Android 8.1 init/SELinux, device governor, Rust/NDK build, Zenoh mTLS and complete AOSP remain open.

Source SHA256:
00b5e0d3542cbe291aa30112f9523779e7718b66abbc37ad36c0b774949addf6  omnicore_host/nano_resources.py
f88abc32717162293967aeb4f9bd2edee9cbdc7ca8eb56dfe3c360bb43809a40  omnicore_host/local_executor.py
c0e8b4b490c2de6515b2ed0f76e2fa945f4c66c3f739d04660769088d6f40adb  omnicore_host/local_worker.py
c2f1c50d39e3bfba0b95b64232b029c2f3258bc6928c7db296f60cccaaefc828  tests/test_nano_integration.py
8cd00f2286eff22dc5ee9fe273274214bb23785eb5a5745270acbe9eebd43017  tests/test_nano_resources.py
