"""Jira+ (G5, belge §4.1): yerel iş yönetimi — gerçek Jira'ya ihtiyaç bırakmayan madde modeli ve işlemleri.

Alanlar: `issue_type` (EPIC … SPIKE), `labels[]`, `components[]`, `estimate`, `due`, `links[]` (ters bağ hedefte tutulur), `comments[]`,
`attachments[]`, `watchers[]`, `history[]` (alan bazlı değişiklik kaydı), `deleted{}` (yumuşak silme), `board_rank` (Kanban sütun sırası).
İşlemler: düzenle, sil/geri al, yorum, bağ, ek, Kanban taşıma (durum + sıra), sprint sabitleme/sıra (eski `/plan` ucu), toplu işlem,
JQL benzeri sorgu, kayıtlı süzgeçler, madde zaman çizelgesi ("neden bu durumda"), kanıt (koşu/adım/commit/doğrulama/DoD/AC kapsama) ve sprint panosu.
Hepsi sunucu durumunda (`hub.jira_issues`) çalışır; her değişiklik denetim izine yazılır ve `JIRA_UPDATED` ile yayınlanır.
Sunucu tarafı planlama (sprint adayları, açık iş, hikâye kırılımı) silinmiş maddeyi görmez.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import sprint as SP
from .i18n import translate as tx, N_

ISSUE_TYPES = ("EPIC", "STORY", "FEATURE", "TASK", "BUG", "IMPROVEMENT", "REFACTOR", "TEST_CASE", "TEST_RUN", "SPIKE")
STATUSES = ("BACKLOG", "SELECTED_FOR_DEV", "IN_PROGRESS", "IN_REVIEW", "DONE")
PRIORITIES = ("P0", "P1", "P2")
ESTIMATES = ("XS", "S", "M", "L", "XL")
LINK_INVERSE = {"blocks": "is_blocked_by", "is_blocked_by": "blocks", "relates": "relates", "duplicates": "duplicates", "tests": "tested_by", "tested_by": "tests"}
EDITABLE = ("title", "description", "priority", "assignee", "acceptance_criteria", "issue_type", "labels", "components", "estimate", "due",
            "parent_id", "watchers", "work_type")
FROZEN_FIELDS = ("title", "description", "acceptance_criteria", "priority", "assignee", "work_type")
PLAN_EDITABLE = ("title", "description", "priority", "assignee", "acceptance_criteria")
STARTED = ("IN_PROGRESS", "IN_REVIEW")
SPRINT_STARTED = ("COMMITTED", "IN_PROGRESS", "IN_REVIEW", "BLOCKED")
HISTORY_MAX = 300
BULK_ACTIONS = ("status", "sprint", "labels_add", "labels_remove", "assignee", "priority", "delete", "restore", "watch")
STATUS_ACTIONS = ("APPROVED", "FIX_REQUESTED", "STEP_FAILED", "REVISE_REQUESTED", "MANUAL_STATUS", "STATUS_OVERRIDE", "AWAITING_APPROVAL",
                  "CARRY_CANDIDATE", "DELETED", "RESTORED", "LLM_OUTPUT_FAILED", "PLANNED_SPRINT")
KIND_FOR_TYPE = {"EPIC": "epic", "STORY": "story", "FEATURE": "story"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
def _att_from_str(s: str) -> Dict[str, Any]:
    p = str(s).replace("\\", "/")
    return {"id": "att-" + hashlib.sha1(p.encode("utf-8")).hexdigest()[:8], "name": p.rsplit("/", 1)[-1][:120], "path": p, "url": "", "by": "", "added_at": ""}


def ensure_fields(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Eski kayıtlara yeni alanları ekler (yerinde); dize ek kayıtları sözlüğe çevrilir."""
    for k in ("labels", "components", "links", "comments", "watchers", "history"):
        if not isinstance(issue.get(k), list):
            issue[k] = []
    att = issue.get("attachments")
    issue["attachments"] = [a if isinstance(a, dict) else _att_from_str(a) for a in (att if isinstance(att, list) else [])]
    issue.setdefault("estimate", None)
    issue.setdefault("due", None)
    issue.setdefault("deleted", None)
    return issue


def active(hub) -> List[Dict[str, Any]]:
    """Silinmemiş maddeler (sunucu tarafı planlama bunları görür)."""
    return [i for i in hub.jira_issues.values() if not i.get("deleted")]


def get(hub, issue_id: str) -> Dict[str, Any]:
    issue = hub.jira_issues.get(issue_id)
    if issue is None:
        raise KeyError(issue_id)
    return ensure_fields(issue)


def _hist(issue: Dict[str, Any], by: str, field: str, old: Any, new: Any) -> None:
    issue["history"].append({"ts": now(), "by": by, "field": field, "from": old, "to": new})
    del issue["history"][:-HISTORY_MAX]


async def _touch(hub, issue: Dict[str, Any], by: str, action: str, notes: str = "") -> None:
    """Denetim izi + `JIRA_UPDATED` yayını + kayıt (record_task_audit hepsini yapar)."""
    issue["updated_at"] = now()
    await hub.record_task_audit(issue["id"], by, action, notes=notes[:400])


def _clean_list(value: Any, limit: int = 20, maxlen: int = 40) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = re.split(r"[,\n]", value)
    if not isinstance(value, list):
        raise ValueError(tx("liste bekleniyor"))
    out: List[str] = []
    for x in value:
        s = str(x).strip()[:maxlen]
        if s and s not in out:
            out.append(s)
    return out[:limit]


def _ancestors(hub, issue_id: str) -> List[str]:
    seen: List[str] = []
    cur = hub.jira_issues.get(issue_id)
    while cur and cur.get("parent_id") and cur["parent_id"] not in seen and len(seen) < 50:
        seen.append(cur["parent_id"])
        cur = hub.jira_issues.get(cur["parent_id"])
    return seen


