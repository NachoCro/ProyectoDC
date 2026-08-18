"""Tests for extraction short-circuiting (middleware/extract.py).

Verifies that products already known in the local DB do NOT consume the
``target_count`` quota — otherwise repeated runs keep walking the same
known products and process fewer new ones than requested.
"""

import pytest

from middleware import db, extract


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", str(p))
    monkeypatch.setattr(db, "_MIGRATED", False)
    return str(p)


class FakeClient:
    """Fake PrestashopClient: flat inactive catalog sliced by offset/limit."""

    def __init__(self, products, stock=None):
        self._products = products
        self._stock = stock or {}
        self._manufacturers = {}

    def get_manufacturers(self):
        return self._manufacturers

    def get_inactive_products(self, limit=10, offset=0):
        return self._products[offset:offset + limit]

    def get_active_products(self, limit=10, offset=0):
        return []

    def get_stock_map(self, pids):
        return {pid: self._stock.get(pid, 1) for pid in pids}


def _run_extract(monkeypatch, db_path, products, stock, target_count, scope="inactive"):
    monkeypatch.setattr(extract, "PrestashopClient", lambda: FakeClient(products, stock))
    return extract._run_inner(
        dry_run=True,
        override={"subcategoria": None, "cantidad": target_count, "scope": scope},
    )


def _make(pid):
    return {
        "id": str(pid),
        "name": f"Producto {pid}",
        "ean13": f"779{pid:09d}",
        "mpn": f"MPN-{pid}",
        "id_manufacturer": "1",
        "id_category_default": "5",
    }


def test_known_products_do_not_consume_quota(monkeypatch, db_path):
    conn = db.get_connection()
    try:
        # ids 1 y 2 ya están en la BD local (procesados en corridas previas).
        for pid in (1, 2):
            db.insert_product(conn, pid, 1, f"779{pid:09d}", f"MPN-{pid}", "X", "Y", "Z")
        conn.commit()
    finally:
        conn.close()

    # Catálogo: 1, 2 ya conocidos + 3..8 nuevos, todos con stock.
    products = [_make(p) for p in range(1, 9)]

    # Antes del fix, el bucle contaba 1 y 2 como candidatos y entregaba solo
    # 1 producto nuevo con target=3. Ahora debe caminar hasta encontrar 3 NUEVOS.
    pending = _run_extract(monkeypatch, db_path, products, {}, target_count=3)
    ids = sorted(p["id_prestashop"] for p in pending)
    assert ids == [3, 4, 5]


def test_fewer_new_than_target_stops_cleanly(monkeypatch, db_path):
    conn = db.get_connection()
    try:
        for pid in (1, 2):
            db.insert_product(conn, pid, 1, f"779{pid:09d}", f"MPN-{pid}", "X", "Y", "Z")
        conn.commit()
    finally:
        conn.close()

    # Solo 1 producto nuevo en todo el catálogo: no debe colgarse ni repetir
    # páginas, y debe devolver el único disponible.
    products = [_make(p) for p in range(1, 4)]
    pending = _run_extract(monkeypatch, db_path, products, {}, target_count=3)
    ids = sorted(p["id_prestashop"] for p in pending)
    assert ids == [3]


def test_stock_filter_applies_before_quota(monkeypatch, db_path):
    # ids 1..3 nuevos pero sin stock (qty 0) → no deben contar.
    products = [_make(p) for p in range(1, 7)]
    stock = {1: 0, 2: 0, 3: 0, 4: 1, 5: 1, 6: 1}
    pending = _run_extract(monkeypatch, db_path, products, stock, target_count=2)
    ids = sorted(p["id_prestashop"] for p in pending)
    assert ids == [4, 5]
