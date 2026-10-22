"""Sunucunun ürettiği/yönettiği belge bölümleri: mimar belgesindeki bayat "Onaysız konular" ve olmayan dosya yolları.

Saha (demo_project, 2026-10-14): ARCHITECT, `ARCHITECTURE.md`'yi bir kez yazar. Sonradan verilen kararlar (ADR 0002 Docker, ADR 0003 istemci çatısı) belgeye yansımadığından
"Onaysız konular" bölümü yanlış kalıyor; "Çözüm yapısı" ise hiç yazılmamış yolları (db/schema.sql, test/e2e/) sayıyordu.
Çözüm: belgenin sonuna işaretli, sunucunun güncel kayıtlardan (onaylı teknolojiler, ADR'li kararlar, açık sorular, gerçek klasör ağacı) ürettiği bir bölüm yazılır;
ajanın yazdığı metin silinmez, çelişkide bu bölümün geçerli olduğu söylenir. Bölüm her yazımda yenilenir (idempotent).
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from .i18n import translate as tx, variants

BEGIN, END = "<!-- fssc:arch-status:begin -->", "<!-- fssc:arch-status:end -->"
_BLOCK_RX = re.compile(r"\n*" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n*", re.DOTALL)
_PATH_RX = re.compile(r"`([^`\n]+)`")


def _section_rx() -> "re.Pattern[str]":
    """Ajanın yazdığı "Çözüm yapısı" bölümünün başlığı proje diline göre değişir (tr/en): her dildeki biçimi kabul eder (eşleştirme tuzağı)."""
    names = "|".join(re.escape(v) for v in variants("Çözüm yapısı"))
    return re.compile(r"(?ms)^##\s+(?:" + names + r")[^\n]*\n(.*?)(?=^##\s|\Z)")


def structure_paths(text: str) -> List[str]:
    """`## Çözüm yapısı` bölümündeki madde başı yolları (yer tutucu/genel desen içerenler hariç)."""
    m = _section_rx().search(text)
    out: List[str] = []
    if not m:
        return out
    for line in m.group(1).splitlines():
        if not re.match(r"^\s*[-*]\s", line):
            continue
        found = _PATH_RX.search(line)
        if not found:
            continue
        p = found.group(1).strip()
        if ("/" in p or "." in p) and not any(c in p for c in "<>*{}$") and " " not in p:
            out.append(p)
    return out


def missing_paths(text: str, project_dir: str) -> List[str]:
    base = os.path.abspath(project_dir)
    return [p for p in structure_paths(text) if not os.path.exists(os.path.join(base, *p.rstrip("/").split("/")))]


def render_status(hub, text: str, project_dir: str) -> str:
    """Güncel karar durumu bölümü (işaretli)."""
    from . import meetings as M
    from . import sprint as SP
    lines = [BEGIN, tx("## Güncel karar durumu (FS-SC otomatik)"),
             tx("Bu bölüm sunucu tarafından güncel kayıtlardan üretilir. Belgenin yazıldığı andaki \"Onaysız konular\" listesiyle çelişirse **bu bölüm geçerlidir**."), ""]
    req = hub.tech_requirements() if hasattr(hub, "tech_requirements") else None
    items = (req or {}).get("items") or []
    approved = [it for it in items if it.get("status") == "ONAYLANDI" and it.get("value")]
    lines.append(tx("### Onaylı teknoloji yığını"))
    if approved:
        for it in approved:
            adr = tx(", ADR {adr}", adr=it['adr']) if it.get("adr") else ""
            lines.append(f"- {it.get('label')}: **{it['value']}** ({it.get('approved_by') or 'MANAGER'}, {str(it.get('approved_at') or '')[:10] or '-'}{adr})")
    else:
        lines.append(tx("- Henüz onaylı teknoloji kalemi yok."))
    decided = [d for d in (SP.ensure_state(hub).get("decisions") or []) if d.get("adr")]
    if decided:
        lines += ["", tx("### ADR ile karara bağlananlar")]
        for d in decided:
            lines.append(f"- {d.get('id')} · {str(d.get('text') or '')[:160]} → `{d['adr']}`")
    try:
        open_qs = [q for q in M.all_questions(hub) if q.get("status") == "OPEN"]
    except Exception:  # noqa: BLE001
        open_qs = []
    lines += ["", tx("### Hâlâ bekleyen kararlar")]
    if open_qs:
        for q in open_qs[:12]:
            lines.append(f"- {q.get('id')} [{q.get('category')}]: {str(q.get('question') or q.get('text') or '')[:150]}")
    else:
        lines.append(tx("- Açık yönetici sorusu yok (belgede \"onaysız\" geçen diğer konular yalnızca ajan notudur)."))
    gone = missing_paths(text, project_dir)
    if gone:
        lines += ["", tx("### Henüz oluşturulmamış yollar (\"Çözüm yapısı\" bölümünde geçenlerden)")]
        lines += [f"- `{p}`" for p in gone]
    lines += [END, ""]
    return "\n".join(lines)


def sync_architecture(hub, project_dir: str) -> Optional[str]:
    """`<docs>/ARCHITECTURE.md` sonuna güncel karar durumu bölümünü yazar/yeniler; belge yoksa dokunmaz. Yazılan göreli yolu (ya da None) döner."""
    try:
        from .paths import hub_docs_path
        rel = hub_docs_path(hub, "ARCHITECTURE.md", project_dir)
        path = os.path.join(project_dir, *rel.split("/"))
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        base = _BLOCK_RX.sub("\n", text).rstrip("\n") + "\n"
        new = base + "\n" + render_status(hub, base, project_dir)
        if new == text:
            return None
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
        return rel
    except (OSError, KeyError):
        return None
