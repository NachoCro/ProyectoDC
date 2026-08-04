"""Generic product specification extractors.

Shared extraction strategies used by both ``official_scraper`` and
``ai_agent``.  These work across most manufacturer websites without
per-brand configuration.
"""

import json
import logging
import re
from typing import cast

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


def is_template_placeholder(text: str) -> bool:
    """Detect JS template-placeholder garbage (e.g. ``{{upgrade.yesAttr.text}}``).

    Samsung and other brands hide Knockout/Angular templates in the DOM that
    extractors pick up as fake specs.  These contain ``{{...}}``, ``[[...]]``
    or ``${...}`` tokens and must never be stored as characteristics.
    """
    if not text:
        return False
    return bool(
        re.search(r"\{\{.*\}\}", text)
        or re.search(r"\[\[.*\]\]", text)
        or re.search(r"\$\{.*\}", text)
    )


def clean_feature(name: str, value: str) -> tuple[str, str]:
    """Return ``(name, value)`` or ``("", "")`` if either is placeholder garbage."""
    if is_template_placeholder(name) or is_template_placeholder(value):
        return "", ""
    return (name or "").strip(), (value or "").strip()


# ── HTML Table extraction ────────────────────────────────────────────────────


def extract_tables(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract key-value pairs from ``<table>`` spec blocks.

    Handles:
    - Standard 2-column tables (``<tr><td>Key</td><td>Value</td>``)
    - Tables with category headers spanning full width
    - GSMArena-style ``td.ttl`` / ``td.nfo`` patterns
    """
    features: list[dict[str, str]] = []
    seen: set[str] = set()

    for table in soup.find_all("table"):
        current_section = ""
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])

            # Category header row (colspan or single th)
            if len(cells) == 1:
                header = cells[0]
                text = header.get_text(strip=True)
                if text and len(text) < 80:
                    current_section = text
                continue

            # Skip non-2-cell rows (3+ column comparison tables, etc.)
            if len(cells) != 2:
                continue

            name, value = clean_feature(cells[0].get_text(strip=True), cells[1].get_text(strip=True))
            if not name or not value or len(name) < 2 or len(value) < 2:
                continue

            key_norm = name.lower().strip()
            if key_norm in seen:
                continue
            seen.add(key_norm)

            # Prefix with section if available
            display_name = f"{current_section} - {name}" if current_section else name
            features.append({"nombre": display_name, "valor": value})

    return features


# ── Definition List extraction ────────────────────────────────────────────────


def extract_dl_dt_dd(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract key-value pairs from ``<dl>`` definition lists.

    Walks ``<dt>`` / ``<dd>`` pairs.  Also handles ``<ul>`` / ``<ol>``
    with ``<strong>`` or ``<b>`` labels followed by text values.
    """
    features: list[dict[str, str]] = []
    seen: set[str] = set()

    # Strategy 1: Standard dl/dt/dd
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            name, value = clean_feature(dt.get_text(strip=True), dd.get_text(strip=True))
            if name and value and len(name) >= 2 and len(value) >= 2:
                key_norm = name.lower().strip()
                if key_norm not in seen:
                    seen.add(key_norm)
                    features.append({"nombre": name, "valor": value})

    # Strategy 2: <li> with <strong>/<b> label + colon or text value
    for li in soup.find_all("li"):
        strong = li.find(["strong", "b"])
        if not strong:
            continue
        label = strong.get_text(strip=True).rstrip(":")
        if not label or len(label) < 2:
            continue
        # Get remaining text after the strong tag
        remaining = li.get_text(strip=True)
        # Remove the label from the beginning
        value = remaining[len(strong.get_text(strip=True)):].strip()
        # Also try text after colon if present
        if ":" in remaining:
            parts = remaining.split(":", 1)
            value = parts[1].strip()
        label, value = clean_feature(label, value)
        if value and len(value) >= 2:
            key_norm = label.lower().strip()
            if key_norm not in seen:
                seen.add(key_norm)
                features.append({"nombre": label, "valor": value})

    return features


# ── Microdata / itemprop extraction ───────────────────────────────────────────


def extract_microdata(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract specs from Schema.org microdata (``itemprop`` attributes).

    Walks the DOM looking for ``itemprop`` attributes within ``itemscope``
    contexts.  Extracts ``name`` + ``value`` pairs from
    ``PropertyValue`` structures, and top-level Product properties.
    """
    features: list[dict[str, str]] = []
    seen: set[str] = set()

    # Strategy 1: itemprop="additionalProperty" with PropertyValue
    for container in soup.find_all(attrs={"itemprop": "additionalProperty"}):  # type: ignore[call-overload]
        name_el = container.find(attrs={"itemprop": "name"})
        value_el = container.find(attrs={"itemprop": "value"})
        if name_el and value_el:
            name, value = clean_feature(name_el.get_text(strip=True), value_el.get_text(strip=True))
            if name and value and len(name) >= 2:
                key_norm = name.lower().strip()
                if key_norm not in seen:
                    seen.add(key_norm)
                    features.append({"nombre": name, "valor": value})

    # Strategy 2: itemprop pairs within itemscope Product blocks
    product_scope = soup.find(attrs={"itemtype": re.compile(r"schema\.org/Product")})  # type: ignore[call-overload]
    if product_scope:
        # Top-level Product properties that are specs
        _SPEC_PROPS = {
            "weight", "depth", "width", "height",
            "color", "material", "brand", "model",
            "memory", "storage", "processor",
        }
        for prop_name in _SPEC_PROPS:
            el = product_scope.find(attrs={"itemprop": prop_name})
            if el:
                value = el.get("content") or el.get_text(strip=True)
                if value and len(value) >= 2:
                    key_norm = prop_name.lower()
                    if key_norm not in seen:
                        seen.add(key_norm)
                        features.append({"nombre": prop_name.replace("_", " ").title(), "valor": value})

    # Strategy 3: itemprop="name" + itemprop="value" siblings
    for name_el in soup.find_all(attrs={"itemprop": "name"}):  # type: ignore[call-overload]
        parent = name_el.parent
        if not parent:
            continue
        value_el = parent.find(attrs={"itemprop": "value"})
        if not value_el:
            continue
        # Meta tags carry the value in the `content` attribute, not text.
        name, value = clean_feature(
            name_el.get("content") or name_el.get_text(strip=True),
            value_el.get("content") or value_el.get_text(strip=True),
        )
        if name and value and len(name) >= 2 and len(value) >= 2:
            key_norm = name.lower().strip()
            if key_norm not in seen:
                seen.add(key_norm)
                features.append({"nombre": name, "valor": value})

    return features


# ── Generic div-based spec row detection ──────────────────────────────────────


def extract_div_spec_rows(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Detect and extract specs from div-based key/value layouts.

    Scans the DOM for common patterns:
    - ``<div class="spec-label">...<div class="spec-value">...``
    - ``<div class="spec-row"><div class="spec-key">...<div class="spec-val">...``
    - BEM-style ``modblo-spec__key`` / ``modblo-spec__val``
    """
    features: list[dict[str, str]] = []
    seen: set[str] = set()

    # ── Pattern 1: CSS class-based label/value pairs ────────────────────────
    _LABEL_CLASSES = re.compile(
        r"(spec|attr|feature|detail|property|info)[_-]?(label|name|key|title|heading)",
        re.IGNORECASE,
    )
    _VALUE_CLASSES = re.compile(
        r"(spec|attr|feature|detail|property|info)[_-]?(value|val|desc|data|content|detail)",
        re.IGNORECASE,
    )

    label_els = soup.find_all(attrs={"class": _LABEL_CLASSES})  # type: ignore[call-overload]
    for label_el in label_els:
        # Find the sibling or nearby value element
        parent = label_el.parent
        if not parent:
            continue
        value_el = parent.find(attrs={"class": _VALUE_CLASSES})  # type: ignore[call-overload]
        if not value_el:
            continue
        name = label_el.get_text(strip=True)
        value = value_el.get_text(strip=True)
        if name and value and len(name) >= 2 and len(value) >= 2 and len(name) < 80:
            key_norm = name.lower().strip()
            if key_norm not in seen:
                seen.add(key_norm)
                features.append({"nombre": name, "valor": value})

    # ── Pattern 2: BEM-style spec rows ──────────────────────────────────────
    # e.g. <div class="modblo-spec__row"><div class="modblo-spec__key">...</div>
    _BEM_SPEC_ROW = re.compile(r"(spec|product|detail)[-_]?(row|item|entry|pair)", re.IGNORECASE)
    _BEM_KEY = re.compile(r"(key|name|label|title)", re.IGNORECASE)
    _BEM_VAL = re.compile(r"(val|value|desc|data|content)", re.IGNORECASE)

    for row in soup.find_all(attrs={"class": _BEM_SPEC_ROW}):  # type: ignore[call-overload]
        children = [c for c in row.children if isinstance(c, Tag)]
        if len(children) < 2:
            continue
        # Try to identify key/value by class names
        key_el = None
        val_el = None
        for child in children:
            classes = " ".join(cast(list[str], child.get("class") or []))
            if _BEM_KEY.search(classes) and not key_el:
                key_el = child
            elif _BEM_VAL.search(classes) and not val_el:
                val_el = child
        if key_el and val_el:
            name = key_el.get_text(strip=True)
            value = val_el.get_text(strip=True)
            if name and value and len(name) >= 2 and len(value) >= 2 and len(name) < 80:
                key_norm = name.lower().strip()
                if key_norm not in seen:
                    seen.add(key_norm)
                    features.append({"nombre": name, "valor": value})

    # ── Pattern 3: data-testid based extraction ──────────────────────────────
    _TESTID_SPEC = re.compile(r"spec(?:ification)?[-_]?(name|label|key|value|val)", re.IGNORECASE)
    testid_els = soup.find_all(attrs={"data-testid": _TESTID_SPEC})  # type: ignore[call-overload]
    for el in testid_els:
        testid = el.get("data-testid", "")
        parent = el.parent
        if not parent:
            continue
        # Find the matching pair
        if "name" in testid.lower() or "label" in testid.lower() or "key" in testid.lower():
            # This is a label, find its value sibling
            value_re = re.compile(r"spec(?:ification)?[-_]?(value|val)", re.IGNORECASE)
            value_el = parent.find(attrs={"data-testid": value_re})  # type: ignore[call-overload]
            if value_el:
                name = el.get_text(strip=True)
                value = value_el.get_text(strip=True)
                if name and value and len(name) >= 2 and len(value) >= 2:
                    key_norm = name.lower().strip()
                    if key_norm not in seen:
                        seen.add(key_norm)
                        features.append({"nombre": name, "valor": value})

    return features


# ── JSON-LD enhanced extraction ──────────────────────────────────────────────


def extract_jsonld_product(soup: BeautifulSoup) -> dict | None:
    """Extract product data from JSON-LD blocks (enhanced version).

    Extends the basic JSON-LD parser to also read:
    - ``additionalProperty`` (PropertyValue array)
    - Top-level Product properties: weight, depth, width, height
    - ``QuantitativeValue`` objects with value + unitText
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

            # Images
            img = ""
            imgs: list[str] = []
            raw_img = item.get("image")
            if isinstance(raw_img, list):
                for img_item in raw_img:
                    if isinstance(img_item, dict):
                        url = img_item.get("url", "")
                    elif isinstance(img_item, str):
                        url = img_item
                    else:
                        continue
                    if url:
                        imgs.append(url)
                        if not img:
                            img = url
            elif isinstance(raw_img, dict):
                img = raw_img.get("url", "")
                if img:
                    imgs.append(img)
            elif isinstance(raw_img, str):
                img = raw_img
                if img:
                    imgs.append(img)

            # Brand
            brand = ""
            raw_brand = item.get("brand")
            if isinstance(raw_brand, dict):
                brand = raw_brand.get("name", "")
            elif isinstance(raw_brand, str):
                brand = raw_brand

            modelo = item.get("mpn") or item.get("sku") or ""

            # Characteristics from additionalProperty
            features: list[dict[str, str]] = []
            for prop in item.get("additionalProperty") or []:
                n, v = clean_feature((prop.get("name") or "").strip(), (prop.get("value") or "").strip())
                if n and v:
                    features.append({"nombre": n, "valor": v})

            # Top-level QuantitativeValue properties
            _QUANT_PROPS = ("weight", "depth", "width", "height")
            for prop in _QUANT_PROPS:
                val = item.get(prop)
                if not val or prop in {f["nombre"].lower() for f in features}:
                    continue
                if isinstance(val, dict):
                    value = str(val.get("value", ""))
                    unit = val.get("unitText", "")
                    if value:
                        features.append({
                            "nombre": prop.title(),
                            "valor": f"{value} {unit}".strip(),
                        })
                elif isinstance(val, (str, int, float)):
                    features.append({"nombre": prop.title(), "valor": str(val)})

            return {
                "title": name,
                "descripcion": desc,
                "descripcion_corta": "",
                "marca": brand,
                "modelo": modelo,
                "resumen": "",
                "caracteristicas": features,
                "imagen_url": img,
                "imagen_urls": imgs,
                "_source": "jsonld",
            }
    return None


# ── TCL spec API extraction ──────────────────────────────────────────────────


def extract_tcl_specs(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract specs from a TCL family page via their JSON API.

    TCL stores the spec data in a Knockout/AEM component whose ``data-api``
    attribute points to a JSON endpoint.  The endpoint is addressed as::

        https://www.tcl.com{data_api}.{base64(productDataPath)}.json

    where ``productDataPath`` comes from the ``#pageData`` hidden input on
    the family page (e.g. ``/content/brandsite-product/ar/es/tvs/c6k/55c6k``).

    Returns a list of ``{"nombre": ..., "valor": ...}`` dicts, or ``[]`` if
    the page is not a TCL family page / the API is unreachable.
    """
    import base64
    import html as _html
    import json as _json

    spec_component = soup.select_one("[data-api]")
    if not spec_component:
        return []
    data_api = str(spec_component.get("data-api") or "").strip()
    if not data_api:
        return []

    page_data = soup.find(id="pageData")
    product_data_path = ""
    if page_data is not None:
        try:
            raw = _html.unescape(str(page_data.get("value") or ""))
            data = _json.loads(raw)
            products = data.get("allproducts") or []
            selected = next(
                (p for p in products if p.get("selected")), None
            )
            product_data_path = (selected or {}).get("productDataPath") or ""
        except (ValueError, TypeError, AttributeError):
            pass

    if not product_data_path:
        return []

    selector_b64 = base64.b64encode(product_data_path.encode()).decode()
    api_url = f"https://www.tcl.com{data_api}.{selector_b64}.json"

    logger.debug("  TCL_SPEC  fetching API: %s", api_url)
    try:
        import requests

        resp = requests.get(api_url, timeout=30)
        resp.raise_for_status()
        api_data = resp.json()
    except Exception as exc:
        logger.debug("  TCL_SPEC  API fetch failed: %s", exc)
        return []

    if api_data.get("code") != 200 or not api_data.get("data"):
        logger.debug("  TCL_SPEC  API returned code=%s", api_data.get("code"))
        return []

    features: list[dict[str, str]] = []
    seen: set[str] = set()
    for tab in api_data["data"]:
        for item in tab.get("specItems") or []:
            name = (item.get("name") or "").strip()
            value = (item.get("value") or "").strip()
            if not name or not value or value == "\\":
                continue
            key_norm = name.lower().strip()
            if key_norm in seen:
                continue
            seen.add(key_norm)
            features.append({"nombre": name, "valor": value})

    logger.info("  TCL_SPEC  extracted %d characteristics", len(features))
    return features


# ── JS state object extraction ────────────────────────────────────────────────


def extract_js_state_objects(html) -> list[dict[str, str]]:
    """Extract product specs from embedded JS state objects.

    Accepts either raw HTML string or a BeautifulSoup object.
    Many modern frameworks (Next.js, Nuxt, Angular) embed product data in
    global state objects:
    - ``window.__NEXT_DATA__``
    - ``window.__NUXT__``
    - ``window.__INITIAL_STATE__``
    - ``<script id="__NEXT_DATA__" type="application/json">``

    This function finds these objects, walks them recursively, and extracts
    key-value pairs that look like product specifications.
    """
    features: list[dict[str, str]] = []
    seen: set[str] = set()

    # Normalize input: accept both str and BeautifulSoup
    if isinstance(html, str):
        soup = BeautifulSoup(html, "lxml")
        html_str = html
    else:
        soup = html
        html_str = str(html)

    # ── Strategy 1: __NEXT_DATA__ script tag ────────────────────────────────
    for script_id in ("__NEXT_DATA__", "__NUXT_DATA__"):
        for script in soup.find_all("script", id=script_id):
            raw = script.string
            if not raw:
                continue
            try:
                data = json.loads(raw)
                _walk_and_extract(data, features, seen, max_depth=8)
            except (json.JSONDecodeError, TypeError):
                pass

    # ── Strategy 2: window.__* assignments in inline scripts ─────────────────
    _OBJ_PATTERNS = [
        r"window\.__NEXT_DATA__\s*=\s*(\{.*?\});",
        r"window\.__NUXT__\s*=\s*(\{.*?\});",
        r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});",
        r"window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});",
    ]
    for pattern in _OBJ_PATTERNS:
        for match in re.finditer(pattern, html_str, re.DOTALL):
            try:
                data = json.loads(match.group(1))
                _walk_and_extract(data, features, seen, max_depth=8)
            except (json.JSONDecodeError, TypeError):
                pass

    # ── Strategy 3: Generic spec-like JSON blobs in <script> tags ────────────
    # Look for arrays of {name, value} or {label, value} objects
    _SPEC_BLOB = re.compile(
        r'"(?:specifications?|specs?|features?|attributes?|properties?)"\s*:\s*(\[.*?\])',
        re.DOTALL | re.IGNORECASE,
    )
    for match in _SPEC_BLOB.finditer(html):
        try:
            items = json.loads(match.group(1))
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        name = (item.get("name") or item.get("label") or item.get("key") or "").strip()
                        value = (item.get("value") or item.get("val") or item.get("data") or "").strip()
                        if name and value and len(name) < 80:
                            key_norm = name.lower()
                            if key_norm not in seen:
                                seen.add(key_norm)
                                features.append({"nombre": name, "valor": value})
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    return features


