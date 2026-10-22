"""Sprint akış adımları (F3): sprint planı/taahhüdü, kapanış, yeniden kapsamlama ve hikâye yapılandırma devamı.

Plan ve kapanış sunucu tarafında koşar (`server_side=True`, bkz. `server/sprint_flow.py`); yeniden kapsamlama ve yapılandırma
devamı ARCHITECT'in LLM adımlarıdır. Faz işleyicileri (3, 4, 8, 10) silinmez; iş türü şablonu olarak yeniden kullanılır (registry).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from ..i18n import translate as tx, N_
from ..llm.parsing import StepOutputError
from .base import StepContext, StepHandler, StepResult
from .handlers import ArchitectHandler


class SprintPlanHandler(StepHandler):
    agent_id = "SCRUM_MASTER"
    next_agent_id = "BACKEND_DEV"
    action = "SPRINT_COMMITTED"
    server_side = True
    critical = True
    estimated_tokens = 0
    title = N_("Sprint planı ve taahhüdü")

    def __init__(self, order: int):
        self.order = int(order)
        self.title = tx("Sprint planı ve taahhüdü")

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:  # sunucu adımı: kullanılmaz
        return self.envelope(ctx, {"summary": tx("Sprint planlandı.")})


class SprintCloseHandler(StepHandler):
    agent_id = "SCRUM_MASTER"
    next_agent_id = "PM"
    action = "SPRINT_CLOSED"
    server_side = True
    estimated_tokens = 0
    title = N_("Sprint kapanışı (review-retro)")

    def __init__(self, order: int):
        self.order = int(order)
        self.title = tx("Sprint kapanışı (review-retro)")

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        return self.envelope(ctx, {"summary": tx("Sprint kapatıldı.")})


class RescopeHandler(StepHandler):
    """FIX_LIMIT / TOKEN_LIMIT nedeniyle taşınan işin yeniden kapsamlanması: aynı tanımla yeniden taahhüt edilemez (§7.8)."""

    agent_id = "ARCHITECT"
    next_agent_id = "SCRUM_MASTER"
    action = "TASK_RESCOPED"
    estimated_tokens = 220
    payload_schema = {
        "rescoped": [{"issue_id": "JIRA-n", "title": N_("yeni, daraltılmış başlık"), "description": N_("değişen yaklaşım / kapsam"),
                      "acceptance_criteria": [N_("ölçülebilir kriter")],
                      "split": [{"title": N_("gerekiyorsa ayrı görev"), "role": "BACKEND_DEV", "work_type": "FEATURE",
                                 "description": "...", "acceptance_criteria": ["..."]}]}],
        "files": [{"path": "<docs>/rescope/<JIRA-n>.md", "content": N_("gerekçe ve yeni yaklaşım (ve varsa düzeltilmiş dosyalar)")}],
    }

    def __init__(self, order: int, issue: Dict[str, Any] | None = None):
        self.order = int(order)
        self.issue = issue or {}
        self.title = tx("Yeniden kapsamlama: {title}", title=self.issue.get('title', ''))[:140]
        self.thinking = (tx("Düzeltme limitine takılan işi inceliyor, böler ya da yaklaşımı değiştirir hâle getiriyorum."),
                         tx("Taşınan işi yeniden kapsamlıyor"), tx("Sprint planı yeni tanımı taahhüt edecek"))
        self.payload_schema = {
            "rescoped": [{"issue_id": "JIRA-n", "title": tx("yeni, daraltılmış başlık"), "description": tx("değişen yaklaşım / kapsam"),
                          "acceptance_criteria": [tx("ölçülebilir kriter")],
                          "split": [{"title": tx("gerekiyorsa ayrı görev"), "role": "BACKEND_DEV", "work_type": "FEATURE",
                                     "description": "...", "acceptance_criteria": ["..."]}]}],
            "files": [{"path": "<docs>/rescope/<JIRA-n>.md", "content": tx("gerekçe ve yeni yaklaşım (ve varsa düzeltilmiş dosyalar)")}],
        }

    def build_user_prompt(self, ctx: StepContext) -> str:
        i = self.issue
        carry = i.get("carry_over") or {}
        parts = [
            tx("# Yeniden kapsamlama: {title} ({issue}, {key})", title=i.get('title'), issue=ctx.issue_id, key=i.get('task_key')),
            tx("Taşınma nedeni: {reason} · kaç kez taşındı: {count}", reason=carry.get('last_reason'), count=carry.get('count')),
            tx("Bu iş aynı tanımla yeniden taahhüt EDİLEMEZ: işi böl ya da yaklaşımı değiştir. `rescoped[0].title` veya `description` mevcut olandan farklı olmalı."),
            "\n" + tx("## Mevcut tanım") + f"\n{i.get('description') or '-'}",
        ]
        if i.get("acceptance_criteria"):
            parts.append("\n" + tx("## Mevcut kabul kriterleri") + "\n" + "\n".join(f"- {c}" for c in i["acceptance_criteria"]))
        trail = [a for a in (i.get("audit_trail") or []) if a.get("action") in ("FIX_REQUESTED", "FIX_LIMIT_REACHED", "VERIFICATION_FAILED")][-4:]
        if trail:
            parts.append("\n" + tx("## Son başarısızlık izleri") + "\n" + "\n".join(f"- {a.get('action')}: {str(a.get('notes'))[:300]}" for a in trail))
        snap = ctx.project_snapshot_md(max_entries=120)
        if snap:
            parts.append("\n" + snap)
        return ctx.r("\n".join(parts))

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        i = self.issue
        key = i.get("task_key") or ctx.issue_id
        fixes: List[Dict[str, str]] = []
        # Şablon motoru, kasıtlı bozuk dosyayı geçerli hâliyle değiştirir (bkz. TaskHandler.template_output)
        broken = f"src/broken_{str(key).lower().replace('-', '_')}.py"
        if os.path.isfile(os.path.join(ctx.project_dir, broken)):
            fixes.append({"path": broken, "content": "def ok() -> bool:\n    return True\n"})
        new_title = str(i.get("title", "")) + tx(" (yeniden kapsamlandı)")
        note = (tx("# Yeniden kapsamlama: {issue}", issue=ctx.issue_id) + "\n\n"
                + tx("- Önceki başlık: {title}", title=i.get('title')) + "\n"
                + tx("- Yeni başlık: {title}", title=new_title) + "\n"
                + tx("- Neden: {reason}", reason=(i.get('carry_over') or {}).get('last_reason')) + "\n")
        return self.envelope(ctx, {
            "summary": tx("'{title}' işi daraltılarak yeniden kapsamlandı.", title=i.get('title')),
            "friendly_dialogue": tx("İşi daha küçük ve doğrulanabilir bir kapsama çektim; sprint planı yeniden taahhüt edebilir."),
            "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
            "rescoped": [{"issue_id": ctx.issue_id, "title": new_title,
                          "description": (i.get("description") or "") + "\n\n" + tx("Yeniden kapsamlama: yaklaşım sadeleştirildi, doğrulama adımları ayrıştırıldı."),
                          "acceptance_criteria": list(i.get("acceptance_criteria") or [tx("Testler yeşil")]), "split": []}],
            "files": [{"path": f"<docs>/rescope/{ctx.issue_id}.md", "content": note}, *fixes],
        })

    def render(self, ctx: StepContext, env: Dict[str, Any]) -> StepResult:
        result = super().render(ctx, env)
        items = env.get("payload", {}).get("rescoped")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise StepOutputError(tx("`rescoped[]` boş olamaz."), [tx("rescoped[] boş")])
        first = items[0]
        if str(first.get("title", "")).strip() == str(self.issue.get("title", "")).strip() and \
                str(first.get("description", "")).strip() == str(self.issue.get("description", "")).strip() and not first.get("split"):
            raise StepOutputError(tx("Aynı tanımla yeniden taahhüt edilemez: başlık/açıklamayı değiştir ya da işi böl (`split`)."),
                                  [tx("rescoped[0] mevcut tanımla aynı")])
        return result


class StructureHandler(ArchitectHandler):
    """Hikâye hikâye yapılandırma: bir ARCHITECT adımına sığmayan hikâyeler için devam adımı (karar 19b)."""

    def __init__(self, order: int = 2):
        self.order = int(order)
        self.title = tx("Görev kırılımı (devam)")
        self.payload_schema = {
            "backlog": ArchitectHandler.payload_schema["backlog"],
            "libraries": ArchitectHandler.payload_schema["libraries"],
            "files": [{"path": "<docs>/ARCHITECTURE.md", "content": tx("(varsa) mimari belge güncellemesi")}],
        }

    payload_schema = {
        "backlog": ArchitectHandler.payload_schema["backlog"],
        "libraries": ArchitectHandler.payload_schema["libraries"],
        "files": [{"path": "<docs>/ARCHITECTURE.md", "content": N_("(varsa) mimari belge güncellemesi")}],
    }

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        from ..sprint import sprint_template_backlog, stories_without_tasks
        env = self.envelope(ctx, {
            "summary": tx("Kalan hikâyeler görevlere bölündü."),
            "friendly_dialogue": tx("Kalan hikâyelerin görev kırılımını da çıkardım."),
            "thinking": tx("Henüz kırılımı olmayan hikâyeleri görevlere bölüyorum."), "what_doing": tx("Görev kırılımına devam ediyor"),
            "what_next": tx("Sprint planı görevleri seçecek"),
            "backlog": sprint_template_backlog(ctx.hub, stories_without_tasks(ctx.hub)),
            "files": [],
        })
        return env


class MeetingHandler(StepHandler):
    """Toplantı adımı (F4, §8): SCRUM_MASTER moderatörlüğünde rollerin turlarını ve yapılandırılmış sonucu üretir; tutanağı sunucu yazar."""

    agent_id = "SCRUM_MASTER"
    next_agent_id = "PM"
    action = "MEETING_CLOSED"
    estimated_tokens = 320
    payload_schema = {
        "meeting": {"type": "kickoff | planning | review-retro | arch-review | adhoc", "sprint": 2, "summary": N_("1-2 cümlelik sonuç")},
        "discussion": [{"from": "ARCHITECT", "to": "BACKEND_DEV", "topic": N_("konu"), "message": N_("kısa, somut konuşma turu")}],
        "decisions": [{"text": N_("alınan karar")}],
        "questions": [{"category": "TECHNOLOGY | EXTERNAL_ACTION | SCOPE | DESIGN", "raised_by": "ROL", "text": N_("soru"),
                       "options": [{"key": "A", "label": N_("seçenek")}, {"key": "B", "label": N_("seçenek")}], "recommended": "A", "rationale": N_("öneri gerekçesi"),
                       "adr": {"title": "...", "context": "...", "consequences": {"positive": ["..."], "negative": ["..."]}, "reversible": True}}],
        "commitment": {"goal": N_("sprint hedefi"), "items": ["JIRA-n"], "out_of_scope": [{"issue_id": "JIRA-n", "reason": N_("neden")}]},
        "retro": {"went_well": ["..."], "problems": ["..."], "action_items": [{"type": "PROCESS | PROMPT | BACKLOG", "target": "settings.max_fix_rounds",
                                                                              "value": 3, "reason": "..."}]},
    }
    MEETING_TITLES = {"kickoff": N_("Kickoff toplantısı"), "planning": N_("Sprint planlama toplantısı"), "review-retro": N_("Değerlendirme ve retrospektif toplantısı"),
                      "arch-review": N_("Mimari gözden geçirme toplantısı"), "adhoc": N_("Acil girdi toplantısı")}

    def __init__(self, order: int, mtype: str = "planning"):
        self.order = int(order)
        self.mtype = mtype or "planning"
        self.title = tx(self.MEETING_TITLES.get(self.mtype, N_("Toplantı")))
        self.thinking = (tx("{title} gündemini kuruyor, girdileri topluyorum.", title=self.title), tx("{title} yürütüyor", title=self.title),
                         tx("Sunucu tutanağı ve kararları kaydedecek"))
        self.payload_schema = {
            "meeting": {"type": "kickoff | planning | review-retro | arch-review | adhoc", "sprint": 2, "summary": tx("1-2 cümlelik sonuç")},
            "discussion": [{"from": "ARCHITECT", "to": "BACKEND_DEV", "topic": tx("konu"), "message": tx("kısa, somut konuşma turu")}],
            "decisions": [{"text": tx("alınan karar")}],
            "questions": [{"category": "TECHNOLOGY | EXTERNAL_ACTION | SCOPE | DESIGN", "raised_by": "ROL", "text": tx("soru"),
                           "options": [{"key": "A", "label": tx("seçenek")}, {"key": "B", "label": tx("seçenek")}], "recommended": "A", "rationale": tx("öneri gerekçesi"),
                           "adr": {"title": "...", "context": "...", "consequences": {"positive": ["..."], "negative": ["..."]}, "reversible": True}}],
            "commitment": {"goal": tx("sprint hedefi"), "items": ["JIRA-n"], "out_of_scope": [{"issue_id": "JIRA-n", "reason": tx("neden")}]},
            "retro": {"went_well": ["..."], "problems": ["..."], "action_items": [{"type": "PROCESS | PROMPT | BACKLOG", "target": "settings.max_fix_rounds",
                                                                                  "value": 3, "reason": "..."}]},
        }

    def build_user_prompt(self, ctx: StepContext) -> str:
        from .. import meetings as M, sprint as SP
        n = int(ctx.record.sprint or 1)
        parts = [tx("# {title} (sprint {n})", title=self.title, n=n), tx("Moderatör: SCRUM_MASTER. Her rol kendi görev tanımı içinde konuşur; başkasının işini üstlenmez."),
                 "\n" + tx("## Girdiler")] + [f"- {x}" for x in M.meeting_inputs(ctx.hub, self.mtype, n)]
        if self.mtype in ("kickoff", "planning"):
            cap, basis = SP.capacity(ctx.hub)
            SP.adopt_manual_tasks(ctx.hub)
            SP.merge_duplicates(ctx.hub)
            items, out = SP.select_items(ctx.hub, cap, n)
            parts.append("\n" + tx("## Taahhüt adayları (kapasite {cap}: {basis})", cap=cap, basis=basis))
            parts += [tx("- {id} · {wt} · {title} · {assignee} · {prio} · bağımlılık: {deps} · AC: {ac}", id=i['id'], wt=i.get('work_type'), title=i.get('title'),
                         assignee=i.get('assignee'), prio=i.get('priority'), deps=', '.join(i.get('depends_on') or []) or '-', ac=', '.join(i.get('ac_refs') or []) or '-')
                      + (tx(" · NETLEŞTİRİLMELİ (yönetici isteği, kapsam belirsiz: gerekiyorsa soru aç)") if i.get("needs_grooming") else "") for i in items]
            parts.append("\n" + tx("Kurallar: `commitment.items` yalnızca yukarıdaki adaylardan seçilir ve kapasiteyi aşamaz; yeniden kapsamlanmamış taşınan iş taahhüt edilemez. "
                                   "Belirsiz bir tasarım/kapsam konusunu soru olarak aç: her sorunun kategorisi, seçenekleri, ÖNERİLEN cevabı ve gerekçesi zorunludur (önerisiz soru reddedilir). "
                                   "Teknoloji ya da dış etkili iş gerekiyorsa TECHNOLOGY / EXTERNAL_ACTION sorusu aç; bunlar engelleyicidir ve ancak yönetici cevaplar."))
        elif self.mtype == "adhoc":
            sp = SP.get_sprint(ctx.hub, n) or {}
            from .. import sprint_flow as SPF
            started = SPF.started_issue_ids(ctx.run, n)
            urgent = [c for c in (sp.get("scope_changes") or []) if c.get("source") == "urgent_input"]
            parts.append("\n" + tx("## Acil yönetici girdisi"))
            parts += [f"- {c.get('text')}" for c in urgent[-3:]] or [tx("- (metin yok)")]
            parts.append("\n" + tx("## Sprint taahhüdü (başlamamış işler yer değiştirebilir)"))
            for iid in sp.get("committed_issue_ids", []):
                i = ctx.hub.jira_issues.get(iid) or {}
                parts.append(f"- {iid} · {i.get('title')} · {i.get('assignee')} · {tx('BAŞLADI') if iid in started else tx('başlamadı')}")
            cands = [i for i in SP.candidates(ctx.hub, n) if i["id"] not in sp.get("committed_issue_ids", [])][:12]
            if cands:
                parts.append("\n" + tx("## Backlog adayları (yer değiştirme için)"))
                parts += [f"- {i['id']} · {i.get('work_type')} · {i.get('title')} · {i.get('priority')}" for i in cands]
            parts.append("\n" + tx("Kurallar: `commitment.out_of_scope` yalnızca BAŞLAMAMIŞ taahhüt işlerini kapsam dışına alabilir (nedeniyle); `commitment.items` "
                                   "boşalan sayı kadar backlog adayı ekleyebilir (kapasite aşılmaz). Acil girdi yeni bir gereksinimse SCOPE/DESIGN sorusu aç; "
                                   "teknoloji gerekiyorsa TECHNOLOGY sorusu (engelleyici). Başlamış işi değiştirme."))
        elif self.mtype == "review-retro":
            summ = SP.summarize(ctx.hub, ctx.run, n)
            parts.append("\n" + tx("## Sunucu metrikleri (rakamları değiştirme)") + "\n" + json.dumps(summ["metrics"], ensure_ascii=False))
            parts.append(tx("Taşınacak işler: ") + (", ".join(f"{c['issue_id']} ({c['reason']})" for c in summ["carried"]) or tx("yok")))
            parts.append("\n" + tx("Retro yalnızca bu metriklere dayanır. Her aksiyon tipi PROCESS | PROMPT | BACKLOG olmalıdır; korkuluk ve bütçe ayarlarını değiştiren aksiyon yazma."))
        parts.append("\n" + tx("Önceki rolün devir notları ve ajanların sorumlulukları sistem promptundadır. Uydurma: notlarda olmayan gereksinimi ya da ölçülmemiş metriği yazma."))
        return ctx.r("\n".join(parts))

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        from .. import meetings as M, sprint as SP
        n = int(ctx.record.sprint or 1)
        hub = ctx.hub
        base: Dict[str, Any] = {"thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
                                "friendly_dialogue": tx("{title} tamamlandı; kararlar ve sorular kaydedildi.", title=self.title),
                                "summary": tx("{title} tamamlandı.", title=self.title)}
        if self.mtype in ("kickoff", "planning"):
            cap, basis = SP.capacity(hub)
            SP.adopt_manual_tasks(hub)
            SP.merge_duplicates(hub)
            items, out = SP.select_items(hub, cap, n)
            carried = [i for i in items if (i.get("carry_over") or {}).get("count")]
            goal = SP.goal_for(hub, items, n)
            discussion = [
                {"from": "PM", "to": "ARCHITECT", "topic": tx("Kapsam"), "message": tx("{n} hikâye var; kullanıcıya dönük akışları öne alalım.", n=len(SP.existing_stories(hub)))},
                {"from": "ARCHITECT", "to": "BACKEND_DEV", "topic": tx("Kırılım"),
                 "message": (tx("Taşınan {ids} yeniden kapsamlandı; ilk sıraya alınmalı.", ids=", ".join(i["id"] for i in carried))) if carried
                 else tx("Görevler tek teslimde bitecek büyüklükte; bağımlılık sırası korunuyor.")},
                {"from": "SCRUM_MASTER", "to": "ALL", "topic": tx("Kapasite"), "message": tx("Kapasite {cap} görev ({basis}); {n} iş taahhüt önerisi.", cap=cap, basis=basis, n=len(items))},
            ]
            question = {"category": "DESIGN", "raised_by": "PM",
                        "text": tx("Sprint {n}: hata yanıtları tek tip bir JSON şemasında mı döndürülsün?", n=n),
                        "options": [{"key": "A", "label": tx("Tek tip hata şeması")}, {"key": "B", "label": tx("Uç başına serbest")}], "recommended": "A",
                        "rationale": tx("İstemci tarafında hata gösterimini sadeleştirir; sonradan değiştirmek ucuzdur."),
                        "adr": {"title": tx("Hata yanıt şeması (sprint {n})", n=n), "context": tx("Hata gövdesinin biçimi notlarda belirtilmemiş."),
                                "consequences": {"positive": [tx("İstemci hata işleme tek yerde")], "negative": [tx("Şema sürümleme ek iş")]}, "reversible": True}}
            exists = any(q["text"] == question["text"] for q in M.store(hub)["questions"])
            base.update({
                "meeting": {"type": self.mtype, "sprint": n, "summary": tx("Sprint {n} hedefi ve taahhüdü belirlendi.", n=n)},
                "discussion": discussion, "decisions": [{"text": tx("Sprint {n} hedefi: {goal}", n=n, goal=goal)}], "questions": [] if exists else [question],
                "commitment": {"goal": goal, "items": [i["id"] for i in items], "out_of_scope": out}})
        elif self.mtype == "review-retro":
            summ = SP.summarize(hub, ctx.run, n)
            m, carried = summ["metrics"], summ["carried"]
            actions = [{"type": "PROCESS", "target": "settings.max_fix_rounds", "value": int(hub.get_settings().get("max_fix_rounds", 2) or 2) + 1,
                        "reason": tx("{ids} düzeltme limitine takıldı", ids=", ".join(c["issue_id"] for c in carried))}] \
                if any(c["reason"] == "FIX_LIMIT" for c in carried) else []
            if n == 1:      # şablon motoru örneği: bir PROMPT ve bir BACKLOG aksiyonu (gerçek koşuda içeriği ekip üretir)
                actions += [{"type": "PROMPT", "target": "BACKEND_DEV", "value": tx("Her API ucu için en az bir test yaz ve testi kabul kriteri kimliğiyle (AC-n) etiketle."),
                             "reason": tx("sprint ölçümünde test kapsamını artırmak")},
                            {"type": "BACKLOG", "target": "", "value": tx("Test verisi üreteci ekle"), "reason": tx("testlerde tekrarlayan veri kurulumu")}]
            base.update({
                "meeting": {"type": "review-retro", "sprint": n, "summary": tx("Sprint {n}: {done}/{committed} iş tamamlandı.", n=n, done=m['completed'], committed=m['committed'])},
                "discussion": [
                    {"from": "SCRUM_MASTER", "to": "ALL", "topic": tx("Metrikler"),
                     "message": tx("Taahhüt {committed}, tamamlanan {done}, ilk seferde geçen {first_pass}, düzeltme turu {fix_rounds}.",
                                   committed=m['committed'], done=m['completed'], first_pass=m['first_pass'], fix_rounds=m['fix_rounds'])},
                    {"from": "PO", "to": "SCRUM_MASTER", "topic": tx("Kabul"),
                     "message": tx("UAT reddi {rej}; E2E sonucu {e2e}.", rej=m['uat_rejections'], e2e=m['e2e'] or tx('yok'))},
                    {"from": "ARCHITECT", "to": "ALL", "topic": tx("Taşıma"),
                     "message": (tx("Taşınan: {items}; yeniden kapsamlanacak.", items=", ".join(f"{c['issue_id']} ({c['reason']})" for c in carried))) if carried else tx("Taşınan iş yok.")},
                ],
                "decisions": [{"text": tx("Sprint {n} kapatılır; taşınan {c} iş sonraki planlamaya girer.", n=n, c=len(carried))}], "questions": [],
                "retro": {"went_well": [tx("{done}/{committed} iş tamamlandı", done=m['completed'], committed=m['committed'])] if m["completed"] else [],
                          "problems": [tx("{id} {reason} nedeniyle taşındı", id=c['issue_id'], reason=c['reason']) for c in carried], "action_items": actions}})
        else:
            base.update({"meeting": {"type": self.mtype, "sprint": n, "summary": tx("Acil girdi değerlendirildi.")},
                         "discussion": [{"from": "SCRUM_MASTER", "to": "ALL", "topic": tx("Girdi"), "message": tx("Girdi sonraki planlamaya alınacak; taahhüt değişmiyor.")}],
                         "decisions": [{"text": tx("Acil girdi sonraki planlamaya alındı.")}], "questions": []})
        return self.envelope(ctx, base)

    def render(self, ctx: StepContext, env: Dict[str, Any]) -> StepResult:
        from .. import meetings as M
        M.normalize_payload(env.get("payload", {}), self.mtype, list(ctx.hub.agents.keys()))   # geçersizse teslim reddedilir (yazmadan önce)
        result = super().render(ctx, env)
        result.files = []
        return result


class ReviewHandler(StepHandler):
    """ARCHITECT'in sprint sonu kod ve mimari uygunluk gözden geçirmesi (F6, §6.3): son sprint etiketinden bu yana oluşan farkı inceler, bulguları iş maddesine çevirir."""

    agent_id = "ARCHITECT"
    next_agent_id = "PO"
    action = "ARCH_REVIEW_DONE"
    estimated_tokens = 260
    payload_schema = {
        "findings": [{"title": N_("bulgu başlığı"), "severity": "LOW | MEDIUM | HIGH | CRITICAL", "description": N_("ne, nerede, neden önemli"),
                      "files": ["ilgili/dosya.py"], "role": "BACKEND_DEV | FRONTEND_DEV | DEVOPS | QA"}],
        "files": [{"path": "<docs>/reviews/sprint-N-review.md", "content": N_("gözden geçirme notu (isteğe bağlı)")}],
    }

    def __init__(self, order: int, sprint: int = 1):
        self.order = int(order)
        self.sprint = int(sprint or 1)
        self.title = tx("Sprint {n}: kod ve mimari gözden geçirme", n=self.sprint)
        self.thinking = (tx("Son etiketten bu yana oluşan farkı sözleşme ve mimariyle karşılaştırıyorum."), tx("Kod ve mimari uygunluğu gözden geçiriyor"),
                         tx("Bulgular iş maddesi olacak; PO kabul kararını kanıtla verecek"))
        self.payload_schema = {
            "findings": [{"title": tx("bulgu başlığı"), "severity": "LOW | MEDIUM | HIGH | CRITICAL", "description": tx("ne, nerede, neden önemli"),
                          "files": ["ilgili/dosya.py"], "role": "BACKEND_DEV | FRONTEND_DEV | DEVOPS | QA"}],
            "files": [{"path": "<docs>/reviews/sprint-N-review.md", "content": tx("gözden geçirme notu (isteğe bağlı)")}],
        }

    def build_user_prompt(self, ctx: StepContext) -> str:
        n = self.sprint
        parts = [f"# {self.title}", tx("Bağımsız değerlendirme: kararını geliştiricinin beyanına değil aşağıdaki sunucu kanıtına dayandır (§6.6)."),
                 tx("Bulgu yoksa `findings` boş olabilir; uydurma bulgu yazma. Kabul veremezsin, kabul kriterini değiştiremezsin.")]
        sp_steps = [s for s in ctx.run.steps if s.sprint == n and s.verification]
        if sp_steps:
            parts.append("\n" + tx("## Doğrulama kanıtı") + "\n" + "\n".join(f"- #{s.order} {s.role}: {s.verification.get('summary')}" for s in sp_steps[-12:]))
        files = ctx.read_files_budget(["<docs>/openapi_spec.json", "<docs>/ARCHITECTURE.md"], total_budget=9000, per_file=5000)
        for rel, content in files.items():
            parts.append("\n" + tx("## Mimari: {rel}", rel=rel) + f"\n```\n{content}\n```")
        diff = getattr(ctx, "git_diff", None) or {"base": "", "stat": "", "patch": ""}   # prepare_step eşzamansız okur
        if diff.get("stat"):
            parts.append("\n" + tx("## Fark ({base}..HEAD)", base=diff['base'][:12]) + f"\n```\n{diff['stat']}\n```")
        if diff.get("patch"):
            # G1: inceleme dosya listesine değil KODA dayanır (yama bütçeli: scm.diff_text kırpar)
            parts.append("\n" + tx("## Yama (sözleşme ve mimariyle karşılaştır; bulguları dosya ve satırla yaz)") + f"\n```diff\n{diff['patch'][:14000]}\n```")
        return ctx.r("\n".join(parts))

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        return self.envelope(ctx, {
            "summary": tx("Sprint {n} kod ve mimari gözden geçirmesi tamamlandı; uygunsuzluk bulunmadı.", n=self.sprint),
            "friendly_dialogue": tx("Fark sözleşmeye ve mimariye uygun; PO kabul kararına geçebilir."),
            "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
            "findings": [], "files": [],
        })

    def render(self, ctx: StepContext, env: Dict[str, Any]) -> StepResult:
        result = super().render(ctx, env)
        if not isinstance(env.get("payload", {}).get("findings", []), list):
            raise StepOutputError(tx("`findings` bir liste olmalı."), [tx("findings liste değil")])
        return result
