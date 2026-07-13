"""Automatic translation module with protected glossary (RF-07)."""

import logging
from functools import lru_cache

try:
    from deep_translator import GoogleTranslator

    _TRANSLATOR_AVAILABLE = True
except ImportError:
    GoogleTranslator = None  # type: ignore
    _TRANSLATOR_AVAILABLE = False

logger = logging.getLogger(__name__)

# Protected technical terms — never translated.
# Sorted longest-first so compound terms match before their components.
GLOSSARY = sorted([
    "Super AMOLED", "IPS LCD", "Ray Tracing",
    "AMD Ryzen", "Intel Core",
    "USB-C", "microUSB", "DisplayPort",
    "HDMI 2.1", "HDMI 2.0", "USB 3.0", "USB 2.0",
    "G-Sync", "FreeSync",
    "QLED", "OLED", "AMOLED", "HDMI", "USB", "LED", "LCD", "IPS", "VA", "TN",
    "DDR5", "DDR4", "DDR3", "DDR", "SSD", "HDD", "NVMe", "M.2", "SATA", "PCIe",
    "WiFi", "Bluetooth", "NFC",
    "4K", "8K", "FHD", "UHD", "HDR",
    "Core i9", "Core i7", "Core i5", "Core i3",
    "Ryzen 9", "Ryzen 7", "Ryzen 5", "Ryzen 3",
    "RTX", "GTX", "RX", "GeForce", "Radeon",
    "DLSS", "RGB", "HDD",
    "Linux", "Windows", "macOS", "Android", "iOS", "iPadOS",
], key=len, reverse=True)


def _protect_glossary(text: str) -> tuple[str, dict[str, str]]:
    """Replace protected terms with opaque placeholders."""
    placeholders: dict[str, str] = {}
    for i, term in enumerate(GLOSSARY):
        if term in text:
            key = f"\x00G{i}\x00"
            text = text.replace(term, key)
            placeholders[key] = term
    return text, placeholders


def _restore_glossary(text: str, placeholders: dict[str, str]) -> str:
    for key, term in placeholders.items():
        text = text.replace(key, term)
    return text


def is_available() -> bool:
    return _TRANSLATOR_AVAILABLE


@lru_cache(maxsize=1024)
def translate(text: str, target: str = "es") -> str:
    """Translate text to target language, preserving glossary terms."""
    if not text or not text.strip():
        return text
    if not _TRANSLATOR_AVAILABLE:
        return text

    protected, placeholders = _protect_glossary(text)
    if not protected.strip():
        return text

    try:
        translator = GoogleTranslator(source="auto", target=target)
        translated = translator.translate(protected)
        return _restore_glossary(translated, placeholders)
    except Exception as exc:
        logger.warning("Translation failed (%s): %s", type(exc).__name__, exc)
        return text


def translate_product(product_data: dict, fields: list[str] | None = None) -> dict:
    """Translate relevant fields of a product dict, preserving glossary."""
    if fields is None:
        fields = ["titulo", "title", "descripcion", "description", "resumen", "summary"]
    result = dict(product_data)
    for field in fields:
        value = result.get(field)
        if value and isinstance(value, str):
            result[field] = translate(value)
    return result
