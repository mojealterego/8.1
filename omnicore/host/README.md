# OmniCore 8.1 host-side control plane — laboratory component

This is a Python/Linux host service layer, **not an AOSP Android system service**. It was developed in the `OmniCore_8_1_Engineering_v1_2` package and extended into v1.3 only by source publication. Run from this directory:

```bash
python3 -m pip install -r requirements-test.txt
python3 -m pytest -q tests
```

It includes signed Ed25519 state transitions, SQLite-backed replay protection, a restricted RPC contract, a Unix-socket transport using the host's peer credentials and deterministic offline intents. It intentionally does not provide a fake Android 8.1 SELinux integration, shell execution, or a working Zenoh/Digital-Life backend.

**Security limits:** Host UID/SELinux observations are not proof of Android UID isolation. Local SQLite audit is not a trustworthy external anti-rollback anchor. There are no signing private keys in this repository. The host test suite must not be used as evidence that Android ROM GATE-F1, F6 or G09 passed.
