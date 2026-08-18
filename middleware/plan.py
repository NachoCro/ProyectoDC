"""Plan de trabajo — objetivo de subcategoría + cantidad por ciclo.

Permite decir "hoy quiero procesar 100 notebooks":

1. **Plan activo** (config ``plan_subcategoria`` + ``plan_cantidad``): filtro
   permanente que se aplica a cada corrida del pipeline hasta que se cambie
   desde la Admin UI.
2. **Agenda semanal** (config ``plan_semana``, JSON): por día de la semana
   (0=lunes … 6=domingo) qué subcategoría y cuántos productos procesar.  Si
   el día actual tiene plan, gana sobre el plan activo.

Las **opciones avanzadas** del plan son globales (aplican al plan efectivo del
día, venga del plan activo o de la agenda semanal) y se guardan en las claves
``plan_scope``, ``plan_modo``, ``plan_skip_extract`` y ``plan_dry_run``:

- ``plan_scope``: ``"inactive"`` (default) | ``"active"`` | ``"both"`` — qué
  catálogo barrer en la extracción.
- ``plan_modo``: ``"publicar"`` (default) | ``"preparar"`` — en ``"preparar"``
  el enriquecimiento guarda la propuesta sin tocar PrestaShop
  (``estado_actualizacion = 'pendiente_revision'``).
- ``plan_skip_extract``: ``"1"`` saltea la fase de extracción (solo enriquecer).
- ``plan_dry_run``: ``"1"`` simula (no escribe en BD ni PrestaShop).

Los valores se leen frescos de la tabla ``config`` en cada llamada (igual que
``config.api_timeout``) para que un cambio desde la UI aplique al daemon en
marcha sin reiniciarlo.
"""

import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher

WEEKDAYS = [
    ("lunes", 0),
    ("martes", 1),
    ("miércoles", 2),
    ("jueves", 3),
    ("viernes", 4),
    ("sábado", 5),
    ("domingo", 6),
]

_KEYS = (
    "plan_subcategoria", "plan_cantidad", "plan_semana",
    "plan_scope", "plan_modo", "plan_skip_extract", "plan_dry_run",
)

_VALID_SCOPES = ("inactive", "active", "both")
_VALID_MODOS = ("publicar", "preparar")


# ── similitud por nombre ────────────────────────────────────────────────
# Selección de productos por tipo de producto: se matchea el texto objetivo
# contra el NOMBRE del producto por similitud de palabras (no por subcategoría
# exacta).  Ej: tipo "MONITORES" alcanza a "Monitor LED 24" y tipo
# "MOTOSIERRAS" alcanza a "Motosierra a gasolina".

_STOPWORDS = {
    "PARA", "CON", "LOS", "LAS", "DEL", "DE", "EL", "LA", "EN", "Y",
    "O", "A", "AL", "UNA", "UN", "UNAS", "UNOS", "POR", "QUE", "SIN",
    "COMO", "SE", "SU", "SUS", "ES", "SON", "LE", "LO", "MAS", "MÁS",
    "ETC", "TIPO", "PRODUCTO",
    # Palabras genéricas de catálogo: describen la tienda, no el tipo de
    # producto.  "repuestos motosierra" no debe exigir que el nombre del
    # producto contenga "REPUESTOS" (ninguno lo tiene) — solo "MOTOSIERRA".
    "KIT", "REPUESTO", "REPUESTOS", "ACCESORIO", "ACCESORIOS",
    "PIEZA", "PIEZAS", "PARTE", "PARTES", "ARTICULO", "ARTICULOS",
    "INSUMO", "INSUMOS", "RECAMBIO", "RECAMBIOS", "AUTOPARTES",
}


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def significant_tokens(text: str) -> list[str]:
    """Términos significativos de *text* (sin acentos, en mayúsculas).

    Se descartan palabras cortas (< 3 chars) y stopwords gramaticales.
    Ej: "MOTOSIERRAS A GASOLINA" → ["MOTOSIERRAS", "GASOLINA"].
    """
    norm = _strip_accents(text or "").upper()
    tokens = [t for t in re.split(r"[^A-Z0-9]+", norm) if len(t) >= 3]
    return [t for t in tokens if t not in _STOPWORDS]


