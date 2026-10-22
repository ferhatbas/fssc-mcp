"""Proje dili: sunucu metinleri için mesaj kataloğu ve ajanlara çıktı dili yönergesi.

Dil proje başınadır (`settings.project_language`: `tr` varsayılan | `en`); pano dili ayrı bir tercihtir (dashboard/src/i18n).
Kaynak dil Türkçedir: kodda `_("Türkçe cümle")` yazılır, `tr` iken aynen döner, `en` iken katalogda (`server/locales/en_*.py`) karşılığı aranır;
karşılığı olmayan metin Türkçe kalır ve `missing()` ile raporlanır (test: tests/test_i18n.py).
Aktif dil: `use_lang()` bağlamı > hub'ın aktif proje ayarı > `AGY_PROMPT_LANG` ortam değişkeni.
"""
from __future__ import annotations

import contextlib
import contextvars
import importlib
import os
import pkgutil
from typing import Any, Callable, Dict, Iterator, List, Optional

SUPPORTED = ("tr", "en")
DEFAULT_LANG = "tr"
LANG_NAMES = {"tr": "Türkçe", "en": "English"}

_current: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("fssc_project_lang", default=None)
_resolver: Optional[Callable[[], Optional[str]]] = None
_catalog_en: Optional[Dict[str, str]] = None
_seen_missing: Dict[str, int] = {}


def normalize(lang: Any) -> str:
    value = str(lang or "").strip().lower()[:2]
    return value if value in SUPPORTED else DEFAULT_LANG


def set_resolver(fn: Optional[Callable[[], Optional[str]]]) -> None:
    """Bağlam kurulu değilken dili veren işlev (hub: aktif projenin `project_language` ayarı)."""
    global _resolver
    _resolver = fn


def current() -> str:
    lang = _current.get()
    if lang:
        return normalize(lang)
    if _resolver is not None:
        try:
            got = _resolver()
            if got:
                return normalize(got)
        except Exception:
            pass
    return normalize(os.environ.get("AGY_PROMPT_LANG", DEFAULT_LANG))


@contextlib.contextmanager
def use_lang(lang: Optional[str]) -> Iterator[str]:
    token = _current.set(normalize(lang) if lang else None)
    try:
        yield current()
    finally:
        _current.reset(token)


def project_lang(hub: Any) -> str:
    try:
        return normalize((hub.get_settings() or {}).get("project_language"))
    except Exception:
        return DEFAULT_LANG


def _load_catalog() -> Dict[str, str]:
    global _catalog_en
    if _catalog_en is None:
        merged: Dict[str, str] = {}
        try:
            from . import locales
            for info in pkgutil.iter_modules(locales.__path__):
                if info.name.startswith("en_"):
                    mod = importlib.import_module(f"{locales.__name__}.{info.name}")
                    merged.update(getattr(mod, "EN", {}))
        except Exception:
            pass
        _catalog_en = merged
    return _catalog_en


def reload_catalog() -> None:
    global _catalog_en
    _catalog_en = None


def translate(text: str, lang: Optional[str] = None, /, **kw: Any) -> str:
    """Türkçe kaynak metni verilen (ya da aktif) dile çevirir; `{ad}` yer tutucularını `kw` ile doldurur."""
    if lang is None and "lang" in kw and "{lang}" not in text:        # `tx(metin, lang=...)` çağrıları dili anahtar sözcükle verir
        lang = kw.pop("lang")
    lg = normalize(lang) if lang else current()
    out = text
    if lg == "en":
        cat = _load_catalog()
        if text in cat:
            out = cat[text]
        else:
            _seen_missing[text] = _seen_missing.get(text, 0) + 1
    if kw:
        try:
            out = out.format(**kw)
        except (KeyError, IndexError, ValueError):
            pass
    return out


_ = translate
tx = translate      # kısa ad: modüllerde `from ..i18n import translate as tx, N_` (çıplak `_` döngü değişkenleriyle çakışır, kullanma)


def N_(text: str) -> str:
    """Çeviri anahtarı işaretçisi (gettext `N_`): metin şimdi çevrilmez, sabit/liste tanımında anahtar olarak kayda geçer; kullanım yerinde `_(değişken)` ile çevrilir."""
    return text


def variants(text: str, **kw: Any) -> List[str]:
    """Metnin tüm dillerdeki biçimleri (eşleştirme için): içinde Türkçe kaynak metni arayan/karşılaştıran kod her dildeki biçimi kabul etmelidir."""
    return list(dict.fromkeys(translate(text, lg, **kw) for lg in SUPPORTED))


def matches(value: str, text: str, **kw: Any) -> bool:
    """`value`, `text`'in herhangi bir dildeki biçimiyle aynı mı?"""
    return str(value) in variants(text, **kw)


def missing() -> List[str]:
    """Bu süreçte `en` istenip katalogda bulunamayan Türkçe kaynak metinler (kalan çeviri işi)."""
    return sorted(_seen_missing)


_DIRECTIVE = {
    "tr": ("## Çıktı dili\nBu projenin dili **Türkçe**. Ürettiğin tüm metni Türkçe yaz: belgeler (PRD, ADR, mimari, toplantı notları, raporlar, README), "
           "Jira başlıkları ve kabul kriterleri, özet (`summary`), devir notları, sorular ve commit mesajları. Kod, dosya yolları, API alanları ve teknik "
           "tanımlayıcılar özgün adlarıyla kalır."),
    "en": ("## Output language\nThe language of this project is **English**. Write ALL text you produce in English, even though parts of this context are in another "
           "language: documents (PRD, ADRs, architecture, meeting notes, reports, README), Jira titles and acceptance criteria, the summary (`summary`), handoff notes, "
           "questions, thinking notes and commit messages. Do not copy Turkish headings or sentences from this context into your output; translate them. "
           "Code, file paths, API fields and technical identifiers keep their original names."),
}


def directive(lang: Optional[str] = None) -> str:
    return _DIRECTIVE[normalize(lang) if lang else current()]
