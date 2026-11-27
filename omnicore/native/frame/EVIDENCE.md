# Native RPC framing / Rust FFI — verification

Base main: 23fa4ef595c770aad76fd4baab5a86dec685be06. Existing host contract: `omnicore/host/omnicore_host/rpc.py` and `transport.py` (4-byte unsigned big-endian length, 1..65536 bytes). Native C codec is called by the Rust wrapper; it is not a replacement Zenoh stack.

NATIVE: Linux x86_64, Clang 17.0.0, Python 3.13.5. From this directory:

- RED: `clang -std=c11 -Isrc tests/frame_test.c src/frame.c -o frame_test` exited 1 before the implementation (missing source).
- NF-01/NF-02: `clang -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -Isrc tests/frame_test.c src/frame.c -o frame_test && ./frame_test` exited 0: 65,536 exhaustive lengths and 7 negative checks. No sanitizer report.
- NF-03: `clang -std=c11 -Wall -Wextra -Werror -shared -fPIC src/frame.c -o libframe.so && python3 tests/interop.py ./libframe.so` exited 0: all 65,536 lengths in both directions against Python struct `!I`. This tests the wire contract, not the host gateway itself.
- NF-04: `clang --target=armv7a-linux-androideabi27 -march=armv7-a -mfloat-abi=softfp -std=c11 -ffreestanding -fPIC -Wall -Wextra -Werror -O2 -c src/frame.c -o frame-armv7.o` exited 0. `readelf -h` reported ELF32, ARM, little endian, REL, EABI5; `readelf -A` reported v7 Application, Thumb-2, VFPv3, NEONv1. No NDK or Android dynamic link/runtime execution was performed. This is a freestanding relocatable object only, not an Android executable. Hardware without the indicated feature set is not certified.

Rust wrapper and build.rs: IMPLEMENTED, NOT_TESTED (rustc, Cargo and Android NDK absent; no network to install). On a provisioned host use `cargo test --offline` and `cargo build --release --target armv7-linux-androideabi`, setting `CC_armv7_linux_androideabi`, `AR_armv7_linux_androideabi` and `CARGO_TARGET_ARMV7_LINUX_ANDROIDEABI_LINKER` to the appropriate NDK tools (API 27). Cross compilation does not prove execution. No endpoint authorization, JSON validation, encryption or authentication is performed by this codec; these remain server responsibilities.

SHA-256 source and test digests:
3e32ddb86d644b94d7e062eca35badad9cfda0e0cea5e83e9fa4efca2db85d41  src/frame.c
d9d71769c5c5196b161f1bfe9dc2c562ebb37ce357b44279477d73a33676e2ec  src/frame.h
e6324e8eab59ea439a5fe0e3fb5e3e6f1e73036e54ac9c9cb947af300415b4a5  src/lib.rs
e751630a1fbc6324268e5c8a7dbb1bec63d0cf2a3365a6d774fb7ef58d7356c6  tests/frame_test.c
e44388ffeb8978c96b41978687b437347a42f03979c19c38808abacf2d243918  tests/interop.py
ce0523c52697652f287f751f89a3bdacd6d46473d5ce5ff51c9acd172319fe7d  Cargo.toml
27b0d57742dabbff6e64549ed2cf63f69a118809ec5f1393f3cedce082840f1a  build.rs
74b9ef9715d0f78ad6e275918891c28fc915f84a406d53f7f110f6936d77494f  frame-armv7.o
