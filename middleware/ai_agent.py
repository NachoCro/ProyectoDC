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
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import spec_extractors
from .config import API_SLEEP

SELENIUM_TIMEOUT = 12

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


def _fetch_with_selenium(url: str) -> str | None:
    """Fetch a URL using headless Chrome for JS-heavy pages."""
    driver = None
    try:
        driver = _create_driver()
        driver.set_script_timeout(SELENIUM_TIMEOUT)
        driver.get(url)
        # Wait for some content to render
        try:
            WebDriverWait(driver, SELENIUM_TIMEOUT).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR,
                     "table, .specs, .specifications, .tech-specs, "
                     ".pdd32-product-spec__content-item, "
                     "[class*='spec'], [class*='Spec'], "
                     "[data-testid*='spec'], [id*='spec'], "
                     "article, main, [role='main']")
                )
            )
        except Exception:
            pass
        try:
            html = driver.execute_script(
                "return document.documentElement.outerHTML"
            )
        except Exception:
            html = driver.page_source
        time.sleep(API_SLEEP)
        return html
    except Exception as exc:
        logger.debug("  AI_AGENT  selenium fetch failed %s: %s", url, exc)
        return None
    finally:
        if driver is not None:
            driver.quit()


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


def _extract_image_from_tags(soup: BeautifulSoup) -> str:
    """Extract product image URL from <img> tags.

    Tries multiple strategies:
    1. <img> with product-related classes/ids
    2. <img> with product-related alt text
    3. Any reasonably sized <img> (last resort)
    """

    def _normalize_url(url: str) -> str:
        if not url or url.startswith("data:"):
            return url
        if url.startswith("//"):
            return "https:" + url
        return url

    # Strategy 1: <img> with product-related attributes
    product_selectors = [
        "[class*='product'] img[src]",
        "[class*='Product'] img[src]",
        "[id*='product'] img[src]",
        "[id*='Product'] img[src]",
        "[class*='gallery'] img[src]",
        "[class*='main-image'] img[src]",
        "[class*='hero'] img[src]",
        "[class*='detail'] img[src]",
    ]
    seen_srcs: set[str] = set()
    for selector in product_selectors:
        for img in soup.select(selector):
            src = str(img.get("src", "")).strip()
            if not src or src in seen_srcs:
                continue
            # Skip tiny images
            try:
                if img.get("width") and int(str(img["width"])) < 100:
                    continue
                if img.get("height") and int(str(img["height"])) < 100:
                    continue
            except (ValueError, TypeError):
                pass
            if src.startswith("data:") or any(
                skip in src.lower()
                for skip in ("icon", "logo", "avatar", "pixel", "spacer", "blank")
            ):
                continue
            seen_srcs.add(src)
            return _normalize_url(src)

    # Strategy 2: <img> with product-related alt text
    for img in soup.find_all("img"):
        src = str(img.get("src", "")).strip()
        if not src or src.startswith("data:"):
            continue
        alt = str(img.get("alt") or "").lower()
        if any(kw in alt for kw in ("product", "producto", "image", "foto")):
            return _normalize_url(src)

    return ""


