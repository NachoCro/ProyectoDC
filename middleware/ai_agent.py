"""AI agent for official product data extraction (last resort).

Uses DuckDuckGo search (free) to find official product pages, fetches
the HTML, and extracts structured data using JSON-LD, OG meta tags,
and HTML table parsing.

This is the last resort in the enrichment cascade, tried only after
brand site search fails.
"""

import logging
import re
import time

import requests
from bs4 import BeautifulSoup

from .config import API_SLEEP

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
})


def _search_web(query: str, max_results: int = 5) -> list[dict]:
    """Search DuckDuckGo and return results with title, href."""
    try:
        from ddgs import DDGS
        return DDGS().text(query, max_results=max_results)
    except Exception as exc:
        logger.warning("  AI_AGENT  search failed: %s", exc)
        return []


def _fetch(url: str) -> str | None:
    """Fetch a URL and return the HTML text."""
    try:
        resp = _SESSION.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        logger.debug("  AI_AGENT  fetch failed %s: %s", url, exc)
        return None
    finally:
        time.sleep(API_SLEEP)


def _extract_json_ld(soup: BeautifulSoup) -> dict | None:
    """Extract product data from JSON-LD blocks."""
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string
        if not raw:
            continue
        try:
            import json
            parsed = json.loads(raw)
        except Exception:
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if item.get("@type") not in ("Product", "product"):
                continue
            name = item.get("name", "")
            desc = item.get("description", "")
            img = ""
            raw_img = item.get("image")
            if isinstance(raw_img, list) and raw_img:
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
            features = []
            for prop in item.get("additionalProperty") or []:
                n = (prop.get("name") or "").strip()
                v = (prop.get("value") or "").strip()
                if n and v:
                    features.append({"nombre": n, "valor": v})
            return {
                "title": name,
                "descripcion": desc,
                "descripcion_corta": "",
                "marca": brand,
                "modelo": modelo,
                "resumen": "",
                "caracteristicas": features,
                "imagen_url": img,
                "_source": "ai_agent_jsonld",
            }
    return None


def _extract_meta(soup: BeautifulSoup) -> dict | None:
    """Extract from OG / meta tags."""
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
    return {
        "title": title,
        "descripcion": og.get("desc", ""),
        "descripcion_corta": "",
        "marca": "",
        "modelo": "",
        "resumen": "",
        "caracteristicas": [],
        "imagen_url": og.get("img", ""),
        "_source": "ai_agent_meta",
    }


def _extract_tables(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract key-value pairs from HTML tables."""
    features = []
    seen = set()
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


def _parse_page(html: str) -> dict | None:
    """Try all parsers on a page and return the best result."""
    soup = BeautifulSoup(html, "lxml")

    result = _extract_json_ld(soup)
    if not result:
        result = _extract_meta(soup)
    if not result:
        return None

    table_features = _extract_tables(soup)
    if table_features:
        existing = {ch["nombre"].lower() for ch in result.get("caracteristicas") or []}
        for tf in table_features:
            if tf["nombre"].lower() not in existing:
                result["caracteristicas"].append(tf)

    return result


def enrich_with_ai(marca: str, mpn: str, nombre: str) -> dict | None:
    """Search the web and scrape official product data (no LLM).

    Parameters
    ----------
    marca:
        Brand name (e.g. "Samsung").
    mpn:
        Manufacturer part number (e.g. "SM-G991B").
    nombre:
        Product name from PrestaShop (e.g. "Galaxy S21 5G").

    Returns
    -------
    dict | None
        Normalized product data on success, ``None`` if nothing found.
    """
    query = f"{marca} {mpn} {nombre} especificaciones".strip()
    logger.info("  AI_AGENT  searching: %s", query)

    results = _search_web(query, max_results=5)
    if not results:
        logger.info("  AI_AGENT  no search results for: %s", query)
        return None

    for r in results:
        url = r.get("href") or r.get("link") or ""
        title = r.get("title", "")
        if not url or not url.startswith("http"):
            continue

        logger.info("  AI_AGENT  trying: %s (%s)", url, title[:60])

        html = _fetch(url)
        if not html or len(html) < 500:
            continue

        data = _parse_page(html)
        if data and (data.get("caracteristicas") or data.get("descripcion")):
            if not data.get("marca"):
                data["marca"] = marca
            if not data.get("modelo"):
                data["modelo"] = mpn
            logger.info(
                "  AI_AGENT  extracted %d characteristics from %s",
                len(data.get("caracteristicas") or []), url,
            )
            return data

    logger.info("  AI_AGENT  no product data found for %s %s", marca, mpn)
    return None
