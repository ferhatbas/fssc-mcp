"""Kapsam düzeltme (yönetici): ürün tanımı değişti / şartnamedeki bir örnek yanlışlıkla zorunluluk sayıldı → sistem kendisi temizler.

Sorun (saha): şartnamedeki örnek ("kampüs, öğrenci, .edu.tr") bağlayıcı gereksinim sanıldı; PRD, hikâyeler, görevler ve ekranlar buna göre üretildi.
Yönetici elle silmek istemez: FS-SC şunları yapar (`correct`):
1. Ürün tanımını (`product_statement`) ayarlara yazar: her adımın bağlamına bağlayıcı olarak girer.
2. Henüz başlamamış (BACKLOG / SELECTED_FOR_DEV) TASK/BUG işlerden, **başlığı** bırakılan terimleri içerenleri siler (denetim izine neden yazılır; geri alınabilir),
   koşudaki bekleyen adımlarını atlar.
3. Bitmiş ya da açıklamasında terim geçen işleri listeler ve acil bir ARCHITECT kapsam-düzeltme görevi açar: PRD/belgeleri yeni tanıma göre baştan yazar,
   kodda/testte/ekranda kalan kısıtları kaldıran ya da genelleştiren görevleri `backlog[]` olarak üretir.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .i18n import translate as tx

DEFAULT_TERMS = ["kampüs", "kampus", "öğrenci", "ogrenci", "student", "campus", ".edu.tr", "edu.tr"]
START_OK = {"BACKLOG", "SELECTED_FOR_DEV"}


def _lower(s: str) -> str:
    return str(s or "").replace("İ", "i").replace("I", "ı").lower()


def _hits(text: str, terms: List[str]) -> List[str]:
    t = _lower(text)
    return [x for x in terms if _lower(x) in t]


def scan(hub, terms: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """{'drop': başlıkta terim olan, başlamamış TASK/BUG; 'review': diğer eşleşenler (bitmiş, hikâye/epik, yalnızca açıklamada geçen)}."""
    drop, review = [], []
    for i in sorted(hub.jira_issues.values(), key=lambda x: int(x.get("order", 0) or 0)):
        if i.get("deleted"):
            continue
        in_title = _hits(i.get("title"), terms)
        body = " ".join([str(i.get("description") or "")] + [str(c) for c in (i.get("acceptance_criteria") or [])])
        in_body = _hits(body, terms)
        if not in_title and not in_body:
            continue
        row = {"id": i["id"], "key": i.get("key") or i["id"], "title": i.get("title"), "status": i.get("status"), "type": i.get("issue_type"), "terms": sorted(set(in_title + in_body))}
        if in_title and i.get("issue_type") in ("TASK", "BUG") and i.get("status") in START_OK and str(i.get("kind", "")).lower() == "task":
            drop.append(row)
        else:
            review.append(row)
    return {"drop": drop, "review": review}


def _task_description(statement: str, drop: List[Dict[str, Any]], review: List[Dict[str, Any]], terms: List[str]) -> str:
    def line(r: Dict[str, Any]) -> str:
        return f"{r['key']} [{r['status']}] {str(r['title'])[:90]}"
    return (
        tx("YÖNETİCİ KAPSAM DÜZELTMESİ. Ürün tanımı (bağlayıcı): {statement}", statement=statement) + "\n"
        + tx("Şartnamedeki şu terimler yalnızca örnekti, zorunluluk değildir: {terms}.", terms=", ".join(terms[:6])) + "\n"
        + tx("1) PRD ve ilgili belgeleri (ürün gereksinimleri, hikâyeler, kabul kriterleri) yeni tanıma göre baştan yaz; bu kısıtları belgelerden çıkar, genel kullanıcı (herkes) için yaz. Teslimde güncellenen belge dosyalarını `files` içinde ver.") + "\n"
        + tx("2) Kodda, testte ve ekranda kalan bu kısıtları (kimlik/rozet/alan adı doğrulaması, kampüs sınırı vb.) kaldıran ya da genelleştiren işleri `backlog[]` olarak üret; genel hesap doğrulaması (e-posta/telefon) kalabilir. Her iş tek bir role verilsin, kabul kriteri ve `files` ipucu olsun.") + "\n"
        + tx("3) Kapsam dışı kalan, başlamamış işler sunucuca silindi ({n}); onları yeniden açma.", n=len(drop)) + "\n"
        + (tx("İncelenecek mevcut işler ({n}):", n=len(review)) + "\n" + "\n".join(line(r) for r in review[:40]) if review else ""))


async def correct(hub, statement: str = "", terms: Optional[List[str]] = None, dry_run: bool = False, by: str = "MANAGER", api: Any = None) -> Dict[str, Any]:
    from . import jira_plus as JPL
    from . import sprint_flow as SPF
    statement = " ".join(str(statement or "").split()) or str(hub.get_settings().get("product_statement") or "")
    if not statement:
        raise ValueError(tx("Ürün tanımı (statement) gerekli."))
    terms = [t for t in (terms or DEFAULT_TERMS) if str(t).strip()]
    found = scan(hub, terms)
    result: Dict[str, Any] = {"statement": statement, "terms": terms, "drop": found["drop"], "review": found["review"], "dry_run": dry_run}
    if dry_run:
        return result
    await hub.update_settings({"product_statement": statement})
    ids = [r["id"] for r in found["drop"]]
    if ids:
        await JPL.bulk(hub, ids, "delete", tx("Kapsam düzeltmesi: ürün tanımı değişti ({terms})", terms=", ".join(terms[:4])), by)
    result["skipped_steps"] = await _skip_pending_steps(hub, set(ids), api)
    task = await SPF.create_manager_task(
        hub, statement[:200], None, urgent=True, role="ARCHITECT", work_type="DECISION_PLAN", title=tx("Kapsam düzeltmesi: PRD'yi yeni ürün tanımına göre güncelle ve kısıtları kaldır")[:160],
        description=_task_description(statement, found["drop"], found["review"], terms),
        criteria=[tx("PRD ve belgeler yeni ürün tanımına göre güncellenir"), tx("Kalan kısıtları kaldıran/genelleştiren işler rol bazlı backlog olarak çıkar"), tx("Silinen işler yeniden açılmaz")])
    result["task"] = task
    return result


async def _skip_pending_steps(hub, deleted_ids: set, api: Any) -> List[int]:
    """Silinen işlerin koşudaki bekleyen adımlarını atlar (sonlanmamış koşular)."""
    skipped: List[int] = []
    if not deleted_ids or api is None:
        return skipped
    for run in list((getattr(hub, "runs", None) or {}).values()):
        if getattr(run, "is_terminal", False):
            continue
        for st in list(run.steps):
            if st.issue_id in deleted_ids and st.status == "PENDING":
                try:
                    await api.skip_step(run.run_id, st.order, "scope change")
                    skipped.append(st.order)
                except Exception:
                    continue
    return skipped
