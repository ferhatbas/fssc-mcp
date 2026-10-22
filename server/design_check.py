"""Tasarım teslimi tamlık denetimi (sunucu): ajanın "tamamladım" beyanına değil dosyalara bakar.

Yenileme turunda (tüm ekranlar + akışlar) şunları ister: her mockup mobil uyumlu (viewport + @media), betiksiz/harici kaynaksız, en az iki durumlu (dolu + alternatif);
`coverage.md` backend uç gruplarının tamamını anar; `flows.md` ve `flows.html` var; bildirilen ekran dosyaları gerçekten var.
Eksik varsa teslim doğrulama hatası gibi düzeltme turu doğurur (pipeline.finish_step).
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from .api_surface import collect
from .i18n import translate as tx

MIN_STATES = 2
_STATE = re.compile(r"(?i)durum\s*:|state\s*:")


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def check(project_dir: str, docs_root: str, design: Dict[str, Any] | None = None, redesign: bool = True) -> List[str]:
    base = os.path.join(project_dir, *docs_root.replace("\\", "/").split("/"), "design")
    issues: List[str] = []
    shots = os.path.join(base, "screens")
    files = sorted(n for n in os.listdir(shots) if n.endswith(".html")) if os.path.isdir(shots) else []
    if not files:
        return [tx("Hiç ekran mockup'ı yok (`<docs>/design/screens/*.html`).")]
    for n in files:
        t = _read(os.path.join(shots, n))
        problems = []
        if "viewport" not in t:
            problems.append(tx("viewport meta yok"))
        if "@media" not in t and not re.search(r"auto-fit|auto-fill|flex-wrap|clamp\(|min\(", t):
            problems.append(tx("mobil/masaüstü için duyarlılık yok (@media ya da esnek yerleşim: auto-fit, flex-wrap, clamp)"))
        if "<script" in t.lower():
            problems.append(tx("JS içeriyor"))
        if re.search(r"""(?:src|href)=["']https?://""", t):
            problems.append(tx("harici kaynak kullanıyor"))
        if len(_STATE.findall(t)) < MIN_STATES:
            problems.append(tx("en az {n} durum bölümü yok (dolu + boş/hata/yükleniyor/alternatif)", n=MIN_STATES))
        if problems:
            issues.append(f"screens/{n}: " + "; ".join(problems))
    if redesign:
        for name in ("coverage.md", "flows.md", "flows.html"):
            if not os.path.isfile(os.path.join(base, name)):
                issues.append(tx("`{name}` yok", name=name))
        cov = _read(os.path.join(base, "coverage.md"))
        if cov:
            eps = collect(project_dir, docs_root)["endpoints"]
            norm = lambda p: re.sub(r"\{[^}]*\}|:\w+", "{}", p)
            covered = {norm(p) for p in re.findall(r"`(/[^`\s]+)`", cov)}
            missing = sorted({f"{m} {p}" for m, p, _ in eps if norm(p) not in covered and not re.match(r"^/(health|ready|api/docs)", p)})
            if missing:
                issues.append(tx("coverage.md şu uçları kapsamıyor ({n}): {list}", n=len(missing), list="; ".join(missing[:8]) + (" …" if len(missing) > 8 else "")))
    for sc in (design or {}).get("screens") or []:
        f = str((sc or {}).get("file") or "") if isinstance(sc, dict) else ""
        if f:
            rel = f.replace("<docs>/", "").replace("\\", "/")
            if not os.path.isfile(os.path.join(project_dir, *docs_root.replace("\\", "/").split("/"), *rel.split("/"))):
                issues.append(tx("Bildirilen ekran dosyası yok: {file}", file=f))
    return issues