def validate_field(hub, issue: Dict[str, Any], field: str, value: Any) -> Any:
    """Alan değerini doğrular/normalize eder; hatada ValueError."""
    if field == "title":
        s = str(value or "").strip()
        if not s:
            raise ValueError(tx("Başlık boş olamaz."))
        return s[:200]
    if field == "description":
        return str(value or "")[:8000]
    if field == "priority":
        if value not in PRIORITIES:
            raise ValueError(tx("Öncelik {values} olmalı.", values='/'.join(PRIORITIES)))
        return value
    if field == "assignee":
        s = str(value or "").strip().upper()
        if not s:
            raise ValueError(tx("Atanan boş olamaz."))
        return s[:40]
    if field == "acceptance_criteria":
        return _clean_list(value, 40, 300)
    if field == "issue_type":
        v = str(value or "").upper()
        if v not in ISSUE_TYPES:
            raise ValueError(tx("Madde tipi {values} olmalı.", values=', '.join(ISSUE_TYPES)))
        return v
    if field in ("labels", "components", "watchers"):
        return _clean_list(value)
    if field == "estimate":
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            raise ValueError(tx("Tahmin XS/S/M/L/XL ya da 0-1000 puan olmalı."))
        if isinstance(value, (int, float)):
            if 0 <= value <= 1000:
                return int(value)
            raise ValueError(tx("Tahmin puanı 0-1000 arası olmalı."))
        v = str(value).strip().upper()
        if v in ESTIMATES:
            return v
        if v.isdigit() and int(v) <= 1000:
            return int(v)
        raise ValueError(tx("Tahmin XS/S/M/L/XL ya da 0-1000 puan olmalı."))
    if field == "due":
        if value in (None, ""):
            return None
        s = str(value)[:10]
        try:
            datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            raise ValueError(tx("Son tarih YYYY-AA-GG biçiminde olmalı."))
        return s
    if field == "parent_id":
        if value in (None, ""):
            return None
        v = str(value)
        if v == issue["id"]:
            raise ValueError(tx("Madde kendi ebeveyni olamaz."))
        if v not in hub.jira_issues:
            raise ValueError(tx("Ebeveyn bulunamadı: {v}", v=v))
        if issue["id"] in _ancestors(hub, v):
            raise ValueError(tx("Ebeveyn döngüsü: hedef bu maddenin altındadır."))
        return v
    if field == "work_type":
        return str(value or "").strip().upper()[:30]
    raise ValueError(tx("Düzenlenemez alan: {field}", field=field))


# ---------------------------------------------------------------------------
# Düzenleme, yumuşak silme
# ---------------------------------------------------------------------------
async def edit_issue(hub, issue_id: str, updates: Dict[str, Any], by: str = "MANAGER") -> Dict[str, Any]:
    issue = get(hub, issue_id)
    if issue.get("deleted"):
        raise PermissionError(tx("Silinmiş madde düzenlenemez; önce geri alın."))
    changes: Dict[str, Any] = {}
    for k, v in (updates or {}).items():
        if k not in EDITABLE:
            continue
        nv = validate_field(hub, issue, k, v)
        if nv != issue.get(k):
            changes[k] = nv
    if not changes:
        return issue
    if SP.is_frozen(hub, issue) and any(k in FROZEN_FIELDS for k in changes):
        raise PermissionError(tx("Kapatılmış sprintin maddesi değiştirilemez; değişiklik yeni madde olarak (related_to) eklenir."))
    notes = []
    for k, nv in changes.items():
        _hist(issue, by, k, issue.get(k), nv)
        notes.append(f"{k}: {str(issue.get(k))[:40]!r} → {str(nv)[:40]!r}")
        issue[k] = nv
    if "issue_type" in changes and issue.get("kind"):
        issue["kind"] = KIND_FOR_TYPE.get(changes["issue_type"], "task")      # sunucu planlaması `kind` ile çalışır
    await _touch(hub, issue, by, "FIELD_CHANGED", "; ".join(notes))
    return issue


async def delete_issue(hub, issue_id: str, by: str = "MANAGER", reason: str = "") -> Dict[str, Any]:
    """Yumuşak silme: madde kalır (geri alınabilir), sunucu planlaması ve pano (varsayılan) onu görmez."""
    issue = get(hub, issue_id)
    if issue.get("deleted"):
        return issue
    if issue.get("status") in STARTED:
        raise PermissionError(tx("Başlamış iş silinemez (IN_PROGRESS/IN_REVIEW); önce adımın bitmesini ya da koşunun kapanmasını bekleyin."))
    sp = SP.get_sprint(hub, int(issue["sprint"])) if issue.get("sprint") else None
    if sp is not None and sp.get("status") in SPRINT_STARTED:
        # Yönetici kararı: başlamamış (kuyrukta bekleyen) iş sprintten çıkarılır; adım koşudan kalkar, kapsam değişikliği kaydedilir.
        from . import sprint_flow as SPF
        queued = SPF._queued_step(hub, issue_id) or SPF._queued_step(hub, issue_id, ("PENDING", "SKIPPED"))
        if queued is None:
            raise PermissionError(tx("Süren sprintin taahhüdündeki iş, koşuda başlamamış bir adım olarak bulunamadı; silinemez (kapsam değişikliği acil girdi ile yapılır)."))
        run, step = queued
        idx = run.steps.index(step)
        run.steps.pop(idx)
        if idx < run.cursor:
            run.cursor -= 1
        run.touch()
        ids = sp.get("committed_issue_ids") or []
        if issue["id"] in ids:
            ids.remove(issue["id"])
        sp.setdefault("scope_changes", []).append({"at": now(), "source": "manager_delete", "removed": [issue["id"]], "added": []})
        issue["sprint"] = None
        from . import pipeline as P
        await P.publish_run(hub, run)
    issue["deleted"] = {"at": now(), "by": by, "reason": str(reason or "")[:300]}
    _hist(issue, by, "deleted", False, True)
    await _touch(hub, issue, by, "DELETED", str(reason or tx("yönetici sildi")))
    return issue


