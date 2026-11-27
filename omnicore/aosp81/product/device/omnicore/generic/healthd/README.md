# OmniCore healthd — Android 8.1 init integration candidate

A dedicated native readiness endpoint, **not** the omnicore.rpc.v1 gateway. The daemon adopts the exact filesystem AF_UNIX stream socket created by init. It never binds or removes a socket pathname and accepts no request bytes. The only response is `OMNICORE-HEALTH/1 READY\n`; clients must receive the complete exact line and EOF. This means the daemon accepted a trusted connection, not that the AI engine, RPC gateway or ROM is healthy.

Android configuration: `/system/bin/omnicore_healthd`, class `late_start`, explicitly disabled; UID/GID `nobody` (9999); socket `/dev/socket/omnicore_health`, mode 0660, owner nobody, group system. The Android entrypoint accepts no arguments and rejects any real/effective UID other than 9999. The only configured client identity is UID 1000 with kernel security context `u:r:system_server:s0`. `OMNI_HOST_TEST` is used only by the host harness and is absent from Android.mk. The daemon has one accepted connection at a time, a bounded listen backlog, nonblocking accept/send, close-on-exec, and handles SIGTERM/SIGINT. It has no TCP/IP transport, shell execution, request parsing or application-data access. A partial nonblocking response must be treated as a failed probe.

## Build and integration boundary

This directory is part of the existing generic overlay and provides an Android.mk executable module with LOCAL_INIT_RC. The default product does **not** include the module in PRODUCT_PACKAGES. The policy files are platform-private candidates; `file_contexts.omnicore` is a fragment, not an automatically loaded file. On a separate full `android-8.1.0_r1` checkout, after the existing overlay is staged, review and incorporate `omnicore_healthd.te` into `system/sepolicy/private` and merge the two nonconflicting context entries into its `file_contexts`; add `omnicore_healthd` to the generic product packages only after validating that the policy compiles with all neverallow checks. Do not add a permissive domain or disable enforcing. No system_server client is installed by this module. Native Android acceptance requires the executable and init RC in the image, an enforcing boot, actual domain transition, expected socket owner/mode/context, and positive system_server plus negative unauthorized-peer probes. Service stays disabled until explicitly started in an authorized test environment. No phone flashing or hardware claim.

References for the candidate contract: AOSP Android 8.1 init documentation (android-8.1.0_r48, https://android.googlesource.com/platform/system/core/+/android-8.1.0_r48/init/README.md) and Oreo MR1 SELinux macro definitions (https://android.googlesource.com/platform/system/sepolicy/+/refs/heads/oreo-mr1-release/public/te_macros). These are reference versions in the same release family; compatibility with the exact r1 policy and Bionic is not yet compiled or established.

## Verification

Base main: ab8fca7c5a6497e5b2033f1f236764930109c8a8. Linux x86_64, Python 3.13.5, Clang 17.0.0, host test UID 0. From this directory:

```
python3 -m unittest discover -s tests -v
clang -std=c11 -Wall -Wextra -Werror -O2 healthd.c -o /tmp/omnicore-healthd
clang --analyze -std=c11 -Wall -Wextra -Werror healthd.c -o /tmp/omnicore-healthd.plist
```

RED: initial suite failed at setup (exit 5, absent healthd.c). GREEN: initial 10 tests passed; after adding two descriptor tests and strengthening the static configuration check, the final 12 tests passed (exit 0, 0.288 s). See evidence/red.log and evidence/green.log for raw output and test IDs. Tests compile the actual C service with AddressSanitizer and UBSan, use real inherited bound sockets, actual kernel peer credentials and labels, three valid sequential probes, invalid descriptor/path/type/listening state, UID/label mismatch, and graceful SIGTERM. The configured mismatches do not establish real cross-UID isolation. Host-mode compilation changes only the entrypoint configuration; it does not simulate Android init or SELinux. The configuration test is static contract checking, not a policy compiler. Production entrypoint variant built on Linux (exit 0); an invocation with extra arguments returned 2. Clang static analysis of this variant completed with zero diagnostics. No existing RPC or AOSP regression tests were rerun; no AOSP build, NDK link, SELinux compilation, real Android boot, activation or deployment was performed.
