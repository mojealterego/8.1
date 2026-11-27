# F1 emulator HOME acceptance — contract evidence

Base commit: cf1cb2b2e25504d03a32d7ac1094ffad39645b8b. Test environment: Linux, Python 3.13.5, no ADB, no emulator, no complete AOSP checkout. No network access in local runner.

Run from omnicore/aosp81: python3 -m unittest discover -s tests -p test_emulator_gate.py -v

RED: initial run failed with ModuleNotFoundError: verify_emulator (new implementation absent).
GREEN: 10 tests passed, 0 failures, 0 errors (0.001s).
IDs (ContractTests): test_nominal, test_physical_device, test_not_qemu, test_wrong_sdk, test_wrong_profile, test_sideloaded_home, test_home_not_registered, test_launch_failure_even_with_zero_exit, test_wrong_foreground, test_transport_timeout.
Source SHA-256: a046b672d835b955a3366d308eea29f19446459cf00eceb1938fcdf1f14f95f2
Test SHA-256: 12b6a7ec7ebb5e61dee400dbfc15183acceaf2a384b1f2a51c042ae0cb0cfdae
Source Git blob: 43a9369c2973c82de27e43c2c4951c411ebcfb3e
Test Git blob: d1a181ed79e9f1fe7657f787dd6a744465abe0a0
py_compile: passed for both files.

Mode: deterministic contract simulation, using actual gate implementation with injected ADB command responses. No random seed needed. Fixed response table with per-test fault substitutions. This tests host-side decision logic only, not Android or ADB implementation. Earlier suites not rerun here.

Native procedure: after real build and emulator startup, run python3 omnicore/aosp81/verify_emulator.py --serial emulator-5554 --timeout 180. Substitute the actual explicit emulator serial. Gate launches HOME for user 0 without changing the default launcher. A successful report proves observed boot, expected properties, installed system HOME, registered HOME intent and resumed activity, not image provenance, UI rendering, default HOME selection or physical hardware.

Actual native invocation here returned BLOCKED with adb_unavailable_or_timeout:get-state.
F1 BUILD and F1 EMULATOR: BLOCKED. Contract gate implementation and its isolated tests: PASS. No device flashing or production deployment performed.
