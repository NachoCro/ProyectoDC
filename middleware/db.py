import logging
import sqlite3
import threading

from .config import DB_PATH

logger = logging.getLogger(__name__)

_MIGRATED = False
_MIGRATE_LOCK = threading.Lock()


def _ensure_schema() -> None:
    """Create base tables and apply migrations (idempotent, self-bootstrapping)."""
    global _MIGRATED
    if _MIGRATED:
        return
    with _MIGRATE_LOCK:
        if _MIGRATED:
            return

        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")

            # ── Base tables ──────────────────────────────────────────────
            conn.execute(
                """CREATE TABLE IF NOT EXISTS categorias (
                    id_categoria     INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_categoria TEXT    NOT NULL UNIQUE
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS subcategorias (
                    id_subcategoria     INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_categoria        INTEGER NOT NULL REFERENCES categorias(id_categoria)
                                            ON DELETE CASCADE ON UPDATE CASCADE,
                    nombre_subcategoria TEXT    NOT NULL UNIQUE
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS caracteristicas (
                    id_caracteristica      INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_caracteristica  TEXT    NOT NULL UNIQUE
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS productos (
                    id_prestashop          INTEGER PRIMARY KEY,
                    id_subcategoria        INTEGER NOT NULL REFERENCES subcategorias(id_subcategoria)
                                               ON UPDATE CASCADE,
                    ean                    TEXT    NULL,
                    mpn                    TEXT    NULL,
                    marca                  TEXT    NOT NULL DEFAULT '',
                    modelo                 TEXT    NOT NULL DEFAULT '',
                    vector_descriptivo     BLOB    NULL,
                    fecha_sincronizacion   TEXT    NULL,
                    estado_actualizacion   TEXT    NOT NULL DEFAULT 'desactualizado'
                                               CHECK (estado_actualizacion IN ('actualizado', 'desactualizado')),
                    product_not_found      INTEGER NOT NULL DEFAULT 0
                                               CHECK (product_not_found IN (0, 1))
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS producto_caracteristicas (
                    id_prestashop      INTEGER NOT NULL REFERENCES productos(id_prestashop)
                                          ON DELETE CASCADE ON UPDATE CASCADE,
                    id_caracteristica  INTEGER NOT NULL REFERENCES caracteristicas(id_caracteristica)
                                          ON DELETE CASCADE ON UPDATE CASCADE,
                    valor              TEXT    NOT NULL,
                    PRIMARY KEY (id_prestashop, id_caracteristica)
                )"""
            )

            # ── Migrations (idempotent ALTER TABLE) ──────────────────────

            # Migration 001 (admin UI): icecat_json + audit_log
            try:
                conn.execute("ALTER TABLE productos ADD COLUMN icecat_json TEXT")
            except sqlite3.OperationalError:
                pass

            conn.execute(
                """CREATE TABLE IF NOT EXISTS audit_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT    NOT NULL DEFAULT (datetime('now')),
                    id_producto INTEGER NOT NULL REFERENCES productos(id_prestashop) ON DELETE CASCADE,
                    actor       TEXT    NOT NULL,
                    accion      TEXT    NOT NULL,
                    detalle     TEXT
                )"""
            )

            # Migration 002: imagen_url
            try:
                conn.execute("ALTER TABLE productos ADD COLUMN imagen_url TEXT NULL")
            except sqlite3.OperationalError:
                pass

            # Migration 003: id_prestashop_categoria on subcategorias
            try:
                conn.execute("ALTER TABLE subcategorias ADD COLUMN id_prestashop_categoria INTEGER NULL")
            except sqlite3.OperationalError:
                pass

            # Migration 004: nombre on productos
            try:
                conn.execute("ALTER TABLE productos ADD COLUMN nombre TEXT NULL")
            except sqlite3.OperationalError:
                pass

            # Migration 005: rename icecat_not_found → product_not_found
            try:
                conn.execute(
                    "ALTER TABLE productos RENAME COLUMN icecat_not_found TO product_not_found"
                )
            except sqlite3.OperationalError:
                pass

            # Migration 006: active_verified (tracks if product was verified as complete)
            try:
                conn.execute(
                    "ALTER TABLE productos ADD COLUMN active_verified INTEGER NOT NULL DEFAULT 0 "
                    "CHECK (active_verified IN (0, 1))"
                )
            except sqlite3.OperationalError:
                pass

            # ── Config table (app settings) ─────────────────────────────
            conn.execute(
                """CREATE TABLE IF NOT EXISTS config (
                    clave  TEXT PRIMARY KEY,
                    valor  TEXT NOT NULL
                )"""
            )

            # ── Seed data if empty ──────────────────────────────────────
            cat_count = conn.execute("SELECT COUNT(*) FROM categorias").fetchone()[0]
            if cat_count == 0:
                conn.executescript("""
                    INSERT OR IGNORE INTO categorias (id_categoria, nombre_categoria) VALUES
                        (1, 'TELEFONIA'),
                        (2, 'INFORMATICA'),
                        (3, 'IMPRESION 3D'),
                        (4, 'MOUSES'),
                        (5, 'TV Y MONITORES'),
                        (6, 'GAMERS');

                    INSERT OR IGNORE INTO subcategorias (id_subcategoria, id_categoria, nombre_subcategoria) VALUES
                        (1,  1, 'CELULARES LIBRES'),
                        (2,  1, 'SMARTPHONES'),
                        (3,  1, 'ACCESORIOS TELEFONIA'),
                        (4,  2, 'NOTEBOOKS'),
                        (5,  2, 'ULTRABOOKS'),
                        (6,  2, 'ALL IN ONE'),
                        (7,  3, 'IMPRESORAS FDM'),
                        (8,  3, 'IMPRESORAS RESINA'),
                        (9,  3, 'FILAMENTOS Y RESINAS'),
                        (10, 4, 'MOUSES INALAMBRICOS'),
                        (11, 4, 'MOUSES CON CABLE'),
                        (12, 4, 'MOUSES ERGONOMICOS'),
                        (13, 5, 'SMART TV'),
                        (14, 5, 'MONITORES'),
                        (15, 5, 'PROYECTORES'),
                        (16, 6, 'SILLAS GAMER'),
                        (17, 6, 'PERIFERICOS GAMER'),
                        (18, 6, 'CONSOLAS');

                    INSERT OR IGNORE INTO caracteristicas (id_caracteristica, nombre_caracteristica) VALUES
                        (1,  'Marca'), (2,  'Modelo'), (3,  'Color'), (4,  'Peso'), (5,  'Dimensiones'),
                        (6,  'Tecnologia de impresion'), (7,  'Volumen de impresion'), (8,  'Resolucion de capa'),
                        (9,  'Diametro de filamento'), (10, 'Materiales compatibles'), (11, 'Velocidad de impresion'),
                        (12, 'Numero de extrusores'), (13, 'Cama caliente'), (14, 'Conectividad'), (15, 'Pantalla tactil'),
                        (16, 'Procesador'), (17, 'RAM'), (18, 'Almacenamiento'), (19, 'Tipo de pantalla'),
                        (20, 'Tamanio de pantalla'), (21, 'Resolucion de pantalla'), (22, 'Tarjeta grafica'),
                        (23, 'Sistema operativo'), (24, 'Duracion de bateria'), (25, 'Puertos'),
                        (26, 'Tipo de conexion'), (27, 'Sensor'), (28, 'DPI'), (29, 'Numero de botones'),
                        (30, 'Tipo de bateria'), (31, 'Iluminacion RGB'), (32, 'Ergonomico'),
                        (33, 'Camara principal'), (34, 'Camara frontal'), (35, 'Capacidad de bateria'),
                        (36, 'Conectividad movil'), (37, 'Resistencia al agua'),
                        (38, 'Frecuencia de actualizacion'), (39, 'Brillo'), (40, 'Relacion de aspecto'),
                        (41, 'HDR'), (42, 'Tiempo de respuesta'),
                        (43, 'Factor de forma'), (44, 'Iluminacion'), (45, 'Material del chasis');
                """)

            # ── Indexes ─────────────────────────────────────────────────
            conn.execute("CREATE INDEX IF NOT EXISTS idx_productos_ean  ON productos(ean)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_productos_mpn  ON productos(mpn)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_productos_estado_actualizacion ON productos(estado_actualizacion)")

            conn.commit()
        finally:
            conn.close()
        _MIGRATED = True


