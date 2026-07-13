"""Load product descriptions from 003 DESCRIPCIONES.xlsx.

Reads the DESCRIPCIONES sheet, maps DB subcategory names to Excel entries
via ``descripcion_mapping.json``, and provides lookup functions.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent
_EXCEL_PATH = _BASE / "003 DESCRIPCIONES.xlsx"

_LOADED: dict[str, dict[str, str]] | None = None


def _load_mapping() -> dict:
    path = _BASE / "descripcion_mapping.json"
    if not path.exists():
        logger.warning("descripcion_mapping.json not found")
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_excel() -> dict[str, dict[str, str]]:
    """Load descriptions from the Excel DESCRIPCIONES sheet.

    Returns ``{excel_subcat_name_lower: {"descripcion": …, "descripcion_corta": …}}``
    """
    try:
        import openpyxl
    except ImportError:
        logger.warning("openpyxl not installed — cannot load Excel descriptions")
        return {}

    if not _EXCEL_PATH.exists():
        logger.warning("003 DESCRIPCIONES.xlsx not found at %s", _EXCEL_PATH)
        return {}

    wb = openpyxl.load_workbook(_EXCEL_PATH, data_only=True, read_only=True)
    ws = wb["DESCRIPCIONES"]
    result: dict[str, dict[str, str]] = {}

    for row in ws.iter_rows(min_row=2, values_only=True):
        subcat = row[1]
        desc = row[3]
        short_desc = row[5] if len(row) > 5 else None
        if not subcat:
            continue
        key = str(subcat).strip().lower()
        result[key] = {
            "descripcion": str(desc).strip() if desc else "",
            "descripcion_corta": str(short_desc).strip() if short_desc else "",
        }

    wb.close()
    logger.info("Loaded %d descriptions from Excel", len(result))
    return result


def _get_all() -> dict[str, dict[str, str]]:
    global _LOADED
    if _LOADED is None:
        _LOADED = _load_excel()
    return _LOADED


def get_description(subcat_name: str) -> dict[str, str]:
    """Return ``{"descripcion": …, "descripcion_corta": …}`` for a DB subcategory.

    Falls back to empty strings if no mapping or Excel entry exists.
    """
    mapping = _load_mapping()
    excel_key = mapping.get(subcat_name, "")
    if not excel_key:
        return {"descripcion": "", "descripcion_corta": ""}

    all_descs = _get_all()
    entry = all_descs.get(excel_key.lower())
    if not entry:
        return {"descripcion": "", "descripcion_corta": ""}

    return dict(entry)
