"""SQLite-backed at-most-once admission within bounded retention.

This is not exactly-once processing, physical anti-rollback or a secure time service.
If the host clock moves backwards, new work is denied until an operator repairs time.
Full capacity denies NEW work rather than evicting unexpired IDs.
"""
from __future__ import annotations
import re
import sqlite3
import time
from pathlib import Path

_COMPONENT = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}\Z')

class ReplayError(ValueError):
    pass

class ReplayStore:
    def __init__(self, path: Path, *, capacity: int = 16384, retention_seconds: int = 86400):
        if not 0 < capacity <= 1_000_000 or not 0 < retention_seconds <= 365 * 86400:
            raise ValueError('invalid_replay_configuration')
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.capacity = capacity
        self.retention_seconds = retention_seconds
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS seen (
                  peer TEXT NOT NULL, tenant TEXT NOT NULL, request_id TEXT NOT NULL,
                  valid_until INTEGER NOT NULL,
                  PRIMARY KEY(peer, tenant, request_id)
                );
                CREATE INDEX IF NOT EXISTS seen_valid_until ON seen(valid_until);
                CREATE TABLE IF NOT EXISTS replay_clock (
                  id INTEGER PRIMARY KEY CHECK(id=1), last_observed INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO replay_clock VALUES (1, 0);
            ''')

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.execute('PRAGMA busy_timeout=5000')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        return db

    def admit(self, peer: str, tenant: str, request_id: str, *, now: int | None = None) -> bool:
        if not all(isinstance(x, str) and _COMPONENT.fullmatch(x) for x in (peer, tenant, request_id)):
            raise ReplayError('invalid_replay_key')
        if now is None:
            now = int(time.time())
        if type(now) is not int or now < 0:
            raise ReplayError('invalid_clock')
        db = self._connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            last = db.execute('SELECT last_observed FROM replay_clock WHERE id=1').fetchone()[0]
            if now < last:
                raise ReplayError('clock_regression')
            # Expiration is a documented replay-window limit, never silent eviction.
            db.execute('DELETE FROM seen WHERE valid_until <= ?', (now,))
            if db.execute('SELECT 1 FROM seen WHERE peer=? AND tenant=? AND request_id=?',
                          (peer, tenant, request_id)).fetchone():
                db.execute('UPDATE replay_clock SET last_observed=? WHERE id=1', (now,))
                db.commit()
                return False
            if db.execute('SELECT count(*) FROM seen').fetchone()[0] >= self.capacity:
                raise ReplayError('replay_capacity_exhausted')
            db.execute('INSERT INTO seen(peer,tenant,request_id,valid_until) VALUES(?,?,?,?)',
                       (peer, tenant, request_id, now + self.retention_seconds))
            db.execute('UPDATE replay_clock SET last_observed=? WHERE id=1', (now,))
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def count(self) -> int:
        with self._connect() as db:
            return db.execute('SELECT count(*) FROM seen').fetchone()[0]