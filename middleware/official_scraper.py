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
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import API_SLEEP
from .db import get_connection, mark_icecat_not_found

logger = logging.getLogger(__name__)

SELENIUM_TIMEOUT = 12  # seconds to wait for spec tables to render
BRAND_SEARCH_TIMEOUT = 10  # seconds to wait for search result cards

# ── Brand search mapping ────────────────────────────────────────────────────

_BRANDS_JSON = Path(__file__).resolve().parent.parent / "brands_mapping.json"
_BRANDS_MAP: dict = {}
try:
    _BRANDS_MAP = json.loads(_BRANDS_JSON.read_text(encoding="utf-8"))
except FileNotFoundError:
    pass


# ── Brand inference from product name ────────────────────────────────────────


def _infer_brand_from_name(nombre: str) -> str | None:
    """Infer the product brand from its name by matching against known brands.

    Scans the product name (case-insensitive) for any brand key present in
    ``brands_mapping.json``.  Returns the matched brand key (lowercase) or
    ``None`` if no known brand is found.
    """
    if not nombre:
        return None
    nombre_lower = nombre.lower()
    for brand_key in _BRANDS_MAP:
        if brand_key in nombre_lower:
            return brand_key
    return None


# ── Name cleanup for search ─────────────────────────────────────────────────


# Common prefixes/suffixes to remove from product names before searching.
# These are generic descriptors that don't help with search and may confuse
# brand site search engines.
_NOISE_WORDS = {
    # Spanish product types
    "impresora", "imp", "monitor", "televisor", "tv", "audifonos", "audífonos",
    "parlante", "bocina", "cargador", "cable", "adaptador", "mouse", "teclado",
    "disco", "memoria", "ram", "procesador", "tarjeta", "fuente",
    # English product types
    "printer", "monitor", "speaker", "charger", "cable", "adapter",
    "keyboard", "mouse", "drive", "memory", "card",
    # Technology descriptors
    "laser", "inkjet", "led", "lcd", "oled", "qled", "uhd", "fhd", "hd",
    "4k", "8k", "smart", "wifi", "bluetooth",
    "无线", "有线",  # Chinese wireless/wired
    # Function descriptors
    "mf", "mfp", " multifuncion", " multifuncional", "multifunction",
    "monocromo", "monocromática", "monocromatico", "mono",
    "color", "blanco", "negro", "gris",
    # Brand names (will be removed separately)
    "brother", "pantum", "samsung", "lg", "sony", "canon", "epson", "hp",
    "dell", "lenovo", "asus", "acer", "msi", "apple", "huawei", "xiaomi",
    "logitech", "razer", "corsair", "hyperx", "steelseries",
    # Other common noise
    "nuevo", "nueva", "original", "oferta", "promocion", "promoción",
    "kit", "pack", "bundle", "set",
}


def _clean_name_for_search(nombre: str, marca: str = "") -> str:
    """Clean up a product name for use as a search query.

    Removes generic descriptors, brand names, and common noise words to
    leave only the model number/identifier that brand sites can match.

    Examples:
        "IMPRESORA BROTHER DCP-1617NW" → "DCP-1617NW"
        "IMP PANTUM MF LASER MONO BM5100FDW" → "BM5100FDW"
        "Samsung Monitor Smart 32" M5 M50F FHD" → "M50F"
        "LG OLED55C4PSA 55" 4K Smart TV" → "OLED55C4PSA"
    """
    if not nombre:
        return nombre

    import re

    # Start with the full name
    cleaned = nombre

    # Remove brand name if provided
    if marca:
        cleaned = re.sub(re.escape(marca), "", cleaned, flags=re.IGNORECASE)

    # Remove size patterns: 32", 55", 27", 32\u201d, etc.
    cleaned = re.sub(r'\d+["\u201d\u2019\u2018]', '', cleaned)

    # Remove pure numbers that look like sizes (2-3 digits)
    cleaned = re.sub(r'\b\d{2,3}\b', '', cleaned)

    # Remove noise words
    words = cleaned.split()
    filtered = []
    for word in words:
        word_clean = word.lower().strip(".,;:()[]{}!?\"'")
        # Skip if it's a noise word
        if word_clean in _NOISE_WORDS:
            continue
        # Skip size suffixes like , " or '"'
        if word in ('"', '"', "'", "''", ",", ":"):
            continue
        # Skip standalone single characters that are likely noise
        if len(word) == 1 and not word.isalnum():
            continue
        filtered.append(word)

    result = " ".join(filtered).strip()

    # Clean up extra spaces
    result = re.sub(r'\s+', ' ', result).strip()

    # If we removed too much, fall back to the original name
    if len(result) < 3:
        return nombre.strip()

    return result


