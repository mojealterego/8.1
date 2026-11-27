"""Strict on-wire OCRS-81 RPC envelope validation.

Do not instantiate CallerIdentity from RPC content. The transport boundary must
construct it from verified peer credentials/mTLS and a fixed authorization map.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import uuid

SCHEMA = "omnicore.rpc.v1"
MAX_FRAME_BYTES = 65_536
MAX_PAYLOAD_BYTES = 32_768
MAX_DEADLINE_MS = 5_000
_CAPABILITIES = frozenset({
    "intent.local", "intent.classify", "rag.query", "media.thumbnail",
    "media.tile_budget", "media.offload", "system.status"
})
_FIELDS = frozenset({"schema", "request_id", "source", "capability", "deadline_ms",
                     "payload_sha256", "reply_to", "payload"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")

class ContractError(ValueError):
    """Invalid / unauthorized RPC request; reason contains no user payload."""

@dataclass(frozen=True)
class CallerIdentity:
    peer_id: str
    tenant: str
    allowed_sources: frozenset[str]
    allowed_capabilities: frozenset[str]

    def __post_init__(self) -> None:
        if not (self.peer_id and self.tenant and self.allowed_sources):
            raise ValueError("invalid_principal")
        if not self.allowed_capabilities.issubset(_CAPABILITIES):
            raise ValueError("invalid_capability_grants")

@dataclass(frozen=True)
class RpcRequest:
    request_id: str
    source: str
    capability: str
    deadline_ms: int
    payload: str
    reply_to: str


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate_key")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise ContractError("invalid_numeric_constant")


def decode_request(raw: bytes, principal: CallerIdentity) -> RpcRequest:
    if not isinstance(raw, bytes) or not (0 < len(raw) <= MAX_FRAME_BYTES):
        raise ContractError("frame_too_large")
    if not isinstance(principal, CallerIdentity):
        raise ContractError("missing_transport_identity")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys,
                          parse_constant=_invalid_constant)
    except ContractError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ContractError("invalid_json") from exc
    if type(data) is not dict or set(data) != _FIELDS:
        raise ContractError("missing_or_extra_fields")
    if data["schema"] != SCHEMA:
        raise ContractError("invalid_schema")
    for key in ("request_id", "source", "capability", "payload_sha256", "reply_to", "payload"):
        if type(data[key]) is not str:
            raise ContractError("invalid_field_type")
    try:
        identifier = uuid.UUID(data["request_id"])
        if str(identifier) != data["request_id"]:
            raise ValueError("noncanonical_uuid")
    except ValueError as exc:
        raise ContractError("invalid_request_id") from exc
    if not _SOURCE.fullmatch(data["source"]):
        raise ContractError("invalid_source")
    if data["source"] not in principal.allowed_sources:
        raise ContractError("untrusted_source")
    cap = data["capability"]
    if cap not in _CAPABILITIES or cap not in principal.allowed_capabilities:
        raise ContractError("capability_denied")
    deadline = data["deadline_ms"]
    if type(deadline) is not int or not 0 < deadline <= MAX_DEADLINE_MS:
        raise ContractError("invalid_deadline")
    if data["reply_to"] != "device/local/session":
        raise ContractError("invalid_reply_destination")
    try:
        payload = data["payload"].encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractError("invalid_payload_encoding") from exc
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ContractError("payload_too_large")
    stated = data["payload_sha256"]
    if not _SHA256.fullmatch(stated) or not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), stated):
        raise ContractError("hash_mismatch")
    return RpcRequest(str(identifier), data["source"], cap, deadline,
                      data["payload"], data["reply_to"])