async def restore_issue(hub, issue_id: str, by: str = "MANAGER") -> Dict[str, Any]:
    issue = get(hub, issue_id)
    if not issue.get("deleted"):
        return issue
    issue["deleted"] = None
    _hist(issue, by, "deleted", True, False)
    await _touch(hub, issue, by, "RESTORED", tx("yönetici geri aldı"))
    return issue


async def correct_assignee(hub, issue_id: str, by: str = "MANAGER") -> Dict[str, Any]:
    """Yanlışlıkla (ör. toplu işlemle) değişen sorumluyu denetim kaydındaki ÖNCEKİ değere döndürür. Kapanmış sprintin dondurulmuş maddesinde de çalışır:
    yeni bir değer yazmaz, yalnızca kayıtlı eski değeri geri koyar ve 'ASSIGNEE_CORRECTED' olarak denetime işler."""
    issue = get(hub, issue_id)
    last = next((a for a in reversed(issue.get("audit_trail") or []) if a.get("action") == "FIELD_CHANGED" and str(a.get("notes") or "").startswith("assignee:")), None)
    m = re.match(r"assignee: '([^']*)' \S+ '([^']*)'", str((last or {}).get("notes") or ""))
    if not m:
        raise ValueError(tx("Bu maddede geri alınabilir bir sorumlu değişikliği kaydı yok."))
    old, cur = m.group(1), m.group(2)
    if issue.get("assignee") != cur:
        raise ValueError(tx("Sorumlu son kayıttan sonra yeniden değişmiş ({assignee}); otomatik düzeltilmez.", assignee=issue.get('assignee')))
    if cur == old:
        return issue
    issue["assignee"] = old
    _hist(issue, by, "assignee", cur, old)
    await _touch(hub, issue, by, "ASSIGNEE_CORRECTED", f"assignee: '{cur}' → '{old}'" + tx(" (yanlışlıkla yapılan değişiklik geri alındı)"))
    return issue


# ---------------------------------------------------------------------------
# Yorum, bağ, ek
# ---------------------------------------------------------------------------
async def add_comment(hub, issue_id: str, text: str, author: str = "MANAGER", kind: str = "manager") -> Dict[str, Any]:
    issue = get(hub, issue_id)
    t = str(text or "").strip()
    if not t:
        raise ValueError(tx("Yorum boş olamaz."))
    c = {"id": f"cm-{uuid.uuid4().hex[:8]}", "author": str(author or "MANAGER")[:40], "kind": "agent" if kind == "agent" else "manager",
         "text": t[:8000], "created_at": now()}
    issue["comments"].append(c)
    await _touch(hub, issue, c["author"], "COMMENTED", t[:200])
    return c


async def delete_comment(hub, issue_id: str, comment_id: str, by: str = "MANAGER") -> Dict[str, Any]:
    issue = get(hub, issue_id)
    c = next((x for x in issue["comments"] if x.get("id") == comment_id), None)
    if c is None:
        raise KeyError(comment_id)
    issue["comments"].remove(c)
    await _touch(hub, issue, by, "COMMENT_DELETED", c["text"][:120])
    return c


async def add_link(hub, issue_id: str, link_type: str, target: str, by: str = "MANAGER") -> Dict[str, Any]:
    """Bağ iki yönlüdür: `A blocks B` yazılınca B'de `is_blocked_by A` tutulur."""
    issue = get(hub, issue_id)
    lt = str(link_type or "").lower()
    if lt not in LINK_INVERSE:
        raise ValueError(tx("Bağ tipi {values} olmalı.", values=', '.join(LINK_INVERSE)))
    if target == issue_id:
        raise ValueError(tx("Madde kendine bağlanamaz."))
    other = get(hub, target)
    link = {"type": lt, "target": target, "by": by, "created_at": now()}
    if not any(x.get("type") == lt and x.get("target") == target for x in issue["links"]):
        issue["links"].append(link)
        _hist(issue, by, "links", None, f"{lt} {target}")
    inv = LINK_INVERSE[lt]
    if not any(x.get("type") == inv and x.get("target") == issue_id for x in other["links"]):
        other["links"].append({"type": inv, "target": issue_id, "by": by, "created_at": link["created_at"]})
        _hist(other, by, "links", None, f"{inv} {issue_id}")
        await _touch(hub, other, by, "LINKED", f"{inv} {issue_id}")
    await _touch(hub, issue, by, "LINKED", f"{lt} {target}")
    return link


async def remove_link(hub, issue_id: str, link_type: str, target: str, by: str = "MANAGER") -> None:
    issue = get(hub, issue_id)
    lt = str(link_type or "").lower()
    link = next((x for x in issue["links"] if x.get("type") == lt and x.get("target") == target), None)
    if link is None:
        raise KeyError(f"{lt} {target}")
    issue["links"].remove(link)
    _hist(issue, by, "links", f"{lt} {target}", None)
    other = hub.jira_issues.get(target)
    if other is not None:
        ensure_fields(other)
        inv = LINK_INVERSE.get(lt)
        back = next((x for x in other["links"] if x.get("type") == inv and x.get("target") == issue_id), None)
        if back is not None:
            other["links"].remove(back)
            _hist(other, by, "links", f"{inv} {issue_id}", None)
            await _touch(hub, other, by, "UNLINKED", f"{inv} {issue_id}")
    await _touch(hub, issue, by, "UNLINKED", f"{lt} {target}")


async def add_attachment(hub, issue_id: str, name: str = "", path: str = "", url: str = "", by: str = "MANAGER") -> Dict[str, Any]:
    """Ek, kasa dosyası / E2E ekran görüntüsü gibi bir yol ya da adres referansıdır (kopyalanmaz)."""
    issue = get(hub, issue_id)
    ref = str(path or url or "").strip()
    if not ref:
        raise ValueError(tx("Ek için path ya da url gerekli."))
    if ".." in ref.replace("\\", "/").split("/"):
        raise ValueError(tx("Geçersiz yol."))
    a = {"id": f"att-{uuid.uuid4().hex[:8]}", "name": str(name or ref.replace("\\", "/").rsplit("/", 1)[-1])[:120],
         "path": str(path or "")[:400], "url": str(url or "")[:400], "by": by, "added_at": now()}
    issue["attachments"].append(a)
    _hist(issue, by, "attachments", None, a["name"])
    await _touch(hub, issue, by, "ATTACHED", a["name"])
    return a


