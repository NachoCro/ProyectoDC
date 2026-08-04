"""Tests for SQLite-backed daemon state (middleware/daemon_state.py)."""

import pytest

from middleware import daemon_state as ds


@pytest.fixture
def ds_db(tmp_path, monkeypatch):
    from middleware import db

    p = tmp_path / "daemon.db"
    monkeypatch.setattr(db, "DB_PATH", str(p))
    monkeypatch.setattr(db, "_MIGRATED", False)
    return str(p)


def test_request_stop_flag(ds_db):
    ds.start(300, False)
    assert ds.stop_requested() is False
    ds.request_stop()
    assert ds.stop_requested() is True
    ds.stop()
    assert ds.stop_requested() is False


def test_start_resets_stop_flag(ds_db):
    ds.start(60, True, check_inactive=True)
    ds.request_stop()
    ds.start(60, True, check_inactive=True)
    assert ds.stop_requested() is False


def test_state_snapshot(ds_db):
    ds.start(60, True)
    ds.set_pid(1234)
    state = ds.get_state()
    assert state["running"] is True
    assert state["dry_run"] is True
    assert state["pid"] == 1234
    assert state["interval"] == 60
    ds.stop()
    assert ds.get_state()["running"] is False
