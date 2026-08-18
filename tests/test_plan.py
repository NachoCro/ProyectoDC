"""Tests para selección de productos por similitud con el nombre (middleware/plan.py)."""

from middleware.plan import matches_name, significant_tokens


# ── significant_tokens ──────────────────────────────────────────────────────


def test_significant_tokens_basic():
    assert significant_tokens("MOTOSIERRAS A GASOLINA") == ["MOTOSIERRAS", "GASOLINA"]


def test_significant_tokens_drops_stopwords_and_short():
    assert significant_tokens("Smart TV de 55") == ["SMART"]


def test_significant_tokens_strips_accents():
    assert significant_tokens("Televisores") == ["TELEVISORES"]


def test_significant_tokens_empty():
    assert significant_tokens("a el la") == []


# ── matches_name ────────────────────────────────────────────────────────────


def test_plural_singular_match():
    assert matches_name("MONITORES", "Monitor LED 24 Pulgadas Samsung")


def test_exact_token_match_case_insensitive():
    assert matches_name("MOTOSIERRAS", "Motosierra a gasolina 62cc")


def test_no_match():
    assert not matches_name("MONITORES", "Impresora Laser HP")


def test_all_tokens_required():
    assert matches_name("MOTOSIERRAS A GASOLINA", "Motosierra a gasolina 62cc")
    assert not matches_name("MOTOSIERRAS A GASOLINA", "Motosierra electrica")


def test_accent_insensitive():
    assert matches_name("TELEVISORES", "Televisor LED 55")


def test_smart_tv_matches_tv_names():
    assert matches_name("Smart TV", "Smart TV 55 4K Samsung")


def test_similarity_does_not_resolve_synonyms():
    assert not matches_name("TELEVISORES", "Smart TV 55")


def test_short_target_falls_back_to_substring():
    assert matches_name("TV", "Smart TV 55 4K")
    assert not matches_name("TV", "Monitor LED 24")


def test_short_target_does_not_match_inside_other_word():
    # "TV" no debe matchear a "CCTV" (subcadena dentro de otra palabra): la
    # ejecución única "TV" seleccionaba cargadores de cámaras como TVs.
    assert not matches_name("TV", "CARGADOR P/CAM CCTV 220/12V 2AMP")
    assert not matches_name("TV", "VIDEOCAM IP 2MP")
    assert matches_name("CCTV", "CARGADOR P/CAM CCTV 220/12V 2AMP")


def test_stopword_only_target_falls_back_to_substring():
    assert matches_name("tipo de", "Notebook tipo de uso hogar")
    assert not matches_name("tipo de", "Notebook")


def test_stopwords_match_case_insensitive():
    assert significant_tokens("MOTOSIERRAS CON GASOLINA") == ["MOTOSIERRAS", "GASOLINA"]
    assert significant_tokens("repuestos motosierra") == ["MOTOSIERRA"]


def test_generic_catalog_words_are_dropped():
    assert matches_name("repuestos motosierra", "BOBINA MOTOSIERRA 38CC")
    assert matches_name("Accesorios desmalezadoras", "CARBURADOR DESMALEZADORA 43-52CC")
    assert matches_name("kit diafragma", "KIT DIAFRAGMA GND307")
    assert not matches_name("repuestos motosierra", "BUJIA CHAMPION N9YC")


def test_no_false_positive_bombin_bobina():
    assert matches_name("bombin", "BOMBIN B&S 3.5HP")
    assert not matches_name("bombin", "BOBINA MOTOSIERRA 38CC")
    assert not matches_name("bobinas", "BOMBIN B&S 3.5HP")


def test_morphological_suffix_variants():
    assert matches_name("cable", "MOUSE LOGITECH CABLEADO")
    assert matches_name("motosierras", "Motosierra a gasolina 62cc")
    assert matches_name("torretas", "TORRETA GIRO CERO 174356")
