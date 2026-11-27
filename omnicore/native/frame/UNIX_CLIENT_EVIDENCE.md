# Native AF_UNIX client — acceptance evidence

Base main: d9de9ef404f8cc6ccb0241f4b89021e797de152b.
Environment: Linux x86_64, Clang 17.0.0, Python 3.13.5. NATIVE host execution. Kernel SO_PEERSEC label observed via socketpair: kernel (NUL terminated). No Android SELinux enforcement claim.

Contract: one request per connection, existing 4-byte big-endian codec, 1..65536 bytes per frame, caller-supplied buffers, deadline 1..5000 ms measured by CLOCK_MONOTONIC, nonblocking socket, exact SO_PEERCRED UID and SO_PEERSEC label before sending, no automatic retry. Output length is zero on error; partial buffer contents must be discarded. A failed exchange can be ambiguous with respect to server-side execution. Trust the configured path and peer identity; this is not a cryptographic identity, RPC authorization or JSON validator.

Reproduction, from omnicore/native/frame:

~~~sh
clang -std=c11 -Wall -Wextra -Werror -Isrc -fsanitize=address,undefined src/frame.c src/unix_client.c tests/unix_probe.c -o unix_probe
python3 -m unittest discover -s tests -p test_unix_client.py -v
clang --analyze -std=c11 -Wall -Wextra -Werror -Isrc src/unix_client.c -o analysis.plist
~~~

RED: first compile failed with exit 1 because src/unix_client.c did not yet exist. See evidence/unix-red.log.
GREEN: compile exit 0, 14 unittest methods PASS, 0 failures/errors, 0.410 seconds. Each invocation asserts empty stderr, including sanitizer output. See evidence/unix-green.log for test IDs and actual run output. The Python peer uses real AF_UNIX sockets and injected response fragments/lengths/EOF; it is a wire-contract test peer, not the production Python gateway. One wall-clock deadline test uses timed writes, not virtual time. Wrong UID/label cases verify rejection before sending using a deliberately incorrect configured identity; they do not establish multi-UID or Android SELinux isolation.

Static analyzer: exit 0, 0 diagnostics in analysis.plist.

SHA-256:
4554d6a159c95a41fed43b7095ed20a024a753f7191c0795c5a5690d49b6b0de  src/unix_client.c
3ccecf66f7ef622cf6b49a12335be0d86604d61fc8b88323e23bab0be6616550  src/unix_client.h
021a5423e952805382921cf0890ba6f322126f1e316ad766db0cd6e831b9b0b8  tests/unix_probe.c
7ecb8a4625aa882dacca638f39e0be7332264accb5e67f184b8afb070988721c  tests/test_unix_client.py
bf8ba737072c94f9ac9c8f0b7b71dfee00de7f5946b3a026affd3a6f4d504717  evidence/unix-red.log
f52f5e03cab08e9340919150f4718e88959fd443c52503ccfe4aaa01c2ccd36c  evidence/unix-green.log

Base codec blobs (verified against local files): frame.h 5e3816317cdf345dfaf52fb71bfca7ae2dc25672; frame.c 279278fc77faa01d612177e2ba3ea96aa370b05b.

Status: C client IMPLEMENTED / TESTED on Linux. Existing full regression suites not rerun. Rust FFI for this client, Android NDK compile/link, init, SELinux policy, production RPC gateway end-to-end, Zenoh mTLS, AOSP build and emulator remain open. No deploy or hardware flashing. No Cargo integration is claimed; the client is built separately with the commands above.
