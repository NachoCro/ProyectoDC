"""Scrape official manufacturer websites for product enrichment (manual URL only).

``scrape_from_direct_url(url, product_id)`` accepts a human-verified
official URL, fetches the page, extracts structured data (JSON-LD, OG meta,
HTML tables), and persists the attributes into the local 3NF EAV tables.

Output is normalised to the same dict shape as ``icecat.py:_normalize``
so the rest of the pipeline (merge → approve → push) works unchanged.
"""

import json
import logging
import time

import requests
from bs4 import BeautifulSoup

from .config import API_SLEEP
from .db import get_connection

logger = logging.getLogger(__name__)


# ── Normalizer ──────────────────────────────────────────────────────────────


def _build_result(
    title: str = "",
    descripcion: str = "",
    marca: str = "",
    modelo: str = "",
    caracteristicas: list | None = None,
    imagen_url: str = "",
) -> dict:
    """Return a dict matching the Icecat ``_normalize`` shape."""
    return {
        "title": title,
        "descripcion": descripcion,
        "descripcion_corta": "",
        "marca": marca,
        "modelo": modelo,
        "resumen": "",
        "caracteristicas": caracteristicas or [],
        "imagen_url": imagen_url,
        "_source": "official_scraper",
    }


# ── Parsers ─────────────────────────────────────────────────────────────────


def _extract_json_ld(soup: BeautifulSoup) -> dict | None:
    """Extract product data from ``application/ld+json`` blocks.

    Looks for ``@type: Product`` and returns the normalized shape.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if item.get("@type") not in ("Product", "product"):
                continue
            name = item.get("name", "")
            desc = item.get("description", "")
            img = ""
            raw_img = item.get("image")
            if isinstance(raw_img, list):
                first = raw_img[0]
                img = first.get("url", first) if isinstance(first, dict) else first
            elif isinstance(raw_img, dict):
                img = raw_img.get("url", "")
            elif isinstance(raw_img, str):
                img = raw_img
            brand = ""
            raw_brand = item.get("brand")
            if isinstance(raw_brand, dict):
                brand = raw_brand.get("name", "")
            elif isinstance(raw_brand, str):
                brand = raw_brand
            modelo = item.get("mpn") or item.get("sku") or ""
            features: list[dict[str, str]] = []
            for prop in item.get("additionalProperty") or []:
                n = (prop.get("name") or "").strip()
                v = (prop.get("value") or "").strip()
                if n and v:
                    features.append({"nombre": n, "valor": v})
            return _build_result(
                title=name, descripcion=desc, marca=brand,
                modelo=modelo, caracteristicas=features, imagen_url=img,
            )
    return None


def _extract_meta(soup: BeautifulSoup) -> dict | None:
    """Extract title, description, and image from OG / meta tags."""
    og = {}
    for attr in ("property", "name"):
        for key, field in [("og:title", "title"), ("og:description", "desc"),
                           ("description", "desc"), ("og:image", "img")]:
            tag = soup.find("meta", attrs={attr: key})
            if tag and tag.get("content") and field not in og:
                og[field] = tag["content"].strip()
    title = og.get("title", "")
    if not title:
        t = soup.find("title")
        if t:
            title = t.get_text(strip=True)
    if not title:
        return None
    return _build_result(
        title=title,
        descripcion=og.get("desc", ""),
        imagen_url=og.get("img", ""),
    )


def _extract_tables(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract key-value pairs from HTML ``<table>`` technical spec blocks.

    Walks every ``<tr>`` with exactly two ``<td>``/``<th>`` cells and treats
    the first cell as the characteristic name and the second as the value.
    Filters out rows where either cell is empty or very short (< 2 chars).
    """
    features: list[dict[str, str]] = []
    seen: set[str] = set()

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) != 2:
                continue
            name = cells[0].get_text(strip=True)
            value = cells[1].get_text(strip=True)
            if not name or not value or len(name) < 2 or len(value) < 2:
                continue
            key_norm = name.lower().strip()
            if key_norm in seen:
                continue
            seen.add(key_norm)
            features.append({"nombre": name, "valor": value})

    return features


# ── EAV writer ──────────────────────────────────────────────────────────────


