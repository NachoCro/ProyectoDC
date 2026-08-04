"""Tests for config precedence (middleware/config.py): DB > .env > default."""

import sqlite3

from middleware import config


def _make_config_table(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE config (clave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
    finally:
        conn.close()


def test_default_when_nothing_set(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "cfg.db"))
    monkeypatch.delenv("BATCH_SIZE", raising=False)
    monkeypatch.setattr(config, "_DB_CACHE", None)
    assert config._get("BATCH_SIZE") == "10"


def test_env_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "cfg.db"))
    monkeypatch.setenv("BATCH_SIZE", "33")
    monkeypatch.setattr(config, "_DB_CACHE", None)
    assert config._get("BATCH_SIZE") == "33"


def test_db_overrides_env(monkeypatch, tmp_path):
    dbp = str(tmp_path / "cfg.db")
    _make_config_table(dbp)
    monkeypatch.setenv("DB_PATH", dbp)
    monkeypatch.setenv("BATCH_SIZE", "33")
    monkeypatch.setattr(config, "_DB_CACHE", None)

    config.set_config("BATCH_SIZE", "25")
    assert config.get_config("BATCH_SIZE") == "25"


def test_set_config_persists_and_reloads(monkeypatch, tmp_path):
    dbp = str(tmp_path / "cfg.db")
    _make_config_table(dbp)
    monkeypatch.setenv("DB_PATH", dbp)
    monkeypatch.setattr(config, "_DB_CACHE", None)

    config.set_config("API_SLEEP", "7")
    monkeypatch.setattr(config, "_DB_CACHE", None)
    assert config.get_config("API_SLEEP") == "7"


def test_get_config_unknown_returns_default(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "cfg.db"))
    monkeypatch.setattr(config, "_DB_CACHE", None)
    assert config.get_config("CLAVE_INEXISTENTE") == ""
    assert config.get_config("CLAVE_INEXISTENTE", "99") == "99"