async def remove_attachment(hub, issue_id: str, attachment_id: str, by: str = "MANAGER") -> Dict[str, Any]:
    issue = get(hub, issue_id)
    a = next((x for x in issue["attachments"] if x.get("id") == attachment_id), None)
    if a is None:
        raise KeyError(attachment_id)
    issue["attachments"].remove(a)
    _hist(issue, by, "attachments", a.get("name"), None)
    await _touch(hub, issue, by, "ATTACHMENT_REMOVED", str(a.get("name")))
    return a


# ---------------------------------------------------------------------------
# Kanban taşıma, sprint sabitleme (eski /plan), toplu işlem
# ---------------------------------------------------------------------------
def _board_key(i: Dict[str, Any]) -> Tuple[int, int]:
    r = i.get("board_rank")
    return (r if isinstance(r, int) and not isinstance(r, bool) else 10 ** 6, int(i.get("order", 0) or 0))


async def move_issue(hub, issue_id: str, status: str, index: Optional[int] = None, by: str = "MANAGER") -> Dict[str, Any]:
    """Sürükle-bırak: hedef sütun (durum) ve sütun içi sıra. DONE'a elle taşıma DoD kanıtı olmadan yönetici sorumluluğundadır (STATUS_OVERRIDE)."""
    issue = get(hub, issue_id)
    if status not in STATUSES:
        raise ValueError(tx("Durum {values} olmalı.", values=', '.join(STATUSES)))
    if issue.get("deleted"):
        raise PermissionError(tx("Silinmiş madde taşınamaz; önce geri alın."))
    old = issue.get("status")
    if old != status and SP.is_frozen(hub, issue):
        raise PermissionError(tx("Kapatılmış sprintin maddesinin durumu değişmez."))
    column = sorted([i for i in active(hub) if i.get("status") == status and i["id"] != issue_id], key=_board_key)
    if index is None or not isinstance(index, int) or isinstance(index, bool) or index < 0 or index > len(column):
        index = len(column)
    column.insert(index, issue)
    for pos, i in enumerate(column):
        i["board_rank"] = pos
    if old != status:
        _hist(issue, by, "status", old, status)
        issue["status"] = status
        action = "STATUS_OVERRIDE" if status == "DONE" else "MANUAL_STATUS"
        notes = tx("Yönetici panoda taşıdı: {old} → {status}", old=old, status=status) + (tx(" (DoD kanıtı olmadan DONE; yönetici sorumluluğunda)") if status == "DONE" else "")
    else:
        action, notes = "REORDERED", tx("Yönetici {status} sütununda {pos}. sıraya taşıdı.", status=status, pos=index + 1)
    await _touch(hub, issue, by, action, notes)
    return issue


