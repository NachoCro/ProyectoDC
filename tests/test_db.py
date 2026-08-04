"""Tests for SQLite helpers and schema bootstrapping (middleware/db.py)."""

import pytest

from middleware import db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", str(p))
    monkeypatch.setattr(db, "_MIGRATED", False)
    return str(p)


def _columns(table):
    conn = db.get_connection()
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r["name"] for r in rows}
    finally:
        conn.close()


def test_ensure_schema_idempotent(db_path):
    conn1 = db.get_connection()
    conn2 = db.get_connection()
    try:
        tables = {r["name"] for r in conn1.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    finally:
        conn1.close()
        conn2.close()
    assert {"categorias", "subcategorias", "productos",
            "caracteristicas", "producto_caracteristicas",
            "config", "audit_log"} <= tables


def test_migrations_columns_present(db_path):
    cols = _columns("productos")
    assert {"proposal_json", "imagen_url", "active_verified",
            "pendiente_activar", "product_not_found", "nombre"} <= cols
    assert _columns("subcategorias") >= {"id_prestashop_categoria"}


def test_insert_and_short_circuit(db_path):
    conn = db.get_connection()
    try:
        ok = db.insert_product(
            conn, 100, 1, "7790000000001", "MPN1", "Samsung", "QN55", "TV Samsung"
        )
        assert ok is True
        conn.commit()
    finally:
        conn.close()

    assert db.has_id_in_db(100) is True
    assert db.has_ean_in_db("7790000000001") is True
    assert db.has_id_in_db(999) is False


def test_insert_collision_returns_false(db_path):
    conn = db.get_connection()
    try:
        assert db.insert_product(conn, 200, 1, None, None, "LG", "C4", "TV") is True
        assert db.insert_product(conn, 200, 1, None, None, "LG", "C4", "TV") is False
        conn.commit()
    finally:
        conn.close()


def test_mark_not_found(db_path):
    conn = db.get_connection()
    try:
        db.insert_product(conn, 300, 1, None, None, "X", "Y", "Z")
        conn.commit()
    finally:
        conn.close()
    assert db.has_product_not_found(None, 300) is False
    db.mark_not_found(300)
    assert db.has_product_not_found(None, 300) is True


def test_has_product_not_found_by_ean(db_path):
    conn = db.get_connection()
    try:
        db.insert_product(conn, 301, 1, "7790000000005", None, "X", "Y", "Z")
        conn.commit()
    finally:
        conn.close()
    db.mark_not_found(301)
    # The EAN branch matches rows by EAN, the id branch by id_prestashop
    assert db.has_product_not_found("7790000000005", 301) is True
    assert db.has_product_not_found("OTRO-EAN", 301) is False
    assert db.has_product_not_found(None, 301) is True


def test_sync_producto_from_prestashop(db_path):
    conn = db.get_connection()
    try:
        db.insert_product(conn, 400, 1, None, None, "", "", None)
        conn.commit()

        updated = db.sync_producto_from_prestashop(
            conn, 400, "7790000000002", "MPN2", "Canon", "Impresora Canon", 5
        )
        assert "ean" in updated and "mpn" in updated and "marca" in updated

        row = conn.execute(
            "SELECT ean, marca, product_not_found FROM productos WHERE id_prestashop=400"
        ).fetchone()
        assert row["ean"] == "7790000000002"
        assert row["marca"] == "Canon"
    finally:
        conn.close()


def test_ensure_subcategoria_creates(db_path):
    conn = db.get_connection()
    try:
        sid = db.ensure_subcategoria(conn, "SIN CLASIFICAR")
        assert sid is not None
        sid2 = db.ensure_subcategoria(conn, "SIN CLASIFICAR")
        assert sid == sid2
    finally:
        conn.close()


def test_write_eav_and_read_back(db_path):
    conn = db.get_connection()
    try:
        db.insert_product(conn, 500, 1, None, None, "HP", "X", "Y")
        db.write_eav(conn, 500, [
            {"nombre": "Color", "valor": "Negro"},
            {"nombre": "Peso", "valor": "1.5 kg"},
            {"nombre": "Basura", "valor": "  "},
        ])
        conn.commit()

        rows = conn.execute(
            """SELECT c.nombre_caracteristica AS nombre, pc.valor AS valor
               FROM producto_caracteristicas pc
               JOIN caracteristicas c ON c.id_caracteristica = pc.id_caracteristica
               WHERE pc.id_prestashop = 500 ORDER BY c.nombre_caracteristica"""
        ).fetchall()
        got = {r["nombre"]: r["valor"] for r in rows}
        assert got == {"Color": "Negro", "Peso": "1.5 kg"}
    finally:
        conn.close()
