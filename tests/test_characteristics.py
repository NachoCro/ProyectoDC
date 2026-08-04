"""Tests for default-characteristics merge logic (middleware/characteristics.py)."""

from middleware import characteristics


def test_clean_drops_placeholders():
    cleaned = characteristics._clean_characteristics([
        {"nombre": "Resolucion", "valor": "4K"},
        {"nombre": "{{upgrade.yesAttr.text}}", "valor": "Si"},
        {"nombre": "Color", "valor": "${state.color}"},
        {"nombre": "Peso", "valor": "  1.2 kg  "},
    ])
    assert cleaned == [
        {"nombre": "Resolucion", "valor": "4K"},
        {"nombre": "Peso", "valor": "1.2 kg"},
    ]


def test_merge_without_template_returns_cleaned(monkeypatch):
    monkeypatch.setattr(characteristics, "get_template", lambda sub: [])
    out = characteristics.merge_characteristics(
        [{"nombre": "  Peso ", "valor": "1 kg"}], "X"
    )
    assert out == [{"nombre": "Peso", "valor": "1 kg"}]


def test_merge_template_rules(monkeypatch):
    template = [
        {"nombre": "Color", "valor_default": "Negro"},
        {"nombre": "Peso", "valor_default": "1 kg"},
    ]
    monkeypatch.setattr(characteristics, "get_template", lambda sub: template)

    proposed = [
        {"nombre": "COLOR", "valor": "Blanco"},
        {"nombre": "Extra", "valor": "123"},
        {"nombre": "{{garbage}}", "valor": "x"},
    ]
    out = characteristics.merge_characteristics(proposed, "X")

    assert out == [
        {"nombre": "Color", "valor": "Blanco"},
        {"nombre": "Peso", "valor": "1 kg"},
        {"nombre": "Extra", "valor": "123"},
    ]


def test_merge_template_missing_value_uses_default(monkeypatch):
    template = [{"nombre": "Tipo de pantalla", "valor_default": "LED"}]
    monkeypatch.setattr(characteristics, "get_template", lambda sub: template)
    out = characteristics.merge_characteristics(
        [{"nombre": "Resolucion", "valor": "1080p"}], "X"
    )
    assert out == [
        {"nombre": "Tipo de pantalla", "valor": "LED"},
        {"nombre": "Resolucion", "valor": "1080p"},
    ]


def test_get_template_unknown_subcat_returns_empty():
    assert characteristics.get_template("NO EXISTE") == []


def test_get_template_real_mapping():
    template = characteristics.get_template("MONITORES")
    assert isinstance(template, list)