# ── Selenium driver factory ──────────────────────────────────────────────────


def _create_driver() -> webdriver.Chrome:
    """Return a headless Chrome WebDriver configured for scraping."""
    opts = ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=opts)


# ── Brand site search ────────────────────────────────────────────────────────


def _search_brand_site(marca: str, mpn: str, product_name: str, pid: int = 0) -> str | None:
    """Search the brand's official site for a product and return the first result URL.

    Uses the full *product_name* as the search query by substituting the
    ``{mpn}`` placeholder in ``brands_mapping.json`` with the product name.
    No MPN validation is performed — the search is purely name-based.

    Returns the absolute URL of the first matching product card, or ``None``
    if the brand has no search config, the search yields no results,
    or Selenium fails.
    """
    key = marca.strip().lower()
    entry = _BRANDS_MAP.get(key)
    if not entry:
        return None

    search_tpl = entry.get("search_url", "")
    selector = entry.get("result_selector", "")
    if not search_tpl or not selector:
        return None

    # Clean the product name for search — remove generic descriptors,
    # brand names, and common noise to leave only the model number.
    cleaned_name = _clean_name_for_search(product_name, marca)
    logger.info(
        "  BRAND_SEARCH  searching %s for cleaned_name=%r (original=%r, MPN=%s)",
        key, cleaned_name, product_name, mpn,
    )

    search_url = search_tpl.replace("{mpn}", cleaned_name)

    driver = None
    try:
        driver = _create_driver()
        driver.get(search_url)

        WebDriverWait(driver, BRAND_SEARCH_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )
        time.sleep(API_SLEEP)

        el = driver.find_element(By.CSS_SELECTOR, selector)
        href = el.get_attribute("href")
        if not href:
            logger.debug("  BRAND_SEARCH  first result has no href for %s %s", key, mpn)
            return None

        logger.info("  BRAND_SEARCH  found result — returning %s", href)
        return href
    except Exception as exc:
        logger.debug("  BRAND_SEARCH  %s %s failed: %s", key, mpn, exc)
        return None
    finally:
        if driver is not None:
            driver.quit()


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


def _extract_image(soup: BeautifulSoup, current_url: str = "") -> str:
    """Extract the main product image URL from the page.

    Tries multiple strategies in order:
    1. JSON-LD image (already handled elsewhere, but this is a standalone helper)
    2. OG image meta tag
    3. <img> tags with product-related classes/ids/alt text
    4. <img> in main content area with reasonable size
    """
    from urllib.parse import urljoin

    def _normalize_url(url: str) -> str:
        """Normalize relative URLs to absolute using current_url as base."""
        if not url or url.startswith("data:"):
            return url
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/") and current_url:
            return urljoin(current_url, url)
        return url

    # Strategy 1: OG image
    for attr in ("property", "name"):
        tag = soup.find("meta", attrs={attr: "og:image"})
        if tag and tag.get("content"):
            return _normalize_url(tag["content"].strip())

    # Strategy 2: <img> with product-related attributes
    product_img_selectors = [
        "[class*='product'] img[src]",
        "[class*='Product'] img[src]",
        "[id*='product'] img[src]",
        "[id*='Product'] img[src]",
        "[data-testid*='product'] img[src]",
        "[class*='gallery'] img[src]",
        "[class*='Gallery'] img[src]",
        "[class*='main-image'] img[src]",
        "[class*='hero'] img[src]",
        "[class*='detail'] img[src]",
    ]
    seen_srcs: set[str] = set()
    for selector in product_img_selectors:
        for img in soup.select(selector):
            src = img.get("src", "").strip()
            if not src or src in seen_srcs:
                continue
            # Skip tiny images (icons, spacers, etc.)
            width = img.get("width", "")
            height = img.get("height", "")
            try:
                if width and int(width) < 100:
                    continue
                if height and int(height) < 100:
                    continue
            except (ValueError, TypeError):
                pass
            # Skip data URIs and common icon patterns
            if src.startswith("data:") or any(
                skip in src.lower()
                for skip in ("icon", "logo", "avatar", "pixel", "spacer", "blank")
            ):
                continue
            seen_srcs.add(src)
            return _normalize_url(src)

    # Strategy 3: Any reasonably sized <img> in the page (last resort)
    for img in soup.find_all("img"):
        src = img.get("src", "").strip()
        if not src or src.startswith("data:"):
            continue
        if any(skip in src.lower() for skip in ("icon", "logo", "avatar", "pixel", "spacer", "blank")):
            continue
        # Check alt text for product hints
        alt = (img.get("alt") or "").lower()
        if any(kw in alt for kw in ("product", "producto", "image", "foto")):
            return _normalize_url(src)

    return ""


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


