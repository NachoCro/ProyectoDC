"""Tests for the PrestaShop 8.1 compat toggle (admin_ui/prestashop.py)."""

import xml.etree.ElementTree as ET

import pytest

from admin_ui import prestashop as ps
from admin_ui.prestashop import ps81_workarounds_enabled


def _fake_request(self, resource, params=None):
    return ET.fromstring(
        '<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<product id="1" nodeType="simple">'
        "<state>0</state><position_in_category>3</position_in_category>"
        '<name><language id="1" xlink:href="http://x">TV</language></name>'
        "</product></prestashop>"
    )


class _FakeSession:
    def __init__(self):
        self.sent = []

    def put(self, url, data, headers):
        self.sent.append(data)
        return type("R", (), {"status_code": 200, "text": "ok"})()


@pytest.fixture
def put_env(monkeypatch):
    from middleware import prestashop as mp

    monkeypatch.setattr(mp, "PRESTASHOP_API_URL", "http://prestashop.example/api")
    monkeypatch.setattr(mp, "PRESTASHOP_API_KEY", "fake-key")
    monkeypatch.setattr(ps.PrestashopClient, "_request", _fake_request)
    monkeypatch.setattr(ps, "API_SLEEP", 0)


def _run_put(monkeypatch, compat: str):
    monkeypatch.setattr(ps, "get_config", lambda key, default="": compat)
    session = _FakeSession()
    client = ps.AdminPrestashopClient()
    client._session = session  # type: ignore[assignment]
    client.put_product(1, {})
    return ET.fromstring(session.sent[-1])


def test_ps81_workarounds_enabled_true(monkeypatch):
    monkeypatch.setattr(ps, "get_config", lambda key, default="": "1")
    assert ps81_workarounds_enabled() is True


def test_ps81_workarounds_enabled_false(monkeypatch):
    monkeypatch.setattr(ps, "get_config", lambda key, default="": "0")
    assert ps81_workarounds_enabled() is False


def test_compat_on_forces_fields_and_strips_attrs(put_env, monkeypatch):
    last = _run_put(monkeypatch, "1")
    body = last.find(".//product")
    assert body.findtext("state") == "1"
    assert body.findtext("visibility") == "both"
    assert body.findtext("indexed") == "1"
    # GET attributes must be stripped (PS 8.1 rejects them)
    assert body.get("nodeType") is None
    lang = last.find(".//language")
    assert lang is not None
    assert "{http://www.w3.org/1999/xlink}href" not in lang.attrib
    assert lang.get("id") == "1"


def test_compat_off_skips_workarounds(put_env, monkeypatch):
    last = _run_put(monkeypatch, "0")
    body = last.find(".//product")
    body_tags = {child.tag for child in body}
    # state was read-only on GET → removed, but NOT re-forced to 1
    assert "state" not in body_tags
    assert "visibility" not in body_tags
    assert "indexed" not in body_tags
    # GET attributes survive untouched (older PS versions tolerate them)
    assert body.get("nodeType") == "simple"
    lang = last.find(".//language")
    assert lang is not None
    assert "{http://www.w3.org/1999/xlink}href" in lang.attrib
