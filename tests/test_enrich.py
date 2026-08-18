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
    assert "<strong>Color:</strong> NEGRO" in desc
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


# ── brand-less / generic products (validated against unrelated scrapes) ─────


def test_validate_brandless_rejects_unrelated_scrape():
    # "KIT DIAFRAGMA GND307" (carburetor part) must not be enriched as a GPU.
    data = {
        "marca": "NVIDIA",
        "title": "GeForce RTX 3070 especificaciones",
        "caracteristicas": [{"nombre": "Muestras", "valor": "38197"}] * 8,
    }
    assert not enrich._validate_scraped_data(data, "", "KIT DIAFRAGMA GND307", 1)


def test_validate_brandless_rejects_part_code_collision():
    # "TORRETA MTD 82-403" shares "82" with the phone "Moto G82" — rejected.
    data = {
        "marca": "Motorola",
        "title": "Motorola Moto G82 5G",
        "caracteristicas": [{"nombre": "Pantalla", "valor": "AMOLED"}] * 8,
    }
    assert not enrich._validate_scraped_data(data, "", "TORRETA MTD 82-403", 1)


def test_validate_brandless_rejects_generic_overlap():
    # Generic words ("tapa"/"combustible") overlap an unrelated truck fuel lid.
    data = {
        "marca": "",
        "title": "Tapa de registro utilizado para camión cisterna de combustible",
        "caracteristicas": [{"nombre": "Material", "valor": "acero"}] * 8,
    }
    assert not enrich._validate_scraped_data(data, "", "TAPA COMBUSTIBLE CHINA", 1)


def test_validate_brandless_rejects_bike_pump_for_bombin():
    data = {
        "marca": "Decathlon",
        "title": "Bombin mano bicicleta de montaña negra",
        "caracteristicas": [{"nombre": "Marca", "valor": "Decathlon"}] * 8,
    }
    assert not enrich._validate_scraped_data(data, "", "BOMBIN CHICO", 1)


def test_validate_brandless_accepts_strong_generic_match():
    # Same family, same code: strong title similarity is accepted.
    data = {
        "marca": "Zama",
        "title": "Kit de diafragma GND 21 para carburador Zama",
        "caracteristicas": [{"nombre": "Material", "valor": "goma"}] * 8,
    }
    assert enrich._validate_scraped_data(data, "", "KIT DIAFRAGMA GND 21", 1)


def test_validate_model_token_not_fragmented_from_hyphenated_code():
    # "NM-ST15" is one code: "st15" must not be treated as a decisive token
    # that rejects a legit TV-mount page.
    data = {
        "marca": "",
        "title": "Soporte de TV para 42 pulgadas con brazo hasta 25kg",
        "caracteristicas": [{"nombre": "Carga", "valor": "25 kg"}] * 8,
    }
    ok = enrich._validate_scraped_data(
        data, "", 'SOPORTE TV DE 17 A 42 HASTA 25KG C/BRAZO NM-ST15', 1
    )
    assert ok


def test_validate_soporte_tv_mount_not_treated_as_support_page():
    # "soporte" = mount/stand here, not a help-desk "support" page.
    data = {
        "marca": "",
        "title": "Soporte de TV brazo articulado para 42 pulgadas hasta 25 kg",
        "caracteristicas": [{"nombre": "Carga", "valor": "25 kg"}] * 8,
    }
    ok = enrich._validate_scraped_data(
        data, "", "SOPORTE TV DE 17 A 42 HASTA 25KG C/BRAZO NM-ST15", 1
    )
    assert ok


# ── _validate_name_coherence ────────────────────────────────────────────────


def test_coherence_scraped_marca_matches_name_brand():
    data = {"marca": "Samsung", "title": "Samsung UE55 Smart TV"}
    assert enrich._validate_name_coherence(data, "Smart TV Samsung UE55 55\" 4K", "Samsung")


