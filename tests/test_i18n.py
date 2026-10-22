"""Proje dili (server/i18n.py): katalog bütünlüğü, çeviri davranışı, çıktı dili yönergesi, karışık dil denetimi."""
import ast
import glob
import os

import pytest

from server import i18n as I18N
from server import langcheck as LC

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CALLEES = {"_", "translate", "N_", "tx"}


def _keys_used():
    """server/ altında `_("...")`, `translate("...")`, `N_("...")` çağrılarının sabit ilk argümanları: {metin: [dosya:satır]}."""
    used = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "server", "**", "*.py"), recursive=True)):
        if os.sep + "locales" + os.sep in path or path.endswith(("i18n.py", "langcheck.py")):
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            arg = node.args[0]
            if name in CALLEES and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                used.setdefault(arg.value, []).append(f"{os.path.relpath(path, ROOT)}:{node.lineno}")
    return used


def test_every_marked_text_has_an_english_translation():
    cat = I18N._load_catalog()
    missing = {k: v for k, v in _keys_used().items() if not str(cat.get(k, "")).strip()}
    assert not missing, "İngilizce karşılığı olmayan metinler (server/locales/en_*.py):\n" + "\n".join(f"{v[0]}  {k[:90]!r}" for k, v in sorted(missing.items(), key=lambda kv: kv[1][0])[:40])


def test_catalog_entries_keep_placeholders_and_are_not_turkish():
    import re
    cat = I18N._load_catalog()
    ph = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*(?:![rsa])?(?::[^{}]*)?\}")
    bad = []
    for src, en in cat.items():
        if sorted(m.split(":")[0].split("!")[0] for m in ph.findall(src)) != sorted(m.split(":")[0].split("!")[0] for m in ph.findall(en)):
            bad.append(("placeholder", src[:70]))
        if LC.TR_LETTERS.search(re.sub(r"`[^`]*`", "", en)):
            bad.append(("turkish", en[:70]))
    assert not bad, bad[:20]


def test_translate_is_identity_in_turkish_and_formats_placeholders():
    with I18N.use_lang("tr"):
        assert I18N._("Görev: {t}", t="X") == "Görev: X"
        assert I18N._("Hiç bilinmeyen cümle") == "Hiç bilinmeyen cümle"
    with I18N.use_lang("en"):
        assert I18N._("Hiç bilinmeyen cümle") == "Hiç bilinmeyen cümle"          # karşılığı yoksa Türkçe kalır ve missing() ile görünür
        assert "Hiç bilinmeyen cümle" in I18N.missing()


def test_use_lang_overrides_and_restores():
    with I18N.use_lang("en"):
        assert I18N.current() == "en"
        with I18N.use_lang("tr"):
            assert I18N.current() == "tr"
        assert I18N.current() == "en"
    assert I18N.normalize("EN-us") == "en" and I18N.normalize("de") == "tr" and I18N.normalize(None) == "tr"


def test_directive_is_in_the_project_language():
    assert "Türkçe" in I18N.directive("tr") and "English" in I18N.directive("en") and "ALL text" in I18N.directive("en")


def test_langcheck_flags_turkish_in_english_projects_only():
    files = [{"path": "docs/PRD.md", "content": "# PRD\n\n## Kabul kriterleri\nKullanıcı giriş yapabilmeli ve yönetici kayıtları görebilmeli.\n"},
             {"path": "docs/ok.md", "content": "# Overview\n\nUsers can sign in.\n\n```\nçalıştır\n```\n"},
             {"path": "src/a.py", "content": "print('çalıştır')"}]
    found = LC.check_files("en", files)
    assert [f["path"] for f in found] == ["docs/PRD.md"] and found[0]["sample"]
    assert LC.check_files("tr", files) == []
    assert "docs/PRD.md" in LC.warning_text(found)
