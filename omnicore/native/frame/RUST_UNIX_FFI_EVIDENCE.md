# Native Unix transport ABI and Rust binding

Base main: c40d0d0523d0d5455dc98acfa0a533b6889c4a4c. Environment Linux x86_64, Python 3.13.5, Clang 17.0.0, Git 2.47.3. NATIVE C ABI verification, not a Rust execution or Android simulation.

The stable C shim exposes uint32_t UID and timeout, int result and size_t lengths; static assertions enforce compatible uid_t and unsigned int. It delegates to the existing client and clears valid bounded response storage on errors. The Rust wrapper adds a typed error enum, trusted configuration validation, borrow-checked buffers and response-length validation. It is synchronous and does not retry; a failed exchange may already have executed on the server. The caller still validates the RPC envelope and response correlation. The Cargo build script includes Unix client and ABI sources only on Linux/Android and requires explicit target-specific tools for cross builds.

Reproduce from omnicore/native/frame:
`python3 -m unittest discover -s tests -p test_ffi_abi.py -v`

RED: missing unix_ffi.c, compilation exit 1 and test setup error (0 tests ran).
GREEN: 8/8 tests passed, exit 0, 0.250s. Actual shared C library called through Python ctypes with real local AF_UNIX peers. Exact IDs and output in evidence/ffi-green.log; RED in evidence/ffi-red.log. The new tests cover nominal exchange, identity mismatch, malformed response, capacity, partial-response erasure, invalid arguments and absent socket. This tests the C ABI, not Rust ownership semantics or real cross-UID/Android SELinux isolation. No sanitizer claim for this run.

Static analyzer: `clang --analyze -std=c11 -Wall -Wextra -Werror src/unix_ffi.c -o analysis.plist`; exit 0, 0 diagnostics. Native static archive: three C objects compiled using -std=c11 -fPIC -O2 -Wall -Wextra -Werror (frame.c also -ffreestanding); ar crs archive frame.o unix_client.o unix_ffi.o; nm -g --defined-only confirmed ocr_frame_encode, ocr_frame_decode, ocr_unix_exchange and ocr_unix_exchange_ffi. This was manual C compilation, NOT cargo build.

Base blobs independently matched local reconstruction: frame.c 279278fc77faa01d612177e2ba3ea96aa370b05b; frame.h 5e3816317cdf345dfaf52fb71bfca7ae2dc25672; unix_client.c c891eeba77926388a1bfbf0f8b8e8b3e39d3bc6e; unix_client.h 53ae3141008c4b3e906c02df6ad1261b9d09994f.

SHA-256:
41aa5e2f88b567d86c14ce2c82dce44851ef66c535b7e58a0301ef42625fd867  build.rs
ab0501582ebedfe964c65b4c167204bc6abb1678a437d7c29e489442174a28f4  src/unix.rs
3cc941211e645056c55a56364f1b273fc852b8f65dd0b444ce75415c926ec79a  src/unix_ffi.c
a57a23c9febfee908d3784b02d827f5e08e2a20c1dff4c2b7b66b3bf9d205e84  src/unix_ffi.h
ebe7517209fc288a0a3ea42760e8989f25dbf48fb9082d9964d0f555aba74c2d  tests/test_ffi_abi.py
e1f485dc56b438920ba81db866fe178e957fb8759c56c888fbce89c8ac4a33db  evidence/ffi-red.log
e05e0f447fb8f6da28057b034a469c5c0fae365bc5ffce88eee9f9ff2501bf75  evidence/ffi-green.log

Rust module and build.rs: IMPLEMENTED / NOT_TESTED. rustc and Cargo not present; DNS resolution of static.rust-lang.org failed; NDK not available. Two Rust tests were authored but not executed. On a provisioned host use cargo test --offline; for API 27 ARMv7 use cargo build --release --target armv7-linux-androideabi with CC_armv7_linux_androideabi, AR_armv7_linux_androideabi and CARGO_TARGET_ARMV7_LINUX_ANDROIDEABI_LINKER set to corresponding NDK API 27 tools. Not a verified Android build. Previous full regression/E2E suites not rerun. Handler execution budget, Android init/SELinux, Zenoh mTLS, AOSP and hardware acceptance remain open. No deployment or flashing.
