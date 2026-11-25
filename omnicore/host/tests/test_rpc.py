"""Contract tests for untrusted RPC, tenant identity, and fail-closed AI adapter."""
import hashlib
import json
import uuid
import pytest

from omnicore_host.rpc import ContractError, CallerIdentity, decode_request
from omnicore_host.adapter import DigitalLifeAdapter


def packet(payload='przykladowa tresc', cap='rag.query', source='omnicore-home', **changes):
    doc = dict(schema='omnicore.rpc.v1', request_id=str(uuid.uuid4()), source=source,
               capability=cap, deadline_ms=1500,
               payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),
               reply_to='device/local/session', payload=payload)
    doc.update(changes)
    return json.dumps(doc, ensure_ascii=False).encode('utf-8')


def principal():
    return CallerIdentity('device-01', 'tenant-01', frozenset({'omnicore-home'}),
                          frozenset({'rag.query', 'intent.classify'}))


def test_valid_unicode_payload_hash_roundtrip():
    req = decode_request(packet('żółć 🦉'), principal())
    assert req.payload == 'żółć 🦉' and req.capability == 'rag.query'


def test_duplicate_top_level_key_is_rejected():
    raw = packet()
    raw = raw[:-1] + b',"capability":"shell.exec"}'
    with pytest.raises(ContractError, match='duplicate_key'):
        decode_request(raw, principal())


def test_nested_duplicate_key_is_rejected():
    raw = packet(payload='tekst')
    raw = raw[:-1] + b',"metadata":{"a":1,"a":2}}'
    with pytest.raises(ContractError, match='duplicate_key'):
        decode_request(raw, principal())


def test_declared_source_cannot_impersonate_other_application():
    with pytest.raises(ContractError, match='untrusted_source'):
        decode_request(packet(source='omnicore-settings'), principal())


def test_capability_requires_authorized_transport_principal():
    with pytest.raises(ContractError, match='capability_denied'):
        decode_request(packet(cap='media.offload'), principal())


def test_no_missing_payload_implicitly_accepted():
    doc = json.loads(packet())
    del doc['payload']
    with pytest.raises(ContractError, match='missing_or_extra_fields'):
        decode_request(json.dumps(doc).encode(), principal())


def test_hash_mismatch_rejected():
    with pytest.raises(ContractError, match='hash_mismatch'):
        decode_request(packet(payload_sha256='0' * 64), principal())


def test_limit_exactly_enforced():
    with pytest.raises(ContractError, match='frame_too_large'):
        decode_request(b'A' * 65537, principal())


def test_payload_urls_remain_data_not_shell_commands():
    req = decode_request(packet('Dokumentacja: https://example.org oraz ../ w cytacie'), principal())
    assert 'https://example.org' in req.payload


def test_adapter_has_no_fake_success_without_engine():
    adapter = DigitalLifeAdapter({})
    response = adapter.handle(packet(), principal())
    assert response['status'] == 'OFFLINE' and response['reason'] == 'handler_unavailable'


def test_adapter_uses_explicit_allowlisted_handler_only():
    adapter = DigitalLifeAdapter({'rag.query': lambda req, caller: {'hits': [], 'tenant': caller.tenant}})
    resp = adapter.handle(packet('pytanie'), principal())
    assert resp['status'] == 'OK' and resp['body']['tenant'] == 'tenant-01'


def test_invalid_wire_frame_denied_without_debug_echo():
    adapter = DigitalLifeAdapter({})
    response = adapter.handle(b'not json', principal())
    assert response['status'] == 'DENY'
    assert 'not json' not in json.dumps(response)
