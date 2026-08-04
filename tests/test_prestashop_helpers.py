"""Tests for AdminPrestashopClient XML helpers (admin_ui/prestashop.py)."""

import xml.etree.ElementTree as ET

from admin_ui.prestashop import (
    _strip_prestashop_attrs,
    _wrap_language_cdata,
)


def test_wrap_language_cdata():
    xml = (
        "<prestashop><product><description>"
        "<language id=\"1\">&lt;p&gt;Hola&lt;/p&gt;</language>"
        "</description></product></prestashop>"
    )
    out = _wrap_language_cdata(xml)
    assert "<![CDATA[<p>Hola</p>]]>" in out


def test_wrap_language_cdata_ignores_self_closing():
    xml = "<prestashop><product><visibility><language id=\"1\"/></visibility></product></prestashop>"
    out = _wrap_language_cdata(xml)
    assert "<![CDATA[" not in out


def test_wrap_language_cdata_empty_content():
    xml = "<prestashop><product><name><language id=\"1\"></language></name></product></prestashop>"
    out = _wrap_language_cdata(xml)
    assert "<![CDATA[]]>" in out


def test_strip_prestashop_attrs():
    root = ET.fromstring(
        '<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<product id="5" nodeType="simple" api="x">'
        '<name><language id="1" xlink:href="http://x">TV</language></name>'
        "</product></prestashop>"
    )
    _strip_prestashop_attrs(root)
    product = root.find(".//product")
    assert product.attrib == {}
    lang = root.find(".//language")
    assert lang.attrib == {"id": "1"}


def test_strip_prestashop_attrs_multilang_keeps_each_id():
    root = ET.fromstring(
        '<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">'
        "<product><name>"
        '<language id="1" xlink:href="a">Uno</language>'
        '<language id="2" xlink:href="b">Dos</language>'
        "</name></product></prestashop>"
    )
    _strip_prestashop_attrs(root)
    langs = root.findall(".//language")
    assert [lang.attrib.get("id") for lang in langs] == ["1", "2"]
    assert all(len(lang.attrib) == 1 for lang in langs)


def test_set_field_scalar_update():
    from admin_ui.prestashop import AdminPrestashopClient

    parent = ET.fromstring("<product><active>0</active></product>")
    AdminPrestashopClient._set_field(parent, "active", "1")
    assert parent.findtext("active") == "1"


def test_set_field_scalar_create():
    from admin_ui.prestashop import AdminPrestashopClient

    parent = ET.fromstring("<product/>")
    AdminPrestashopClient._set_field(parent, "visibility", "both")
    assert parent.findtext("visibility") == "both"


def test_set_field_multilang_update():
    from admin_ui.prestashop import AdminPrestashopClient

    parent = ET.fromstring("<product><name><language id=\"1\">Viejo</language></name></product>")
    AdminPrestashopClient._set_field(parent, "name", "Nuevo")
    lang = parent.find(".//name/language")
    assert lang is not None
    assert lang.text == "Nuevo"


def test_set_field_multilang_create():
    from admin_ui.prestashop import AdminPrestashopClient

    parent = ET.fromstring("<product/>")
    AdminPrestashopClient._set_field(parent, "link_rewrite", "mi-tv")
    lang = parent.find(".//link_rewrite/language")
    assert lang is not None
    assert lang.get("id") == "1"
    assert lang.text == "mi-tv"


def test_read_only_fields_removed_on_put(monkeypatch):
    from admin_ui import prestashop as ps

    puts_sent = []

    def fake_request(self, resource, params=None):
        return ET.fromstring(
            "<prestashop><product id=\"1\" nodeType=\"simple\">"
            "<state>0</state><position_in_category>3</position_in_category>"
            "<name><language id=\"1\">TV</language></name>"
            "</product></prestashop>"
        )

    def fake_put(url, data, headers):
        puts_sent.append(data)
        return type("R", (), {"status_code": 200, "text": "ok"})()

    class FakeSession:
        def put(self, url, data, headers):
            return fake_put(url, data, headers)

    from middleware import prestashop as mp

    monkeypatch.setattr(mp, "PRESTASHOP_API_URL", "http://prestashop.example/api")
    monkeypatch.setattr(mp, "PRESTASHOP_API_KEY", "fake-key")
    monkeypatch.setattr(ps.PrestashopClient, "_request", fake_request)
    monkeypatch.setattr(ps, "API_SLEEP", 0)

    client = ps.AdminPrestashopClient()
    client._session = FakeSession()
    client.put_product(1, {})

    last = ET.fromstring(puts_sent[-1])
    body = last.find(".//product")
    body_tags = {child.tag for child in body}
    # Read-only fields must not be sent back to PrestaShop
    assert "position_in_category" not in body_tags
    # state is read-only on GET but re-forced to 1 by put_product (PS 8.1)
    assert body.findtext("state") == "1"
    # put_product re-forces visibility + indexed for PrestaShop 8.1
    assert body.findtext("visibility") == "both"
    assert body.findtext("indexed") == "1"