def _token_similar(a: str, b: str) -> bool:
    """¿Los tokens *a* y *b* representan la misma palabra?

    Igualdad exacta, variantes morfológicas (singular/plural, sufijos como
    -ado/-es), semejanza con prefijo largo compartido o contención (ej:
    MONITORES ↔ MONITOR).

    El ratio de ``SequenceMatcher`` por sí solo es poco fiable: "BOMBIN" y
    "BOBINA" dan 0.83 y son piezas distintas.  Por eso todo match de
    semejanza exige además un prefijo compartido.
    """
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    n = len(shorter)

    # Variante morfológica: la palabra corta es prefijo de la larga con un
    # sufijo corto (CABLE → CABLEADO, MOTOSIERRA → MOTOSIERRAS).
    if n >= 4 and abs(len(a) - len(b)) <= 3 and longer.startswith(shorter):
        return True

    # Semejanza con prefijo largo compartido (typos, reordenamientos leves).
    prefix = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), n)
    if (
        prefix >= 3
        and prefix >= n - 1
        and SequenceMatcher(None, a, b).ratio() >= 0.8
    ):
        return True

    # Contención: la palabra corta está completa dentro de la larga.
    return n >= 6 and shorter in longer


def matches_name(target: str, product_name: str) -> bool:
    """¿Es *product_name* similar al texto objetivo (tipo de producto)?

    Regla: cada término significativo del objetivo (sin stopwords ni palabras
    genéricas de catálogo como "repuestos") debe aparecer (exacto o parecido)
    en el nombre del producto.  Si el objetivo no tiene términos
    significativos (acrónimos cortos como "TV", o todo stopwords como
    "tipo de"), se usa coincidencia de subcadena con **límite de palabra**:
    "TV" alcanza a "SMART TV 55" pero no a "CCTV" (donde "TV" es parte de
    otra palabra).
    """
    tokens = significant_tokens(target)
    name_norm = _strip_accents(product_name or "").upper()
    if not tokens:
        needle = _strip_accents(target or "").upper()
        if not needle:
            return False
        return (
            re.search(rf"(?<![A-Z0-9]){re.escape(needle)}(?![A-Z0-9])", name_norm)
            is not None
        )
    name_tokens = set(re.split(r"[^A-Z0-9]+", name_norm))
    return all(any(_token_similar(t, nt) for nt in name_tokens) for t in tokens)


def _read(key: str) -> str:
    try:
        conn = sqlite3.connect(os.getenv("DB_PATH", "catalogo.db"))
        try:
            row = conn.execute(
                "SELECT valor FROM config WHERE clave = ?", (key,)
            ).fetchone()
            return row[0] if row else ""
        finally:
            conn.close()
    except Exception:
        return ""