def _walk_and_extract(
    obj,
    features: list[dict[str, str]],
    seen: set[str],
    max_depth: int = 8,
    _depth: int = 0,
) -> None:
    """Recursively walk a JSON object and extract spec-like key-value pairs.

    Looks for dict entries where keys contain spec-like words and values
    are strings or simple QuantitativeValue-like objects.
    """
    if _depth > max_depth:
        return

    if isinstance(obj, dict):
        for key, val in obj.items():
            key_lower = key.lower()

            # Skip navigation/UI keys
            if key_lower in ("__typename", "id", "type", "url", "href", "src", "image", "icon"):
                continue

            if isinstance(val, str) and val.strip():
                # Check if this looks like a spec key
                if _is_spec_key(key) and len(val) < 500:
                    key_norm = key_lower.strip()
                    if key_norm not in seen:
                        seen.add(key_norm)
                        display_key = _humanize_key(key)
                        features.append({"nombre": display_key, "valor": val.strip()})

            elif isinstance(val, dict):
                # QuantitativeValue pattern: {value: ..., unitText: ...}
                if "value" in val and len(val) <= 3:
                    unit = val.get("unitText") or val.get("unit") or ""
                    value = str(val.get("value", ""))
                    if value and _is_spec_key(key):
                        display_key = _humanize_key(key)
                        key_norm = key_lower.strip()
                        if key_norm not in seen:
                            seen.add(key_norm)
                            features.append({"nombre": display_key, "valor": f"{value} {unit}".strip()})
                else:
                    _walk_and_extract(val, features, seen, max_depth, _depth + 1)

            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        _walk_and_extract(item, features, seen, max_depth, _depth + 1)

    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                _walk_and_extract(item, features, seen, max_depth, _depth + 1)


