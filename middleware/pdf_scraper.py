"""PDF specification extractor for product data sheets.

Downloads PDF spec sheets and extracts key-value pairs (characteristics)
using pdfplumber for table and text extraction.
"""

import io
import logging
import re
from typing import TYPE_CHECKING

import pdfplumber
import requests

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Keywords that indicate a PDF is a spec sheet / data sheet
_SPEC_KEYWORDS = (
    "ficha", "specs", "especificaciones", "datasheet", "data-sheet",
    "specifications", "technical", "tecnica", "caracteristicas",
    "hoja de datos", "ficha tecnica", "ficha técnica",
)

# Keywords to skip (manuals, guides, etc.)
_SKIP_KEYWORDS = (
    "manual", "guia", "guía", "tutorial", "soporte", "support",
    "faq", "preguntas", "solucion", "troubleshoot", "service",
    "repair", "warranty", "garantia", "garantía",
)


def _is_spec_pdf_url(url: str, link_text: str = "") -> bool:
    """Check if a URL points to a spec sheet PDF."""
    url_lower = url.lower()
    text_lower = link_text.lower()

    # Must be a PDF
    if not url_lower.endswith(".pdf"):
        return False

    # Skip manuals/guides
    if any(skip in url_lower or skip in text_lower for skip in _SKIP_KEYWORDS):
        return False

    # Check for spec keywords
    if any(kw in url_lower or kw in text_lower for kw in _SPEC_KEYWORDS):
        return True

    # If no clear signal, assume it might be a spec sheet
    return True


def _download_pdf(url: str, timeout: int = 30) -> bytes | None:
    """Download PDF content from URL."""
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        })
        resp.raise_for_status()

        # Verify it's actually a PDF
        content_type = resp.headers.get("Content-Type", "")
        if "pdf" not in content_type and not resp.content[:5] == b"%PDF-":
            logger.warning("  PDF_SCRAPER  URL does not point to a PDF: %s", url[:80])
            return None

        return resp.content
    except requests.RequestException as exc:
        logger.warning("  PDF_SCRAPER  failed to download %s: %s", url[:80], exc)
        return None


def _extract_tables_from_pdf(pdf_bytes: bytes) -> list[dict[str, str]]:
    """Extract key-value pairs from PDF tables."""
    characteristics: list[dict[str, str]] = []
    seen_keys: set[str] = set()

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    for row in table:
                        if not row or len(row) < 2:
                            continue
                        # Clean cells
                        key = str(row[0] or "").strip()
                        value = str(row[1] or "").strip()

                        # Skip empty or very short entries
                        if not key or not value or len(key) < 2 or len(value) < 2:
                            continue

                        # Skip headers/labels that look like column names
                        if key.lower() in ("specification", "feature", "parameter", "property"):
                            continue

                        # Deduplicate
                        key_norm = key.lower().strip()
                        if key_norm in seen_keys:
                            continue
                        seen_keys.add(key_norm)

                        characteristics.append({"nombre": key, "valor": value})
    except Exception as exc:
        logger.warning("  PDF_SCRAPER  failed to extract tables: %s", exc)

    return characteristics


def _extract_text_from_pdf(pdf_bytes: bytes) -> list[dict[str, str]]:
    """Extract key-value pairs from PDF text using regex patterns."""
    characteristics: list[dict[str, str]] = []
    seen_keys: set[str] = set()

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"

            if not full_text:
                return characteristics

            # Pattern 1: "Key: Value" or "Key : Value"
            # Pattern 2: "Key\tValue" (tab-separated)
            # Pattern 3: Lines with "Key ... Value" (dots or spaces)
            patterns = [
                r"^([A-Za-zÀ-ÿ\s\-\(\)]+?)\s*:\s*(.+)$",  # Key: Value
                r"^([A-Za-zÀ-ÿ\s\-\(\)]+?)\t+(.+)$",  # Tab-separated
                r"^([A-Za-zÀ-ÿ\s\-\(\)]+?)\s*\.{2,}\s*(.+)$",  # Key...Value
            ]

            for line in full_text.split("\n"):
                line = line.strip()
                if not line or len(line) < 5:
                    continue

                for pattern in patterns:
                    match = re.match(pattern, line, re.MULTILINE)
                    if match:
                        key = match.group(1).strip()
                        value = match.group(2).strip()

                        # Skip entries that look like headers or section titles
                        if len(key) > 50 or len(value) > 200:
                            continue
                        if key.lower() in ("specification", "feature", "table of contents"):
                            continue

                        # Deduplicate
                        key_norm = key.lower().strip()
                        if key_norm in seen_keys:
                            continue
                        seen_keys.add(key_norm)

                        characteristics.append({"nombre": key, "valor": value})
                        break  # Only match first pattern per line

    except Exception as exc:
        logger.warning("  PDF_SCRAPER  failed to extract text: %s", exc)

    return characteristics


def extract_specs_from_pdf(
    pdf_url: str,
    marca: str = "",
    modelo: str = "",
) -> dict | None:
    """Download a PDF spec sheet and extract characteristics.

    Parameters
    ----------
    pdf_url:
        URL of the PDF spec sheet.
    marca:
        Brand name (for logging).
    modelo:
        Model number (for logging).

    Returns
    -------
    dict | None
        Normalized product data dict with extracted characteristics,
        or None if extraction fails.
    """
    logger.info("  PDF_SCRAPER  downloading: %s", pdf_url[:100])

    pdf_bytes = _download_pdf(pdf_url)
    if not pdf_bytes:
        return None

    logger.info("  PDF_SCRAPER  downloaded %d bytes, extracting...", len(pdf_bytes))

    # Try table extraction first (more structured)
    chars = _extract_tables_from_pdf(pdf_bytes)

    # Fall back to text extraction if no tables found
    if len(chars) < 3:
        logger.info("  PDF_SCRAPER  few table results (%d), trying text extraction", len(chars))
        text_chars = _extract_text_from_pdf(pdf_bytes)
        # Merge, preferring table results
        existing_keys = {c["nombre"].lower() for c in chars}
        for tc in text_chars:
            if tc["nombre"].lower() not in existing_keys:
                chars.append(tc)
                existing_keys.add(tc["nombre"].lower())

    if not chars:
        logger.info("  PDF_SCRAPER  no characteristics extracted from PDF")
        return None

    logger.info("  PDF_SCRAPER  extracted %d characteristics", len(chars))

    return {
        "title": "",
        "descripcion": "",
        "descripcion_corta": "",
        "marca": marca,
        "modelo": modelo,
        "resumen": "",
        "caracteristicas": chars,
        "imagen_url": "",
        "imagen_urls": [],
        "_source": "pdf_scraper",
    }


def find_spec_pdf_links(
    soup: "BeautifulSoup",
    base_url: str = "",
) -> list[dict[str, str]]:
    """Find spec sheet PDF links in a BeautifulSoup parsed page.

    Parameters
    ----------
    soup:
        Parsed HTML page.
    base_url:
        Base URL for resolving relative links.

    Returns
    -------
    list[dict]
        List of {"url": str, "text": str} for found PDF links.
    """
    from urllib.parse import urljoin

    pdf_links: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        href = str(a_tag["href"]).strip()
        if not href.lower().endswith(".pdf"):
            continue

        # Resolve relative URLs
        if base_url and not href.startswith(("http://", "https://")):
            href = urljoin(base_url, href)

        if href in seen_urls:
            continue
        seen_urls.add(href)

        link_text = a_tag.get_text(strip=True)

        if _is_spec_pdf_url(href, link_text):
            pdf_links.append({"url": href, "text": link_text})

    return pdf_links
