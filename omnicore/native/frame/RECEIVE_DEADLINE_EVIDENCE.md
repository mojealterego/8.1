# Host RPC receive deadline — native E2E acceptance

Base main: ab567ca02cc2b8c830d872d8d415f5e3ea05af37. During work main advanced from a8625e8ba17075eb53c615883d958f3beaeb72e4 to this base. Concurrent Unicode validation and E2E changes were retained; the existing E2E suite was extended by one regression scenario, not replaced. Earlier unreferenced candidate d5dcb29c992b8b4234a125afd52b38dfb240c637 was not applied.

Environment: Linux x86_64, Python 3.13.5, SQLite 3.46.1, pytest 9.0.2, Clang 17.0.0, Git 2.47.3. Mode NATIVE: real AF_UNIX, native C probe built by tests with ASan/UBSan, real host gateway and persistent SQLite. Fixed UUIDs, isolated databases. No random seed. Timing uses real monotonic time, 200 ms receive budget, 120 ms fragment cadence; overloaded host scheduling can affect reproducibility. Not a virtual-time simulation.

Reproduction from omnicore/native/frame:
`python3 -m unittest discover -s tests -p test_gateway_e2e.py -v`

From omnicore/host:
`python3 -m pytest -q tests/test_transport.py tests/test_rpc.py tests/test_replay.py`

RED on the new base transport: 8 pass, 1 fail, exit 1. Fragmented header and body were accepted after the total budget (SQLite count 1 instead of 0).
GREEN: 9 pass, 0 failures/errors, exit 0, 2.093s. After rejection, a new legitimate request is accepted. Regression: 25 pass, 0.12s. Exact test IDs in E2E logs; regression commands identify original test files. Original test blobs: transport 1152d9f7ca170fa43471d98d7ee948f452e9de89, rpc b15e5e75a177c2be18b0fe896e1906efde358dd6, replay 079e2b50e27465c91480e88d1ad1aa003f790e12.

Base source identity: 13 original source/probe files matched original base blobs. Concurrent rpc.py (8698e73677e862749427ffbf1db2e95dbc782c2a) and E2E test (dc0bb7e57f16f78f00772df54d4d570e285d5d5b) were reconstructed and verified against new base before rerunning RED and GREEN. Old transport blob 399005f0f5412953768cb04eef22520ded2dbc9c.

SHA-256:
001d8a0db5e399a6da42146daa202b98aafd8a078aec3bdff538ce940ab885f9  omnicore/host/omnicore_host/transport.py
f4c53f81f5b577776db525a2874b82408c9e9dd53d5f1c667cc26ef2952f2e77  tests/test_gateway_e2e.py
4b775884ed347592efeff87f0df1491777de6149131b6bf04ead24e2cdb511d7  evidence/receive-deadline-red.log
9747d24275297ac2a629fb0b5b3975d917a1eccb3c81473781c270cc7cff988b  evidence/receive-deadline-green.log
c15b71be04f4376528c0ffb06a7288697e528de596c4cc548b1bdce763d39bd5  evidence/receive-deadline-regression.log

Scope: header and body share one monotonic receive deadline; response send has a separate bounded window. This does not bound execution of handlers, SQLite operations, or all request processing. Restart tests recreate server and store in the same process, not power-loss recovery. No Android SELinux isolation, remote AI, Zenoh mTLS, NDK or Rust execution established. Other AOSP and host promotion suites not rerun. No deployment or flashing.
