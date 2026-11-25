"""Verify tamper-evident local event history, not a fabricated anti-rollback anchor."""
import sqlite3
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from omnicore_host.promotion import PromotionStore, PromotionError, sign_transition


def demo_store(tmp_path):
    keys = {r: Ed25519PrivateKey.generate() for r in ('verifier','owner','release')}
    s = PromotionStore(tmp_path / 'releases.sqlite3',{r:k.public_key() for r,k in keys.items()})
    s.propose('candidate1', b'patch data')
    for state in ('STATIC_VALIDATED','SANDBOX_TESTED','FUNCTIONAL_ACCEPTED','SECURITY_ACCEPTED','OWNER_APPROVED','SIGNED_RELEASE'):
        role = 'verifier' if state.endswith('VALIDATED') or state in ('SANDBOX_TESTED','FUNCTIONAL_ACCEPTED','SECURITY_ACCEPTED') else ('owner' if state=='OWNER_APPROVED' else 'release')
        s.advance('candidate1',state,sign_transition(keys[role],s.transition_message('candidate1',state)))
    return s


def test_signed_audit_history_verifies(tmp_path):
    s=demo_store(tmp_path)
    assert s.verify_integrity() == {'candidates':1,'events':7}


def test_signed_audit_history_detects_modified_message(tmp_path):
    s=demo_store(tmp_path)
    with sqlite3.connect(s.db_file) as db:
        db.execute('UPDATE events SET message=? WHERE stage=?', (b'{}','OWNER_APPROVED'))
    with pytest.raises(PromotionError,match='event_integrity_failed'):
        s.verify_integrity()


def test_signed_audit_history_detects_modified_candidate_state(tmp_path):
    s=demo_store(tmp_path)
    with sqlite3.connect(s.db_file) as db:
        db.execute('UPDATE candidates SET state=? WHERE cid=?', ('PROPOSED','candidate1'))
    with pytest.raises(PromotionError,match='candidate_integrity_failed'):
        s.verify_integrity()