def _write(key: str, value: str) -> None:
    try:
        conn = sqlite3.connect(os.getenv("DB_PATH", "catalogo.db"))
        try:
            conn.execute(
                "INSERT INTO config (clave, valor) VALUES (?, ?) "
                "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    try:
        from .config import reload_db_config
        reload_db_config()
    except Exception:
        pass


def _parse_int(raw, default: int | None = None) -> int | None:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


# ── plan activo ────────────────────────────────────────────────────────

def set_active(subcategoria: str, cantidad: str) -> None:
    """Guardar el plan activo (``""`` limpia el valor)."""
    _write("plan_subcategoria", (subcategoria or "").strip())
    _write("plan_cantidad", (cantidad or "").strip())


def get_active_plan() -> dict | None:
    """Plan activo ``{'subcategoria': str|None, 'cantidad': int|None}`` o None."""
    sub = _read("plan_subcategoria").strip()
    cant = _parse_int(_read("plan_cantidad"))
    if not sub and not cant:
        return None
    return {"subcategoria": sub or None, "cantidad": cant}


# ── agenda semanal ─────────────────────────────────────────────────────

def set_weekly(weekly: dict) -> None:
    """Guardar la agenda semanal: ``{day: {'subcategoria': str, 'cantidad': str}}``."""
    _write("plan_semana", json.dumps(weekly, ensure_ascii=False))


def get_weekly() -> dict[int, dict]:
    """Agenda semanal ``{0: {'subcategoria': ..., 'cantidad': int|None}, ...}``."""
    raw = _read("plan_semana")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    out: dict[int, dict] = {}
    for k, v in (data or {}).items():
        try:
            day = int(k)
        except (TypeError, ValueError):
            continue
        if isinstance(v, dict):
            out[day] = {
                "subcategoria": (v.get("subcategoria") or "").strip() or None,
                "cantidad": _parse_int(v.get("cantidad")),
            }
    return out


# ── plan efectivo (hoy) ────────────────────────────────────────────────

def get_today_plan() -> dict | None:
    """Plan que aplica hoy: agenda semanal si el día tiene plan, si no, plan activo."""
    day_plan = get_weekly().get(datetime.now().weekday())
    if day_plan and (day_plan.get("subcategoria") or day_plan.get("cantidad")):
        return day_plan
    active = get_active_plan()
    if active and (active.get("subcategoria") or active.get("cantidad")):
        return active
    return None


def effective_cantidad(default: int) -> int:
    """Cantidad de productos a procesar por ciclo (plan → default)."""
    plan = get_today_plan()
    if plan and plan.get("cantidad"):
        return plan["cantidad"]
    return default


def effective_subcategoria() -> str | None:
    """Texto objetivo de hoy (tipo de producto), o None."""
    plan = get_today_plan()
    if plan:
        return plan.get("subcategoria") or None
    return None


# ── opciones avanzadas del plan (globales, aplican al plan efectivo) ───

def set_options(scope: str = "", modo: str = "", skip_extract: bool = False,
                dry_run: bool = False) -> None:
    """Guardar las opciones avanzadas del plan (``""`` deja el default)."""
    _write("plan_scope", (scope or "").strip())
    _write("plan_modo", (modo or "").strip())
    _write("plan_skip_extract", "1" if skip_extract else "0")
    _write("plan_dry_run", "1" if dry_run else "0")


def get_options() -> dict:
    """Opciones avanzadas actuales del plan (para la UI)."""
    return {
        "scope": _read("plan_scope").strip(),
        "modo": _read("plan_modo").strip(),
        "skip_extract": _read("plan_skip_extract").strip() == "1",
        "dry_run": _read("plan_dry_run").strip() == "1",
    }


def effective_scope(default: str = "inactive") -> str:
    """Qué catálogo barrer en la extracción (plan → default)."""
    scope = _read("plan_scope").strip()
    return scope if scope in _VALID_SCOPES else default


def effective_modo(default: str = "publicar") -> str:
    """Modo de enriquecimiento (plan → default): publicar | preparar."""
    modo = _read("plan_modo").strip()
    return modo if modo in _VALID_MODOS else default


def effective_skip_extract() -> bool:
    """Si el plan pide saltar la extracción (solo enriquecer)."""
    return _read("plan_skip_extract").strip() == "1"


def effective_dry_run() -> bool:
    """Si el plan pide simulación (no escribir en BD ni PrestaShop)."""
    return _read("plan_dry_run").strip() == "1"


# ── helpers de selección (para extract / enrich) ───────────────────────

def list_subcategorias(conn) -> list[str]:
    """Nombres de subcategorías (para el selector de la UI)."""
    return [
        row["nombre_subcategoria"]
        for row in conn.execute(
            "SELECT nombre_subcategoria FROM subcategorias ORDER BY nombre_subcategoria"
        ).fetchall()
    ]


def describe_plan(conn=None) -> str:
    """Descripción legible del plan de hoy (para logs / dashboard)."""
    plan = get_today_plan()
    if not plan:
        return "sin plan (todas las categorías)"
    return describe_target(
        conn, plan.get("subcategoria") or None, plan.get("cantidad") or None
    )


def describe_target(conn, subcategoria, cantidad) -> str:
    """Descripción legible de un objetivo cualquiera (plan o ejecución única).

    La selección se hace por similitud del nombre del producto con el texto
    del objetivo (``matches_name``).
    """
    parts = []
    if subcategoria:
        parts.append(subcategoria)
        parts.append("por similitud con el nombre del producto")
    if cantidad:
        parts.append(f"{cantidad} por ciclo")
    return ", ".join(parts) or "sin plan (todas las categorías)"
