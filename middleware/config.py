import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()

# ── Env defaults ───────────────────────────────────────────────────────
DEFAULTS = {
    "PRESTASHOP_API_URL": "",
    "PRESTASHOP_API_KEY": "",
    "ICECAT_USERNAME": "",
    "ICECAT_API_TOKEN": "",
    "DB_PATH": "catalogo.db",
    "BATCH_SIZE": "10",
    "API_SLEEP": "2",
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
    """Force reload from DB (call after saving settings)."""
    global _DB_CACHE
    _DB_CACHE = None


# ── Public config constants (used by all modules) ──────────────────────
DB_PATH = _get("DB_PATH")
PRESTASHOP_API_URL = _get("PRESTASHOP_API_URL").rstrip("/")
PRESTASHOP_API_KEY = _get("PRESTASHOP_API_KEY")
ICECAT_USERNAME = _get("ICECAT_USERNAME")
ICECAT_API_TOKEN = _get("ICECAT_API_TOKEN")
BATCH_SIZE = int(_get("BATCH_SIZE"))
API_SLEEP = int(_get("API_SLEEP"))
