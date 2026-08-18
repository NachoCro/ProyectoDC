"""Default characteristics templates and merge logic.

Reads ``default_characteristics.json`` (templates keyed by subcategory name)
and ``subcategory_mapping.json`` (DB subcategory → template key), then merges
product characteristics with the default template.
"""

import json
import logging
import re
from pathlib import Path

from .spec_extractors import normalize_text

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent

_TEMPLATES: dict | None = None
_MAPPING: dict | None = None

_PLACEHOLDER_RE = re.compile(r"\{\{.*\}\}|\[\[.*\]\]|\$\{.*\}")

# Excel-cell style for description values.
_MAX_NOMBRE_LEN = 60
_ACCENTS = "áéíóúüñàèìòùâêîôûç"
_MEASUREMENT_RE = re.compile(r"\d\s*[A-Za-zµ°²³×]")


def _is_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(text or ""))


def _clean_characteristics(
    caracteristicas: list[dict],
) -> list[dict]:
    """Drop characteristics whose name or value is JS template garbage.

    Samsung and other sites embed Knockout/Angular templates in the DOM
    (``{{upgrade.yesAttr.text}}`` etc.) that generic scrapers pick up as
    specs.  These are never valid PrestaShop features.
    """
    cleaned: list[dict] = []
    for ch in caracteristicas:
        nombre = (ch.get("nombre") or "").strip()
        valor = (ch.get("valor") or "").strip()
        if _is_placeholder(nombre) or _is_placeholder(valor):
            continue
        cleaned.append({"nombre": nombre, "valor": valor})
    return cleaned


def _load_json(name: str) -> dict:
    path = _BASE / name
    if not path.exists():
        logger.warning("%s not found", path)
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get_templates() -> dict:
    global _TEMPLATES
    if _TEMPLATES is None:
        _TEMPLATES = _load_json("default_characteristics.json")
    return _TEMPLATES


def _get_mapping() -> dict:
    global _MAPPING
    if _MAPPING is None:
        _MAPPING = _load_json("subcategory_mapping.json")
    return _MAPPING


def get_template(subcat_name: str) -> list[dict]:
    """Return the default-characteristic list for a DB subcategory name.

    Uses ``subcategory_mapping.json`` to resolve *subcat_name* to a template
    key, then looks it up in ``default_characteristics.json``.
    Returns an empty list when no template applies.
    """
    mapping = _get_mapping()
    templates = _get_templates()

    template_key = mapping.get(subcat_name)
    if not template_key:
        return []
    return templates.get(template_key, [])


def merge_characteristics(
    proposed_caracteristicas: list[dict],
    subcat_name: str,
) -> list[dict]:
    """Merge characteristics with the default template for *subcat_name*.

    Rules:
    1. Every entry from the template is included.
    2. If a matching characteristic is provided (by name), its value is used.
    3. Extra entries not in the template are appended at the end.
    4. Names are compared case-insensitively.

    Returns a single merged list ready for ``sync_characteristics_as_features``.
    """
    template = get_template(subcat_name)
    if not template:
        return _clean_characteristics(proposed_caracteristicas)

    # Build a lookup of proposed values by lowercased name (first wins)
    proposed_by_name: dict[str, str] = {}
    for ch in proposed_caracteristicas:
        nombre = (ch.get("nombre") or "").strip()
        valor = (ch.get("valor") or "").strip()
        if not nombre or _is_placeholder(nombre) or _is_placeholder(valor):
            continue
        if nombre.lower() not in proposed_by_name:
            proposed_by_name[nombre.lower()] = valor

    merged: list[dict] = []
    seen: set[str] = set()

    for tpl in template:
        nombre = (tpl.get("nombre") or "").strip()
        if not nombre:
            continue
        key = nombre.lower()
        seen.add(key)

        valor = proposed_by_name.get(key, tpl.get("valor_default", ""))
        merged.append({"nombre": nombre, "valor": valor})

    # Append extra entries that weren't in the template
    for ch in proposed_caracteristicas:
        nombre = (ch.get("nombre") or "").strip()
        valor = (ch.get("valor") or "").strip()
        if not nombre or _is_placeholder(nombre) or _is_placeholder(valor):
            continue
        if nombre.lower() not in seen:
            seen.add(nombre.lower())
            merged.append({"nombre": nombre, "valor": valor})

    return merged


def _should_uppercase(value: str) -> bool:
    """Return True when *value* looks like a short technical/acronym value.

    Short values with no accented letters and no prose words are uppercased
    (``si`` → ``SI``, ``cable`` → ``CABLE``), matching Excel-cell style.
    Measurements (``44mm``, ``1.4 GHz``), accented Spanish words (``Sí``)
    and prose-like values (``Samsung Exynos W920``, ``Gorilla Glass DX+``)
    are left untouched.
    """
    if not value or len(value) > 30:
        return False
    low = value.lower()
    if any(c in low for c in _ACCENTS):
        return False
    if _MEASUREMENT_RE.search(low):
        return False
    for token in value.split():
        t = token.strip(".,:;()[]\"'“”‘’")
        if t.isalpha() and not t.isupper() and len(t) >= 6:
            return False
    return True


def format_excel_value(value: str) -> str:
    """Format a characteristic value with Excel-cell style.

    - Collapses whitespace/newlines to single spaces.
    - Normalizes option-list separators (``|`` and ``/``) to `` / `` —
      except ``MB/S``-style unit expressions.
    - Uppercases short technical values/acronyms (see :func:`_should_uppercase`).
    """
    if not value:
        return value
    value = normalize_text(value)
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\s*\|\s*", " / ", value)
    if not _MEASUREMENT_RE.search(value.lower()):
        value = re.sub(r"\s*/\s*", " / ", value)
    value = value.strip()
    if _should_uppercase(value):
        value = value.upper()
    return value


def format_characteristic_name(nombre: str) -> str:
    """Truncate absurdly long characteristic names for the description."""
    nombre = (nombre or "").strip()
    if len(nombre) > _MAX_NOMBRE_LEN:
        return nombre[:_MAX_NOMBRE_LEN - 1].rstrip() + "…"
    return nombre


def build_description_html(caracteristicas: list[dict]) -> str:
    """Build the ``<div class="caracteristicas">`` description from a list.

    Each characteristic becomes a ``*nombre*: valor`` line following
    Excel-cell style: option lists separated by `` / ``, short technical
    values uppercased, duplicate lines dropped and giant names truncated.
    """
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for ch in caracteristicas:
        nombre = (ch.get("nombre") or "").strip()
        valor = (ch.get("valor") or "").strip()
        if not nombre or not valor:
            continue
        if _is_placeholder(nombre) or _is_placeholder(valor):
            continue
        nombre = format_characteristic_name(nombre)
        valor = format_excel_value(valor)
        key = (nombre.lower(), valor.lower())
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            f"<p><strong>{normalize_text(nombre)}:</strong> {normalize_text(valor)}</p>"
        )
    if not lines:
        return ""
    return f'<div class="caracteristicas">{"".join(lines)}</div>'
