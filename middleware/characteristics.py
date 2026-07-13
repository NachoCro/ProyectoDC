"""Default characteristics templates and merge logic.

Reads ``default_characteristics.json`` (templates keyed by subcategory name)
and ``subcategory_mapping.json`` (DB subcategory → template key), then merges
Icecat characteristics with the default template.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent

_TEMPLATES: dict | None = None
_MAPPING: dict | None = None


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
    icecat_caracteristicas: list[dict],
    subcat_name: str,
) -> list[dict]:
    """Merge Icecat characteristics with the default template for *subcat_name*.

    Rules:
    1. Every entry from the template is included.
    2. If Icecat provides a matching characteristic (by name), its value is used.
    3. Extra Icecat entries not in the template are appended at the end.
    4. Names are compared case-insensitively.

    Returns a single merged list ready for ``sync_characteristics_as_features``.
    """
    template = get_template(subcat_name)
    if not template:
        return icecat_caracteristicas

    # Build a lookup of Icecat values by lowercased name (first wins)
    icecat_by_name: dict[str, str] = {}
    for ch in icecat_caracteristicas:
        nombre = (ch.get("nombre") or "").strip()
        valor = (ch.get("valor") or "").strip()
        if nombre and nombre.lower() not in icecat_by_name:
            icecat_by_name[nombre.lower()] = valor

    merged: list[dict] = []
    seen: set[str] = set()

    for tpl in template:
        nombre = (tpl.get("nombre") or "").strip()
        if not nombre:
            continue
        key = nombre.lower()
        seen.add(key)

        valor = icecat_by_name.get(key, tpl.get("valor_default", ""))
        merged.append({"nombre": nombre, "valor": valor})

    # Append extra Icecat entries that weren't in the template
    for ch in icecat_caracteristicas:
        nombre = (ch.get("nombre") or "").strip()
        valor = (ch.get("valor") or "").strip()
        if nombre and nombre.lower() not in seen:
            seen.add(nombre.lower())
            merged.append({"nombre": nombre, "valor": valor})

    return merged
