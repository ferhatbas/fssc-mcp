"""Mimari karar kayıtları (ADR, F4, belge §10.6): `FS-docs/adr/NNNN-<kebab-baslik>.md`.

Numara proje genelinde dört haneli sıradır (F2'deki teknoloji ADR'leri aynı klasörü ve numaralamayı kullanır).
Teknoloji kararının ADR'si hiçbir zaman `VARSAYIM` olamaz: yalnızca yönetici onayıyla `KABUL EDİLDİ` açılır.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .i18n import translate as tx, N_, variants

ADR_STATUSES = ("ÖNERİLDİ", "KABUL EDİLDİ", "VARSAYIM", "REDDEDİLDİ", "YERİNİ ALDI")
_TR = str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c", "İ": "i", "Ş": "s", "Ğ": "g", "Ü": "u", "Ö": "o", "Ç": "c"})


def _status_label() -> str:
    """Durum etiketi her dildeki biçimiyle (ADR başka dilde yazılmış olabilir): üretilen belge sonradan aranıyor."""
    return "(?:" + "|".join(re.escape(v) for v in variants("Durum")) + ")"


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(title).translate(_TR).lower()).strip("-")[:48] or "karar"


def adr_dir(project_dir: str, docs_rel: str) -> str:
    return os.path.join(project_dir, *docs_rel.split("/"), "adr")


def next_number(directory: str) -> str:
    nums = [int(m.group(1)) for f in (os.listdir(directory) if os.path.isdir(directory) else []) for m in [re.match(r"^(\d{4})-", f)] if m]
    return f"{(max(nums) + 1) if nums else 1:04d}"


def write_adr(project_dir: str, docs_rel: str, *, title: str, status: str, context: str, options: Optional[List[str]] = None,
              chosen: Optional[str] = None, rationale: str = "", consequences: Optional[Dict[str, List[str]]] = None, sprint: Optional[int] = None,
              decision_ref: Optional[str] = None, question_ref: Optional[str] = None, decider: str = "", reversible: bool = True,
              technology: bool = False) -> Dict[str, str]:
    """ADR dosyasını yazar ve {number, file, status} döner. Teknoloji ADR'si `VARSAYIM` olamaz."""
    if status not in ADR_STATUSES:
        raise ValueError(f"ADR durumu geçersiz: {status}")
    if technology and status == "VARSAYIM":
        raise ValueError("Teknoloji kararının ADR'si VARSAYIM olamaz; yalnızca yönetici onayıyla KABUL EDİLDİ açılır.")
    directory = adr_dir(project_dir, docs_rel)
    os.makedirs(directory, exist_ok=True)
    number = next_number(directory)
    rel = f"{docs_rel}/adr/{number}-{slug(title)}.md"
    head = [f"# ADR {number}: {title}", "", "- **" + tx("Durum") + ":** " + status,
            "- **" + tx("Tarih") + ":** " + datetime.now(timezone.utc).strftime("%Y-%m-%d") + (" · **" + tx("Sprint") + f":** {sprint}" if sprint else "")
            + (" · **" + tx("Karar") + f":** {decision_ref}" if decision_ref else "") + (" · **" + tx("Soru") + f":** {question_ref}" if question_ref else ""),
            "- **" + tx("Karar veren") + f":** {decider or '-'}", "- **" + tx("Geri alınabilir") + ":** " + (tx("Evet") if reversible else tx("Hayır")), "", "## " + tx("Bağlam"), context or "-"]
    if options:
        head += ["", "## " + tx("Seçenekler")] + [f"{i}. {o}" + (" " + tx("(seçilen)") if chosen and o == chosen else "") for i, o in enumerate(options, 1)]
    cons = consequences or {}
    head += ["", "## " + tx("Karar ve gerekçe"), (f"{chosen}. " if chosen else "") + (rationale or ""), "", "## " + tx("Sonuçlar")]
    head += [f"- {tx('Olumlu')}: {x}" for x in cons.get("positive", [])] or [f"- {tx('Olumlu')}: -"]
    head += [f"- {tx('Olumsuz')}: {x}" for x in cons.get("negative", [])] or [f"- {tx('Olumsuz')}: -"]
    with open(os.path.join(project_dir, *rel.split("/")), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(head) + "\n")
    return {"number": number, "file": rel, "status": status}


def set_status(project_dir: str, rel: str, status: str, note: str = "") -> bool:
    """ADR durum satırını günceller (ör. VARSAYIM → KABUL EDİLDİ, eski karar → YERİNİ ALDI)."""
    if status not in ADR_STATUSES:
        raise ValueError(f"ADR durumu geçersiz: {status}")
    path = os.path.join(project_dir, *rel.split("/"))
    if not os.path.isfile(path):
        return False
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    new = re.sub(r"^- \*\*" + _status_label() + r":\*\* .*$", lambda _m: "- **" + tx("Durum") + ":** " + status + (f" ({note})" if note else ""), text, count=1, flags=re.MULTILINE)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new)
    return True


def list_adrs(project_dir: str, docs_rel: str) -> List[Dict[str, Any]]:
    directory = adr_dir(project_dir, docs_rel)
    out: List[Dict[str, Any]] = []
    for f in sorted(os.listdir(directory)) if os.path.isdir(directory) else []:
        m = re.match(r"^(\d{4})-.*\.md$", f)
        if not m:
            continue
        try:
            text = open(os.path.join(directory, f), encoding="utf-8").read()
        except Exception:
            continue
        title = re.search(r"^# ADR \d{4}: (.*)$", text, re.MULTILINE)
        status = re.search(r"^- \*\*" + _status_label() + r":\*\* (.*)$", text, re.MULTILINE)
        out.append({"number": m.group(1), "file": f"{docs_rel}/adr/{f}", "title": title.group(1) if title else f,
                    "status": (status.group(1).split(" (")[0] if status else "")})
    return out