def _write_eav(pid: int, caracteristicas: list[dict]) -> None:
    """Persist scraped characteristics into local 3NF EAV tables."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM producto_caracteristicas WHERE id_prestashop = ?", (pid,)
        )
        for ch in caracteristicas:
            nombre = ch.get("nombre", "").strip()
            valor = ch.get("valor", "").strip()
            if not nombre or not valor:
                continue
            row_c = conn.execute(
                "SELECT id_caracteristica FROM caracteristicas WHERE nombre_caracteristica = ?",
                (nombre,),
            ).fetchone()
            if row_c:
                cid = row_c["id_caracteristica"]
            else:
                cur = conn.execute(
                    "INSERT INTO caracteristicas (nombre_caracteristica) VALUES (?)",
                    (nombre,),
                )
                cid = cur.lastrowid
            conn.execute(
                "INSERT OR REPLACE INTO producto_caracteristicas "
                "(id_prestashop, id_caracteristica, valor) VALUES (?, ?, ?)",
                (pid, cid, valor),
            )
        conn.commit()
    finally:
        conn.close()


# ── HTTP helper ─────────────────────────────────────────────────────────────

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
})


def _fetch(url: str) -> requests.Response | None:
    try:
        resp = _SESSION.get(url, timeout=30)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        logger.debug("  OFFICIAL  HTTP error %s: %s", url, exc)
        return None
    finally:
        time.sleep(API_SLEEP)


# ════════════════════════════════════════════════════════════════════════════
#  PUBLIC API — Manual URL enrichment (the only entry point)
# ════════════════════════════════════════════════════════════════════════════


def scrape_from_direct_url(url: str, product_id: int) -> dict | None:
    """Fetch a verified official URL, parse it, and persist to EAV tables.

    Parameters
    ----------
    url:
        Human-verified official manufacturer product page URL.
    product_id:
        PrestaShop product ID (``id_prestashop``).

    Returns
    -------
    dict | None
        Normalized product data dict (same shape as Icecat) on success,
        ``None`` if the fetch or parse fails.

    Side effects
    -------------
    - Writes characteristics into ``producto_caracteristicas`` (EAV).
    - Updates ``productos.icecat_json``, ``productos.marca``,
      ``productos.modelo``, ``productos.imagen_url``.
    - Clears ``productos.icecat_not_found`` for this product.
    - Appends an audit log entry.
    """
    logger.info("  MANUAL_URL  id=%d  fetching %s", product_id, url)

    resp = _fetch(url)
    if resp is None:
        logger.warning("  MANUAL_URL  id=%d  fetch failed for %s", product_id, url)
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # 1. Try JSON-LD (most structured)
    result = _extract_json_ld(soup)

    # 2. Fallback to OG / meta tags
    if not result:
        result = _extract_meta(soup)

    if not result:
        logger.warning("  MANUAL_URL  id=%d  no product data found at %s", product_id, url)
        return None

    # 3. Augment with HTML table specs (deduplicated merge)
    table_features = _extract_tables(soup)
    if table_features:
        existing_names = {
            ch["nombre"].lower().strip()
            for ch in (result.get("caracteristicas") or [])
        }
        for tf in table_features:
            if tf["nombre"].lower().strip() not in existing_names:
                result["caracteristicas"].append(tf)

    logger.info(
        "  MANUAL_URL  id=%d  extracted %d characteristics from %s",
        product_id, len(result.get("caracteristicas") or []), url,
    )

    # 4. Persist to DB
    conn = get_connection()
    try:
        marca = (result.get("marca") or "").strip()
        modelo = (result.get("modelo") or "").strip()
        imagen = (result.get("imagen_url") or "").strip() or None

        conn.execute(
            """UPDATE productos
               SET icecat_json     = ?,
                   marca           = COALESCE(NULLIF(?, ''), marca),
                   modelo          = COALESCE(NULLIF(?, ''), modelo),
                   imagen_url      = COALESCE(?, imagen_url),
                   icecat_not_found = 0,
                   estado_actualizacion = 'desactualizado',
                   fecha_sincronizacion = datetime('now')
               WHERE id_prestashop = ?""",
            (
                json.dumps(result, ensure_ascii=False),
                marca,
                modelo,
                imagen,
                product_id,
            ),
        )

        # Audit
        detalle = json.dumps({
            "source": "manual_url",
            "url": url,
            "marca": marca,
            "modelo": modelo,
            "characteristics": len(result.get("caracteristicas") or []),
        }, ensure_ascii=False)
        conn.execute(
            "INSERT INTO audit_log (id_producto, actor, accion, detalle) "
            "VALUES (?, ?, ?, ?)",
            (product_id, "admin", "scrape_manual_url", detalle),
        )
        conn.commit()
    finally:
        conn.close()

    # 5. Write EAV (outside the products conn — _write_eav opens its own)
    _write_eav(product_id, result.get("caracteristicas") or [])

    logger.info(
        "  MANUAL_URL  id=%d  saved %s %s (%d chars)",
        product_id, marca, modelo,
        len(result.get("caracteristicas") or []),
    )
    return result