async def plan_issue(hub, issue_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Yönetici müdahalesi: görevi düzenle, bir sprinte sabitle (`planned_sprint`) ya da backlog sırasında taşı (`move`: up|down).
    Başlamış/bitmiş ya da kapanmış sprintte kalan işin sprinti ve sırası değişmez (PermissionError)."""
    issue = get(hub, issue_id)
    updates: Dict[str, Any] = {k: body[k] for k in PLAN_EDITABLE if k in body}
    plans = "planned_sprint" in body or body.get("move") in ("up", "down")
    if plans:
        if issue.get("status") != "BACKLOG" or issue.get("sprint"):
            raise PermissionError(tx("Yalnızca backlog'daki ve henüz bir sprinte alınmamış iş sprint/sıra değişikliğine açıktır."))
        if "planned_sprint" in body:
            n = body["planned_sprint"]
            if n is not None:
                if not isinstance(n, int) or isinstance(n, bool) or n < 1:
                    raise ValueError(tx("planned_sprint pozitif tamsayı ya da null olmalı."))
                if (SP.get_sprint(hub, n) or {}).get("status") in ("CLOSED", "IN_PROGRESS", "IN_REVIEW", "COMMITTED"):
                    raise PermissionError(tx("Sprint {n} başlamış ya da kapanmış; yalnızca planlanacak sprintlere iş sabitlenir.", n=n))
            updates["planned_sprint"] = n
            updates["audit_action"] = "PLANNED_SPRINT"
            updates["audit_notes"] = tx("Yönetici işi {target} için sabitledi.", target=('Sprint ' + str(n) if n else 'backlog'))
    if updates:
        await hub.update_jira_issue(issue_id, updates)
    if body.get("move") in ("up", "down"):
        if not SP.reorder_backlog(hub, issue_id, body["move"], hub.jira_issues[issue_id].get("planned_sprint")):
            raise PermissionError(tx("Madde bu yönde taşınamaz (sıranın başında/sonunda ya da aday değil)."))
        await hub.record_task_audit(issue_id, "MANAGER", "REORDERED", notes=tx("Yönetici backlog sırasında {move} taşıdı.", move=body['move']))
        hub.mark_dirty()
        await hub.broadcast({"type": "JIRA_UPDATED", "issue_id": issue_id})
    return hub.jira_issues[issue_id]


async def bulk(hub, ids: List[str], action: str, value: Any = None, by: str = "MANAGER") -> Dict[str, Any]:
    """Toplu işlem; her madde için ayrı sonuç (biri kalınca diğerleri sürer)."""
    if action not in BULK_ACTIONS:
        raise ValueError(tx("Toplu işlem {values} olmalı.", values=', '.join(BULK_ACTIONS)))
    results: List[Dict[str, Any]] = []
    for iid in [str(x) for x in (ids or [])][:200]:
        try:
            if action == "status":
                await move_issue(hub, iid, str(value or ""), None, by)
            elif action == "sprint":
                n = None if value in (None, "", "null", 0, "0") else int(value)
                await plan_issue(hub, iid, {"planned_sprint": n})
            elif action == "labels_add":
                issue = get(hub, iid)
                await edit_issue(hub, iid, {"labels": [*issue["labels"], *_clean_list(value)]}, by)
            elif action == "labels_remove":
                rm = set(_clean_list(value))
                issue = get(hub, iid)
                await edit_issue(hub, iid, {"labels": [x for x in issue["labels"] if x not in rm]}, by)
            elif action == "assignee":
                await edit_issue(hub, iid, {"assignee": value}, by)
            elif action == "priority":
                await edit_issue(hub, iid, {"priority": value}, by)
            elif action == "delete":
                await delete_issue(hub, iid, by, str(value or ""))
            elif action == "restore":
                await restore_issue(hub, iid, by)
            elif action == "watch":
                issue = get(hub, iid)
                await edit_issue(hub, iid, {"watchers": [*issue["watchers"], str(value or by)]}, by)
            results.append({"id": iid, "ok": True})
        except KeyError:
            results.append({"id": iid, "ok": False, "error": tx("bulunamadı")})
        except (ValueError, PermissionError) as e:
            results.append({"id": iid, "ok": False, "error": str(e)})
    return {"action": action, "results": results, "ok": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"])}


# ---------------------------------------------------------------------------
# JQL benzeri sorgu: `status in (BACKLOG, DONE) and assignee = QA and label = api and not type = BUG order by priority desc`
# ---------------------------------------------------------------------------
_TOKEN_RX = re.compile(r'"[^"]*"|\'[^\']*\'|\(|\)|,|!=|>=|<=|!~|=|~|>|<|[^\s(),=~!<>]+')
FIELDS: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "status": lambda i: i.get("status"),
    "type": lambda i: i.get("issue_type"),
    "issue_type": lambda i: i.get("issue_type"),
    "assignee": lambda i: i.get("assignee"),
    "role": lambda i: i.get("assignee"),
    "priority": lambda i: i.get("priority"),
    "label": lambda i: i.get("labels") or [],
    "labels": lambda i: i.get("labels") or [],
    "component": lambda i: i.get("components") or [],
    "components": lambda i: i.get("components") or [],
    "watcher": lambda i: i.get("watchers") or [],
    "sprint": lambda i: i.get("sprint"),
    "planned_sprint": lambda i: i.get("planned_sprint"),
    "parent": lambda i: i.get("parent_id"),
    "parent_id": lambda i: i.get("parent_id"),
    "key": lambda i: i.get("key"),
    "id": lambda i: i.get("id"),
    "kind": lambda i: i.get("kind"),
    "work_type": lambda i: i.get("work_type"),
    "estimate": lambda i: i.get("estimate"),
    "due": lambda i: i.get("due"),
    "order": lambda i: i.get("order"),
    "deleted": lambda i: bool(i.get("deleted")),
    "title": lambda i: i.get("title"),
    "text": lambda i: " ".join(str(i.get(k) or "") for k in ("key", "id", "title", "description")),
}
_OPS = ("=", "!=", "~", "!~", ">", "<", ">=", "<=", "in", "not in")


def _unq(t: str) -> Any:
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    if t.lower() in ("null", "empty", "none"):
        return None
    return t


def parse_query(q: str) -> Tuple[Any, Optional[Tuple[str, bool]]]:
    """→ (AST | None, (sıralama alanı, azalan mı) | None). AST: ('and'|'or', a, b) | ('not', a) | ('cmp', alan, op, [değerler])."""
    toks = _TOKEN_RX.findall(q or "")
    low = [t.lower() for t in toks]
    order: Optional[Tuple[str, bool]] = None
    if "order" in low and low.index("order") + 1 < len(low) and low[low.index("order") + 1] == "by":
        idx = low.index("order")
        rest = low[idx + 2:]
        if not rest or rest[0] not in FIELDS:
            raise ValueError(tx("order by için geçerli bir alan verin."))
        order = (rest[0], len(rest) > 1 and rest[1] == "desc")
        toks = toks[:idx]
    pos = 0

    def peek() -> Optional[str]:
        return toks[pos] if pos < len(toks) else None

    def take() -> str:
        nonlocal pos
        if pos >= len(toks):
            raise ValueError(tx("Sorgu beklenmedik şekilde bitti."))
        t = toks[pos]
        pos += 1
        return t

    def parse_or():
        node = parse_and()
        while peek() and peek().lower() == "or":
            take()
            node = ("or", node, parse_and())
        return node

    def parse_and():
        node = parse_not()
        while peek() and peek().lower() == "and":
            take()
            node = ("and", node, parse_not())
        return node

    def parse_not():
        if peek() and peek().lower() == "not":
            take()
            return ("not", parse_not())
        return parse_atom()

    def parse_atom():
        t = peek()
        if t is None:
            raise ValueError(tx("Koşul bekleniyor."))
        if t == "(":
            take()
            node = parse_or()
            if peek() != ")":
                raise ValueError(tx("')' bekleniyor."))
            take()
            return node
        field = take().lower()
        if field not in FIELDS:
            raise ValueError(tx("Bilinmeyen alan: {field} (alanlar: {fields})", field=field, fields=', '.join(sorted(FIELDS))))
        op = take().lower()
        if op == "not":
            if take().lower() != "in":
                raise ValueError(tx("'not in' bekleniyor."))
            op = "not in"
        if op == "is":
            neg = False
            v = take().lower()
            if v == "not":
                neg = True
                v = take().lower()
            if v != "empty":
                raise ValueError(tx("'is empty' / 'is not empty' bekleniyor."))
            return ("cmp", field, "!=" if neg else "=", [None])
        if op not in _OPS:
            raise ValueError(tx("Bilinmeyen operatör: {op}", op=op))
        if op in ("in", "not in"):
            if take() != "(":
                raise ValueError(tx("'(' bekleniyor."))
            vals: List[Any] = []
            while peek() is not None and peek() != ")":
                t2 = take()
                if t2 != ",":
                    vals.append(_unq(t2))
            if peek() != ")":
                raise ValueError(tx("')' bekleniyor."))
            take()
            return ("cmp", field, op, vals)
        return ("cmp", field, op, [_unq(take())])

    if not toks:
        return None, order
    ast = parse_or()
    if pos != len(toks):
        raise ValueError(tx("Beklenmeyen: {token}", token=toks[pos]))
    return ast, order


def _eq(actual: Any, v: Any) -> bool:
    if v is None:
        return actual in (None, "", [], False)
    if isinstance(actual, bool):
        return (str(v).lower() in ("true", "1", "yes", "evet")) == actual
    if isinstance(actual, (int, float)):
        try:
            return float(v) == float(actual)
        except (TypeError, ValueError):
            return False
    return str(actual).lower() == str(v).lower()


def _cmp(actual: Any, op: str, vals: List[Any]) -> bool:
    if isinstance(actual, list):
        if op in ("!=", "!~", "not in"):
            return all(_cmp(a, op, vals) for a in actual) if actual else True
        return any(_cmp(a, op, vals) for a in actual)
    v = vals[0] if vals else None
    s = "" if actual is None else str(actual)
    if op == "=":
        return _eq(actual, v)
    if op == "!=":
        return not _eq(actual, v)
    if op == "in":
        return any(_eq(actual, x) for x in vals)
    if op == "not in":
        return not any(_eq(actual, x) for x in vals)
    if op == "~":
        return v is not None and str(v).lower() in s.lower()
    if op == "!~":
        return not (v is not None and str(v).lower() in s.lower())
    if actual is None or v is None:
        return False
    try:
        a, b = float(s), float(str(v))
    except (TypeError, ValueError):
        a, b = s.lower(), str(v).lower()        # tarih (ISO) ve metin: sözlük sırası
    return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]


def match(issue: Dict[str, Any], ast: Any) -> bool:
    if ast is None:
        return True
    kind = ast[0]
    if kind == "and":
        return match(issue, ast[1]) and match(issue, ast[2])
    if kind == "or":
        return match(issue, ast[1]) or match(issue, ast[2])
    if kind == "not":
        return not match(issue, ast[1])
    _, field, op, vals = ast
    return _cmp(FIELDS[field](issue), op, vals)


def _mentions(ast: Any, field: str) -> bool:
    if ast is None:
        return False
    if ast[0] == "cmp":
        return ast[1] == field
    return any(_mentions(x, field) for x in ast[1:])


def query(hub, q: str, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Sorguya uyan maddeler (silinmişler, sorgu `deleted` alanını anmıyorsa ya da include_deleted verilmediyse dışarıda)."""
    ast, order = parse_query(q)
    items = [ensure_fields(i) for i in hub.jira_issues.values() if include_deleted or _mentions(ast, "deleted") or not i.get("deleted")]
    out = [i for i in items if match(i, ast)]
    field, desc = order or ("order", False)
    getter = FIELDS[field]

    def key(i: Dict[str, Any]):
        v = getter(i)
        if isinstance(v, list):
            v = ",".join(str(x) for x in v)
        return (v is None, v if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v or "").lower())
    out.sort(key=key, reverse=desc)
    return out