def _extract_brand_specs(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract specs from brand-specific dynamic containers.

    Many manufacturer sites (Samsung, LG, etc.) render specs via JS into
    custom component classes instead of standard ``<table>`` elements.
    This function tries a curated list of known selectors and returns the
    first set of results that yields at least one characteristic.
    """
    features: list[dict[str, str]] = []
    seen: set[str] = set()

    # ── Samsung: pdd32-product-spec components ────────────────────────────
    for item in soup.select(".pdd32-product-spec__content-item"):
        title_el = item.select_one(".pdd32-product-spec__content-item-title")
        desc_el = item.select_one(".pdd32-product-spec__content-item-desc")
        name = (title_el.get_text(strip=True) if title_el else "").strip()
        value = (desc_el.get_text(strip=True) if desc_el else "").strip()
        if not name or not value:
            continue
        key_norm = name.lower().strip()
        if key_norm in seen:
            continue
        seen.add(key_norm)
        features.append({"nombre": name, "valor": value})

    if features:
        return features

    # ── LG: .result-info__spec-list ───────────────────────────────────────
    for item in soup.select(".result-info__spec-list li, .pd-spec__item"):
        text = item.get_text(strip=True)
        if ":" in text:
            name, _, value = text.partition(":")
            name, value = name.strip(), value.strip()
            if name and value:
                key_norm = name.lower().strip()
                if key_norm not in seen:
                    seen.add(key_norm)
                    features.append({"nombre": name, "valor": value})

    if features:
        return features

    # ── Brother: .product-spec__item, .spec-table, #spec ──────────────────
    for item in soup.select(".product-spec__item, .spec-item, .specification-item"):
        name_el = item.select_one(".product-spec__label, .spec-label, .spec-name, dt, th")
        value_el = item.select_one(".product-spec__value, .spec-value, .spec-desc, dd, td")
        name = (name_el.get_text(strip=True) if name_el else "").strip()
        value = (value_el.get_text(strip=True) if value_el else "").strip()
        if not name or not value:
            continue
        key_norm = name.lower().strip()
        if key_norm in seen:
            continue
        seen.add(key_norm)
        features.append({"nombre": name, "valor": value})

    if features:
        return features

    # ── Pantum: .specs-block, .product-specs, .technical-specs ────────────
    for item in soup.select(".specs-block__item, .product-specs__item, .tech-spec__item"):
        name_el = item.select_one(".specs-block__label, .product-specs__label, .tech-spec__label")
        value_el = item.select_one(".specs-block__value, .product-specs__value, .tech-spec__value")
        name = (name_el.get_text(strip=True) if name_el else "").strip()
        value = (value_el.get_text(strip=True) if value_el else "").strip()
        if not name or not value:
            continue
        key_norm = name.lower().strip()
        if key_norm in seen:
            continue
        seen.add(key_norm)
        features.append({"nombre": name, "valor": value})

    if features:
        return features

    # ── Generic: .product-detail__specs, .detail-specs, .specs-table ──────
    for item in soup.select(".product-detail__specs li, .detail-specs li, .specs-table tr"):
        text = item.get_text(strip=True)
        if ":" in text:
            name, _, value = text.partition(":")
            name, value = name.strip(), value.strip()
            if name and value:
                key_norm = name.lower().strip()
                if key_norm not in seen:
                    seen.add(key_norm)
                    features.append({"nombre": name, "valor": value})

    if features:
        return features

    # ── Generic: dl/dt+dd pairs ───────────────────────────────────────────
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            name = dt.get_text(strip=True)
            value = dd.get_text(strip=True)
            if name and value and len(name) >= 2 and len(value) >= 2:
                key_norm = name.lower().strip()
                if key_norm not in seen:
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


# ── HTTP helper (kept for potential future use) ─────────────────────────────

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


# ── Category page detection ─────────────────────────────────────────────────


def _is_category_page(soup: BeautifulSoup, url: str) -> bool:
    """Detect if the page is a category/listing page rather than a product detail page.

    Returns True if the page looks like a category listing (multiple product cards,
    filters, pagination) rather than a single product detail page.
    """
    url_lower = url.lower()

    # URL patterns that indicate category pages
    category_url_patterns = [
        "/product-center", "/products", "/catalog", "/category",
        "/list", "/shop", "/store", "/collection", "/all",
        "?page=", "&page=", "/p-", "/page-",
        "/search/", "/buscar/",
    ]
    if any(pat in url_lower for pat in category_url_patterns):
        # But check if it's actually a product page with weird URL
        # If page has JSON-LD Product, it's a product page despite URL
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string
            if raw and '"Product"' in raw:
                return False
        return True

    # HTML-based detection: multiple product cards/links
    product_card_selectors = [
        "[class*='product-card']",
        "[class*='product-card']",
        "[class*='ProductCard']",
        "[class*='product-item']",
        "[class*='product-grid']",
        "[class*='product-list']",
        "[data-testid*='product-card']",
    ]
    for selector in product_card_selectors:
        cards = soup.select(selector)
        if len(cards) >= 3:  # 3+ product cards = likely category page
            return True

    # Check for filter/facet elements (common on category pages)
    filter_selectors = [
        "[class*='filter']",
        "[class*='Filter']",
        "[class*='facet']",
        "[class*='Facet']",
        "[class*='sidebar'] select",
    ]
    for selector in filter_selectors:
        if soup.select(selector):
            # Filters + multiple links = category page
            links = soup.find_all("a", href=True)
            product_links = [
                a for a in links
                if any(kw in (a.get("href") or "").lower()
                       for kw in ("/product", "/item", "/detail", "/p/"))
            ]
            if len(product_links) >= 3:
                return True

    # Heuristic: many product links but no JSON-LD Product = category page
    links = soup.find_all("a", href=True)
    product_link_count = sum(
        1 for a in links
        if any(kw in (a.get("href") or "").lower()
               for kw in ("/product", "/item", "/detail", "/p/"))
    )
    if product_link_count >= 5:
        # Check if page has JSON-LD Product (if not, it's likely a category)
        has_jsonld_product = False
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string
            if raw and '"Product"' in raw:
                has_jsonld_product = True
                break
        if not has_jsonld_product:
            return True

    return False


def _find_product_link_on_category(soup: BeautifulSoup, base_url: str) -> str | None:
    """Find the most relevant product link on a category/listing page.

    Looks for links that look like product detail pages and returns the first one.
    """
    from urllib.parse import urljoin

    links = soup.find_all("a", href=True)
    product_links = []

    for a in links:
        href = a.get("href", "")
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        full_url = urljoin(base_url, href).lower()
        # Look for product detail URL patterns
        if any(pat in full_url for pat in ("/product", "/item", "/detail", "/p/")):
            # Prefer links with product-related text
            text = a.get_text(strip=True).lower()
            if any(kw in text for kw in ("spec", "detail", "view", "more", "info")):
                return urljoin(base_url, href)
            product_links.append(urljoin(base_url, href))

    # Return first product-looking link
    return product_links[0] if product_links else None


# ════════════════════════════════════════════════════════════════════════════
#  PUBLIC API — Manual URL enrichment (the only entry point)
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════


def scrape_from_direct_url(url: str, product_id: int) -> dict | None:
    """Fetch a verified official URL, parse it, and persist to EAV tables.

    Uses a headless Chrome WebDriver to render JavaScript-heavy pages
    (Samsung, LG, etc.) before parsing the static HTML with BeautifulSoup.

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

    driver = None
    try:
        driver = _create_driver()
        driver.set_script_timeout(SELENIUM_TIMEOUT)
        driver.get(url)

        # Wait for technical spec tables or common spec containers to render.
        # Many brand sites inject specs via JS; wait up to SELENIUM_TIMEOUT.
        # Samsung uses .pdd32-product-spec__content-item for spec data.
        try:
            WebDriverWait(driver, SELENIUM_TIMEOUT).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR,
                     "table, .specs, .specifications, .tech-specs, "
                     ".pdd32-product-spec__content-item, "
                     "[class*='spec'], [class*='Spec'], "
                     "[data-testid*='spec'], [id*='spec']")
                )
            )
        except Exception:
            logger.debug(
                "  MANUAL_URL  id=%d  no spec containers found within %ds, "
                "proceeding with whatever rendered",
                product_id, SELENIUM_TIMEOUT,
            )

        # Use JS execution instead of driver.page_source — Samsung's
        # heavy pages often cause the /source endpoint to time out.
        try:
            page_source = driver.execute_script(
                "return document.documentElement.outerHTML"
            )
        except Exception:
            page_source = driver.page_source

        # Get the final URL after redirects (important for category detection)
        final_url = driver.current_url
        time.sleep(API_SLEEP)
    except Exception as exc:
        logger.warning("  MANUAL_URL  id=%d  selenium fetch failed: %s", product_id, exc)
        return None
    finally:
        if driver is not None:
            driver.quit()

    soup = BeautifulSoup(page_source, "lxml")

    # 0. Category page detection — if we landed on a listing/category page,
    #    try to find and follow the first product link.
    #    Use final_url (after redirects) instead of the original url.
    if _is_category_page(soup, final_url):
        product_url = _find_product_link_on_category(soup, final_url)
        if product_url and product_url != url:
            logger.info(
                "  MANUAL_URL  id=%d  landed on category page, following product link: %s",
                product_id, product_url,
            )
            driver = None
            try:
                driver = _create_driver()
                driver.set_script_timeout(SELENIUM_TIMEOUT)
                driver.get(product_url)
                try:
                    WebDriverWait(driver, SELENIUM_TIMEOUT).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR,
                             "table, .specs, .specifications, .tech-specs, "
                             ".pdd32-product-spec__content-item, "
                             "[class*='spec'], [class*='Spec'], "
                             "[data-testid*='spec'], [id*='spec']")
                        )
                    )
                except Exception:
                    pass
                try:
                    page_source = driver.execute_script(
                        "return document.documentElement.outerHTML"
                    )
                except Exception:
                    page_source = driver.page_source
                time.sleep(API_SLEEP)
                url = product_url  # Update URL for logging
            except Exception as exc:
                logger.warning("  MANUAL_URL  id=%d  follow-up fetch failed: %s", product_id, exc)
            finally:
                if driver is not None:
                    driver.quit()
            soup = BeautifulSoup(page_source, "lxml")

    # 1. Try JSON-LD (most structured)
    result = _extract_json_ld(soup)

    # 2. Fallback to OG / meta tags
    if not result:
        result = _extract_meta(soup)

    if not result:
        logger.warning("  MANUAL_URL  id=%d  no product data found at %s", product_id, url)
        return None

    # 3. Augment with brand-specific + HTML table specs (deduplicated merge)
    brand_features = _extract_brand_specs(soup)
    table_features = _extract_tables(soup)
    all_spec_features = brand_features + table_features
    if all_spec_features:
        existing_names = {
            ch["nombre"].lower().strip()
            for ch in (result.get("caracteristicas") or [])
        }
        for tf in all_spec_features:
            if tf["nombre"].lower().strip() not in existing_names:
                result["caracteristicas"].append(tf)

    # 3b. If no image from JSON-LD/OG, try <img> tag extraction
    if not result.get("imagen_url"):
        img_url = _extract_image(soup, final_url)
        if img_url:
            result["imagen_url"] = img_url

    logger.info(
        "  MANUAL_URL  id=%d  extracted %d characteristics from %s",
        product_id, len(result.get("caracteristicas") or []), final_url,
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