def test_coherence_rejects_retailer_as_brand():
    data = {"marca": "Fravega", "title": "Smart TV Samsung UE55 55\" 4K"}
    ok = enrich._validate_name_coherence(
        data, "Smart TV Samsung UE55 55\" 4K", "Samsung"
    )
    assert not ok


def test_coherence_rejects_mismatched_brand():
    data = {"marca": "LG", "title": "Smart TV LG 55"}
    ok = enrich._validate_name_coherence(
        data, "Smart TV Samsung UE55 55\" 4K", "Samsung"
    )
    assert not ok


def test_coherence_accepts_subbrand_variant():
    data = {"marca": "Samsung Electronics", "title": "Samsung UE55 Smart TV"}
    assert enrich._validate_name_coherence(data, "Smart TV Samsung UE55", "Samsung")


def test_coherence_uses_db_marca_when_name_has_no_brand():
    data = {"marca": "Brother", "title": "Impresora laser multifuncion"}
    assert enrich._validate_name_coherence(
        data, "Impresora laser 4 en 1 inalambrica", "Brother"
    )
    assert not enrich._validate_name_coherence(
        data, "Impresora laser 4 en 1 inalambrica", "HP"
    )


def test_coherence_no_reference_passes():
    data = {"marca": "Generic", "title": "Accesorio generico"}
    assert enrich._validate_name_coherence(data, "Cable USB generico", "")


def test_coherence_rejects_title_with_different_brand():
    data = {"marca": "", "title": "Compralo en Fravega - Smart TV LG UE55"}
    ok = enrich._validate_name_coherence(
        data, "Smart TV Samsung UE55 55\" 4K", "Samsung"
    )
    assert not ok


def test_validate_scraped_data_includes_coherence():
    data = {"marca": "Fravega", "title": "Smart TV Samsung UE55 55\" 4K"}
    ok = enrich._validate_scraped_data(data, "Samsung", "Smart TV Samsung UE55 55\" 4K", 1)
    assert not ok


# ── Excel-style value formatting (middleware/characteristics) ───────────────


def test_format_excel_value_uppercases_short_technical_values():
    from middleware.characteristics import format_excel_value

    assert format_excel_value("si") == "SI"
    assert format_excel_value("cable") == "CABLE"
    assert format_excel_value("no") == "NO"


def test_format_excel_value_normalizes_option_lists():
    from middleware.characteristics import format_excel_value

    assert format_excel_value("USB/PS2/Wireless") == "USB / PS2 / Wireless"
    assert format_excel_value("USB | PS2 | Wireless") == "USB / PS2 / Wireless"
    assert format_excel_value("BULLET  /  DOMO") == "BULLET / DOMO"


def test_format_excel_value_keeps_measurements_and_prose():
    from middleware.characteristics import format_excel_value

    assert format_excel_value("100 MB/S") == "100 MB/S"
    assert format_excel_value("1.4 GHz") == "1.4 GHz"
    assert format_excel_value("44mm") == "44mm"
    assert format_excel_value("Samsung Exynos W920") == "Samsung Exynos W920"
    assert format_excel_value("Sí") == "Sí"
    assert format_excel_value("Membrana / Mecánico") == "Membrana / Mecánico"


def test_build_description_html_dedupes_and_truncates():
    from middleware.characteristics import build_description_html

    chars = [
        {"nombre": "PROCESADOR", "valor": "si"},
        {"nombre": "PROCESADOR", "valor": "SI"},
        {"nombre": "x" * 80, "valor": "44mm"},
        {"nombre": "Garbage", "valor": "{{upgrade.yesAttr.text}}"},
    ]
    desc = build_description_html(chars)
    assert desc.count("<strong>PROCESADOR:</strong> SI") == 1
    assert "x" * 80 not in desc
    assert "{{upgrade" not in desc
    assert "<strong>" + "x" * 59 in desc
    assert "44mm" in desc
