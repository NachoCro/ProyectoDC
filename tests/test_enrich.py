"""Tests for enrichment helpers (middleware/enrich.py)."""

from middleware import enrich

# ── _build_description ──────────────────────────────────────────────────────


def test_build_description_from_caracteristicas():
    chars = [
        {"nombre": "Color", "valor": "Negro"},
        {"nombre": "Peso", "valor": "1 kg"},
        {"nombre": "Vacio", "valor": ""},
    ]
    desc = enrich._build_description({"caracteristicas": chars})
    assert "<strong>Color:</strong> Negro" in desc
    assert "<strong>Peso:</strong> 1 kg" in desc
    assert "Vacio" not in desc


def test_build_description_empty():
    assert enrich._build_description({}) == ""
    assert enrich._build_description({"caracteristicas": []}) == ""


# ── _validate_scraped_data ──────────────────────────────────────────────────


def test_validate_brand_match_ok():
    data = {"marca": "Logitech G", "title": "Logitech G Pro X Superlight"}
    assert enrich._validate_scraped_data(data, "Logitech", "Logitech G Pro X Superlight", 1)


def test_validate_brand_mismatch():
    data = {"marca": "TCL", "title": "TV TCL 55"}
    assert not enrich._validate_scraped_data(data, "Samsung", "TV Samsung 55", 1)


def test_validate_junk_support_page_rejected():
    data = {
        "url": "https://support.samsung.com/manual/um-0001",
        "title": "Manual de usuario",
        "marca": "Samsung",
    }
    assert not enrich._validate_scraped_data(data, "Samsung", "TV Samsung 55", 1)


def test_validate_specs_page_on_support_accepted():
    data = {
        "url": "https://support.hp.com/hp-product-specifications/dcp1617nw",
        "title": "HP DCP1617NW Technical Specifications",
        "marca": "HP",
    }
    assert enrich._validate_scraped_data(data, "HP", "Impresora HP DCP1617NW", 1)


def test_validate_size_mismatch_in_title_rejected():
    data = {"marca": "Samsung", "title": "UN55U8000F 55\" 4K Smart TV"}
    ok = enrich._validate_scraped_data(
        data, "Samsung", "Samsung UN75U8000F 75\" 4K Smart TV", 1
    )
    assert not ok


def test_validate_size_mismatch_in_characteristics_rejected():
    data = {
        "marca": "Samsung",
        "title": "Samsung U8000F Smart TV",
        "caracteristicas": [{"nombre": "Tamaño de pantalla", "valor": '55"'}],
    }
    ok = enrich._validate_scraped_data(
        data, "Samsung", "Samsung UN75U8000F 75\" 4K Smart TV", 1
    )
    assert not ok


def test_validate_size_match_in_characteristics_accepted():
    data = {
        "marca": "Samsung",
        "title": "Samsung UN75U8000F Smart TV",
        "caracteristicas": [{"nombre": "Tamaño de pantalla", "valor": '75"'}],
    }
    ok = enrich._validate_scraped_data(
        data, "Samsung", "Samsung UN75U8000F 75\" 4K Smart TV", 1
    )
    assert ok


def test_validate_model_token_match():
    data = {"marca": "Brother", "title": "Brother DCP1617NW Especificaciones"}
    assert enrich._validate_scraped_data(data, "Brother", "Impresora Brother DCP1617NW", 1)


def test_validate_model_token_missing_rejected():
    data = {"marca": "Brother", "title": "Pantalla genérica para impresora"}
    ok = enrich._validate_scraped_data(data, "Brother", "Impresora Brother DCP1617NW", 1)
    assert not ok


def test_validate_empty_data_rejected():
    assert not enrich._validate_scraped_data(None, "HP", "x", 1)
    assert not enrich._validate_scraped_data({}, "HP", "x", 1)
