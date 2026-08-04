"""Extended PrestaShop client with write support for Admin UI."""

import logging
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from xml.etree.ElementTree import Element, SubElement

import requests

from middleware.config import API_SLEEP, get_config
from middleware.prestashop import PrestashopClient, PrestashopError

logger = logging.getLogger(__name__)

LANG_ID = "1"  # default language ID


def ps81_workarounds_enabled() -> bool:
    """Whether PrestaShop 8.1 PUT workarounds are enabled.

    PrestaShop 8.1 rejects PUT bodies that contain GET-returned attributes
    (``xlink:href``, ``nodeType``), image/combination associations, or leave
    ``state=0``.  Set ``PS_COMPAT_81=0`` in config to disable these
    sanitizations for other PrestaShop versions.
    """
    return get_config("PS_COMPAT_81", "1") == "1"

# Fields returned by GET that PrestaShop rejects on PUT
_READ_ONLY_FIELDS = {
    "manufacturer_name", "supplier_name",
    "date_add", "date_upd",
    "state", "position_in_category",
    "cache_default_attribute", "id_default_image",
    "id_default_combination", "quantity",
    "id_supplier",
}


def _wrap_language_cdata(xml_str: str) -> str:
    """Replace escaped HTML inside <language> tags with CDATA sections.

    ElementTree serializes text with XML escaping (e.g. ``&lt;p&gt;``).
    PrestaShop's API expects raw HTML wrapped in ``<![CDATA[...]]>``.
    This function finds each non-self-closing ``<language>`` tag with content,
    unescapes the content, and wraps it in a CDATA section.
    """
    import re
    from xml.sax.saxutils import unescape

    def _replace(m: re.Match) -> str:
        before = m.group(1)   # <language ...>
        content = m.group(2)
        after = m.group(3)    # </language>
        raw = unescape(content)
        return f"{before}<![CDATA[{raw}]]>{after}"

    # Match only non-self-closing <language> tags with content:
    #   <language ...>content</language>
    # Negative lookbehind ensures the opening tag doesn't end with /.
    return re.sub(
        r"(<language[^>]*[^/]>)(.*?)(</language>)",
        _replace,
        xml_str,
        flags=re.DOTALL,
    )


def _strip_prestashop_attrs(root: ET.Element) -> None:
    """Remove attributes that PrestaShop's PUT endpoint rejects.

    GET responses include ``xlink:href``, ``notFilterable``, ``nodeType``,
    ``api``, etc.  PrestaShop 8.1 chokes on these during PUT with a 500.
    This strips all attributes except ``id`` on ``<language>`` tags.
    """
    for el in root.iter():
        if el.tag == "language":
            # Keep only the id attribute
            lang_id = el.get("id")
            el.attrib.clear()
            if lang_id:
                el.attrib["id"] = lang_id
        else:
            el.attrib.clear()


# ======================================================================
# fuzzy matching for existing features/values
# ======================================================================

