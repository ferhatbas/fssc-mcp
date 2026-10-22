"""Karışık dil denetimi: proje dili `en` iken teslim edilen belge ve metinlerde Türkçe kalıntıyı yakalar (yalnızca uyarı; teslimi reddetmez).

Neden yalnızca uyarı: ajan özel adları (kişi, yer, ürün) Türkçe harfle yazabilir; amaç ajanın bağlamdaki Türkçe başlıkları kopyalamasını görünür kılmaktır.
Ölçüt: Türkçeye özgü harfler (ığüşöçİĞÜŞÖÇ) kod blokları ve satır içi kod hariç düz metinde; ve sık Türkçe başlık/sözcükler.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

TR_LETTERS = re.compile(r"[ığüşöçİĞÜŞÖÇ]")
_FENCE = re.compile(r"```.*?```", re.S)
_INLINE = re.compile(r"`[^`\n]*`")
_STRONG_TR_WORDS = re.compile(r"\b(görev|kabul kriter\w*|açıklama|toplantı|karar\w*|gerekçe|teslim|yönetici|kullanıcı)\b", re.I)
TEXT_SUFFIXES = (".md", ".txt", ".html", ".json", ".csv", ".yml", ".yaml")
# Kod ve veri dosyaları (içinde Türkçe sabit metin başka bir sorundur): yalnızca belge uzantıları taranır
DOC_SUFFIXES = (".md", ".txt")
MIN_LETTERS = 3          # bir dosyada bu kadar Türkçe harf yoksa uyarı verilmez
MIN_WORDS = 4


def _prose(text: str) -> str:
    return _INLINE.sub(" ", _FENCE.sub(" ", text or ""))


def scan_text(text: str) -> Dict[str, Any]:
    prose = _prose(text)
    letters = TR_LETTERS.findall(prose)
    words = _STRONG_TR_WORDS.findall(prose)
    sample = next((ln.strip()[:120] for ln in prose.splitlines() if TR_LETTERS.search(ln) or _STRONG_TR_WORDS.search(ln)), "")
    return {"letters": len(letters), "words": len(words), "sample": sample}


def is_mixed(scan: Dict[str, Any]) -> bool:
    return scan["letters"] >= MIN_LETTERS or scan["words"] >= MIN_WORDS


def check_files(lang: str, files: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """`en` projede teslim edilen belge dosyalarını tarar; Türkçe kalıntısı olanların listesini döner. Diğer dillerde boştur."""
    if lang != "en":
        return []
    out: List[Dict[str, Any]] = []
    for f in files or []:
        path = str(f.get("path") or "")
        if not path.lower().endswith(DOC_SUFFIXES):
            continue
        scan = scan_text(str(f.get("content") or ""))
        if is_mixed(scan):
            out.append({"path": path, **scan})
    return out


def check_texts(lang: str, texts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Alan adı -> metin sözlüğünü (özet, Jira başlığı, kabul kriteri...) tarar."""
    if lang != "en":
        return []
    out: List[Dict[str, Any]] = []
    for name, value in (texts or {}).items():
        items = value if isinstance(value, list) else [value]
        joined = "\n".join(str(v) for v in items if v)
        scan = scan_text(joined)
        if scan["letters"] >= 1 or scan["words"] >= 2:
            out.append({"path": name, **scan})
    return out


def warning_text(findings: List[Dict[str, Any]]) -> str:
    names = ", ".join(f["path"] for f in findings[:4]) + (" …" if len(findings) > 4 else "")
    return (f"Language check: {len(findings)} item(s) in this English project still contain Turkish text ({names}). "
            f"Example: \"{findings[0]['sample']}\"")
