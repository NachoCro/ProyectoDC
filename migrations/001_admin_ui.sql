-- Migration 001: Admin UI support
--  * productos.icecat_json  — payload completo de Icecat pendiente de aprobación
--  * audit_log             — registro inmutable de acciones

ALTER TABLE productos ADD COLUMN icecat_json TEXT;

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
    id_producto INTEGER NOT NULL REFERENCES productos(id_prestashop) ON DELETE CASCADE,
    actor       TEXT    NOT NULL,
    accion      TEXT    NOT NULL,
    detalle     TEXT
);
