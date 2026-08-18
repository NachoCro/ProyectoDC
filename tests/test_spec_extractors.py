"""Tests for generic spec extractors (middleware/spec_extractors.py)."""

import json

from bs4 import BeautifulSoup

from middleware import spec_extractors as se


def soup(html):
    return BeautifulSoup(html, "lxml")


def test_is_template_placeholder():
    assert se.is_template_placeholder("{{upgrade.yesAttr.text}}")
    assert se.is_template_placeholder("[[foo]]")
    assert se.is_template_placeholder("${state.color}")
    assert not se.is_template_placeholder("Resolución 4K")
    assert not se.is_template_placeholder("")


def test_clean_feature():
    assert se.clean_feature("Peso", "{{x}}") == ("", "")
    assert se.clean_feature("  Peso ", " 1 kg ") == ("Peso", "1 kg")


def test_extract_tables():
    html = """
    <table>
      <tr><th colspan="2">Pantalla</th></tr>
      <tr><td>Resolución</td><td>4K</td></tr>
      <tr><td>resolución</td><td>duplicado</td></tr>
      <tr><td>Tamaño</td><td>55"</td></tr>
    </table>
    <table>
      <tr><td>A</td><td>B</td><td>C</td></tr>
      <tr><td>Peso</td><td>1.2 kg</td></tr>
      <tr><td>{{tpl}}</td><td>x</td></tr>
    </table>
    """
    feats = se.extract_tables(soup(html))
    names = [f["nombre"] for f in feats]
    assert "Pantalla - Resolución" in names
    assert "Pantalla - Tamaño" in names
    assert "Peso" in names  # second table: section resets, no prefix
    assert len(feats) == 3  # dup y placeholder filtrados


def test_extract_dl_dt_dd():
    html = """
    <dl>
      <dt>Procesador</dt><dd>Core i7</dd>
      <dt>RAM</dt><dd>16 GB</dd>
    </dl>
    <ul>
      <li><strong>Color:</strong> Negro</li>
      <li><strong>Peso</strong> 2 kg</li>
    </ul>
    """
    feats = se.extract_dl_dt_dd(soup(html))
    by_name = {f["nombre"]: f["valor"] for f in feats}
    assert by_name["Procesador"] == "Core i7"
    assert by_name["RAM"] == "16 GB"
    assert by_name["Color"] == "Negro"
    assert by_name["Peso"] == "2 kg"


def test_extract_microdata():
    html = """
    <div itemscope itemtype="https://schema.org/Product">
      <div itemprop="additionalProperty" itemscope>
        <meta itemprop="name" content="Color"><meta itemprop="value" content="Negro">
      </div>
      <span itemprop="weight">1.2 kg</span>
      <span itemprop="brand">Logitech</span>
    </div>
    """
    feats = se.extract_microdata(soup(html))
    by_name = {f["nombre"].lower(): f["valor"] for f in feats}
    assert by_name["color"] == "Negro"
    assert by_name["weight"] == "1.2 kg"
    assert by_name["brand"] == "Logitech"


def test_extract_jsonld_product():
    data = {
        "@type": "Product",
        "name": "TV Samsung QLED",
        "description": "Una TV",
        "brand": {"name": "Samsung"},
        "mpn": "QN55Q60C",
        "image": ["https://img/a.jpg", "https://img/b.jpg"],
        "additionalProperty": [
            {"name": "Resolución", "value": "4K"},
            {"name": "Tamaño", "value": "55"},
        ],
        "weight": {"value": 12.5, "unitText": "kg"},
    }
    html = (
        "<script type='application/ld+json'>"
        + json.dumps(data)
        + "</script>"
    )
    out = se.extract_jsonld_product(soup(html))
    assert out is not None
    assert out["title"] == "TV Samsung QLED"
    assert out["marca"] == "Samsung"
    assert out["modelo"] == "QN55Q60C"
    assert out["imagen_url"] == "https://img/a.jpg"
    chars = {c["nombre"]: c["valor"] for c in out["caracteristicas"]}
    assert chars["Resolución"] == "4K"
    assert chars["Weight"] == "12.5 kg"


def test_extract_jsonld_none_when_no_product():
    html = "<script type='application/ld+json'>{\"@type\":\"Organization\",\"name\":\"X\"}</script>"
    assert se.extract_jsonld_product(soup(html)) is None


def test_extract_og_product_meta():
    html = """
    <meta property="og:title" content="Mouse Gamer">
    <meta name="description" content="Un mouse">
    <meta property="product:brand" content="Logitech">
    <meta property="og:image" content="https://img/x.png">
    """
    out = se.extract_og_product_meta(soup(html))
    assert out["title"] == "Mouse Gamer"
    assert out["desc"] == "Un mouse"
    assert out["brand"] == "Logitech"
    assert out["img"] == "https://img/x.png"


