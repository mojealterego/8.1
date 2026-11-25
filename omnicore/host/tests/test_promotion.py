"""Signed, artifact-bound stage transitions. No actor-name authorization."""
import hashlib
import json
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from omnicore_host.promotion import PromotionStore, PromotionError, sign_transition, canonical

@pytest.fixture
def keys():
    return {role: Ed25519PrivateKey.generate() for role in ('verifier', 'owner', 'release')}

@pytest.fixture
def store(tmp_path, keys):
    return PromotionStore(tmp_path / 'admission.sqlite3', {k: v.public_key() for k, v in keys.items()})


def progress(store, keys, cid, artifact):
    store.propose(cid, artifact)
    for state in ('STATIC_VALIDATED','SANDBOX_TESTED','FUNCTIONAL_ACCEPTED','SECURITY_ACCEPTED'):
        receipt = sign_transition(keys['verifier'], store.transition_message(cid, state))
        store.advance(cid, state, receipt)


def test_agent_cannot_self_approve_without_owner_signature(store, keys):
    progress(store, keys, 'candidate1', b'patch')
    bad = sign_transition(keys['verifier'], store.transition_message('candidate1', 'OWNER_APPROVED'))
    with pytest.raises(PromotionError, match='signature_invalid'):
        store.advance('candidate1', 'OWNER_APPROVED', bad)
    assert store.state('candidate1') == 'SECURITY_ACCEPTED'


def test_owner_signature_is_tied_to_exact_candidate_and_digest(store, keys):
    progress(store, keys, 'candidate1', b'patch1')
    progress(store, keys, 'candidate2', b'patch2')
    receipt1 = sign_transition(keys['owner'], store.transition_message('candidate1', 'OWNER_APPROVED'))
    with pytest.raises(PromotionError, match='signature_invalid'):
        store.advance('candidate2', 'OWNER_APPROVED', receipt1)
    store.advance('candidate1', 'OWNER_APPROVED', receipt1)
    assert store.state('candidate1') == 'OWNER_APPROVED'


def test_no_skipped_states(store, keys):
    store.propose('candidate1', b'patch')
    signature = sign_transition(keys['verifier'], store.transition_message('candidate1', 'SANDBOX_TESTED'))
    with pytest.raises(PromotionError, match='invalid_transition'):
        store.advance('candidate1', 'SANDBOX_TESTED', signature)


def test_candidate_ids_are_immutable(store):
    store.propose('candidate1', b'patch1')
    with pytest.raises(PromotionError, match='duplicate_candidate'):
        store.propose('candidate1', b'patch2')


def test_proposal_digest_matches_artifact(store):
    record = store.propose('candidate1', b'known patch')
    assert record['artifact_sha256'] == hashlib.sha256(b'known patch').hexdigest()


def test_signer_cannot_skip_owner_gate(store, keys):
    progress(store, keys, 'candidate1', b'patch')
    signed = sign_transition(keys['release'], store.transition_message('candidate1', 'SIGNED_RELEASE'))
    with pytest.raises(PromotionError, match='invalid_transition'):
        store.advance('candidate1', 'SIGNED_RELEASE', signed)


def test_valid_signed_release_has_monotonic_local_version(store, keys):
    progress(store, keys, 'candidate1', b'patch')
    store.advance('candidate1', 'OWNER_APPROVED',
                  sign_transition(keys['owner'], store.transition_message('candidate1', 'OWNER_APPROVED')))
    store.advance('candidate1', 'SIGNED_RELEASE',
                  sign_transition(keys['release'], store.transition_message('candidate1', 'SIGNED_RELEASE')))
    assert store.state('candidate1') == 'SIGNED_RELEASE'
    assert store.version('candidate1') == 1


def test_only_known_states_are_accepted(store, keys):
    store.propose('candidate1', b'patch')
    with pytest.raises(PromotionError, match='unknown_state'):
        store.transition_message('candidate1', 'BOOT_FLASHED')


def test_persistent_evidence_survives_restart(tmp_path, keys):
    db = tmp_path / 'persistent.sqlite3'
    pub = {k: v.public_key() for k, v in keys.items()}
    s1 = PromotionStore(db, pub)
    s1.propose('candidate1', b'patch')
    s2 = PromotionStore(db, pub)
    assert s2.state('candidate1') == 'PROPOSED'
    assert s2.event_count('candidate1') == 1