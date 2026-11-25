"""Persistent replay gate: a retry must not re-execute a committed request."""
import sqlite3
import pytest
from omnicore_host.replay import ReplayStore, ReplayError


def test_first_admission_and_duplicate_denial(tmp_path):
    s = ReplayStore(tmp_path / 'replay.db', capacity=5, retention_seconds=300)
    assert s.admit('device-01', 'tenant-a', 'request-001', now=1000) is True
    assert s.admit('device-01', 'tenant-a', 'request-001', now=1001) is False


def test_persists_across_process_restart(tmp_path):
    path = tmp_path / 'replay.db'
    ReplayStore(path).admit('device-01', 'tenant-a', 'request-001', now=1000)
    assert ReplayStore(path).admit('device-01', 'tenant-a', 'request-001', now=1002) is False


def test_replay_scoped_to_authenticated_identity(tmp_path):
    s = ReplayStore(tmp_path / 'replay.db')
    assert s.admit('device-01', 'tenant-a', 'request-001', now=1000)
    assert s.admit('device-02', 'tenant-a', 'request-001', now=1001)
    assert s.admit('device-01', 'tenant-b', 'request-001', now=1002)


def test_full_replay_database_fails_closed_not_evicted(tmp_path):
    s = ReplayStore(tmp_path / 'replay.db', capacity=1, retention_seconds=100)
    s.admit('device-01', 'tenant-a', 'one', now=1000)
    with pytest.raises(ReplayError, match='replay_capacity_exhausted'):
        s.admit('device-01', 'tenant-a', 'two', now=1001)
    assert s.admit('device-01', 'tenant-a', 'one', now=1002) is False


def test_expired_rows_can_be_collected_with_explicit_retention(tmp_path):
    s = ReplayStore(tmp_path / 'replay.db', capacity=1, retention_seconds=10)
    s.admit('device-01', 'tenant-a', 'old', now=1000)
    assert s.admit('device-01', 'tenant-a', 'new', now=1011) is True
    assert s.count() == 1


def test_rollback_of_clock_fails_closed(tmp_path):
    s = ReplayStore(tmp_path / 'replay.db')
    s.admit('device-01', 'tenant-a', 'old', now=1000)
    with pytest.raises(ReplayError, match='clock_regression'):
        s.admit('device-01', 'tenant-a', 'new', now=999)


def test_invalid_identity_rejected(tmp_path):
    s = ReplayStore(tmp_path / 'replay.db')
    with pytest.raises(ReplayError, match='invalid_replay_key'):
        s.admit('bad/name', 'tenant-a', 'id', now=1000)