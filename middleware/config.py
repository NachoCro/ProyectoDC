import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()

# ── Env defaults ───────────────────────────────────────────────────────
DEFAULTS = {
    "PRESTASHOP_API_URL": "",
    "PRESTASHOP_API_KEY": "",
    "DB_PATH": "catalogo.db",
    "BATCH_SIZE": "10",
    "API_SLEEP": "2",
    "DAEMON_INTERVAL": "300",  # seconds between checks (5 min default)
    "PS_COMPAT_81": "1",  # PrestaShop 8.1 PUT workarounds (strip attrs, drop assocs, force state)
    "PS_CREATE_FEATURES": "0",  # 1 = create missing features/values in PS; 0 = reuse existing only
    "PS_MPN_FIELD": "mpn",  # product model field in the API (mpn = 1.7+; use reference for 1.6)
}

# ── DB-backed config (overrides .env) ──────────────────────────────────
_DB_CACHE: dict[str, str] | None = None


def _load_db_config() -> dict[str, str]:
    global _DB_CACHE
    if _DB_CACHE is not None:
        return _DB_CACHE
    db_path = os.getenv("DB_PATH", "catalogo.db")
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("SELECT clave, valor FROM config").fetchall()
            _DB_CACHE = {r[0]: r[1] for r in rows}
        except sqlite3.OperationalError:
            _DB_CACHE = {}
        finally:
            conn.close()
    except Exception:
        _DB_CACHE = {}
    return _DB_CACHE


def _get(key: str) -> str:
    """Return config value: DB table → .env → default."""
    db = _load_db_config()
    if key in db:
        return db[key]
    return os.getenv(key, DEFAULTS.get(key, ""))


def reload_db_config() -> None:
    """Force reload of DB-backed config (clears cache)."""
    global _DB_CACHE
    _DB_CACHE = None


def get_config(key: str, default: str = "") -> str:
    """Public getter — reads from DB cache, falls back to env/default."""
    return _get(key) or default


def set_config(key: str, value: str) -> None:
    """Write a config value to the DB ``config`` table and invalidate cache."""
    import os as _os
    db_path = _os.getenv("DB_PATH", "catalogo.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO config (clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()
    reload_db_config()


# ── Public config constants (used by all modules) ──────────────────────
DB_PATH = _get("DB_PATH")
PRESTASHOP_API_URL = _get("PRESTASHOP_API_URL").rstrip("/")
PRESTASHOP_API_KEY = _get("PRESTASHOP_API_KEY")
BATCH_SIZE = int(_get("BATCH_SIZE"))
API_SLEEP = int(_get("API_SLEEP"))
DAEMON_INTERVAL = int(_get("DAEMON_INTERVAL"))