def _extract_apple_specs(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract specs from Apple Support pages (gb-header + gb-list_item format).

    Apple support pages use a custom component system:
    - h3.gb-header for section names (e.g. "Chip", "Pantalla")
    - li.gb-list_item for spec values under each section
    """
    features = []
    seen = set()

    # Find all section headers
    headers = soup.select("h3.gb-header")
    for header in headers:
        section_name = header.get_text(strip=True)
        if not section_name:
            continue

        # Get the parent container and find list items
        parent = header.parent
        if not parent:
            continue

        items = parent.select("li.gb-list_item")
        for item in items:
            item_text = item.get_text(strip=True)
            if not item_text or len(item_text) < 2:
                continue

            # For items with ":" separator, use as key-value
            if ":" in item_text:
                name, _, value = item_text.partition(":")
                name = name.strip()
                value = value.strip()
            else:
                # Use section name as key, item text as value
                name = section_name
                value = item_text

            if not name or not value:
                continue

            key_norm = name.lower().strip()
            if key_norm in seen:
                continue
            seen.add(key_norm)
            features.append({"nombre": name, "valor": value})

    return features


def _get_brand_official_urls(marca: str, nombre: str) -> list[str]:
    """Generate candidate official product page URLs for known brands.

    For brands with predictable URL patterns, this constructs URLs
    that might lead to the official product page.

    Returns a list of candidate URLs to try (empty if brand is not supported).
    """

    marca_lower = marca.lower().strip()
    urls = []

    # TCL: https://www.tcl.com/{locale}/tvs/{model_slug}
    if marca_lower == "tcl":
        # Extract model slug from product name (e.g. "L55P735-F" → "p735")
        model_match = re.search(r'P\d{3}', nombre, re.IGNORECASE)
        if model_match:
            model_slug = model_match.group(0).lower()
            # Try multiple locales
            for locale in ["ar/es", "us/en", "global/en", "asia/en"]:
                urls.append(f"https://www.tcl.com/{locale}/tvs/{model_slug}")

    # Samsung, LG, Sony, etc. could be added here with their URL patterns

    return urls


def _parse_page(html: str, current_url: str = "") -> dict | None:
    """Try all parsers on a page and return the best result."""
    soup = BeautifulSoup(html, "lxml")

    result = spec_extractors.extract_jsonld_product(soup)
    if not result:
        # Fallback to basic OG meta
        og_data = spec_extractors.extract_og_product_meta(soup)
        if og_data.get("title"):
            result = {
                "title": og_data.get("title", ""),
                "descripcion": og_data.get("desc", ""),
                "descripcion_corta": "",
                "marca": og_data.get("brand", ""),
                "modelo": og_data.get("retailer_id", ""),
                "resumen": "",
                "caracteristicas": [],
                "imagen_url": og_data.get("img", ""),
                "imagen_urls": [og_data["img"]] if og_data.get("img") else [],
                "_source": "og_meta",
            }
    if not result:
        return None

    # Merge features from multiple sources
    existing = {ch["nombre"].lower() for ch in result.get("caracteristicas") or []}

    # Brand-specific extractors (TCL, Apple)
    tcl_features = spec_extractors.extract_tcl_specs(soup)
    for tf in tcl_features:
        if tf["nombre"].lower() not in existing:
            result["caracteristicas"].append(tf)
            existing.add(tf["nombre"].lower())

    apple_features = _extract_apple_specs(soup)
    for af in apple_features:
        if af["nombre"].lower() not in existing:
            result["caracteristicas"].append(af)
            existing.add(af["nombre"].lower())

    # Generic extractors (work across all sites)
    _generic_extractors = [
        ("tables", spec_extractors.extract_tables),
        ("dl/dt/dd", spec_extractors.extract_dl_dt_dd),
        ("microdata", spec_extractors.extract_microdata),
        ("div_spec_rows", spec_extractors.extract_div_spec_rows),
        ("body_text", spec_extractors.extract_body_text_specs),
    ]
    for name, extractor in _generic_extractors:
        try:
            generic_features = extractor(soup)
            for gf in generic_features:
                if gf["nombre"].lower() not in existing:
                    result["caracteristicas"].append(gf)
                    existing.add(gf["nombre"].lower())
        except Exception as exc:
            logger.debug("  AI_AGENT  %s extractor failed: %s", name, exc)

    # JS state objects (Next.js, Nuxt, etc.)
    try:
        js_features = spec_extractors.extract_js_state_objects(html)
        for jf in js_features:
            if jf["nombre"].lower() not in existing:
                result["caracteristicas"].append(jf)
                existing.add(jf["nombre"].lower())
    except Exception as exc:
        logger.debug("  AI_AGENT  js_state extraction failed: %s", exc)

    # Extract image from <img> tags if not found in JSON-LD/OG
    if not result.get("imagen_url"):
        from urllib.parse import urljoin
        img_url = _extract_image_from_tags(soup)
        if img_url:
            # Normalize relative URLs using current page URL
            if img_url.startswith("/") and current_url:
                img_url = urljoin(current_url, img_url)
            result["imagen_url"] = img_url
            # Also add to imagen_urls if not already there
            if img_url not in result.get("imagen_urls", []):
                result.setdefault("imagen_urls", []).append(img_url)

    # Store the source URL so validation can check for junk sources
    if current_url:
        result["url"] = current_url

    return result


def _build_search_query(marca: str, nombre: str) -> str:
    """Build a clean search query from brand and product name.

    Extracts the model number from the product name and constructs
    a cleaner query that's more likely to find official product pages.

    Examples:
        "tcl", "TV TCL 55 SMART 4K UHD HDR L55P735-F" → "TCL L55P735-F especificaciones"
        "apple", "iphone 15 pro max" → "apple iphone 15 pro max especificaciones"
        "samsung", "Galaxy S21 5G" → "Samsung Galaxy S21 5G especificaciones"
    """

    if not nombre:
        return f"{marca} especificaciones" if marca else "especificaciones"

    # Extract model numbers - patterns like L55P735-F, SM-G991B, DCP-1617NW, OLED55C4PSA
    # Pattern: letter(s) + digits + letter(s) + digits + optional dash/letter suffix
    model_patterns = re.findall(
        r'[A-Z]+\d+[A-Z]+\d+[-]?[A-Z]*', nombre, re.IGNORECASE
    )

    # Pattern 2: Short standalone model identifiers (e.g. "S21", "P735", "M50F")
    # Must have at least one letter and one digit
    short_models = re.findall(
        r'(?<![A-Za-z0-9])[A-Z]{1,3}\d{2,4}[A-Z]?(?![A-Za-z0-9])',
        nombre, re.IGNORECASE
    )

    # Combine and deduplicate, preferring longer matches
    all_models = list(dict.fromkeys(model_patterns + short_models))
    # Sort by length (longest first) to prefer more specific models
    all_models.sort(key=len, reverse=True)

    if all_models:
        # Use the first (most specific) model number
        model = all_models[0]
        # Build query with brand + model, excluding manual/support pages
        if marca:
            query = f"{marca} {model} especificaciones -manual -guia -tutorial -soporte"
        else:
            query = f"{model} especificaciones -manual -guia"
    else:
        # No model found, use full name but remove noise words
        from .official_scraper import _NOISE_WORDS

        words = nombre.split()
        cleaned_words = [
            w for w in words
            if w.lower() not in _NOISE_WORDS and len(w) > 1
        ]
        cleaned_name = " ".join(cleaned_words[:5])  # Limit to 5 words
        if marca:
            query = f"{marca} {cleaned_name} especificaciones -manual -guia"
        else:
            query = f"{cleaned_name} especificaciones -manual -guia"

    return query


def enrich_with_ai(marca: str, nombre: str) -> dict | None:
    """Search the web and scrape official product data (no LLM).

    Uses the product name (which already contains brand + model) as the
    primary search term.

    Parameters
    ----------
    marca:
        Brand name (e.g. "Samsung").
    nombre:
        Product name from PrestaShop (e.g. "Galaxy S21 5G").

    Returns
    -------
    dict | None
        Normalized product data on success, ``None`` if nothing found.
    """
    query = _build_search_query(marca, nombre)
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
        # Skip PDFs, manuals, and support pages
        if any(url.lower().endswith(ext) for ext in ('.pdf', '.doc', '.docx', '.xls')):
            logger.info("  AI_AGENT  skipping non-HTML: %s", url[:80])
            continue

        logger.info("  AI_AGENT  trying: %s (%s)", url, title[:60])

        # First try simple HTTP fetch
        html = _fetch(url)
        http_data = None
        if html and len(html) >= 500:
            http_data = _parse_page(html, url)
            if http_data and (http_data.get("caracteristicas") or http_data.get("descripcion")):
                if not http_data.get("marca"):
                    http_data["marca"] = marca
                if not http_data.get("modelo"):
                    http_data["modelo"] = ""
                # If we got characteristics, return immediately
                if http_data.get("caracteristicas"):
                    logger.info(
                        "  AI_AGENT  extracted %d characteristics from %s (http)",
                        len(http_data["caracteristicas"]), url,
                    )
                    return http_data

        # Fallback: try Selenium for JS-heavy pages (when no characteristics from HTTP)
        logger.info("  AI_AGENT  trying Selenium for: %s", url)
        html_selenium = _fetch_with_selenium(url)
        if html_selenium and len(html_selenium) >= 500:
            selenium_data = _parse_page(html_selenium, url)
            if selenium_data and (selenium_data.get("caracteristicas") or selenium_data.get("descripcion")):
                if not selenium_data.get("marca"):
                    selenium_data["marca"] = marca
                if not selenium_data.get("modelo"):
                    selenium_data["modelo"] = ""
                # Prefer Selenium result if it has characteristics
                if selenium_data.get("caracteristicas"):
                    logger.info(
                        "  AI_AGENT  extracted %d characteristics from %s (selenium)",
                        len(selenium_data["caracteristicas"]), url,
                    )
                    return selenium_data
                # If both have only descriptions (no characteristics), prefer HTTP
                elif http_data:
                    logger.info(
                        "  AI_AGENT  using HTTP result (no characteristics from either source)",
                    )
                    return http_data
                else:
                    return selenium_data

    # ── Brand-specific fallback: try official website directly ────────────
    # For brands with predictable URL patterns, try the official site directly
    # if web search didn't find it.
    if marca:
        brand_urls = _get_brand_official_urls(marca, nombre)
        for official_url in brand_urls:
            logger.info("  AI_AGENT  trying official URL: %s", official_url)
            html_official = _fetch_with_selenium(official_url)
            if html_official and len(html_official) >= 500:
                data_official = _parse_page(html_official, official_url)
                if data_official and data_official.get("caracteristicas"):
                    if not data_official.get("marca"):
                        data_official["marca"] = marca
                    logger.info(
                        "  AI_AGENT  extracted %d characteristics from official URL %s",
                        len(data_official["caracteristicas"]), official_url,
                    )
                    return data_official

    logger.info("  AI_AGENT  no product data found for %s %s", marca, nombre)
    return None
