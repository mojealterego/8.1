"""Signed, durable local admission of candidate artifacts (not a deployment agent).

An agent cannot approve its own candidates without the OWNER private key.
Local SQLite sequence is NOT an external tamper-proof anti-rollback witness.
Do not expose trusted private keys to Digital-Life/OMEGA-X workers.
"""
from __future__ import annotations
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Mapping
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

STAGES = ("PROPOSED", "STATIC_VALIDATED", "SANDBOX_TESTED",
          "FUNCTIONAL_ACCEPTED", "SECURITY_ACCEPTED", "OWNER_APPROVED",
          "SIGNED_RELEASE")
_SIGNER = {
    "STATIC_VALIDATED": "verifier", "SANDBOX_TESTED": "verifier",
    "FUNCTIONAL_ACCEPTED": "verifier", "SECURITY_ACCEPTED": "verifier",
    "OWNER_APPROVED": "owner", "SIGNED_RELEASE": "release"
}
_ID = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}\Z")

class PromotionError(ValueError):
    pass


def canonical(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":"),
                      sort_keys=True, allow_nan=False).encode("utf-8")


def sign_transition(private_key: Ed25519PrivateKey, msg: bytes) -> bytes:
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("invalid_key_type")
    return private_key.sign(msg)

class PromotionStore:
    def __init__(self, db_file: Path, public_keys: Mapping[str, Ed25519PublicKey]) -> None:
        self.db_file = Path(db_file)
        if set(public_keys) != {"verifier", "owner", "release"} or any(
            not isinstance(key, Ed25519PublicKey) for key in public_keys.values()
        ):
            raise ValueError("missing_trust_keys")
        self.public_keys = dict(public_keys)
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS candidates (
                           cid TEXT PRIMARY KEY, sha TEXT NOT NULL,
                           state TEXT NOT NULL, version INTEGER)""")
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                           id INTEGER PRIMARY KEY AUTOINCREMENT, cid TEXT NOT NULL,
                           stage TEXT NOT NULL, receipt BLOB NOT NULL,
                           message BLOB NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS release_counter (
                           id INTEGER PRIMARY KEY CHECK (id=1), next_version INTEGER NOT NULL)""")
            db.execute("INSERT OR IGNORE INTO release_counter VALUES(1, 1)")
            db.commit()

    def _db(self):
        db = sqlite3.connect(self.db_file, timeout=5.0)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=5000")
        return closing(db)

    def propose(self, cid: str, artifact: bytes) -> dict:
        if not isinstance(cid, str) or not _ID.fullmatch(cid):
            raise PromotionError("invalid_candidate_id")
        if type(artifact) is not bytes or not (0 < len(artifact) <= 4_194_304):
            raise PromotionError("invalid_artifact")
        digest = hashlib.sha256(artifact).hexdigest()
        with self._db() as db:
            with db:
                try:
                    db.execute("INSERT INTO candidates VALUES(?,?,?,NULL)",
                               (cid, digest, "PROPOSED"))
                except sqlite3.IntegrityError as exc:
                    raise PromotionError("duplicate_candidate") from exc
                db.execute("INSERT INTO events(cid,stage,receipt,message) VALUES(?,?,?,?)",
                           (cid, "PROPOSED", b"", canonical({"cid": cid, "sha": digest})))
        return {"id": cid, "artifact_sha256": digest, "state": "PROPOSED"}

    def _record(self, db, cid: str):
        row = db.execute("SELECT sha,state,version FROM candidates WHERE cid=?", (cid,)).fetchone()
        if row is None:
            raise PromotionError("unknown_candidate")
        return row

    def _message(self, db, cid: str, next_state: str) -> bytes:
        if next_state not in _SIGNER:
            raise PromotionError("unknown_state")
        sha, state, _ = self._record(db, cid)
        row = db.execute("SELECT next_version FROM release_counter WHERE id=1").fetchone()
        version = row[0] if next_state == "SIGNED_RELEASE" else None
        return canonical({"domain": "OCRS81-PROMOTION-V1", "id": cid, "sha256": sha,
                          "from": state, "to": next_state, "release_version": version})

    def transition_message(self, cid: str, next_state: str) -> bytes:
        with self._db() as db:
            return self._message(db, cid, next_state)

    def advance(self, cid: str, next_state: str, signature: bytes) -> dict:
        if next_state not in _SIGNER:
            raise PromotionError("unknown_state")
        if type(signature) is not bytes or len(signature) != 64:
            raise PromotionError("signature_invalid")
        with self._db() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                sha, state, oldversion = self._record(db, cid)
                if STAGES.index(next_state) != STAGES.index(state) + 1:
                    raise PromotionError("invalid_transition")
                message = self._message(db, cid, next_state)
                try:
                    self.public_keys[_SIGNER[next_state]].verify(signature, message)
                except InvalidSignature as exc:
                    raise PromotionError("signature_invalid") from exc
                version = json.loads(message)["release_version"] if next_state == "SIGNED_RELEASE" else oldversion
                cur = db.execute("UPDATE candidates SET state=?,version=? WHERE cid=? AND state=?",
                                 (next_state, version, cid, state))
                if cur.rowcount != 1:
                    raise PromotionError("race_lost")
                if next_state == "SIGNED_RELEASE":
                    db.execute("UPDATE release_counter SET next_version=next_version+1 WHERE id=1")
                db.execute("INSERT INTO events(cid,stage,receipt,message) VALUES(?,?,?,?)",
                           (cid, next_state, signature, message))
                db.commit()
                return {"id": cid, "state": next_state, "artifact_sha256": sha,
                        "release_version": version}
            except Exception:
                db.rollback()
                raise

    def state(self, cid: str) -> str:
        with self._db() as db:
            return self._record(db, cid)[1]

    def version(self, cid: str) -> int | None:
        with self._db() as db:
            return self._record(db, cid)[2]

    def event_count(self, cid: str) -> int:
        with self._db() as db:
            return db.execute("SELECT count(*) FROM events WHERE cid=?", (cid,)).fetchone()[0]

    def verify_integrity(self) -> dict[str, int]:
        """Verify signed event transitions and the materialized candidate states.

        This detects local corruption/tampering in stored events and state. It is
        NOT independent anti-rollback protection: a privileged attacker can
        delete/restore the entire DB and its local counter.
        """
        with self._db() as db:
            candidates = db.execute(
                "SELECT cid,sha,state,version FROM candidates ORDER BY cid"
            ).fetchall()
            count = 0
            versions = set()
            for cid, sha, stored_state, stored_version in candidates:
                rows = db.execute(
                    "SELECT stage,receipt,message FROM events WHERE cid=? ORDER BY id",(cid,)
                ).fetchall()
                if not rows or rows[0][0] != 'PROPOSED':
                    raise PromotionError('event_integrity_failed')
                stage,receipt,message = rows[0]
                if receipt != b'' or message != canonical({'cid':cid,'sha':sha}):
                    raise PromotionError('event_integrity_failed')
                prev_state = 'PROPOSED'
                last_version = None
                for stage, receipt, message in rows[1:]:
                    if stage not in _SIGNER:
                        raise PromotionError('event_integrity_failed')
                    try:
                        if STAGES.index(stage) != STAGES.index(prev_state) + 1:
                            raise PromotionError('event_integrity_failed')
                        doc = json.loads(message)
                        if type(doc) is not dict or set(doc) != {
                            'domain','id','sha256','from','to','release_version'
                        }:
                            raise PromotionError('event_integrity_failed')
                        ver = doc['release_version']
                        if (doc['domain'] != 'OCRS81-PROMOTION-V1' or
                            doc['id'] != cid or doc['sha256'] != sha or
                            doc['from'] != prev_state or doc['to'] != stage or
                            message != canonical(doc) or
                            (stage != 'SIGNED_RELEASE' and ver is not None) or
                            (stage == 'SIGNED_RELEASE' and (type(ver) is not int or ver < 1))):
                            raise PromotionError('event_integrity_failed')
                        self.public_keys[_SIGNER[stage]].verify(receipt, message)
                        if stage == 'SIGNED_RELEASE':
                            if ver in versions:
                                raise PromotionError('event_integrity_failed')
                            versions.add(ver)
                            last_version = ver
                    except (ValueError,TypeError,UnicodeError,InvalidSignature,IndexError) as exc:
                        raise PromotionError('event_integrity_failed') from exc
                    prev_state = stage
                if stored_state != prev_state or stored_version != last_version:
                    raise PromotionError('candidate_integrity_failed')
                count += len(rows)
            orphans = db.execute(
                'SELECT count(*) FROM events e LEFT JOIN candidates c ON e.cid=c.cid WHERE c.cid IS NULL'
            ).fetchone()[0]
            if orphans:
                raise PromotionError('event_integrity_failed')
            next_version = db.execute(
                'SELECT next_version FROM release_counter WHERE id=1'
            ).fetchone()[0]
            if next_version <= max(versions, default=0):
                raise PromotionError('event_integrity_failed')
            return {'candidates':len(candidates),'events':count}