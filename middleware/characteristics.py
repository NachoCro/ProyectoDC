"""Default characteristics templates and merge logic.

Reads ``default_characteristics.json`` (templates keyed by subcategory name)
and ``subcategory_mapping.json`` (DB subcategory → template key), then merges
product characteristics with the default template.
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent

_TEMPLATES: dict | None = None
_MAPPING: dict | None = None

_PLACEHOLDER_RE = re.compile(r"\{\{.*\}\}|\[\[.*\]\]|\$\{.*\}")


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
