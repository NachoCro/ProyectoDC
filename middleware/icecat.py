"""Icecat Live API client for product enrichment."""

import json
import logging
import time

import requests

from .config import ICECAT_API_TOKEN, ICECAT_USERNAME, API_SLEEP

logger = logging.getLogger(__name__)

ICECAT_API_URL = "https://live.icecat.biz/api"


class IcecatError(Exception):
    """Wraps Icecat API errors."""


def _normalize(icecat_data: dict) -> dict:
    """Convert raw Icecat API response into the flat dict the app expects.

    Keys: title, descripcion, descripcion_corta, marca, modelo, resumen,
          caracteristicas (list of {nombre, valor}).
    """
    gi = icecat_data.get("GeneralInfo") or {}
    desc = gi.get("Description") or {}
    sd = gi.get("SummaryDescription") or {}

    title = gi.get("Title") or ""
    marca = gi.get("Brand") or ""
    modelo = gi.get("BrandPartCode") or ""

    long_desc = (desc.get("LongDesc") or "").strip()
    short_desc = (
        sd.get("ShortSummaryDescription")
        or desc.get("ShortSummaryDescription")
        or ""
    ).strip()
    summary = (
        sd.get("LongSummaryDescription")
        or desc.get("LongSummaryDescription")
        or ""
    ).strip()

    # Extract features (EAV)
    caracteristicas: list[dict[str, str]] = []
    for group in icecat_data.get("FeaturesGroups") or []:
        for f in group.get("Features") or []:
            nombre = (
                f.get("Feature", {}).get("Name", {}).get("Value", "") or ""
            ).strip()
            valor = (f.get("Value") or "").strip()
            pval = (f.get("PresentationValue") or "").strip()
            if nombre:
                caracteristicas.append({
                    "nombre": nombre,
                    "valor": pval or valor,
                })

    # Extract main product image
    img = icecat_data.get("Image") or {}
    imagen_url = (
        img.get("HighPic")
        or img.get("Pic500x500")
        or img.get("LowPic")
        or ""
    ).strip()

    return {
        "title": title,
        "descripcion": long_desc,
        "descripcion_corta": short_desc,
        "marca": marca,
        "modelo": modelo,
        "resumen": summary or short_desc,
        "caracteristicas": caracteristicas,
        "imagen_url": imagen_url,
        "_raw": icecat_data,
    }


class IcecatClient:
    """Client for the Icecat Live JSON API (read-only).

    Auth via ``api-token`` header + ``shopname`` query param (see
    https://iceclog.com/manual-for-icecat-json-product-requests/).
    """

    def __init__(self) -> None:
        if not ICECAT_USERNAME or not ICECAT_API_TOKEN:
            raise IcecatError(
                "ICECAT_USERNAME and ICECAT_API_TOKEN must be set in .env"
            )
        self._session = requests.Session()
        self._session.headers["api-token"] = ICECAT_API_TOKEN
        self._base_params = {
            "shopname": ICECAT_USERNAME,
            "content": "",
        }

    def _fetch(self, extra_params: dict, label: str) -> dict | None:
        """GET Icecat API, parse JSON, check for errors.

        Returns the **normalized** product dict on success, or ``None`` when
        Icecat cleanly reports the product was not found.
        Raises ``IcecatError`` on transport / parse failures.
        """
        params = dict(self._base_params)
        params.update(extra_params)
        url = ICECAT_API_URL
        logger.debug("GET %s  %s", url, params)
        try:
            resp = self._session.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            raise IcecatError(f"Icecat API error for {label}: {exc}") from exc
        finally:
            time.sleep(API_SLEEP)

        if resp.status_code in (400, 404):
            try:
                body = resp.json()
            except json.JSONDecodeError:
                body = {}
            if isinstance(body, dict) and "not be found" in body.get("Message", ""):
                logger.info("  Icecat: %s not found (%s)", label, body.get("Message", ""))
                return None
            # 404 without "not be found" message — still not found
            if resp.status_code == 404:
                logger.info("  Icecat: %s not found (HTTP 404)", label)
                return None
            raise IcecatError(
                f"Icecat error for {label}: HTTP {resp.status_code} {body.get('Message', '')}"
            )
        resp.raise_for_status()

        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise IcecatError(
                f"Icecat returned non-JSON for {label}: {resp.text[:200]}"
            ) from exc

        if not isinstance(body, dict) or body.get("msg") != "OK":
            logger.info("  Icecat: %s not found", label)
            return None

        raw = body.get("data")
        if not raw:
            logger.info("  Icecat: %s — empty data", label)
            return None

        return _normalize(raw)

    def get_product_by_ean(self, ean: str, lang: str = "ES") -> dict | None:
        """Fetch product by GTIN (EAN/UPC)."""
        return self._fetch({"GTIN": ean, "lang": lang}, f"GTIN {ean}")

    def get_product_by_brand_mpn(
        self, brand: str, mpn: str, lang: str = "ES"
    ) -> dict | None:
        """Fetch product by Brand + ProductCode (MPN)."""
        return self._fetch(
            {"Brand": brand, "ProductCode": mpn, "lang": lang},
            f"brand={brand} mpn={mpn}",
        )
