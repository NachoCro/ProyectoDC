import logging
import time
import xml.etree.ElementTree as ET

import requests
from requests.auth import HTTPBasicAuth

from .config import API_SLEEP, PRESTASHOP_API_KEY, PRESTASHOP_API_URL, get_config

logger = logging.getLogger(__name__)


def _mpn_field_name() -> str:
    """Name of the product model field in the PrestaShop API.

    PrestaShop >= 1.7 exposes ``mpn``; 1.6 has no such field — set
    ``PS_MPN_FIELD=reference`` (or ``supplier_reference``) via config.
    """
    return (get_config("PS_MPN_FIELD", "mpn") or "mpn").strip() or "mpn"


class PrestashopError(Exception):
    """Wraps HTTP / API errors from PrestaShop."""


class PrestashopClient:
    """Thin wrapper around the PrestaShop REST web service."""

    def __init__(self) -> None:
        if not PRESTASHOP_API_URL or not PRESTASHOP_API_KEY:
            raise PrestashopError(
                "PRESTASHOP_API_URL and PRESTASHOP_API_KEY must be set in .env"
            )
        self._base = PRESTASHOP_API_URL
        logger.info("PrestaShop base URL: %s", self._base)
        self._auth = HTTPBasicAuth(PRESTASHOP_API_KEY, "")
        self._session = requests.Session()
        self._session.auth = self._auth
        self._session.headers.update({"Accept": "application/xml"})

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _request(self, resource: str, params: dict | None = None) -> ET.Element:
        url = f"{self._base}/{resource}"
        logger.debug("GET %s %s", url, params or "")
        try:
            resp = self._session.get(url, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(exc, "response", None)
            detail = getattr(status, "text", str(exc))[:300] if status else str(exc)[:300]
            raise PrestashopError(
                f"PrestaShop API error: {detail}"
            ) from exc

        time.sleep(API_SLEEP)  # RF-10: throttle

        try:
            return ET.fromstring(resp.content)
        except ET.ParseError as exc:
            raise PrestashopError(
                f"PrestaShop returned non-XML (HTTP {resp.status_code}): "
                f"{resp.text[:200]}"
            ) from exc

    @staticmethod
    def _text(elem: ET.Element | None, tag: str) -> str | None:
        if elem is None:
            return None
        child = elem.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def get_manufacturers(self) -> dict[int, str]:
        """Return {id: name} for every manufacturer."""
        root = self._request("manufacturers", {"display": "[id,name]"})
        mapping: dict[int, str] = {}
        for m in root.findall(".//manufacturer"):
            mid = self._text(m, "id")
            name = self._text(m, "name")
            if mid and name:
                mapping[int(mid)] = name
        return mapping

    def get_inactive_products(
        self, limit: int = 10, offset: int = 0
    ) -> list[dict]:
        """Fetch products with ``active = 0`` (paginated).

        Returns a list of dicts with keys:
        ``id``, ``ean13``, ``mpn``, ``id_manufacturer``, ``id_category_default``,
        ``name`` (product name in default language).
        """
        root = self._request("products", {
            "filter[active]": "[0]",
            "display": f"[id,ean13,{_mpn_field_name()},id_manufacturer,id_category_default,name]",
            "limit": f"{offset},{limit}",
        })
        products_el = root.find(".//products")
        if products_el is None:
            return []

        result: list[dict] = []
        for p in products_el.findall("product"):
            name = None
            name_el = p.find("name")
            if name_el is not None:
                lang = name_el.find("language")
                if lang is not None and lang.text:
                    name = lang.text.strip()
            result.append({
                "id": self._text(p, "id"),
                "ean13": self._text(p, "ean13"),
                "mpn": self._text(p, _mpn_field_name()),
                "id_manufacturer": self._text(p, "id_manufacturer"),
                "id_category_default": self._text(p, "id_category_default"),
                "name": name,
            })
        return result

    def get_active_products(
        self, limit: int = 10, offset: int = 0
    ) -> list[dict]:
        """Fetch products with ``active = 1`` (paginated).

        Returns a list of dicts with keys:
        ``id``, ``ean13``, ``mpn``, ``id_manufacturer``, ``id_category_default``,
        ``name`` (product name in default language).
        """
        root = self._request("products", {
            "filter[active]": "[1]",
            "display": f"[id,ean13,{_mpn_field_name()},id_manufacturer,id_category_default,name]",
            "limit": f"{offset},{limit}",
        })
        products_el = root.find(".//products")
        if products_el is None:
            return []

        result: list[dict] = []
        for p in products_el.findall("product"):
            name = None
            name_el = p.find("name")
            if name_el is not None:
                lang = name_el.find("language")
                if lang is not None and lang.text:
                    name = lang.text.strip()
            result.append({
                "id": self._text(p, "id"),
                "ean13": self._text(p, "ean13"),
                "mpn": self._text(p, _mpn_field_name()),
                "id_manufacturer": self._text(p, "id_manufacturer"),
                "id_category_default": self._text(p, "id_category_default"),
                "name": name,
            })
        return result

    def get_stock_map(self, product_ids: list[int]) -> dict[int, int]:
        """Return ``{id_product: quantity}`` for the given product IDs."""
        if not product_ids:
            return {}
        ids = "|".join(str(pid) for pid in product_ids)
        root = self._request("stock_availables", {
            "filter[id_product]": f"[{ids}]",
            "display": "[id_product,quantity]",
        })
        stock: dict[int, int] = {}
        for sa in root.findall(".//stock_available"):
            pid = self._text(sa, "id_product")
            qty = self._text(sa, "quantity")
            if pid is not None:
                stock[int(pid)] = int(qty) if qty else 0
        return stock