def _normalize_name(value: str) -> str:
    """Lowercase, strip accents and collapse non-alphanumerics to spaces."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _name_similarity(a: str, b: str) -> float:
    """Similarity in [0, 1] between two characteristic/feature names.

    Exact normalized match → 1.0.  Otherwise SequenceMatcher ratio, with a
    0.9 bonus when one is a whole-word substring of the other (both length
    ≥ 4) — this maps e.g. ``Resolución`` → ``Resolución de pantalla``.
    """
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    if len(na) >= 4 and len(nb) >= 4 and (na in nb or nb in na):
        return max(ratio, 0.9)
    return ratio


def _best_fuzzy_match(query: str, candidates: list[tuple[str, int]], threshold: float = 0.85):
    """Return ``(id, matched_name, score)`` for the best candidate ≥ threshold.

    ``candidates`` is a list of ``(name, id)``.  Returns ``(None, None, 0.0)``
    when nothing reaches the threshold.
    """
    best_id = None
    best_name = None
    best_score = 0.0
    for name, cid in candidates:
        score = _name_similarity(query, name)
        if score > best_score:
            best_score = score
            best_id = cid
            best_name = name
    if best_id is not None and best_score >= threshold:
        return best_id, best_name, best_score
    return None, None, 0.0


class AdminPrestashopClient(PrestashopClient):
    """Adds GET / PUT product capabilities needed for the approval flow."""

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    def get_product(self, product_id: int) -> dict:
        """Fetch a single product as a plain dict (JSON format)."""
        resp = self._session.get(
            f"{self._base}/products/{product_id}",
            params={"output_format": "JSON"},
            timeout=30,
        )
        resp.raise_for_status()
        time.sleep(API_SLEEP)
        data = resp.json()
        # PrestaShop webservice returns {"product": …}
        return data["product"]

    def get_product_completeness(self, product_id: int) -> dict:
        """Check if a product is complete (has image, description, characteristics).

        Returns a dict with:
        - ``is_complete``: True if all fields are present
        - ``missing``: list of missing field names ('image', 'description', 'characteristics')
        - ``product``: full product data from PrestaShop
        """
        product = self.get_product(product_id)
        missing = []

        # Check image
        has_image = False
        associations = product.get("associations", {})
        images = associations.get("images", [])
        if images and len(images) > 0:
            has_image = True
        if not has_image:
            missing.append("image")

        # Check description
        has_description = False
        description = product.get("description", "")
        if description:
            # Handle multi-language: could be string or list of dicts
            if isinstance(description, str) and description.strip():
                has_description = True
            elif isinstance(description, list):
                for desc in description:
                    if isinstance(desc, dict) and desc.get("#text", "").strip():
                        has_description = True
                        break
                    elif isinstance(desc, str) and desc.strip():
                        has_description = True
                        break
        if not has_description:
            missing.append("description")

        # Check characteristics (product_features)
        has_characteristics = False
        product_features = associations.get("product_features", [])
        if product_features and len(product_features) > 0:
            has_characteristics = True
        if not has_characteristics:
            missing.append("characteristics")

        return {
            "is_complete": len(missing) == 0,
            "missing": missing,
            "product": product,
        }

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def put_product(
        self, product_id: int, updates: dict,
        feature_pairs: list[tuple[int, int]] | None = None,
        category_ids: list[int] | None = None,
    ) -> None:
        """Partial update of a product via GET → modify → PUT.

        If *feature_pairs* is provided, each ``(id_feature, id_feature_value)``
        pair is written into ``<product_features>``, replacing any existing
        product features.

        If *category_ids* is provided, the product is ensured to belong to
        those categories (keeps any existing categories already present) and
        ``id_category_default`` is set to the first ID in the list.
        """
        root = self._request(f"products/{product_id}")
        product_el = root.find(".//product")
        if product_el is None:
            raise PrestashopError(f"Product {product_id} has no <product> element")

        for tag in list(product_el):
            if tag.tag in _READ_ONLY_FIELDS:
                product_el.remove(tag)

        for key, value in updates.items():
            if value is None:
                continue
            self._set_field(product_el, key, str(value))

        # Replace product_features inside <associations>
        if feature_pairs is not None:
            assoc_el = product_el.find("associations")
            if assoc_el is None:
                assoc_el = SubElement(product_el, "associations")
            old_pf = assoc_el.find("product_features")
            if old_pf is not None:
                assoc_el.remove(old_pf)
            pf_el = SubElement(assoc_el, "product_features")
            seen = set()
            for fid, fvid in feature_pairs:
                if (fid, fvid) in seen:
                    continue
                seen.add((fid, fvid))
                pf_item = SubElement(pf_el, "product_feature")
                id_el = SubElement(pf_item, "id")
                id_el.text = str(fid)
                id_fv_el = SubElement(pf_item, "id_feature_value")
                id_fv_el.text = str(fvid)

        # Ensure product belongs to specified categories
        if category_ids is not None:
            assoc_el = product_el.find("associations")
            if assoc_el is None:
                assoc_el = SubElement(product_el, "associations")
            cats_el = assoc_el.find("categories")
            if cats_el is None:
                cats_el = SubElement(assoc_el, "categories")
            existing_ids = set()
            for cat_item in cats_el.findall("category"):
                cid = cat_item.findtext("id")
                if cid:
                    existing_ids.add(cid)
            for cat_id in category_ids:
                cid_str = str(cat_id)
                if cid_str not in existing_ids:
                    cat_item = SubElement(cats_el, "category")
                    id_el = SubElement(cat_item, "id")
                    id_el.text = cid_str
                    existing_ids.add(cid_str)

            # Set id_category_default to the primary target category
            if category_ids:
                self._set_field(product_el, "id_category_default", str(category_ids[0]))

        # PrestaShop 8.1: force visibility + indexing + state (prevents invisible products)
        if ps81_workarounds_enabled():
            self._set_field(product_el, "visibility", "both")
            self._set_field(product_el, "indexed", "1")
            self._set_field(product_el, "state", "1")

            # Strip associations down to only product_features + categories.
            # PrestaShop 8.1 rejects PUTs that include images, combinations,
            # stock_availables, etc. inside <associations>.
            assoc_el = product_el.find("associations")
            if assoc_el is not None:
                for child in list(assoc_el):
                    if child.tag not in ("product_features", "categories"):
                        assoc_el.remove(child)

        # Debug: check critical fields before PUT
        assoc_el = product_el.find("associations")
        cats_el = assoc_el.find("categories") if assoc_el is not None else None
        shops_el = assoc_el.find("shop") if assoc_el is not None else None
        id_shop_def = product_el.findtext("id_shop_default")
        logger.debug(
            "  PUT product %d — assoc=%s cats=%s shops=%s "
            "active=%s id_category_default=%s id_shop_default=%s "
            "visibility=%s indexed=%s",
            product_id,
            assoc_el is not None,
            cats_el is not None,
            shops_el is not None,
            product_el.findtext("active"),
            product_el.findtext("id_category_default"),
            id_shop_def,
            product_el.findtext("visibility"),
            product_el.findtext("indexed"),
        )

        if ps81_workarounds_enabled():
            _strip_prestashop_attrs(root)
        xml_str = ET.tostring(root, encoding="unicode", xml_declaration=True)
        xml_str = _wrap_language_cdata(xml_str)

        url = f"{self._base}/products/{product_id}"
        headers = {"Content-Type": "application/xml"}
        resp = self._session.put(url, data=xml_str.encode(), headers=headers)

        logger.debug(
            "  PUT product %d → HTTP %d  body=%.200s",
            product_id, resp.status_code, resp.text[:200],
        )
        if resp.status_code >= 400:
            raise PrestashopError(
                f"PUT products/{product_id} failed HTTP {resp.status_code}: "
                f"{resp.text[:500]}"
            )
        time.sleep(API_SLEEP)

        # Verify: re-fetch and log critical fields
        root2 = self._request(f"products/{product_id}")
        product2 = root2.find(".//product")
        if product2 is not None:
            logger.debug(
                "  POST-PUT product %d — active=%s id_category_default=%s "
                "id_shop_default=%s id_manufacturer=%s has_assoc=%s "
                "visibility=%s indexed=%s",
                product_id,
                product2.findtext("active"),
                product2.findtext("id_category_default"),
                product2.findtext("id_shop_default"),
                product2.findtext("id_manufacturer"),
                product2.find("associations") is not None,
                product2.findtext("visibility"),
                product2.findtext("indexed"),
            )

    # ------------------------------------------------------------------
    # features
    # ------------------------------------------------------------------

    def _fetch_all_features(self) -> dict[str, int]:
        """Fetch all product features, return ``{name_lower: id}`` map."""
        root = self._request("product_features", {"display": "[id,name]"})
        index: dict[str, int] = {}
        for f in root.findall(".//product_feature"):
            fid = f.findtext("id")
            if not fid:
                continue
            for lang in f.findall("name/language"):
                if lang.text:
                    index[lang.text.strip().lower()] = int(fid)
        return index

    def _fetch_all_feature_values(self) -> dict[tuple[int, str], int]:
        """Fetch all feature values, return ``{(feature_id, value_lower): id}``."""
        root = self._request("product_feature_values", {"display": "[id,id_feature,value]"})
        index: dict[tuple[int, str], int] = {}
        for fv in root.findall(".//product_feature_value"):
            fvid = fv.findtext("id")
            fid = fv.findtext("id_feature")
            if not fvid or not fid:
                continue
            for lang in fv.findall("value/language"):
                if lang.text:
                    index[(int(fid), lang.text.strip().lower())] = int(fvid)
        return index

    def sync_characteristics_as_features(
        self, characteristics: list[dict],
    ) -> list[tuple[int, int]]:
        """Resolve every characteristic to an existing PrestaShop Feature +
        Feature-Value pair.

        Fetches all existing features and values in just 2 GET calls.  Each
        characteristic is resolved in order:

        1. Exact match (case/accent-insensitive) on feature name, then on
           value within that feature.
        2. Fuzzy match by similarity (`_best_fuzzy_match`) — maps e.g.
           ``Resolución`` → ``Resolución de pantalla``.
        3. If nothing matches and ``PS_CREATE_FEATURES=1``, the missing
           feature/value is created (legacy behavior).  Otherwise the
           characteristic is skipped and logged as a warning.

        Returns ``[(id_feature, id_feature_value), …]`` ready to pass to
        :meth:`put_product`.
        """
        create_new = get_config("PS_CREATE_FEATURES", "0") == "1"

        feature_map = self._fetch_all_features()
        value_map = self._fetch_all_feature_values()

        # Normalized exact indexes + fuzzy candidate lists
        norm_features: dict[str, int] = {}
        feature_candidates: list[tuple[str, int]] = []
        for name, fid in feature_map.items():
            norm_features.setdefault(_normalize_name(name), fid)
            feature_candidates.append((name, fid))

        norm_values: dict[tuple[int, str], int] = {}
        values_by_feature: dict[int, list[tuple[str, int]]] = {}
        for (fid, value), fvid in value_map.items():
            norm_values.setdefault((fid, _normalize_name(value)), fvid)
            values_by_feature.setdefault(fid, []).append((value, fvid))

        pairs: list[tuple[int, int]] = []
        skipped: list[tuple[str, str, str]] = []
        for ch in characteristics:
            nombre = (ch.get("nombre") or "").strip()
            valor = (ch.get("valor") or "").strip()
            if not nombre or not valor:
                continue

            # Resolve feature
            fid = norm_features.get(_normalize_name(nombre))
            if fid is None:
                fid, matched_name, score = _best_fuzzy_match(nombre, feature_candidates)
                if fid is not None:
                    logger.info(
                        "  Característica '%s' → feature '%s' (similitud %.2f)",
                        nombre, matched_name, score,
                    )
            if fid is None:
                if create_new:
                    fid = self._create_feature(nombre)
                    norm_features.setdefault(_normalize_name(nombre), fid)
                    feature_candidates.append((nombre, fid))
                else:
                    skipped.append((nombre, valor, "característica no existe en PrestaShop"))
                    continue

            # Resolve feature value (PrestaShop limit: 255 chars)
            valor_trunc = valor[:255]
            fvid = norm_values.get((fid, _normalize_name(valor_trunc)))
            if fvid is None:
                fvid, matched_value, _ = _best_fuzzy_match(
                    valor_trunc, values_by_feature.get(fid, [])
                )
                if fvid is not None:
                    logger.info(
                        "  Valor '%s' → '%s' (feature %d, similitud %.2f)",
                        valor_trunc, matched_value, fid, _name_similarity(valor_trunc, matched_value),
                    )
            if fvid is None:
                if create_new:
                    fvid = self._create_feature_value(fid, valor_trunc)
                    norm_values.setdefault((fid, _normalize_name(valor_trunc)), fvid)
                    values_by_feature.setdefault(fid, []).append((valor_trunc, fvid))
                else:
                    skipped.append((nombre, valor, "valor no existe en PrestaShop"))
                    continue

            pairs.append((fid, fvid))

        if skipped:
            logger.warning(
                "  %d característica(s) omitidas (no existen en PrestaShop): %s",
                len(skipped),
                "; ".join(f"{n} = {v} ({r})" for n, v, r in skipped[:10]),
            )
        return pairs

    def _create_feature(self, name: str) -> int:
        """POST a new feature, return its ID."""
        payload = Element("prestashop")
        feature_el = SubElement(payload, "product_feature")
        name_el = SubElement(feature_el, "name")
        lang_el = SubElement(name_el, "language")
        lang_el.set("id", LANG_ID)
        lang_el.text = name[:128]  # PrestaShop limit: 128 chars for feature name
        xml_body = ET.tostring(payload, encoding="utf-8", xml_declaration=True)
        resp = self._session.post(
            f"{self._base}/product_features",
            data=xml_body,
            headers={"Content-Type": "application/xml"},
        )
        if not resp.ok:
            logger.error("  PrestaShop error for feature '%s': %s", name, resp.text[:500])
            raise PrestashopError(
                f"Create feature '{name}' failed HTTP {resp.status_code}: "
                f"{resp.text[:500]}"
            )
        created = ET.fromstring(resp.content)
        fid = created.findtext(".//product_feature/id")
        if fid:
            logger.info("  Created feature '%s' → id=%s", name, fid)
            return int(fid)
        raise PrestashopError(f"Failed to create feature '{name}'")

    def _create_feature_value(self, feature_id: int, value: str) -> int:
        """POST a new feature value, return its ID."""
        payload = Element("prestashop")
        fv_el = SubElement(payload, "product_feature_value")
        idf_el = SubElement(fv_el, "id_feature")
        idf_el.text = str(feature_id)
        val_el = SubElement(fv_el, "value")
        lang_el = SubElement(val_el, "language")
        lang_el.set("id", LANG_ID)
        lang_el.text = value
        xml_body = ET.tostring(payload, encoding="utf-8", xml_declaration=True)
        logger.debug("  POST product_feature_values XML: %s", xml_body.decode())
        resp = self._session.post(
            f"{self._base}/product_feature_values",
            data=xml_body,
            headers={"Content-Type": "application/xml"},
        )
        if not resp.ok:
            logger.error("  PrestaShop 400 for value '%s' (feature %d): %s",
                         value, feature_id, resp.text[:500])
            raise PrestashopError(
                f"Create feature value '{value}' (feature {feature_id}) failed HTTP "
                f"{resp.status_code}: {resp.text[:500]}"
            )
        created = ET.fromstring(resp.content)
        fvid = created.findtext(".//product_feature_value/id")
        if fvid:
            logger.info("  Created feature value '%s' for feature %d → id=%s", value, feature_id, fvid)
            return int(fvid)
        raise PrestashopError(f"Failed to create feature value '{value}'")

    def upload_product_image(self, product_id: int, image_url: str) -> int | None:
        """Download image from *image_url* and upload to PrestaShop.

        Returns the new image ID on success, or ``None`` on failure.
        """
        if not image_url:
            return None

        # Normalize protocol-relative URLs (e.g. "//cdn.example.com/img.png")
        if image_url.startswith("//"):
            image_url = "https:" + image_url

        # Download
        try:
            img_resp = requests.get(image_url, timeout=30)
            img_resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Failed to download image %s: %s", image_url, exc)
            return None

        content_type = img_resp.headers.get("Content-Type", "image/jpeg")
        image_data = img_resp.content

        # Upload to PrestaShop
        url = f"{self._base}/images/products/{product_id}"
        files = {"image": ("image.jpg", image_data, content_type)}
        try:
            resp = self._session.post(url, files=files)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Failed to upload image for product %d: %s", product_id, exc)
            return None
        finally:
            time.sleep(API_SLEEP)

        # Parse image ID from response
        try:
            root = ET.fromstring(resp.text)
            img_el = root.find(".//image//id")
            if img_el is not None and img_el.text:
                return int(img_el.text)
        except (ET.ParseError, ValueError):
            pass

        logger.warning("Could not parse image ID from PrestaShop response for product %d", product_id)
        return None

    def upload_product_images(self, product_id: int, image_urls: list[str]) -> list[int]:
        """Download and upload multiple images to PrestaShop.

        Returns list of successfully uploaded image IDs.
        """
        uploaded_ids: list[int] = []
        for url in image_urls:
            img_id = self.upload_product_image(product_id, url)
            if img_id is not None:
                uploaded_ids.append(img_id)
        return uploaded_ids

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _set_field(parent: ET.Element, key: str, value: str) -> None:
        """Set or create a scalar text field.

        Multi-language fields (with `<language>` children) get their first
        language element updated; if none exist, one is created with
        ``id="1"``.  Other fields are set directly.
        """
        field = parent.find(key)
        if field is None:
            field = ET.SubElement(parent, key)

        lang = field.find("language")
        if lang is not None:
            lang.text = value
            return

        if key in ("description", "description_short", "name",
                   "link_rewrite", "meta_title", "meta_description",
                   "meta_keywords", "delivery_in_stock", "delivery_out_stock",
                   "available_now", "available_later"):
            lang = ET.SubElement(field, "language")
            lang.set("id", LANG_ID)
            lang.text = value
            return

        field.text = value