def test_extract_og_fallback_title_tag():
    html = "<title>El Titulo</title>"
    out = se.extract_og_product_meta(soup(html))
    assert out["title"] == "El Titulo"


def test_extract_js_state_objects_next_data():
    data = {
        "props": {
            "product": {
                "screenSize": '55"',
                "resolution": "4K",
                "id": 123,
                "url": "/tv",
            }
        }
    }
    html = "<script id='__NEXT_DATA__' type='application/json'>" + json.dumps(data) + "</script>"
    feats = se.extract_js_state_objects(html)
    by_name = {f["nombre"]: f["valor"] for f in feats}
    assert by_name["Screen Size"] == '55"'
    assert by_name["Resolution"] == "4K"
    assert "Id" not in by_name and "Url" not in by_name


def test_humanize_key():
    assert se._humanize_key("batteryLife") == "Battery Life"
    assert se._humanize_key("screen_size") == "Screen Size"
    assert se._humanize_key("refreshRate") == "Refresh Rate"


def test_extract_body_text_specs():
    html = """
    <html><body>
      Resolución: 4K
      Precio: $100
      Peso: 1.2 kg
      tamaño: 55"
      HDR10: Si
    </body></html>
    """
    feats = se.extract_body_text_specs(soup(html))
    by_name = {f["nombre"]: f["valor"] for f in feats}
    assert by_name["Resolución"] == "4K"
    assert by_name["Peso"] == "1.2 kg"
    assert "Precio" not in by_name
    assert "tamaño" not in by_name


class _FakeResp:
    def __init__(self, content, encoding=None, apparent_encoding=None):
        self.content = content
        self.encoding = encoding
        self.apparent_encoding = apparent_encoding


def test_decode_response_utf8_no_charset_header():
    body = "<html><body><p>Resolución 4K — ñandú</p></body></html>"
    resp = _FakeResp(body.encode("utf-8"), encoding=None)
    assert se.decode_response(resp) == body


def test_decode_response_meta_charset_beats_latin_header():
    body = (
        '<html><head><meta charset="utf-8"></head>'
        "<body><p>Resolución 4K — ñandú</p></body></html>"
    )
    resp = _FakeResp(body.encode("utf-8"), encoding="ISO-8859-1")
    assert se.decode_response(resp) == body


def test_decode_response_header_charset_honored():
    body = '<html><body><p>Größe: 55"</p></body></html>'
    resp = _FakeResp(body.encode("iso-8859-1"), encoding="ISO-8859-1")
    out = se.decode_response(resp)
    assert "Größe" in out


def test_decode_response_apparent_encoding_fallback():
    body = '<html><body><p>Déjà vu — 100%</p></body></html>'
    resp = _FakeResp(body.encode("utf-8"), encoding=None,
                     apparent_encoding="utf-8")
    assert se.decode_response(resp) == body


def test_decode_response_empty_body():
    resp = _FakeResp(b"")
    assert se.decode_response(resp) == ""


def test_normalize_text_decodes_html_entities():
    assert se.normalize_text("Encontr&#225; en Space &#128640;") == "Encontrá en Space 🚀"
    assert se.normalize_text('Estuche &quot;Tomo&quot;') == 'Estuche "Tomo"'
    assert se.normalize_text("CADENA 3/8&#039;&#039; 1.3mm") == "CADENA 3/8'' 1.3mm"
    assert se.normalize_text("B&amp;s") == "B&s"
    assert se.normalize_text("OSLO&nbsp;es &amp;nbsp;") == "OSLO\u00a0es \u00a0"


def test_normalize_text_repairs_mojibake():
    assert se.normalize_text("caracterÃ\xadsticas") == "características"
    assert se.normalize_text("resoluciÃ³n Full HD+") == "resolución Full HD+"
    assert se.normalize_text("diseÃ±ado") == "diseñado"
    # double-encoded numeric entities
    assert se.normalize_text("&#195;&#179;") == "ó"


def test_normalize_text_leaves_clean_text_untouched():
    assert se.normalize_text("Resolución y configuración — correcto") == "Resolución y configuración — correcto"
    assert se.normalize_text("Mejorá el rendimiento") == "Mejorá el rendimiento"
    assert se.normalize_text("") == ""
    assert se.normalize_text(None) is None


def test_normalize_product_recursive():
    data = {
        "title": "Filtro de Aire B&amp;s",
        "descripcion": "caracterÃ\xadsticas",
        "caracteristicas": [
            {"nombre": "Resoluci&#243;n", "valor": "4K"},
            {"nombre": "Marca", "valor": "diseÃ±ado en ES"},
        ],
        "imagen_urls": ["http://x/a.png"],
    }
    out = se.normalize_product(data)
    assert out["title"] == "Filtro de Aire B&s"
    assert out["descripcion"] == "características"
    assert out["caracteristicas"][0] == {"nombre": "Resolución", "valor": "4K"}
    assert out["caracteristicas"][1]["valor"] == "diseñado en ES"



