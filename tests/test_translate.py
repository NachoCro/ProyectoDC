"""Tests for glossary-protected translation (middleware/translate.py)."""

from middleware import translate


def test_glossary_sorted_longest_first():
    lens = [len(t) for t in translate.GLOSSARY]
    assert lens == sorted(lens, reverse=True)


def test_protect_restore_roundtrip():
    text = "Pantalla QLED 4K con HDMI 2.1 y USB-C"
    protected, placeholders = translate._protect_glossary(text)
    assert "{{" not in protected and "[[" in protected
    restored = translate._restore_glossary(protected, placeholders)
    assert restored == text


def test_protect_no_glossary_terms():
    protected, placeholders = translate._protect_glossary("una frase común")
    assert protected == "una frase común"
    assert placeholders == {}


def test_translate_empty_returns_same():
    assert translate.translate("") == ""
    assert translate.translate("   ") == "   "


def test_translate_unavailable_returns_original(monkeypatch):
    monkeypatch.setattr(translate, "_TRANSLATOR_AVAILABLE", False)
    assert translate.translate("Hola mundo") == "Hola mundo"


def test_translate_preserves_glossary(monkeypatch):
    class FakeTranslator:
        def __init__(self, *args, **kwargs):
            pass

        def translate(self, text):
            return text.replace("Pantalla", "Pantalla traducida")

    monkeypatch.setattr(translate, "_TRANSLATOR_AVAILABLE", True)
    monkeypatch.setattr(translate, "GoogleTranslator", FakeTranslator)

    result = translate.translate("Pantalla USB-C 4K")
    assert result == "Pantalla traducida USB-C 4K"


def test_translate_error_returns_original(monkeypatch):
    class FailingTranslator:
        def __init__(self, *args, **kwargs):
            pass

        def translate(self, text):
            raise RuntimeError("boom")

    monkeypatch.setattr(translate, "_TRANSLATOR_AVAILABLE", True)
    monkeypatch.setattr(translate, "GoogleTranslator", FailingTranslator)
    assert translate.translate("Hola mundo") == "Hola mundo"


def test_translate_product_translates_named_fields(monkeypatch):
    calls = []

    class FakeTranslator:
        def __init__(self, *args, **kwargs):
            pass

        def translate(self, text):
            calls.append(text)
            return text + "!"

    monkeypatch.setattr(translate, "_TRANSLATOR_AVAILABLE", True)
    monkeypatch.setattr(translate, "GoogleTranslator", FakeTranslator)

    data = {"titulo": "TV", "descripcion": "desc", "sku": "ABC123", "precio": 10}
    out = translate.translate_product(data)
    assert out["titulo"] == "TV!"
    assert out["descripcion"] == "desc!"
    assert out["sku"] == "ABC123"
    assert out["precio"] == 10