def saved_filters(hub) -> List[Dict[str, Any]]:
    return [f for f in ((hub.get_settings() or {}).get("jira_filters") or []) if isinstance(f, dict)]


async def save_filter(hub, name: str, q: str) -> Dict[str, Any]:
    n = str(name or "").strip()[:60]
    if not n:
        raise ValueError(tx("Süzgeç adı gerekli."))
    parse_query(q)                                           # geçersiz sorgu kaydedilmez
    f = {"name": n, "q": str(q or "")[:500], "created_at": now()}
    await hub.update_settings({"jira_filters": [*[x for x in saved_filters(hub) if x.get("name") != n], f]})
    return f


async def delete_filter(hub, name: str) -> None:
    cur = saved_filters(hub)
    nxt = [x for x in cur if x.get("name") != name]
    if len(nxt) == len(cur):
        raise KeyError(name)
    await hub.update_settings({"jira_filters": nxt})


# ---------------------------------------------------------------------------
# Zaman çizelgesi ("neden bu durumda") ve kanıt
# ---------------------------------------------------------------------------
def _iso(ts: Any) -> str:
    s = str(ts or "")
    return s.replace(" ", "T") + ("+00:00" if len(s) == 19 else "") if s else ""


def _issue_steps(hub, issue_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for run in sorted(hub.runs.values(), key=lambda r: r.created_at):
        for s in run.steps:
            if s.issue_id != issue_id:
                continue
            out.append({"run_id": run.run_id, "run_status": run.status, "engine": run.engine, "order": s.order, "kind": s.kind, "fix_round": s.fix_round,
                        "role": s.role, "status": s.status, "started_at": s.started_at, "finished_at": s.finished_at, "summary": (s.summary or "")[:300],
                        "verification": s.verification, "commit": s.commit, "commit_status": s.commit_status, "dod": s.dod,
                        "artifacts": list(s.artifacts or []), "attempts": s.attempts, "error": s.error})
    return out


def timeline(hub, issue_id: str) -> Dict[str, Any]:
    issue = get(hub, issue_id)
    entries: List[Dict[str, Any]] = []
    for h in issue["history"]:
        entries.append({"ts": h.get("ts", ""), "kind": "field", "by": h.get("by"), "field": h.get("field"), "from": h.get("from"), "to": h.get("to"),
                        "text": f"{h.get('field')}: {str(h.get('from'))[:60]!r} → {str(h.get('to'))[:60]!r}"})
    for a in issue.get("audit_trail") or []:
        entries.append({"ts": _iso(a.get("timestamp")), "kind": "audit", "by": a.get("agent_id"), "action": a.get("action"), "status": a.get("status"),
                        "text": a.get("notes") or a.get("action") or "", "files": a.get("files_affected") or []})
    for c in issue["comments"]:
        entries.append({"ts": c.get("created_at", ""), "kind": "comment", "by": c.get("author"), "comment_id": c.get("id"), "text": c.get("text", "")[:400]})
    for s in _issue_steps(hub, issue_id):
        if not (s["started_at"] or s["finished_at"]):
            continue
        v = s["verification"] or {}
        entries.append({"ts": s["finished_at"] or s["started_at"] or "", "kind": "step", "by": s["role"], "run_id": s["run_id"], "order": s["order"],
                        "step_kind": s["kind"], "status": s["status"], "verification": v.get("status"), "commit": s["commit"],
                        "text": tx("Adım #{order} ({kind}) {status}: {summary}", order=s['order'], kind=s['kind'], status=s['status'], summary=s['summary'][:160])})
    entries.sort(key=lambda e: e.get("ts") or "")
    return {"issue_id": issue_id, "status": issue.get("status"), "entries": entries, "why": _why(issue, entries)}


def _why(issue: Dict[str, Any], entries: List[Dict[str, Any]]) -> str:
    """Son durum geçişini yapan kapı/adım: "DONE: APPROVED — … (PM, 2026-…)"."""
    last = None
    for e in entries:
        if e["kind"] == "audit" and (str(e.get("action", "")).startswith("STATUS_") or e.get("action") in STATUS_ACTIONS):
            last = e
        elif e["kind"] == "field" and e.get("field") == "status":
            last = e
    if last is None:
        return tx("{status}: durum geçişi kaydı yok (başlangıç durumu).", status=issue.get('status'))
    who = last.get("by") or "?"
    if last["kind"] == "field":
        return tx("{status}: yönetici {frm} → {to} taşıdı ({who}, {ts}).", status=issue.get('status'), frm=last.get('from'), to=last.get('to'), who=who, ts=last.get('ts'))
    return f"{issue.get('status')}: {last.get('action')} — {str(last.get('text') or '')[:200]} ({who}, {last.get('ts')})."


def _scenario_files(hub, tests: List[str]) -> List[Dict[str, Any]]:
    """Kanıt dosyaları için sözel senaryo listesi (test başlıkları): pano kanıt satırında kod okumadan görülür. Dosya olmayan kanıtlar (test kimliği) atlanır."""
    from . import project_files as PF
    out: List[Dict[str, Any]] = []
    for t in tests[:6]:
        if "/" not in str(t) and "." not in str(t):
            continue
        try:
            doc = PF.read_document(hub, str(t))
        except Exception:  # noqa: BLE001
            continue
        out.append({"path": doc["path"], "summary": doc["summary"], "scenarios": doc["scenarios"][:40]})
    return out


def evidence(hub, issue_id: str) -> Dict[str, Any]:
    """Madde kartı rozetleri (§4.1 madde 4): kim/hangi adım/hangi commit, doğrulama, DoD listesi, AC kapsama."""
    issue = get(hub, issue_id)
    steps = _issue_steps(hub, issue_id)
    last_ver = next((s["verification"] for s in reversed(steps) if s["verification"]), None)
    commits = [{"commit": s["commit"], "run_id": s["run_id"], "order": s["order"], "at": s["finished_at"], "role": s["role"]} for s in steps if s["commit"]]
    dod = next((s["dod"] for s in reversed(steps) if s["dod"]), None)
    project_dir = (hub.projects.get(hub.active_project_id) or {}).get("path") or hub.default_project_path
    if not commits:
        # Koşu kaydı yoksa (registry/runs.json kaybı) commit kanıtı git geçmişinden okunur
        from .scm import commits_by_issue
        commits = [{"commit": c["commit"], "run_id": "", "order": issue.get("order") or 0, "at": c["at"], "role": "SCM", "source": "git"}
                   for c in commits_by_issue(project_dir).get(str(issue_id).upper(), [])]
    refs = [f"AC-{int(re.sub(r'[^0-9]', '', str(r)) or 0)}" for r in (issue.get("ac_refs") or []) if re.sub(r"[^0-9]", "", str(r))]
    cov: Dict[str, Any] = {"total": len(refs), "covered": 0, "items": [], "basis": "none"}
    if refs:
        ev: Dict[str, List[str]] = {}
        try:
            from .guard import ac_evidence
            from .verify import junit_path, junit_results
            junit = junit_results(junit_path(project_dir))
            ev = ac_evidence(project_dir, junit)
            cov["basis"] = "junit" if junit else "mentions"
        except Exception:
            ev = {}
        acs_state = SP.ensure_state(hub).get("acs") or {}
        for r in refs:
            tests = ev.get(r) or []
            cov["items"].append({"ac": r, "evidence": tests, "ac_text": (acs_state.get(r) or {}).get("text") or "", "files": _scenario_files(hub, tests)})
            cov["covered"] += 1 if tests else 0
    last = steps[-1] if steps else None
    return {"issue_id": issue_id, "steps": steps, "last_step": last, "last_verification": last_ver, "commits": commits, "dod": dod,
            "ac_coverage": cov, "acceptance_criteria": issue.get("acceptance_criteria") or []}


# ---------------------------------------------------------------------------
# Sprint panosu (§4.1 madde 3)
# ---------------------------------------------------------------------------
def _done_at(issue: Dict[str, Any]) -> str:
    for a in reversed(issue.get("audit_trail") or []):
        if a.get("status") == "DONE":
            return _iso(a.get("timestamp"))
    return str(issue.get("updated_at") or "")


def _slim(i: Dict[str, Any]) -> Dict[str, Any]:
    return {k: i.get(k) for k in ("id", "key", "order", "title", "status", "priority", "assignee", "issue_type", "work_type", "estimate", "carry_over", "sprint",
                                  "planned_sprint", "deleted")}


def _burndown(sp: Dict[str, Any], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    start = sp.get("started_at") or sp.get("committed_at") or sp.get("planned_at") or ""
    remaining = len(items)
    points = [{"ts": start, "remaining": remaining}]
    for ts in sorted(_done_at(i) for i in items if i.get("status") == "DONE"):
        remaining -= 1
        points.append({"ts": ts, "remaining": remaining})
    points.append({"ts": sp.get("closed_at") or now(), "remaining": remaining})
    return points


def _sprint_summary(hub, sp: Dict[str, Any]) -> Dict[str, Any]:
    committed = [i for i in (sp.get("committed_issue_ids") or []) if i in hub.jira_issues]
    done = [i for i in committed if hub.jira_issues[i].get("status") == "DONE"]
    completed = sp.get("completed_issue_ids") or done
    m = sp.get("metrics") or {}
    return {"sprint_number": sp.get("sprint_number"), "status": sp.get("status"), "goal": sp.get("goal"), "committed": len(committed), "done": len(done),
            "completed": len(completed), "carried": len(sp.get("carried_over") or []), "blocked": sp.get("blocked"), "planned_at": sp.get("planned_at"),
            "committed_at": sp.get("committed_at"), "started_at": sp.get("started_at"), "closed_at": sp.get("closed_at"), "git_tag": sp.get("git_tag"),
            "commit_approval": sp.get("commit_approval"), "commit_deadline": sp.get("commit_deadline"), "scope_changes": len(sp.get("scope_changes") or []),
            "metrics": {k: m.get(k) for k in ("first_pass_rate", "fix_rounds", "uat_rejections", "e2e", "active_min", "tokens") if m}}


def sprint_board(hub) -> Dict[str, Any]:
    st = SP.ensure_state(hub)
    c = SP.cfg(hub)
    sprints = st.get("sprints") or []
    open_sprints = [s for s in sprints if s.get("status") not in ("CLOSED", "CANCELLED")]
    # Güncel sprint: çalışan (IN_PROGRESS) en yeni sprint; yoksa açık olanların en yenisi (eski, takılı kalmış IN_REVIEW/BLOCKED sprint güncel sayılmaz)
    current = next((s for s in reversed(open_sprints) if s.get("status") == "IN_PROGRESS"), open_sprints[-1] if open_sprints else (sprints[-1] if sprints else None))
    pending = hub.pending_step_approval if (hub.pending_step_approval or {}).get("kind") == "sprint_commit" else None
    cap, cap_reason = SP.capacity(hub)
    wip_limit = int(c.get("wip_limit", 0) or 0)
    wip = [i for i in active(hub) if i.get("status") == "IN_PROGRESS" and str(i.get("kind", "")).lower() == "task"]
    velocity = [{"sprint": s.get("sprint_number"), "committed": len(s.get("committed_issue_ids") or []),
                 "done": ((s.get("metrics") or {}).get("completed") if s.get("metrics") else len(s.get("completed_issue_ids") or []))}
                for s in sprints if s.get("status") == "CLOSED"]
    out: Dict[str, Any] = {
        "enabled": SP.enabled(hub), "settings": c, "project_status": st.get("project_status"), "capacity": cap, "capacity_reason": cap_reason,
        "wip": {"limit": wip_limit, "count": len(wip), "over": bool(wip_limit and len(wip) > wip_limit), "items": [_slim(i) for i in wip]},
        "pending_commit": None, "current": None, "velocity": velocity, "sprints": [_sprint_summary(hub, s) for s in sprints],
        "can_plan_next": bool(SP.enabled(hub) and hub.active_run_for(hub.active_project_id) is None),
    }
    if pending is not None:
        n = int(str(pending.get("issue_id") or "SPRINT-0").split("-")[-1] or 0)
        sp_p = SP.get_sprint(hub, n) if n else None
        out["pending_commit"] = {"sprint": n, "token": hub.gate.token if hasattr(hub, "gate") and hasattr(hub.gate, "token") else None,
                                 "proposed": pending.get("proposed") or [], "summary": pending.get("summary"), "since": pending.get("timestamp"),
                                 "deadline": (sp_p or {}).get("commit_deadline")}
    if current is not None:
        items = [ensure_fields(hub.jira_issues[i]) for i in (current.get("committed_issue_ids") or []) if i in hub.jira_issues]
        proposed = [ensure_fields(hub.jira_issues[i]) for i in (current.get("proposed_issue_ids") or []) if i in hub.jira_issues]
        carried = [{**_slim(hub.jira_issues[x["issue_id"]]), "reason": x.get("reason"), "count": x.get("count")} if isinstance(x, dict) and x.get("issue_id") in hub.jira_issues
                   else x for x in (current.get("carried_over") or [])]
        out["current"] = {**_sprint_summary(hub, current), "items": [_slim(i) for i in items], "proposed": [_slim(i) for i in proposed],
                          "carried_items": carried, "burndown": _burndown(current, items),
                          "can": {"commit": pending is not None, "unblock": current.get("status") == "BLOCKED",
                                  "cancel": current.get("status") not in ("CLOSED", "CANCELLED"), "edit_goal": current.get("status") == "PLANNING"}}
    return out


async def set_sprint_goal(hub, n: int, goal: str, by: str = "MANAGER") -> Dict[str, Any]:
    sp = SP.get_sprint(hub, n)
    if sp is None:
        raise KeyError(f"Sprint {n}")
    if sp.get("status") != "PLANNING":
        raise PermissionError(tx("Sprint hedefi yalnızca PLANNING durumunda düzenlenir."))
    g = str(goal or "").strip()
    if not g:
        raise ValueError(tx("Hedef boş olamaz."))
    old = sp.get("goal")
    sp["goal"] = g[:300]
    sp.setdefault("scope_changes", []).append({"at": now(), "by": by, "kind": "goal", "from": old, "to": sp["goal"]})
    hub.mark_dirty()
    await hub.broadcast({"type": "SPRINT_UPDATED", "sprint": n, "goal": sp["goal"]})
    return sp
