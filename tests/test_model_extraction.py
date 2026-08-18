"""Tests for brand inference and model extraction (middleware/official_scraper.py).

Only pure helpers are tested; Selenium/network paths are exercised by the
integration suite, never by these unit tests.
"""

from middleware.official_scraper import (
    _clean_name_for_search,
    _extract_model_from_name,
    _infer_brand_from_name,
)

# ── _extract_model_from_name ────────────────────────────────────────────────


def test_extract_model_brother():
    assert _extract_model_from_name(
        "DCP1617NW | Impresora láser monocromática | Brother Argentina",
        "Brother",
    ) == "DCP1617NW"


def test_extract_model_brother_short():
    assert _extract_model_from_name("BROTHER DCP1617NW", "Brother") == "DCP1617NW"


def test_extract_model_lg_tv():
    assert _extract_model_from_name('LG OLED55C4PSA 55" 4K Smart TV', "LG") == "OLED55C4PSA"


def test_extract_model_pantum():
    assert _extract_model_from_name("IMP PANTUM MF LASER MONO BM5100FDW", "Pantum") == "BM5100FDW"


def test_extract_model_empty():
    assert _extract_model_from_name("") == ""
    assert _extract_model_from_name(None) == ""


def test_extract_model_no_model_returns_empty():
    assert _extract_model_from_name("IMPRESORA LASER", "Generic") == ""


# ── _clean_name_for_search ──────────────────────────────────────────────────


def test_clean_name_basic():
    assert _clean_name_for_search("IMPRESORA BROTHER DCP-1617NW", "Brother") == "DCP-1617NW"


def test_clean_name_pantum():
    assert _clean_name_for_search("IMP PANTUM MF LASER MONO BM5100FDW", "Pantum") == "BM5100FDW"


def test_clean_name_samsung_monitor():
    out = _clean_name_for_search('Samsung Monitor Smart 32" M5 M50F FHD', "Samsung")
    assert "M50F" in out


def test_clean_name_falls_back_when_too_short():
    assert _clean_name_for_search("TV", "Samsung") == "TV"


# ── _infer_brand_from_name ──────────────────────────────────────────────────


def test_infer_brand_direct_match():
    assert _infer_brand_from_name("Impresora Brother DCP1617NW") == "brother"


def test_infer_brand_product_line():
    assert _infer_brand_from_name("iPhone 15 Pro Max 256GB") == "apple"
    assert _infer_brand_from_name("Galaxy S24 Ultra") == "samsung"
    assert _infer_brand_from_name("ThinkPad X1 Carbon") == "lenovo"


def test_infer_brand_none():
    assert _infer_brand_from_name("") is None
    assert _infer_brand_from_name("Dispositivo generico 123") is None


def test_infer_brand_word_boundary_no_false_match():
    # "blu" should not match "Bluetooth" / "Blu-ray"
    assert _infer_brand_from_name("Parlante Bluetooth") is None


def test_infer_brand_echo_only_for_amazon_device():
    # "ECHO 4605" is Echo-brand garden equipment, not an Amazon Echo speaker.
    assert _infer_brand_from_name("CILINDRO COMPLETO ECHO 4605") is None
    assert _infer_brand_from_name("FILTRO AIRE ECHO4605") is None
    assert _infer_brand_from_name("Echo Dot 5ta gen") == "amazon"
    assert _infer_brand_from_name("Amazon Echo Show 8") == "amazon"


def test_infer_brand_hp_not_horsepower():
    # "9 - 13 HP" is horsepower, not the HP brand.
    assert _infer_brand_from_name("AGUJA MOTOR 9 - 13 HP") is None
    assert _infer_brand_from_name("AGUJA MOTOR 5.5 - 6.5 HP") is None
    assert _infer_brand_from_name("Notebook HP 250 G8") == "hp"