# Spec-like key patterns (common across e-commerce / manufacturer sites)
_SPEC_KEY_PATTERNS = re.compile(
    r"(?:"
    r"weight|height|width|depth|thickness|size|dimension"
    r"|color|colour|material|finish|texture"
    r"|resolution|display|screen|panel|brightness|contrast|refresh"
    r"|processor|cpu|gpu|ram|memory|storage|capacity"
    r"|battery|power|watt|voltage|amp|charge"
    r"|connectivity|wifi|bluetooth|usb|hdmi|ethernet|nfc"
    r"|camera|lens|aperture|zoom|sensor"
    r"|os|operating|system|version"
    r"|speed|frequency|rpm|dpi|ppi"
    r"|noise|decibel|db"
    r"|capacity|volume|liter|gallon"
    r"|speed|velocity|mph|kmh"
    r"|warranty|guarantee"
    r"|compatible|compatibility|supports"
    r"|feature|function|mode|type|kind"
    r"|rating|class|grade|tier"
    r"|protocol|standard|certification"
    r")",
    re.IGNORECASE,
)


def _is_spec_key(key: str) -> bool:
    """Check if a dict key looks like it names a product specification."""
    return bool(_SPEC_KEY_PATTERNS.search(key))


def _humanize_key(key: str) -> str:
    """Convert camelCase/snake_case key to human-readable title."""
    # Insert spaces before capitals: "batteryLife" → "battery Life"
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", key)
    # Replace underscores/hyphens with spaces
    s = re.sub(r"[_\-]+", " ", s)
    return s.strip().title()


