"""Tests para el login / gestión de usuarios (middleware/users.py)."""

import pytest

from middleware import users


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    from middleware import db

    p = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", str(p))
    monkeypatch.setattr(db, "_MIGRATED", False)
    return str(p)


def test_create_and_verify(db_path):
    ok, err = users.create_user("Admin", "clave123", "admin")
    assert ok and err is None
    user = users.verify_user("admin", "clave123")  # normaliza a minúsculas
    assert user == {"usuario": "admin", "rol": "admin"}


def test_wrong_password_rejected(db_path):
    users.create_user("operador", "clave-segura", "operador")
    assert users.verify_user("operador", "otra-clave") is None
    assert users.verify_user("operador", "") is None
    assert users.verify_user("", "clave-segura") is None


def test_duplicate_user_rejected(db_path):
    ok, err = users.create_user("juan", "clave", "operador")
    assert ok
    ok2, err2 = users.create_user("JUAN", "otra-clave", "admin")
    assert ok2 is False and err2 == "El usuario ya existe."


def test_invalid_role_rejected(db_path):
    ok, err = users.create_user("raro", "clave", "superadmin")
    assert ok is False
    assert "Rol inválido" in err


def test_password_not_stored_in_clear(db_path):
    users.create_user("secret", "mi-clave-super-secreta", "admin")
    from middleware.db import get_connection

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT password_hash FROM usuarios WHERE usuario = 'secret'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert "mi-clave-super-secreta" not in row["password_hash"]


def test_count_and_env_admin(db_path, monkeypatch):
    assert users.count_users() == 0
    monkeypatch.setenv("ADMIN_USER", "jefe")
    monkeypatch.setenv("ADMIN_PASS", "s3cr3t")
    users.ensure_admin_from_env()
    assert users.count_users() == 1
    assert users.verify_user("jefe", "s3cr3t") == {"usuario": "jefe", "rol": "admin"}
