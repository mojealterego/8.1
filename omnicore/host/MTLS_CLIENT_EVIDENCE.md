# One-shot mTLS client and recovery contract

Base main: 54a853229b9fe3cc0ddcde1585c793a8d5f6fd60. Reconstructed original mtls.py and rpc.py were verified against Git blobs e7baf7cb72bb0c9085895f04c80c73de2810c02a and 8698e73677e862749427ffbf1db2e95dbc782c2a. Environment: Linux, Python 3.13.5, OpenSSL 3.5.5, cryptography 46.0.4, Git 2.47.3. Actual IPv4 TCP loopback, real TLS and existing MtlsEndpoint, ephemeral EC test certificates and injected response fixtures. No private keys committed.

Run from omnicore/host: python3 -m unittest discover -s tests -p test_mtls_client.py -v
RED: missing module import (exit 1). GREEN: 11 tests, 0.774 s, OK. python3 -m compileall -q omnicore_host tests exited 0 in the reconstructed subset. Tests identified in evidence/mtls-client-green.log. Prior 13 mTLS tests and other suites not rerun in this session. Native test of timeout uses a real 150 ms client budget and 400 ms callback delay; scheduler affects timing. No deterministic seed for real crypto.

Design: static numeric IP endpoint plus independently configured SAN hostname and SHA256 leaf pin, CA validation, ALPN, single fresh connection per exchange, bounded connect/handshake/send/receive deadline, frame limit 65536 bytes, response schema/status and canonical request ID correlation. Request validation here covers envelope schema and request ID only; complete request validation remains the server gateway's responsibility. A DENY without correlation ID is rejected as ambiguous rather than attributed to a request. ExchangeError.may_have_executed is conservatively true as soon as sendall starts; false means the client did not start application payload transmission. No automatic retry, no queue, no background worker, no cancellation or rollback of remote side effects. A fresh independent connection can succeed after timeout. Tests use a response fixture callback, not the full gateway/replay DB; the previous commit covered server-side gateway integration. No IPv6 runtime test. No production certificate provisioning or revocation infrastructure, no Zenoh session, no Android integration or deployment.

SHA256:
16159efd2c0a3bb2d7a952c4c965569ac29234c37bad7c4c8ecf6da885e6671e  omnicore_host/mtls_client.py
8af102226d677a40e461c345abac1107020da474bb0001378ab3de671b32ccf3  tests/test_mtls_client.py
9daef7713ad8e705861b658f8c776995dc8d1a6ba6a139a7606380eb326e421d  evidence/mtls-client-red.log
6e2803fb3ed3e627c55f47553eece4a4ac2b929431d5f293e3bfbdecdc54c191  evidence/mtls-client-green.log