# ── OpenGraph product meta tags ──────────────────────────────────────────────


def extract_og_product_meta(soup: BeautifulSoup) -> dict:
    """Extract product metadata from OpenGraph and product-specific meta tags.

    Reads beyond basic og:title/description/image to include:
    - ``product:brand``, ``product:retailer_item_id``, ``product:ean``
    - ``og:price:amount``, ``og:price:currency``
    """
    result: dict[str, str] = {}

    _OG_MAPPING = {
        "og:title": "title",
        "og:description": "desc",
        "og:image": "img",
        "product:brand": "brand",
        "product:retailer_item_id": "retailer_id",
        "product:ean": "ean",
        "og:price:amount": "price",
        "og:price:currency": "currency",
        "description": "desc",
    }

    for attr in ("property", "name"):
        for og_key, field in _OG_MAPPING.items():
            if field in result:
                continue
            tag = soup.find("meta", attrs={attr: og_key})
            if tag and tag.get("content"):
                result[field] = str(tag["content"]).strip()

    # Fallback title from <title> tag
    if "title" not in result:
        t = soup.find("title")
        if t:
            result["title"] = t.get_text(strip=True)

    return result


# ── Body text heuristic extraction ────────────────────────────────────────────


def extract_body_text_specs(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract specs from visible body text using heuristic parsing.

    After ``force_full_page_load`` expands all accordions, this scans the
    rendered text for ``Key: Value`` patterns.  Filters out navigation,
    footer, and non-spec content.
    """
    features: list[dict[str, str]] = []
    seen: set[str] = set()

    body_text = soup.get_text(separator="\n")

    # Skip common non-spec sections
    _SKIP_SECTIONS = {
        "cookie", "privacy", "terms", "subscribe", "newsletter",
        "copyright", "all rights reserved", "follow us",
        "add to cart", "buy now", "price", "shop", "cart",
        "sign up", "log in", "account", "menu", "search",
        "monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday", "contact", "support", "help",
        "faq", "return", "shipping", "delivery", "warranty",
        # Spanish equivalents
        "precio", "comprar", "carrito", "envio", "envío", "suscripcion",
        "suscripción", "contacto", "soporte", "ayuda", "garantia", "garantía",
    }
    _SKIP_VALUES = {
        "yes", "no", "true", "false", "n/a", "none", "n/a", "-",
    }
    # Bare size words appear in variant selectors ("tamaño: 50\"") — not real specs
    _SKIP_NAMES = {
        "tamaño", "talla", "size", "medida", "pantalla", "dimension", "dimensions",
    }
    # Review/navigation/non-spec noise seen on JS-heavy brand pages
    _JUNK_NAME_PATTERNS = (
        "review", "promotion", "trustmark", "navigate to", "go to ",
        "to do this", "to fine-tune",
    )

    for line in body_text.split("\n"):
        line = line.strip()
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name, value = clean_feature(name.strip(), value.strip())

        if not name or not value:
            continue
        if len(name) < 3 or len(name) > 60:
            continue
        if len(value) < 2 or len(value) > 200:
            continue
        if value.lower() in _SKIP_VALUES:
            continue
        # Skip if name looks like navigation or non-spec
        if any(s in name.lower() for s in _SKIP_SECTIONS):
            continue
        # Skip bare size words (variant selector remnants)
        if name.lower().strip() in _SKIP_NAMES:
            continue
        # Skip review/navigation noise
        if any(j in name.lower() for j in _JUNK_NAME_PATTERNS):
            continue
        # Skip title/heading duplication (name == value, e.g. product title)
        if len(name) > 20 and name.lower().strip() == value.lower().strip():
            continue
        # Skip time/date patterns (e.g. "Monday - Friday 9:00am to 9:00pm")
        if re.search(r"\b(?:am|pm|eastern|pacific|central|gmt|utc)\b", value.lower()):
            continue
        # Skip lines with digits-only name (e.g. "123: Some value")
        if name.isdigit():
            continue

        key_norm = name.lower().strip()
        if key_norm not in seen:
            seen.add(key_norm)
            features.append({"nombre": name, "valor": value})

    return features
