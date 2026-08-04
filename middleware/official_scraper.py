"""Scrape official manufacturer websites for product enrichment (manual URL only).

``scrape_from_direct_url(url, product_id)`` accepts a human-verified
official URL, fetches the page, extracts structured data (JSON-LD, OG meta,
HTML tables), and persists the attributes into the local 3NF EAV tables.
"""

import json
import logging
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import spec_extractors
from .config import API_SLEEP
from .db import get_connection, write_eav

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


# ── Sitemap-based brand search ──────────────────────────────────────────────

_SITEMAP_CACHE_DIR = Path("/tmp")


def _fetch_sitemap_urls(
    sitemap_url: str,
    url_pattern: str = "",
    cache_ttl_hours: int = 24,
) -> list[str]:
    """Fetch a sitemap XML and return filtered <loc> URLs.

    Caches the XML on disk under ``/tmp/<brand>_sitemap.xml``.  If the cache
    file exists and is younger than *cache_ttl_hours*, it is reused without
    a network fetch.

    Parameters
    ----------
    sitemap_url:
        Full URL of the sitemap XML (e.g. ``https://www.acer.com/sitemap_ares.xml``).
    url_pattern:
        If provided, only URLs containing this substring are returned.
    cache_ttl_hours:
        Cache lifetime in hours (default 24).

    Returns
    -------
    list[str]
        List of matching ``<loc>`` URLs from the sitemap.
    """
    import time as _time
    from xml.etree import ElementTree as ET

    brand_key = sitemap_url.split("//")[-1].split("/")[0].replace(".", "_")
    cache_path = _SITEMAP_CACHE_DIR / f"{brand_key}_sitemap.xml"

    xml_bytes: bytes | None = None

    # Try cache first
    if cache_path.exists():
        age_hours = (_time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < cache_ttl_hours:
            logger.debug("  SITEMAP  using cached %s (%.1fh old)", cache_path, age_hours)
            xml_bytes = cache_path.read_bytes()

    # Fetch from network if cache miss or expired
    if xml_bytes is None:
        try:
            resp = _SESSION.get(sitemap_url, timeout=30)
            resp.raise_for_status()
            xml_bytes = resp.content
            cache_path.write_bytes(xml_bytes)
            logger.info(
                "  SITEMAP  fetched %s (%d bytes) → cached to %s",
                sitemap_url, len(xml_bytes), cache_path,
            )
        except Exception as exc:
            logger.warning("  SITEMAP  fetch failed %s: %s", sitemap_url, exc)
            # Fallback: try stale cache
            if cache_path.exists():
                logger.info("  SITEMAP  falling back to stale cache %s", cache_path)
                xml_bytes = cache_path.read_bytes()
            else:
                return []

    # Parse XML
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("  SITEMAP  XML parse error: %s", exc)
        return []

    # Handle sitemap index (nested <sitemap><loc>)
    # Some brands use sitemap index files that point to sub-sitemaps.
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls: list[str] = []

    # Check if this is a sitemap index (contains <sitemap> children)
    sitemap_tags = root.findall("sm:sitemap", ns) or root.findall("sitemap")
    if sitemap_tags:
        logger.info("  SITEMAP  detected sitemap index with %d sub-sitemaps", len(sitemap_tags))
        for sm_tag in sitemap_tags[:5]:  # limit to first 5 sub-sitemaps
            sub_loc = sm_tag.findtext("sm:loc", default="", namespaces=ns) or sm_tag.findtext("loc", default="")
            if sub_loc:
                sub_urls = _fetch_sitemap_urls(sub_loc, url_pattern, cache_ttl_hours=0)
                urls.extend(sub_urls)
        return urls

    # Normal sitemap: extract <url><loc> entries
    for url_tag in root.findall("sm:url", ns) or root.findall("url"):
        loc = url_tag.findtext("sm:loc", default="", namespaces=ns) or url_tag.findtext("loc", default="")
        if not loc:
            continue
        if url_pattern and url_pattern not in loc:
            continue
        urls.append(loc)

    logger.info("  SITEMAP  extracted %d URLs (pattern=%r)", len(urls), url_pattern)
    return urls


def _search_brand_sitemap(
    sitemap_url: str,
    url_pattern: str,
    product_name: str,
    marca: str,
    pid: int = 0,
) -> str | None:
    """Search a brand's sitemap for the best-matching product URL.

    Fetches the sitemap XML (with disk cache), extracts product URLs matching
    *url_pattern*, normalises their path slugs, and picks the one with the
    highest fuzzy-match score against the cleaned product name.

    Returns the best-matching URL if the score exceeds a threshold, else ``None``.
    """
    from difflib import SequenceMatcher

    urls = _fetch_sitemap_urls(sitemap_url, url_pattern)
    if not urls:
        logger.debug("  SITEMAP_SEARCH  no URLs found for %s", sitemap_url)
        return None

    cleaned_name = _clean_name_for_search(product_name, marca)
    # Also try with just the MPN-like part (uppercase, alphanumeric+dashes)
    import re
    model_tokens = re.findall(r'[A-Za-z0-9][A-Za-z0-9\-]+', cleaned_name)
    search_terms = " ".join(model_tokens).lower() if model_tokens else cleaned_name.lower()

    # TV/monitor size from product name (e.g. "75\"", "75 pulgadas") — used to
    # disambiguate size-specific variants that share the same family slug.
    size_match = re.search(r"(\d{2})\s*(?:\"|''|pulgadas|inches|inch|')(?!\w)", product_name, re.I)
    wanted_size = size_match.group(1) if size_match else ""
    # Serial-like token (e.g. "un75u8000fgczb", "55c6k") — strong product-page signal
    serial_re = re.compile(r"[a-z]{1,4}\d{2}[a-z0-9]{2,}")

    logger.info(
        "  SITEMAP_SEARCH  id=%d  searching %d URLs for %r (cleaned=%r, size=%r)",
        pid, len(urls), product_name, search_terms, wanted_size,
    )

    best_url = None
    best_score = 0.0
    threshold = 0.4

    for url in urls:
        # Extract the last meaningful path segment as the "slug"
        path = url.split("?")[0].rstrip("/")
        slug = path.rsplit("/", 1)[-1] if "/" in path else path
        # Normalise: replace hyphens/underscores with spaces, lowercase
        slug_norm = slug.replace("-", " ").replace("_", " ").lower()
        # Remove common suffixes like .html
        slug_norm = re.sub(r'\.html?$', '', slug_norm)

        score = SequenceMatcher(None, search_terms, slug_norm).ratio()

        # Boost exact model token matches (e.g. "A315" in slug vs name)
        for token in model_tokens:
            if token.lower() in slug_norm:
                score = min(score + 0.15, 1.0)

        # Category/listing pages rarely contain digits — penalise them so the
        # family/serial product pages win (e.g. "/tvs/crystal-uhd/" vs "/tvs/.../un75u8000fgczb/").
        if not re.search(r"\d", slug):
            score -= 0.4

        # Serial-like pattern (e.g. "un75u8000fgczb", "55c6k") → product page
        if serial_re.search(slug):
            score = min(score + 0.2, 1.0)

        # Size-specific variants: boost the slug containing the wanted size
        if wanted_size and re.search(rf"\b{wanted_size}\b", slug_norm):
            score = min(score + 0.1, 1.0)

        if score > best_score:
            best_score = score
            best_url = url

    if best_url and best_score >= threshold:
        logger.info(
            "  SITEMAP_SEARCH  id=%d  best match score=%.2f → %s",
            pid, best_score, best_url,
        )
        return best_url

    logger.debug(
        "  SITEMAP_SEARCH  id=%d  no match above threshold %.2f (best=%.2f)",
        pid, threshold, best_score,
    )
    return None


# ── PDF-from-sitemap brand search ────────────────────────────────────────────
# Some brands (gfast) publish each product's data sheet as a PDF linked from a
# category/landing page instead of a per-product HTML page.  The sitemap gives
# the landing pages; each page lists several products — each with a "ficha
# técnica" PDF whose filename embeds the model — so we collect every spec PDF
# link and pick the one matching the product name/model.

_PDF_PAGE_CACHE: dict[str, tuple[float, "BeautifulSoup | None", list[dict[str, str]]]] = {}
_PDF_PAGE_CACHE_TTL_HOURS = 24


def _fetch_page(page_url: str) -> tuple["BeautifulSoup | None", list[dict[str, str]]]:
    """Fetch a category/landing page and return ``(soup, spec-PDF links)``.

    Pages are cached in memory for ``_PDF_PAGE_CACHE_TTL_HOURS`` to avoid
    re-fetching the same landing page for every product of the brand.
    """
    now = time.time()
    cached = _PDF_PAGE_CACHE.get(page_url)
    if cached and now - cached[0] < _PDF_PAGE_CACHE_TTL_HOURS * 3600:
        return cached[1], cached[2]

    soup: BeautifulSoup | None = None
    links: list[dict[str, str]] = []
    try:
        time.sleep(API_SLEEP)  # throttle external requests
        resp = _SESSION.get(page_url, timeout=30)
        resp.raise_for_status()
        from .pdf_scraper import find_spec_pdf_links
        soup = BeautifulSoup(resp.text, "lxml")
        links = find_spec_pdf_links(soup, page_url)
        logger.info("  PDF_SITEMAP  %s → %d spec PDF links", page_url, len(links))
    except Exception as exc:
        logger.warning("  PDF_SITEMAP  page fetch failed %s: %s", page_url, exc)

    _PDF_PAGE_CACHE[page_url] = (now, soup, links)
    return soup, links


def _fetch_page_pdf_links(page_url: str) -> list[dict[str, str]]:
    """Fetch a category/landing page and return its spec-sheet PDF links."""
    _, links = _fetch_page(page_url)
    return links


def _pages_for_pdf(pdf_url: str) -> list[str]:
    """Return cached page URLs that link to *pdf_url* (matched by filename)."""
    fname = pdf_url.lower().split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    now = time.time()
    pages: list[str] = []
    for page_url, (ts, _soup, links) in _PDF_PAGE_CACHE.items():
        if now - ts >= _PDF_PAGE_CACHE_TTL_HOURS * 3600:
            continue
        if any(
            link["url"].lower().split("?")[0].rstrip("/").rsplit("/", 1)[-1] == fname
            for link in links
        ):
            pages.append(page_url)
    return pages


def _extract_inline_specs_from_soup(soup: "BeautifulSoup | None", pdf_url: str) -> list[dict[str, str]]:
    """Extract "Key: Value" spec lines from the product block linking to a PDF.

    gfast category pages list each product inline (Elementor): a heading, a
    text-editor with ``Key: Value`` lines (``<br>`` separated) and a button
    linking to the product's data-sheet PDF.  Used as a fallback when the PDF
    is image-based and yields no extractable text.
    """
    if soup is None:
        return []

    fname = pdf_url.lower().split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    anchor = None
    for cand in soup.find_all("a", href=True):
        href = str(cand.get("href") or "").lower()
        if href.endswith(fname):
            anchor = cand
            break

    if anchor is None:
        return []

    node = anchor
    for _ in range(12):
        parent = node.parent
        if parent is None or parent.name in ("body", "html"):
            break
        specs: list[dict[str, str]] = []
        for p in parent.find_all("p"):
            if anchor in p.find_all("a"):
                continue
            text = p.get_text(separator="\n", strip=True)
            for line in text.split("\n"):
                line = line.strip()
                if not line or ":" not in line:
                    continue
                name, _, value = line.partition(":")
                name, value = name.strip(), value.strip()
                if not name or not value or len(name) > 60 or len(value) > 200:
                    continue
                if name.lower() in ("especificaciones", "specifications", "caracteristicas"):
                    continue
                specs.append({"nombre": name, "valor": value})
        if len(specs) >= 2:
            return specs
        node = parent
    return []


def _extract_pdf_model_tokens(product_name: str, marca: str = "") -> set[str]:
    """Model-ish tokens (letter + digit, hyphens kept) from a product name.

    gfast-style models embed hyphens (``T-195``, ``N-536R``, ``H-500``) that
    ``_extract_model_from_name`` strips, so PDF matching extracts its own
    tokens.  Returns normalized tokens (hyphens removed) of length ≥ 3,
    e.g. ``"Monitor Gfast T-195 19.5 LED"`` → ``{"t195"}``.
    """
    import re
    import unicodedata

    def _norm(s: str) -> str:
        s = unicodedata.normalize("NFKD", s.lower())
        return "".join(c for c in s if not unicodedata.combining(c))

    cleaned = _norm(product_name)
    if marca:
        cleaned = re.sub(re.escape(_norm(marca)), "", cleaned)
    for w in _NOISE_WORDS:
        cleaned = re.sub(rf"\b{re.escape(w)}\b", "", cleaned)
    # Drop bare decimal sizes (19.5, 15.6) — not model identifiers
    cleaned = re.sub(r"\d+\.\d+", " ", cleaned)

    tokens = set()
    for tok in re.findall(r"[a-z]+\-?\d+[a-z0-9\-]*", cleaned):
        norm_tok = re.sub(r"[^a-z0-9]", "", tok)
        if len(norm_tok) >= 3:
            tokens.add(norm_tok)
    return tokens


def _score_pdf_url(pdf_url: str, product_name: str, marca: str) -> float:
    """Score a spec-sheet PDF URL against a product name.

    PDF filenames typically embed the model (e.g. ``Ficha-Tecnica-Gfast-N-536R.pdf``
    vs ``Notebook Gfast N-536R``).  Combines a model-token bonus, token
    overlap, and a fuzzy ratio on the normalized slugs.
    """
    import re
    import unicodedata
    from difflib import SequenceMatcher

    def _norm(s: str) -> str:
        s = unicodedata.normalize("NFKD", s.lower())
        s = "".join(c for c in s if not unicodedata.combining(c))
        return re.sub(r"[^a-z0-9]", "", s)

    fname = pdf_url.split("?")[0].rstrip("/")
    fname = fname.rsplit("/", 1)[-1]
    if fname.lower().endswith(".pdf"):
        fname = fname[:-4]
    fname_norm = _norm(fname)
    if not fname_norm:
        return 0.0

    name_norm = _norm(product_name)

    score = 0.0

    # Strongest signal: the product's model token appears in the filename
    for tok in _extract_pdf_model_tokens(product_name, marca):
        if tok in fname_norm:
            score += 6.0

    # Secondary: general token overlap on the raw name
    tokens = {t for t in re.findall(r"[a-z0-9]{3,}", name_norm)}
    score += sum(1 for t in tokens if t in fname_norm) * 1.5

    score += SequenceMatcher(None, name_norm, fname_norm).ratio() * 10.0
    return score


def _search_brand_pdf_sitemap(
    sitemap_url: str,
    product_name: str,
    marca: str,
    pid: int = 0,
) -> str | None:
    """Search a brand sitemap whose product pages embed PDF data sheets.

    Walks every sitemap URL, collects the spec-sheet PDF links found on each
    page (cached), and returns the PDF whose filename best matches the product
    name/model.  Returns the best PDF URL if it beats the acceptance
    threshold, else ``None``.
    """
    pages = _fetch_sitemap_urls(sitemap_url)
    if not pages:
        logger.debug("  PDF_SITEMAP  no sitemap URLs for %s", sitemap_url)
        return None

    logger.info(
        "  PDF_SITEMAP  id=%d  scanning %d pages for %r",
        pid, len(pages), product_name,
    )

    best_url: str | None = None
    best_score = 0.0
    for page in pages:
        pdf_links = _fetch_page_pdf_links(page)
        for link in pdf_links:
            score = _score_pdf_url(link["url"], product_name, marca)
            logger.debug(
                "  PDF_SITEMAP  id=%d  score=%.1f  %s",
                pid, score, link["url"],
            )
            if score > best_score:
                best_score = score
                best_url = link["url"]

    if best_url and best_score >= 9.0:
        logger.info(
            "  PDF_SITEMAP  id=%d  best match score=%.1f → %s",
            pid, best_score, best_url,
        )
        return best_url

    logger.debug(
        "  PDF_SITEMAP  id=%d  no PDF match above threshold (best=%.1f)",
        pid, best_score,
    )
    return None


# ── PDF-sitemap auto-discovery ───────────────────────────────────────────────
# Some sites (gfast) publish each product's data sheet as a PDF linked from a
# category/landing page, with no per-product pages and no brands_mapping.json
# entry.  When a brand has no mapping, we *discover* the source: probe
# candidate official domains + common sitemap paths and detect the "category
# pages full of spec-sheet PDF links" pattern.  Results are cached per brand
# key for the process lifetime, so the probe cost is paid once per brand — not
# once per product.  Page fetches run through the shared 24h _fetch_page cache
# and the API_SLEEP throttle.

_PDF_SITEMAP_DISCOVERY: dict[str, str | None] = {}
_PDF_SITEMAP_DISCOVERY_MAX = 64

# Candidate official domains for an unmapped brand, tried in order.
_PDF_SITEMAP_DOMAIN_TEMPLATES = (
    "{brand}.com.ar",
    "{brand}.com",
    "www.{brand}.com",
    "{brand}.net",
    "{brand}.com.uy",
)

# Common sitemap paths (WordPress core + Yoast/RankMath-style indices), tried
# per domain until one yields the PDF-spec pattern.
_PDF_SITEMAP_PATH_CANDIDATES = (
    "/wp-sitemap-posts-page-1.xml",
    "/wp-sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap.xml",
    "/sitemap-1.xml",
    "/page-sitemap.xml",
)

# Pattern-detection thresholds over a sample of sitemap pages.
_PDF_SITEMAP_DETECT_SAMPLE = 8
_PDF_SITEMAP_DETECT_MIN_TOTAL = 3
_PDF_SITEMAP_DETECT_MIN_MULTI = 1


def _detect_pdf_spec_site(page_urls: list[str]) -> bool:
    """Return True if the sampled pages look like a PDF-spec listing site.

    Fetches up to ``_PDF_SITEMAP_DETECT_SAMPLE`` pages (shared 24h cache) and
    counts the spec-sheet PDF links.  Accepts the pattern when the sample has at
    least ``_PDF_SITEMAP_DETECT_MIN_TOTAL`` PDF links and at least one page
    lists several of them (a category/listing page).
    """
    total = 0
    multi_pages = 0
    for page in page_urls[:_PDF_SITEMAP_DETECT_SAMPLE]:
        links = _fetch_page_pdf_links(page)
        total += len(links)
        if len(links) >= 2:
            multi_pages += 1
    return total >= _PDF_SITEMAP_DETECT_MIN_TOTAL and multi_pages >= _PDF_SITEMAP_DETECT_MIN_MULTI


def _cache_pdf_sitemap_discovery(key: str, sitemap_url: str | None) -> None:
    if len(_PDF_SITEMAP_DISCOVERY) >= _PDF_SITEMAP_DISCOVERY_MAX:
        _PDF_SITEMAP_DISCOVERY.clear()
    _PDF_SITEMAP_DISCOVERY[key] = sitemap_url


def _discover_brand_pdf_sitemap(
    marca: str,
    product_name: str,
    pid: int = 0,
) -> str | None:
    """Discover a gfast-style PDF-sitemap source for an unmapped brand.

    Probes candidate domains and common sitemap paths; the first sitemap whose
    pages show the PDF-spec pattern wins.  The outcome is cached per brand key,
    so later products of the same brand skip straight to
    ``_search_brand_pdf_sitemap`` (or straight to ``None`` when no source was
    found).
    """
    import re

    key = marca.strip().lower()
    if key in _PDF_SITEMAP_DISCOVERY:
        sitemap_url = _PDF_SITEMAP_DISCOVERY[key]
        if sitemap_url:
            return _search_brand_pdf_sitemap(sitemap_url, product_name, marca, pid)
        return None

    slug = re.sub(r"[^a-z0-9]", "", key)
    if not slug:
        _cache_pdf_sitemap_discovery(key, None)
        return None

    for tpl in _PDF_SITEMAP_DOMAIN_TEMPLATES:
        domain = tpl.format(brand=slug)
        for path in _PDF_SITEMAP_PATH_CANDIDATES:
            sitemap_url = f"https://{domain}{path}"
            pages = _fetch_sitemap_urls(sitemap_url, cache_ttl_hours=0)
            if not pages:
                continue
            logger.info(
                "  PDF_DISCOVERY  %s → %d pages, checking PDF-spec pattern",
                sitemap_url, len(pages),
            )
            if _detect_pdf_spec_site(pages):
                _cache_pdf_sitemap_discovery(key, sitemap_url)
                logger.info("  PDF_DISCOVERY  %s is a PDF-spec source", sitemap_url)
                return _search_brand_pdf_sitemap(sitemap_url, product_name, marca, pid)

    _cache_pdf_sitemap_discovery(key, None)
    logger.info("  PDF_DISCOVERY  no PDF-sitemap source found for %r", key)
    return None


# ── Brand inference from product name ────────────────────────────────────────

# Product-line names that map to a brand key in brands_mapping.json.
# Used when the product name contains the product line but not the brand itself
# (e.g. "iphone 15 pro max" → "apple").
_PRODUCT_LINE_TO_BRAND: dict[str, str] = {
    "iphone": "apple",
    "ipad": "apple",
    "macbook": "apple",
    "airpods": "apple",
    "apple tv": "apple",
    "homepod": "apple",
    "galaxy": "samsung",
    "gear": "samsung",
    "pixel": "google",
    "nexus": "google",
    "redmi": "xiaomi",
    "poco": "xiaomi",
    "mi ": "xiaomi",
    "thinkpad": "lenovo",
    "ideapad": "lenovo",
    "legion": "lenovo",
    "surface": "microsoft",
    "xbox": "microsoft",
    "playstation": "sony",
    "wh-": "sony",
    "wf-": "sony",
    "mdr-": "sony",
    "bravia": "sony",
    "vaio": "vaio",
    "chromebook": "acer",
    "predator": "acer",
    "nitro": "acer",
    "zenfone": "asus",
    "rog": "asus",
    "tuf": "asus",
    "matebook": "huawei",
    "nova": "huawei",
    "echo": "amazon",
    "kindle": "amazon",
    "fire tv": "amazon",
    "dcp-": "brother",
    "dcp": "brother",
    "mfc-": "brother",
    "mfc": "brother",
    "hl-": "brother",
    "hl": "brother",
}


def _infer_brand_from_name(nombre: str) -> str | None:
    """Infer the product brand from its name by matching against known brands.

    Scans the product name (case-insensitive) for any brand key present in
    ``brands_mapping.json``.  If no direct match, checks product-line aliases
    (e.g. "iphone" → "apple").  Returns the matched brand key (lowercase) or
    ``None`` if no known brand is found.
    """
    if not nombre:
        return None
    import re
    nombre_lower = nombre.lower()
    # Use word boundaries to avoid false matches (e.g. "blu" matching "bluetooth")
    for brand_key in _BRANDS_MAP:
        pattern = r'\b' + re.escape(brand_key) + r'\b'
        if re.search(pattern, nombre_lower):
            return brand_key
    for line, brand in _PRODUCT_LINE_TO_BRAND.items():
        pattern = r'\b' + re.escape(line) + r'\b'
        if re.search(pattern, nombre_lower) and brand in _BRANDS_MAP:
            return brand
    return None


def _extract_model_from_name(text: str, marca: str = "") -> str:
    """Extract the model number from a product title or name.

    Removes the brand name and common descriptors, leaving the alphanumeric
    model identifier (e.g. "DCP1617NW", "OLED55C4PSA", "BM5100FDW").

    Examples:
        "DCP1617NW | Impresora láser monocromática | Brother Argentina" → "DCP1617NW"
        "BROTHER DCP1617NW" → "DCP1617NW"
        "LG OLED55C4PSA 55\" 4K Smart TV" → "OLED55C4PSA"
    """
    if not text:
        return ""

    import re

    cleaned = text

    # Remove brand name if provided
    if marca:
        cleaned = re.sub(re.escape(marca), "", cleaned, flags=re.IGNORECASE)

    # Remove common descriptors / noise (same as _clean_name_for_search)
    for word in _NOISE_WORDS:
        cleaned = re.sub(rf"\b{re.escape(word)}\b", "", cleaned, flags=re.IGNORECASE)

    # Remove separators and extra punctuation
    cleaned = re.sub(r"[|/\\:;,\-–—(){}\[\]\"'«»]", " ", cleaned)

    # Remove size patterns like 55", 32", 27"
    cleaned = re.sub(r'\d+["\u201d\u2019\u2018]', "", cleaned)

    # Extract the most likely model token: alphanumeric sequences with at least
    # one letter and one digit (e.g. DCP1617NW, OLED55C4PSA, BM5100FDW, M50F)
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", cleaned)
    if candidates:
        # Prefer candidates containing digits (model numbers like DCP1617NW, M404dn)
        with_digits = [c for c in candidates if any(d.isdigit() for d in c)]
        pool = with_digits if with_digits else candidates
        # Pick the longest candidate
        best = max(pool, key=len)
        return best.strip()

    return ""


# ── Name cleanup for search ─────────────────────────────────────────────────


# Common prefixes/suffixes to remove from product names before searching.
# These are generic descriptors that don't help with search and may confuse
# brand site search engines.
_NOISE_WORDS = {
    # Spanish product types
    "impresora", "imp", "monitor", "televisor", "tv", "audifonos", "audífonos",
    "parlante", "bocina", "cargador", "cable", "adaptador", "mouse", "teclado",
    "disco", "memoria", "ram", "procesador", "tarjeta", "fuente",
    # Common abbreviations
    "note", "notebook", "nb", "laptop", "portatil", "portátil",
    "parl", "boc", "carg", "adapt", "aud", "proc", "mem",
    "mon", "pant", "display", "pantalla",
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
    # Block images/fonts to speed up heavy brand pages (Samsung can exceed
    # 60s under full load, timing out the renderer).
    opts.add_argument("--blink-settings=imagesEnabled=false")
    opts.add_argument("--disable-features=PreloadMediaEngagement,MediaEngagementBatching")
    opts.add_experimental_option("prefs", {
        "profile.managed_default_content_settings.images": 2,
        "disk-cache-size": 4096,
    })
    opts.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(90)
    return driver


# ── Brand site search ────────────────────────────────────────────────────────


def _search_brand_site(marca: str, product_name: str, pid: int = 0) -> str | None:
    """Search the brand's official site for a product and return the best result URL.

    Uses the full *product_name* as the search query by substituting the
    ``{mpn}`` placeholder in ``brands_mapping.json`` with the cleaned
    product name.  Evaluates **all** matching results and picks the one
    that best matches the product name.

    Returns the absolute URL of the best matching product card, or ``None``
    if the brand has no search config, the search yields no results,
    or Selenium fails.
    """
    key = marca.strip().lower()
    entry = _BRANDS_MAP.get(key)
    if not entry:
        # Unmapped brand → try auto-discovery of a gfast-style PDF-sitemap
        # source (sites whose data sheets are PDFs linked from category pages).
        return _discover_brand_pdf_sitemap(marca, product_name, pid)

    # ── Sitemap strategy ─────────────────────────────────────────────────
    if entry.get("strategy") == "sitemap":
        sitemap_url = entry.get("sitemap_url", "")
        url_pattern = entry.get("url_pattern", "")
        if sitemap_url:
            return _search_brand_sitemap(
                sitemap_url, url_pattern, product_name, marca, pid,
            )
        return None

    # ── PDF-sitemap strategy (category pages with inline PDF data sheets) ─
    if entry.get("strategy") == "pdf_sitemap":
        sitemap_url = entry.get("sitemap_url", "")
        if sitemap_url:
            return _search_brand_pdf_sitemap(
                sitemap_url, product_name, marca, pid,
            )
        return None

    # ── Standard search-url strategy ─────────────────────────────────────
    search_tpl = entry.get("search_url", "")
    selector = entry.get("result_selector", "")
    if not search_tpl or not selector:
        return None

    # Clean the product name for search — remove generic descriptors,
    # brand names, and common noise to leave only the model number.
    cleaned_name = _clean_name_for_search(product_name, marca)
    logger.info(
        "  BRAND_SEARCH  searching %s for cleaned_name=%r (original=%r)",
        key, cleaned_name, product_name,
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

        # Get ALL matching results — pick the one whose title shares the
        # most words with the product name.
        elements = driver.find_elements(By.CSS_SELECTOR, selector)
        if not elements:
            logger.debug("  BRAND_SEARCH  no results for %s", key)
            return None

        import re as _re
        import unicodedata as _ud

        def _strip_acc(s: str) -> str:
            return "".join(
                c for c in _ud.normalize("NFKD", s)
                if not _ud.combining(c)
            )

        cleaned = _clean_name_for_search(product_name, marca)
        # Build search words from the FULL product name (not just cleaned)
        # so we get more differentiating tokens: brother, dcp, 1617nw …
        _GENERIC = frozenset({
            "de", "del", "la", "el", "un", "una", "los", "las", "para", "con",
            "impresora", "monitor", "televisor", "smart", "tv", "led", "lcd",
            "laser", "inkjet", "mf", "mfp", "multifuncion", "multifuncional",
            "printer",
        })
        search_words = {
            w for w in _strip_acc(product_name).lower().split()
            if len(w) > 1 and w not in _GENERIC
        }
        # Also include the full cleaned model as one token  e.g. "dcp-1617nw"
        raw_token = _strip_acc(cleaned).lower().replace(" ", "")
        if len(raw_token) > 2:
            search_words.add(raw_token)

        # Model slug for URL matching (e.g. "dcp1617nw")
        model_slug = _strip_acc(cleaned).lower().replace(" ", "").replace("-", "")

        # Accessory keywords — penalize results that are clearly not the product
        _ACCESSORY_WORDS = frozenset({
            "toner", "cartucho", "cable", "cargador", "bateria", "batería",
            "funda", "estuche", "soporte", "adapter", "adaptador", "kit",
            "tinta", "drum", "recambio", "accesorio", "replacement",
        })

        best_url = None
        best_score = -1

        for el in elements:
            href = el.get_attribute("href")
            if not href:
                continue

            try:
                title = _strip_acc(el.text.lower())
            except Exception:
                continue
            if not title:
                continue

            # --- Score calculation ---
            matches = sum(1 for w in search_words if w in title)

            # Bonus: model slug appears in the URL (strongest signal)
            url_slug = href.lower().replace("-", "").replace("/", " ")
            url_has_model = model_slug in url_slug or model_slug in href.lower().replace("-", "")
            url_bonus = 20 if url_has_model else 0

            # Bonus: title starts with the model number
            first_word = title.split()[0] if title.split() else ""
            first_match = first_word in search_words
            first_bonus = 10 if first_match else 0

            # Penalty: accessory keywords in title
            accessory_penalty = sum(
                5 for aw in _ACCESSORY_WORDS if aw in title
            )

            score = matches + url_bonus + first_bonus - accessory_penalty

            logger.debug(
                "  BRAND_SEARCH  title=%r  score=%d (matches=%d url=%d first=%d -accessory=%d)  url=%s",
                el.text.strip(), score, matches, url_bonus, first_bonus,
                accessory_penalty, href,
            )

            if score > best_score:
                best_score = score
                best_url = href

        if best_url and best_score > 0:
            logger.info(
                "  BRAND_SEARCH  best match (score=%d) — %s",
                best_score, best_url,
            )
        else:
            logger.debug("  BRAND_SEARCH  no matching titles for %s", key)
            best_url = None

        # Direct URL fallback — try constructed product URL from brands_mapping
        if not best_url:
            direct_pattern = entry.get("direct_url_pattern", "")
            if direct_pattern:
                import re as _re
                slug = _re.sub(r'[^a-z0-9]', '', cleaned.lower())
                if slug:
                    direct_url = direct_pattern.replace("{model_slug}", slug)
                    logger.info(
                        "  BRAND_SEARCH  id=%d  trying direct URL fallback: %s", pid, direct_url,
                    )
                    best_url = direct_url

        return best_url

    except Exception as exc:
        logger.debug("  BRAND_SEARCH  %s failed: %s", key, exc)
        return None
    finally:
        if driver is not None:
            driver.quit()


# ── Parsers ─────────────────────────────────────────────────────────────────


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
            return _normalize_url(str(tag["content"]).strip())

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
            src = str(img.get("src", "")).strip()
            if not src or src in seen_srcs:
                continue
            # Skip tiny images (icons, spacers, etc.)
            width = str(img.get("width", ""))
            height = str(img.get("height", ""))
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
        src = str(img.get("src", "")).strip()
        if not src or src.startswith("data:"):
            continue
        if any(skip in src.lower() for skip in ("icon", "logo", "avatar", "pixel", "spacer", "blank")):
            continue
        # Check alt text for product hints
        alt = str(img.get("alt") or "").lower()
        if any(kw in alt for kw in ("product", "producto", "image", "foto")):
            return _normalize_url(src)

    return ""


def _extract_images(soup: BeautifulSoup, current_url: str = "", max_images: int = 4) -> list[str]:
    """Extract multiple product image URLs from the page.

    Tries multiple strategies in order:
    1. JSON-LD images (all from @type: Product)
    2. OG image meta tag
    3. <img> tags with product-related classes/ids/alt text
    4. <img> in main content area with reasonable size

    Returns up to max_images unique URLs, sorted by relevance.
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

    def _is_valid_image(url: str) -> bool:
        """Check if URL is a valid product image (not icon/logo/spacer)."""
        if not url or url.startswith("data:"):
            return False
        lower = url.lower()
        if any(skip in lower for skip in ("icon", "logo", "avatar", "pixel", "spacer", "blank", "favicon")):
            return False
        return True

    seen_srcs: set[str] = set()
    result_images: list[str] = []

    def _add_image(url: str) -> bool:
        """Add image URL if valid and not duplicate. Returns True if added."""
        normalized = _normalize_url(url)
        if not normalized or normalized in seen_srcs or not _is_valid_image(normalized):
            return False
        seen_srcs.add(normalized)
        result_images.append(normalized)
        return len(result_images) < max_images

    # Strategy 1: JSON-LD images (all from @type: Product)
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
            raw_img = item.get("image")
            if isinstance(raw_img, list):
                for img_item in raw_img:
                    if isinstance(img_item, dict):
                        _add_image(img_item.get("url", ""))
                    elif isinstance(img_item, str):
                        _add_image(img_item)
            elif isinstance(raw_img, dict):
                _add_image(raw_img.get("url", ""))
            elif isinstance(raw_img, str):
                _add_image(raw_img)
            if len(result_images) >= max_images:
                return result_images

    # Strategy 2: OG image meta tag
    for attr in ("property", "name"):
        tag = soup.find("meta", attrs={attr: "og:image"})
        if tag and tag.get("content"):
            _add_image(str(tag["content"]).strip())
            if len(result_images) >= max_images:
                return result_images

    # Strategy 3: <img> with product-related attributes
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
    for selector in product_img_selectors:
        for img in soup.select(selector):
            src = str(img.get("src", "")).strip()
            if not src:
                continue
            # Skip tiny images (icons, spacers, etc.)
            width = str(img.get("width", ""))
            height = str(img.get("height", ""))
            try:
                if width and int(width) < 100:
                    continue
                if height and int(height) < 100:
                    continue
            except (ValueError, TypeError):
                pass
            _add_image(src)
            if len(result_images) >= max_images:
                return result_images

    # Strategy 4: <img> with descriptive alt text (product views)
    # Look for images with alt text containing view patterns like "Front", "Back", "Left", etc.
    view_patterns = ("front", "back", "left", "right", "side", "view", "angle", "hero", "main")
    for img in soup.find_all("img"):
        src = str(img.get("src", "")).strip()
        if not src:
            continue
        alt = str(img.get("alt") or "").lower()
        # Match images with view-related alt text
        if any(pat in alt for pat in view_patterns):
            _add_image(src)
            if len(result_images) >= max_images:
                return result_images

    # Strategy 5: Any reasonably sized <img> in the page (last resort)
    for img in soup.find_all("img"):
        src = str(img.get("src", "")).strip()
        if not src:
            continue
        # Check alt text for product hints
        alt = str(img.get("alt") or "").lower()
        if any(kw in alt for kw in ("product", "producto", "image", "foto")):
            _add_image(src)
            if len(result_images) >= max_images:
                return result_images

    return result_images


def _extract_brand_specs(soup: BeautifulSoup, marca: str = "") -> list[dict[str, str]]:
    """Extract specs from brand-specific dynamic containers.

    Many manufacturer sites (Samsung, LG, etc.) render specs via JS into
    custom component classes instead of standard ``<table>`` elements.
    This function tries a curated list of known selectors and returns the
    first set of results that yields at least one characteristic.

    *marca* (lowercase) is used to gate network-backed extractors (TCL)
    so we only hit their APIs for the matching brand.
    """
    features: list[dict[str, str]] = []
    seen: set[str] = set()

    # ── TCL: JSON API via #pageData + data-api ────────────────────────────
    if marca == "tcl":
        tcl_features = spec_extractors.extract_tcl_specs(soup)
        for tf in tcl_features:
            if tf["nombre"].lower() not in seen:
                seen.add(tf["nombre"].lower())
                features.append(tf)
        if features:
            return features

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


def force_full_page_load(driver: webdriver.Chrome) -> None:
    """Progressive-scroll + expand all hidden content so page_source is complete.

    Steps:
      1. Smooth incremental scroll to bottom (triggers IntersectionObserver
         and other lazy-load hooks).
      2. Click / open every collapsed accordion, <details>, and
         button[aria-expanded="false"].
      3. Scroll back to top and let the browser settle.
    """
    # 1. Progressive scroll down in 500px increments
    scroll_pause = 0.3
    driver.execute_script("""
        return (async () => {
            const delay = ms => new Promise(r => setTimeout(r, ms));
            const step = 500;
            const max  = document.body.scrollHeight;
            for (let y = 0; y <= max; y += step) {
                window.scrollTo({top: y, behavior: 'smooth'});
                await delay(""" + str(int(scroll_pause * 1000)) + """);
            }
            window.scrollTo(0, document.body.scrollHeight);
            await delay(500);
        })();
    """)
    time.sleep(1)

    # 2. Expand all collapsed elements
    driver.execute_script("""
        // buttons / divs with aria-expanded="false"
        document.querySelectorAll(
            '[aria-expanded="false"], details:not([open])'
        ).forEach(el => {
            try { el.click(); } catch(e) {}
            if (el.tagName === 'DETAILS') el.open = true;
        });
        // common accordion / tab triggers
        document.querySelectorAll(
            '[class*="accordion"] > [role="button"],' +
            '[class*="Accordion"] > [role="button"],' +
            '[class*="tab"][role="tab"]:not([aria-selected="true"]),' +
            '.collapsible-header, .expand-more, .show-more'
        ).forEach(el => { try { el.click(); } catch(e) {} });
    """)
    time.sleep(1.5)

    # 3. Scroll back to top and let animations finish
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)


def _extract_logitech_specs(html: str, url: str = "") -> list[dict[str, str]]:
    """Extract specs from Logitech product pages.

    Logitech embeds structured spec data in JavaScript objects with two
    patterns:

    1. Physical dimensions (nested specs:{spec:[...]})
       Dimensions:{facet:"Dimensiones",...,specs:{spec:[
         {facet:"Mouse MX Master 3S",...,specs:{spec:[
           {facet:"Altura",value:"124.9 mm",...},
           ...
         ]}},
       ]}}

    2. Technical specs (facet + values array)
       {facet:"Tecnología del sensor",values:[{value:"Alta precisión Darkfield",...}]}

    This function extracts both patterns via regex on the raw HTML.
    """
    import re

    features: list[dict[str, str]] = []
    seen: set[str] = set()

    try:
        # ── Strategy 1: Physical dimensions (nested specs:{spec:[...]}) ──
        # The Dimensions block contains nested spec arrays.  We cannot use
        # a simple [^}] bracket-counting regex because the content itself
        # contains nested braces.  Instead, find every leaf-level
        # facet:"Name",value:"Value" pair inside the Dimensions block.
        #
        # Locate the Dimensions block start → grab a large window after it
        dim_start = re.search(r'Dimensions:\{', html)
        if dim_start:
            # Grab up to 3000 chars after Dimensions:{ — enough for all
            # nested specs (mouse + receiver) without crossing into the
            # next top-level key.
            window = html[dim_start.start():dim_start.start() + 3000]
            # Leaf specs have: facet:"Name",value:"NonEmpty",numeric:
            # Skip entries with value:"" (section headers like "Mouse MX Master 3S")
            for m in re.finditer(
                r'facet:"([^"]+)",value:"([^"]+)",numeric:', window
            ):
                name, value = m.group(1), m.group(2)
                if name not in seen:
                    seen.add(name)
                    features.append({"nombre": name, "valor": value})

        # ── Strategy 2: Technical specs (facet + values:[{value:...}]) ──
        # These appear in sections: connectivity, sensor, battery, etc.
        # Pattern: facet:"FacetName",values:[{value:"ValueStr",variants:
        for m in re.finditer(
            r'facet:"([^"]+)",values:\[\{value:"([^"]*)"',
            html,
        ):
            name, value = m.group(1), m.group(2)
            if value and name not in seen:
                seen.add(name)
                features.append({"nombre": name, "valor": value})

        # ── Strategy 3: Visible DOM text (fallback) ─────────────────────
        # After force_full_page_load, accordions are open and spec text
        # is rendered.  Parse "Key: Value" lines from body text.
        body_soup = BeautifulSoup(html, "lxml")
        body_text = body_soup.get_text(separator="\n")
        _SKIP = {"mouse mx master 3s", "receiver usb logi bolt (sólo para standard edition)"}
        for line in body_text.split("\n"):
            line = line.strip()
            if ":" not in line:
                continue
            # Split on first colon only
            name, _, value = line.partition(":")
            name, value = name.strip(), value.strip()
            if (
                name
                and value
                and len(name) < 60
                and len(value) < 200
                and name.lower() not in _SKIP
                and name.lower() not in seen
            ):
                seen.add(name.lower())
                features.append({"nombre": name, "valor": value})

    except Exception as exc:
        logger.warning("  LOGITECH  extraction failed: %s", exc)

    return features


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
        "/product-center", "/catalog", "/category",
        "/list", "/shop", "/store", "/collection", "/all",
        "?page=", "&page=", "/p-", "/page-",
        "/search/", "/buscar/",
    ]

    # Check if URL matches category patterns
    is_category_url = any(pat in url_lower for pat in category_url_patterns)

    # Exclude product detail pages: URLs ending in .html, with numeric IDs,
    # or paths that look like product slugs (e.g., /products/2024/12/13/...)
    if is_category_url:
        path = url.split("?")[0]  # Remove query params
        segments = path.rstrip("/").split("/")

        # URLs ending in .html are typically product detail pages
        if path.endswith(".html"):
            is_category_url = False
        # URLs with many numeric segments (like Brother's date-based IDs)
        elif sum(1 for seg in segments if seg.isdigit()) >= 3:
            is_category_url = False
        # URLs with "products" followed by date-like patterns
        elif "/products/" in url_lower:
            # Check if it looks like a product detail page
            after_products = url_lower.split("/products/")[1] if "/products/" in url_lower else ""
            if re.search(r'\d{4}/\d{2}/\d{2}', after_products):
                is_category_url = False

    if is_category_url:
        # Check if it's actually a product page with JSON-LD Product
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string
            if raw and '"Product"' in raw:
                return False
        return True

    # HTML-based detection: multiple product cards/links in the main content area
    # Exclude navigation, header, footer elements
    product_card_selectors = [
        "main [class*='product-card']",
        "main [class*='ProductCard']",
        "main [class*='product-item']",
        "main [class*='product-grid']",
        "main [class*='product-list']",
        "main [data-testid*='product-card']",
        ".content [class*='product-card']",
        ".content [class*='product-item']",
    ]
    for selector in product_card_selectors:
        cards = soup.select(selector)
        if len(cards) >= 3:  # 3+ product cards in main content = likely category page
            return True

    # Check for filter/facet elements (common on category pages)
    # Only count if there are also product detail links in the main content
    filter_selectors = [
        "main [class*='filter']",
        "main [class*='Filter']",
        "main [class*='facet']",
        "main [class*='Facet']",
        ".content [class*='filter']",
        ".content [class*='facet']",
    ]
    for selector in filter_selectors:
        if soup.select(selector):
            # Filters + multiple product detail links = category page
            links = soup.find_all("a", href=True)
            product_links = [
                a for a in links
                if any(kw in str(a.get("href") or "").lower()
                       for kw in ("/product", "/item", "/detail", "/p/"))
            ]
            if len(product_links) >= 3:
                return True

    # Heuristic: many product links in main content but no JSON-LD Product = category page
    main_content = soup.find("main") or soup.find("article") or soup.find(class_="content")
    if main_content:
        links = main_content.find_all("a", href=True)
        product_link_count = sum(
            1 for a in links
            if any(kw in str(a.get("href") or "").lower()
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
        href = str(a.get("href", ""))
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
        Normalized product data dict on success,
        ``None`` if the fetch or parse fails.

    Side effects
    -------------
    - Writes characteristics into ``producto_caracteristicas`` (EAV).
    - Updates ``productos.proposal_json``, ``productos.marca``,
      ``productos.modelo``, ``productos.imagen_url``.
    - Appends an audit log entry.
    """
    logger.info("  MANUAL_URL  id=%d  fetching %s", product_id, url)

    # Spec-sheet PDFs (gfast & co.): download + extract directly, no Selenium.
    if (url or "").lower().split("?")[0].rstrip("/").endswith(".pdf"):
        return _scrape_pdf_datasheet(url, product_id)

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

        # Hydrate: progressive scroll + expand accordions + settle
        # Increase script timeout for async scroll JS on heavy pages
        # Non-fatal: specs are usually rendered at page load already; the
        # smooth-scroll can exceed the timeout on heavy pages (Samsung 4MB+),
        # but a partial DOM is still usable.
        driver.set_script_timeout(60)
        try:
            force_full_page_load(driver)
        except Exception as exc:
            logger.warning(
                "  MANUAL_URL  id=%d  force_full_page_load failed (%s), "
                "proceeding with partial DOM",
                product_id, exc,
            )
        driver.set_script_timeout(SELENIUM_TIMEOUT)
        logger.debug(
            "  MANUAL_URL  id=%d  force_full_page_load done", product_id
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
                driver.set_script_timeout(60)
                force_full_page_load(driver)
                driver.set_script_timeout(SELENIUM_TIMEOUT)
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

    # 1. Try enhanced JSON-LD (most structured, includes QuantitativeValue)
    result = spec_extractors.extract_jsonld_product(soup)

    # 2. Fallback to OG / meta tags (enhanced with product: tags)
    if not result:
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
        logger.warning("  MANUAL_URL  id=%d  no product data found at %s", product_id, url)
        return None

    # 2b. Backfill marca/modelo from DB product name when scraper didn't find them
    if not result.get("marca") or not result.get("modelo"):
        try:
            _conn = get_connection()
            try:
                _row = _conn.execute(
                    "SELECT nombre, marca FROM productos WHERE id_prestashop = ?",
                    (product_id,),
                ).fetchone()
            finally:
                _conn.close()
            if _row:
                db_nombre = _row["nombre"] or ""
                if not result.get("marca"):
                    inferred = _infer_brand_from_name(db_nombre)
                    if inferred:
                        result["marca"] = inferred.title()
                        logger.info(
                            "  MANUAL_URL  id=%d  inferred marca=%r from product name",
                            product_id, inferred,
                        )
                if not result.get("modelo"):
                    title = result.get("title") or db_nombre
                    model = _extract_model_from_name(title, result.get("marca") or "")
                    if model:
                        result["modelo"] = model
                        logger.info(
                            "  MANUAL_URL  id=%d  inferred modelo=%r from title",
                            product_id, model,
                        )
        except Exception as exc:
            logger.debug("  MANUAL_URL  id=%d  marca/modelo inference failed: %s", product_id, exc)

    # 3. Augment with generic + brand-specific spec extractors
    existing_names = {
        ch["nombre"].lower().strip()
        for ch in (result.get("caracteristicas") or [])
    }

    # 3a. Brand-specific extraction (Logitech, Samsung, LG, Brother, Pantum)
    marca_lower = (result.get("marca") or "").lower()

    # Logitech: regex on JS-embedded spec objects + body text
    if marca_lower == "logitech" and page_source:
        logger.info("  MANUAL_URL  id=%d  trying Logitech-specific extraction", product_id)
        logitech_features = _extract_logitech_specs(page_source, final_url)
        for lf in logitech_features:
            if lf["nombre"].lower().strip() not in existing_names:
                result["caracteristicas"].append(lf)
                existing_names.add(lf["nombre"].lower().strip())
        logger.info(
            "  MANUAL_URL  id=%d  Logitech extraction: %d specs",
            product_id, len(logitech_features),
        )

    # Samsung, LG, Brother, Pantum and other brand-specific selectors
    brand_features = _extract_brand_specs(soup, marca_lower)
    for bf in brand_features:
        if bf["nombre"].lower().strip() not in existing_names:
            result["caracteristicas"].append(bf)
            existing_names.add(bf["nombre"].lower().strip())

    # 3b. Generic extractors (work across all sites without per-brand config)
    _generic_extractors = [
        ("tables", spec_extractors.extract_tables),
        ("dl/dt/dd", spec_extractors.extract_dl_dt_dd),
        ("microdata", spec_extractors.extract_microdata),
        ("div_spec_rows", spec_extractors.extract_div_spec_rows),
    ]
    for name, extractor in _generic_extractors:
        try:
            generic_features = extractor(soup)
            added = 0
            for gf in generic_features:
                if gf["nombre"].lower().strip() not in existing_names:
                    result["caracteristicas"].append(gf)
                    existing_names.add(gf["nombre"].lower().strip())
                    added += 1
            if added:
                logger.debug(
                    "  MANUAL_URL  id=%d  %s: +%d specs",
                    product_id, name, added,
                )
        except Exception as exc:
            logger.debug("  MANUAL_URL  id=%d  %s extractor failed: %s", product_id, name, exc)

    # 3b2. body-text fallback — only when structured extractors under-produced.
    # It scans rendered text for "Key: Value" lines and is noisy on JS-heavy
    # pages (variant selectors, review snippets, navigation help).  Skipping it
    # when we already have a solid set avoids pushing junk characteristics.
    if len(result.get("caracteristicas") or []) < 10:
        try:
            bt_features = spec_extractors.extract_body_text_specs(soup)
            for bf in bt_features:
                if bf["nombre"].lower().strip() not in existing_names:
                    result["caracteristicas"].append(bf)
                    existing_names.add(bf["nombre"].lower().strip())
            if bt_features:
                logger.debug(
                    "  MANUAL_URL  id=%d  body_text: +%d specs",
                    product_id, len(bt_features),
                )
        except Exception as exc:
            logger.debug("  MANUAL_URL  id=%d  body_text extractor failed: %s", product_id, exc)

    # 3c. JS state objects extraction (Next.js, Nuxt, etc.)
    if page_source:
        try:
            js_features = spec_extractors.extract_js_state_objects(page_source)
            for jf in js_features:
                if jf["nombre"].lower().strip() not in existing_names:
                    result["caracteristicas"].append(jf)
                    existing_names.add(jf["nombre"].lower().strip())
            if js_features:
                logger.debug(
                    "  MANUAL_URL  id=%d  js_state: +%d specs",
                    product_id, len(js_features),
                )
        except Exception as exc:
            logger.debug("  MANUAL_URL  id=%d  js_state extraction failed: %s", product_id, exc)

    # 3a. PDF spec sheet fallback (for brands like Xerox that publish specs in PDFs)
    MIN_CHARS_FOR_PDF = 5
    if len(result.get("caracteristicas") or []) < MIN_CHARS_FOR_PDF:
        from .pdf_scraper import extract_specs_from_pdf, find_spec_pdf_links

        pdf_links = find_spec_pdf_links(soup, final_url)
        if pdf_links:
            logger.info(
                "  MANUAL_URL  id=%d  found %d PDF links, trying extraction",
                product_id, len(pdf_links),
            )
            # Try the first spec PDF link
            for pdf_info in pdf_links[:1]:  # Try first PDF only
                pdf_url = pdf_info["url"]
                pdf_text = pdf_info.get("text", "")
                logger.info("  MANUAL_URL  id=%d  trying PDF: %s (%s)", product_id, pdf_url[:80], pdf_text[:50])
                pdf_data = extract_specs_from_pdf(
                    pdf_url,
                    marca=result.get("marca") or "",
                    modelo=result.get("modelo") or "",
                )
                if pdf_data and pdf_data.get("caracteristicas"):
                    # Merge PDF characteristics (don't overwrite existing)
                    existing_names = {
                        ch["nombre"].lower().strip()
                        for ch in (result.get("caracteristicas") or [])
                    }
                    for pc in pdf_data["caracteristicas"]:
                        if pc["nombre"].lower().strip() not in existing_names:
                            result["caracteristicas"].append(pc)
                    logger.info(
                        "  MANUAL_URL  id=%d  PDF extraction succeeded (%d new characteristics)",
                        product_id, len(pdf_data["caracteristicas"]),
                    )
                    break

    # 3b. If no image from JSON-LD/OG, try <img> tag extraction
    if not result.get("imagen_url"):
        img_url = _extract_image(soup, final_url)
        if img_url:
            result["imagen_url"] = img_url
            # Also add to imagen_urls if not already there
            if img_url not in result.get("imagen_urls", []):
                result.setdefault("imagen_urls", []).append(img_url)

    # 3c. Ensure we have multiple images if possible
    if len(result.get("imagen_urls") or []) < 2:
        more_imgs = _extract_images(soup, final_url, max_images=4)
        for img in more_imgs:
            if img not in result.get("imagen_urls", []):
                result.setdefault("imagen_urls", []).append(img)
        # Update main imagen_url if still empty
        if not result.get("imagen_url") and result.get("imagen_urls"):
            result["imagen_url"] = result["imagen_urls"][0]

    # 3c. Final cleanup: drop obvious junk characteristics regardless of source
    # (title duplication, bare size-word names, review/navigation noise).
    cleaned = []
    for ch in (result.get("caracteristicas") or []):
        chn = str(ch.get("nombre") or "").strip()
        chv = str(ch.get("valor") or "").strip()
        chn_lower = chn.lower()
        if chn_lower in ("tamaño", "talla", "size", "medida", "pantalla", "dimension", "dimensions"):
            continue
        junk_tokens = ("review", "promotion", "trustmark", "navigate to", "go to ", "to do this", "to fine-tune")
        if any(j in chn_lower for j in junk_tokens):
            continue
        if len(chn) > 20 and chn_lower == chv.lower():
            continue
        cleaned.append(ch)
    if len(cleaned) != len(result.get("caracteristicas") or []):
        logger.info(
            "  MANUAL_URL  id=%d  cleanup dropped %d junk characteristics",
            product_id, len(result.get("caracteristicas") or []) - len(cleaned),
        )
    result["caracteristicas"] = cleaned

    logger.info(
        "  MANUAL_URL  id=%d  extracted %d characteristics from %s",
        product_id, len(result.get("caracteristicas") or []), final_url,
    )

    # Store source URL for validation
    result["url"] = url

    # 4. Persist to DB
    _persist_scrape_result(product_id, result, source="manual_url", url=url)

    logger.info(
        "  MANUAL_URL  id=%d  saved %s %s (%d chars)",
        product_id,
        (result.get("marca") or "").strip(),
        (result.get("modelo") or "").strip(),
        len(result.get("caracteristicas") or []),
    )
    return result


def _persist_scrape_result(product_id: int, result: dict, source: str, url: str) -> None:
    """Persist a scraped product result to the local DB.

    Updates ``productos`` (proposal JSON, marca/modelo, imagen, status) with
    the *source* URL, appends an audit entry, and writes the EAV
    characteristics — all in one transaction.
    """
    conn = get_connection()
    try:
        marca = (result.get("marca") or "").strip()
        modelo = (result.get("modelo") or "").strip()
        imagen = (result.get("imagen_url") or "").strip() or None

        conn.execute(
            """UPDATE productos
               SET proposal_json = ?,
                   marca           = COALESCE(NULLIF(?, ''), marca),
                   modelo          = COALESCE(NULLIF(?, ''), modelo),
                   imagen_url      = COALESCE(?, imagen_url),
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
            "source": source,
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

        # Write EAV using the same connection
        write_eav(conn, product_id, result.get("caracteristicas") or [])
        conn.commit()
    finally:
        conn.close()


def _scrape_pdf_datasheet(pdf_url: str, product_id: int) -> dict | None:
    """Download a spec-sheet PDF and persist the extracted characteristics.

    Used for brands whose data sheets are PDFs (gfast) reached via the
    ``pdf_sitemap`` strategy or pasted manually in the Admin UI.

    Some data sheets are image-based PDFs with no extractable text; those are
    supplemented from the "Key: Value" spec lines rendered inline on the
    category page the PDF was found on.
    """
    from .pdf_scraper import extract_specs_from_pdf

    logger.info("  PDF_DATASHEET  id=%d  extracting %s", product_id, pdf_url[:100])

    data = extract_specs_from_pdf(pdf_url, marca="", modelo="")
    characteristics = (data.get("caracteristicas") or []) if data else []

    # Fall back to the inline spec lines of the category page the PDF came from
    if len(characteristics) < 5:
        seen = {c["nombre"].lower().strip() for c in characteristics}
        for page_url in _pages_for_pdf(pdf_url):
            soup, _links = _fetch_page(page_url)
            inline = _extract_inline_specs_from_soup(soup, pdf_url)
            if inline:
                logger.info(
                    "  PDF_DATASHEET  id=%d  %d inline specs from %s",
                    product_id, len(inline), page_url,
                )
                for ic in inline:
                    if ic["nombre"].lower().strip() not in seen:
                        characteristics.append(ic)
                        seen.add(ic["nombre"].lower().strip())
            if len(characteristics) >= 5:
                break

    if not characteristics:
        logger.warning(
            "  PDF_DATASHEET  id=%d  no characteristics extracted from %s",
            product_id, pdf_url[:100],
        )
        return None

    result = {
        "title": "",
        "descripcion": "",
        "descripcion_corta": "",
        "marca": "",
        "modelo": "",
        "resumen": "",
        "caracteristicas": characteristics,
        "imagen_url": "",
        "imagen_urls": [],
        "_source": "pdf_scraper",
    }

    # Backfill marca/modelo from the DB product name when the PDF has none
    try:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT nombre FROM productos WHERE id_prestashop = ?",
                (product_id,),
            ).fetchone()
        finally:
            conn.close()
        db_nombre = (row["nombre"] or "") if row else ""
        if db_nombre:
            inferred = _infer_brand_from_name(db_nombre)
            if inferred:
                result["marca"] = inferred.title()
                logger.info(
                    "  PDF_DATASHEET  id=%d  inferred marca=%r from product name",
                    product_id, inferred,
                )
            # gfast models embed hyphens (T-195, N-536R) which
            # _extract_model_from_name strips away, so derive the modelo from
            # the digit-bearing model tokens instead of the noisy name words.
            digit_tokens = [
                t for t in _extract_pdf_model_tokens(db_nombre, inferred or "")
                if any(ch.isdigit() for ch in t)
            ]
            if digit_tokens:
                model = max(digit_tokens, key=len).upper()
                result["modelo"] = model
                logger.info(
                    "  PDF_DATASHEET  id=%d  inferred modelo=%r from product name",
                    product_id, model,
                )
    except Exception as exc:
        logger.debug(
            "  PDF_DATASHEET  id=%d  marca/modelo inference failed: %s",
            product_id, exc,
        )

    result["url"] = pdf_url

    _persist_scrape_result(
        product_id, result, source="pdf_sitemap", url=pdf_url,
    )

    logger.info(
        "  PDF_DATASHEET  id=%d  saved %s %s (%d chars)",
        product_id,
        result["marca"],
        result["modelo"],
        len(result["caracteristicas"]),
    )
    return result