def get_connection() -> sqlite3.Connection:
    _ensure_schema()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def has_ean_in_db(ean: str) -> bool:
    """Check whether *any* row in `productos` already holds this EAN.

    Short-circuit gate (RF-04): if True, the product is already known locally
    and lookup can be skipped entirely.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM productos WHERE ean = ? LIMIT 1", (ean,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def has_id_in_db(id_prestashop: int) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM productos WHERE id_prestashop = ? LIMIT 1", (id_prestashop,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def has_product_not_found(ean: str | None, id_prestashop: int) -> bool:
    """Check whether this product has already been flagged as not found in any source.

    RF-05: skip products whose lookup previously failed so they are not
    reprocessed on every run.
    """
    if not ean:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT 1 FROM productos WHERE id_prestashop = ? AND product_not_found = 1 LIMIT 1",
                (id_prestashop,),
            ).fetchone()
            return row is not None
        finally:
            conn.close()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM productos WHERE ean = ? AND product_not_found = 1 LIMIT 1",
            (ean,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def insert_product(
    conn: sqlite3.Connection,
    id_prestashop: int,
    id_subcategoria: int,
    ean: str | None,
    mpn: str | None,
    marca: str,
    modelo: str,
    nombre: str | None = None,
) -> bool:
    """Insert a product row. Returns True if a new row was inserted."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO productos
           (id_prestashop, id_subcategoria, ean, mpn, marca, modelo, nombre,
            estado_actualizacion, product_not_found)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'desactualizado', 0)""",
        (id_prestashop, id_subcategoria, ean, mpn, marca, modelo, nombre),
    )
    return cur.rowcount > 0


def mark_not_found(id_prestashop: int) -> None:
    """Set `product_not_found = True` so the product is excluded from future runs (RF-05)."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE productos SET product_not_found = 1 WHERE id_prestashop = ?",
            (id_prestashop,),
        )
        conn.commit()
    finally:
        conn.close()


