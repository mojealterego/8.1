# Native client to actual host gateway — E2E evidence

Base main: a8625e8ba17075eb53c615883d958f3beaeb72e4. Linux x86_64, Python 3.13.5, Clang 17, SQLite. Test mode NATIVE. Source files were reconstructed locally from the connector contents and their Git blob SHA verified against the base before testing. No mocked gateway, replay store, adapter, or native transport.

Run from omnicore/native/frame: `python -m unittest discover -s tests -p test_gateway_e2e.py -v`. The test suite builds the C executable with Clang, -Wall -Wextra -Werror and ASan/UBSan, then opens real filesystem AF_UNIX sockets, runs the existing LocalHostServer with the existing gateway and actual SQLite replay store and local handlers. Fixed UUIDs, per-test isolated databases. Each native subprocess must exit zero and produce no stderr.

RED: 7 passed, 1 failed (exit 1, 1.993s). A JSON escaped unpaired UTF-16 surrogate was previously rejected by the outer transport as invalid_frame, rather than the RPC validator returning a typed contract error. This was already denied; not an authorization bypass. Corrected the validator to catch UnicodeEncodeError, preserving fail-closed behavior and allowing precise error classification.
GREEN: 8 passed, 0 failures/errors, exit 0, 1.769s. py_compile passed. Logs in evidence/gateway-red.log and evidence/gateway-green.log.

Coverage: local intent decision, truthful status, persistent replay across server-instance restart, denial of untrusted source/capability/hash before admission, missing remote handler, replay capacity, incorrect configured server UID/label before transmitting, invalid Unicode plus service recovery. The restart recreates the server and store in the same Python process; it does not simulate power loss.

SHA-256:
695baac575cd2505adf8e41c110c1a2c220a27d533b2ee95e3e6c98ece33ff1a  ../../host/omnicore_host/rpc.py
08ee42c004213c7835fd08928af24a8b71cc28d3e427a93cc69036ac8c691abe  tests/test_gateway_e2e.py
9d9c104203da271ac022e2e804a271dac9c48a2eb6bf6f3e5e6ea63aa7fe1384  evidence/gateway-red.log
bf2772abd463179231a5294847e19e3beda34512c19fddd51036fb7c4caef260  evidence/gateway-green.log

Base input blobs verified:
__init__.py 12acb4c29f3ac536b97b959764a7a640da29ae0c
adapter.py 1aca299398ad2b3679115fc73d53db901f7f242f
gateway.py b39a4db28283097f8cd84c871d5a8a5436ac078b
local_services.py e6e1d9429c9c560c5ac48b0cf084d236f46fc167
replay.py 24b4e44b197ffc608ec49be582a5c7ef4e7678ef
rpc.py (before correction) 80a00125bf4dde68292d1a567c1880a36b022d88
transport.py 399005f0f5412953768cb04eef22520ded2dbc9c
server.py 59d6d305e6b6666a48c9aa16dd32b73a06d02246
frame.h 5e3816317cdf345dfaf52fb71bfca7ae2dc25672
frame.c 279278fc77faa01d612177e2ba3ea96aa370b05b
unix_client.h 53ae3141008c4b3e906c02df6ad1261b9d09994f
unix_client.c c891eeba77926388a1bfbf0f8b8e8b3e39d3bc6e
unix_probe.c 75646c8b432a68e6ed2506db72fdd42f56f0ac54

Status: native C client -> host gateway INTEGRATED / TESTED for these scenarios on Linux. No complete host or AOSP regression suite rerun. Rust/Cargo, NDK, Android SELinux/init, Zenoh mTLS and hardware remain open. No claim of remote AI, production deployment or Android boot.