def sync_producto_from_prestashop(
    conn: sqlite3.Connection,
    id_prestashop: int,
    ean: str | None,
    mpn: str | None,
    marca: str,
    nombre: str | None,
    id_category_default: int | None,
) -> list[str]:
    """Sync a local product row with current PrestaShop data.

    PrestaShop is the source of truth.  Updates fields where the local value
    is empty or differs from PrestaShop.  Also resets ``product_not_found``
    if the product exists in PrestaShop (it was found).
    Returns a list of updated field names (empty list = nothing changed).
    """
    row = conn.execute(
        "SELECT ean, mpn, marca, nombre, product_not_found FROM productos WHERE id_prestashop = ?",
        (id_prestashop,),
    ).fetchone()
    if not row:
        return []

    set_parts: list[str] = []
    params: list[str | int | None] = []

    # Field sync: update if local is empty/different AND PS has a value
    for col, ps_val in [
        ("ean", ean),
        ("mpn", mpn),
        ("marca", marca),
        ("nombre", nombre),
    ]:
        local_val = row[col]
        if ps_val and ps_val != local_val:
            set_parts.append(f"{col} = ?")
            params.append(ps_val)

    # Reset product_not_found if it was set — product exists in PrestaShop
    if row["product_not_found"]:
        set_parts.append("product_not_found = 0")

    if not set_parts:
        return []

    params.append(id_prestashop)
    conn.execute(
        f"UPDATE productos SET {', '.join(set_parts)} WHERE id_prestashop = ?",
        params,
    )

    return [p.split(" =")[0] for p in set_parts]


def get_subcategoria_id(conn: sqlite3.Connection, nombre: str) -> int | None:
    row = conn.execute(
        "SELECT id_subcategoria FROM subcategorias WHERE nombre_subcategoria = ?", (nombre,)
    ).fetchone()
    return row["id_subcategoria"] if row else None


def get_subcategoria_by_ps_category(conn: sqlite3.Connection, ps_category_id: int) -> int | None:
    row = conn.execute(
        "SELECT id_subcategoria FROM subcategorias WHERE id_prestashop_categoria = ?",
        (ps_category_id,),
    ).fetchone()
    return row["id_subcategoria"] if row else None
