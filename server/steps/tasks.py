"""
Dinamik geliştirme adımları: backlog görevleri (kind='task') ve doğrulama sonrası düzeltmeler (kind='fix').

Mimar (adım 2) şartnameden bir backlog çıkarır; sunucu her görev için bir Jira maddesi açar ve koşuya bir
TaskHandler adımı ekler. Görevin ajanı Jira'daki `assignee` alanıdır (BACKEND_DEV, FRONTEND_DEV, DEVOPS, QA...).
Adım dosyalarını yazdıktan sonra sunucu doğrulama (test/build/lint) koşar; başarısızsa aynı görev için bir
'fix' adımı eklenir (sınırlı tur). Doğrulama geçince SCM commit atılır.
"""

from __future__ import annotations
import os

import json
from typing import Any, Dict, List, Optional

from ..i18n import translate as tx, N_
from .base import StepContext, StepHandler, StepResult

ROLE_PROMPT_HINT = {
    "BACKEND_DEV": N_("Sunucu tarafı kod, veri modelleri, servisler, birim testleri."),
    "FRONTEND_DEV": N_("Arayüz bileşenleri, API istemcisi, form/doğrulama, bileşen testleri. Onaylı tasarım sistemine ve mockup'lara uyar."),
    "DESIGNER": N_("Tasarım sistemi (renk/tipografi/boşluk/bileşen) ve ekran mockup'ları: kodsuz, tek dosyalık HTML+CSS; yönetici onayına sunulur."),
    "DEVOPS": N_("Yapılandırma, konteyner, CI, betikler, ortam değişkenleri."),
    "QA": N_("Test senaryoları ve otomasyon kodu; hata bulursan bugs[] ile bildir."),
    "ARCHITECT": N_("Tasarım dokümanı ve sözleşmeler."),
    "DOCUMENTOR": N_("Dokümantasyon."),
}

ARCHITECTURE_FILES = ["<docs>/PRD.md", "<docs>/ARCHITECTURE.md", "<docs>/openapi_spec.json"]


NL = chr(10)


class TaskHandler(StepHandler):
    """Jira maddesinden türetilen tek bir geliştirme görevi (veya onun düzeltme turu)."""

    verify_after = True
    commit_after = True
    estimated_tokens = 420

    def __init__(self, order: int, issue: Optional[Dict[str, Any]] = None, kind: str = "task", fix_round: int = 0,
                 role: Optional[str] = None):
        issue = issue or {}
        self.order = int(order)
        self.issue = issue
        self.kind = kind
        self.fix_round = int(fix_round or 0)
        # Düzeltme adımlarında rol kayıttan gelir (QA testleri kalınca düzeltme geliştiriciye gider)
        self.agent_id = str(role or issue.get("assignee") or "BACKEND_DEV").upper()
        self.ui_design = str(issue.get("work_type") or "") == "DESIGN"
        if self.ui_design:
            self.verify_after = False          # tasarım kod değil: test/build yok; yönetici onayı zorunlu (should_wait)
            self.force_approval = True
            self.critical = True
        self.design = str(issue.get("work_type") or "") == "TEST_DESIGN"
        if self.design:
            self.verify_after = False          # test tasarımı kod değil case üretir; doğrulama/DoD kod teslimine özgü
        self.next_agent_id = "FRONTEND_DEV" if self.ui_design else "QA"
        self.action = "SUBMIT_FIX" if kind == "fix" else "SUBMIT_CODE"
        self.title = str(issue.get("title") or tx("Görev {n}", n=order))
        self.task_key = str(issue.get("task_key") or issue.get("id") or f"T-{order}")
        self.thinking = (
            (tx("'{title}' için başarısız doğrulama çıktısını inceliyor, kök nedeni düzeltiyorum.", title=self.title)
             if kind == "fix" else
             tx("'{title}' görevinin kabul kriterlerini ve mevcut kodu inceliyor, dosya planını çıkarıyorum.", title=self.title)),
            tx("'{title}' üzerinde çalışıyor", title=self.title),
            tx("Sunucu doğrulaması (test/build) koşacak, ardından SCM commit atılacak"),
        )
        self.payload_schema = {
            "task_key": self.task_key,
            "files": [{"path": tx("göreli/dosya/yolu"), "content": tx("dosyanın TAM içeriği (parça değil)")}],
            "tests_added": [tx("eklenen/güncellenen test dosyaları")],
            "notes_for_qa": tx("QA için kısa not (nasıl test edilir, bilinen sınırlar)"),
            "root_cause": tx("(yalnızca düzeltme turunda) hatanın kök nedeni"),
        }
        if self.ui_design:
            self.payload_schema = {
                "task_key": self.task_key,
                "files": [{"path": "<docs>/design/design-system.html", "content": tx("tasarım sistemi sayfası (TAM içerik)")},
                          {"path": tx("<docs>/design/screens/<ekran-kimliği>.html"), "content": tx("ekran mockup'ı (TAM içerik)")}],
                "design": {"tokens": {"color": {"primary": "#3a48cc"}, "font": "...", "radius": "..."},
                           "screens": [{"id": "giris", "title": "Giriş", "route": "/giris", "file": "<docs>/design/screens/giris.html"}]},
                "notes": tx("tasarım kararları ve frontend'e notlar"),
            }
        if self.design:
            self.payload_schema = {
                "task_key": self.task_key,
                "testcases": [{"title": tx("case başlığı"), "type": "unit | integration | e2e | security | performance | exploratory", "priority": "P0 | P1 | P2",
                               "ac_refs": ["AC-1"], "story_ref": "JIRA-n", "precondition": tx("ön koşul"), "steps": [tx("adım 1"), tx("adım 2")],
                               "expected": tx("beklenen sonuç"), "data": tx("test verisi"),
                               "automation": tx("MANUAL | AUTOMATED:<test adı ya da senaryo kimliği>"), "labels": ["regression", "smoke"]}],
                "files": [],
            }

    # ------------------------------------------------------------------
    def _role_hint(self, ctx: StepContext) -> str:
        """Çekirdek rolde sabit ipucu; özel ajanda tanımındaki açıklama + devraldığı temel rolün ipucu (G6)."""
        if self.agent_id in ROLE_PROMPT_HINT:
            return tx(ROLE_PROMPT_HINT[self.agent_id])
        agent = (getattr(ctx.hub, "agents", None) or {}).get(self.agent_id) or {}
        from .. import agent_registry as AR
        base = ROLE_PROMPT_HINT.get(AR.base_role_of(agent), "")
        base = tx(base) if base else ""
        return " ".join(p for p in (str(agent.get("description") or "").strip(), base) if p)

    @staticmethod
    def _claude_design_text(url: str) -> str:
        """Designer'ın Claude Design'ı (claude.ai Artifact 'Design' tuvali) kullanma yönergesi. Sunucu claude.ai'a erişemez: adımı yürüten Claude oturumunun Artifact aracı varsa o kullanır."""
        if url:
            src = "\n" + tx("CLAUDE DESIGN KAYNAĞI: {url} — Artifact aracın varsa `action: read` ile bu tuvali oku (`project/canvas.json` ve `project/*.dc.html`); ekranları statik HTML+CSS'e çevirip "
                            "`files` ile `<docs>/design/` altına teslim et (`.dc.html` ham biçimi değil, tek başına açılan HTML). Tuvali güncellediysen `design.source_url` ile aynı bağlantıyı bildir. "
                            "Artifact aracın yoksa bu kaynağı kullanamazsın: tasarımı kendin üret ve teslimde bunu `notes` içinde belirt.", url=url)
        else:
            src = "\n" + tx("CLAUDE DESIGN (isteğe bağlı): Artifact aracın varsa tasarımı Claude Design'da (Artifact `quickstart` intent=design) üretebilirsin; ürettiğin tuvalin bağlantısını "
                            "`design.source_url` ile bildir, ekranları statik HTML+CSS olarak `<docs>/design/` altına da teslim et. Aracın yoksa tasarımı doğrudan HTML olarak üret.")
        return src

    def _design_reference(self, ctx: StepContext) -> str:
        """Onaylı tasarım sistemi ve ekran mockup'ları varsa frontend'in uyması gereken referans (belirteçler + ekran listesi)."""
        import os
        sys_rel = ctx.r("<docs>/design/design-system.html")
        base = os.path.join(ctx.project_dir, *sys_rel.replace("\\", "/").split("/"))
        if not os.path.isfile(base):
            return ""
        try:
            with open(base, encoding="utf-8") as f:
                text = f.read()[:6000]
        except OSError:
            return ""
        hub = getattr(ctx, "hub", None)
        cd_url = str(hub.get_settings().get("claude_design_url") or "") if hub is not None else ""
        shots = ctx.r("<docs>/design/screens")
        folder = os.path.join(ctx.project_dir, *shots.replace("\\", "/").split("/"))
        screens = sorted(n for n in os.listdir(folder) if n.endswith(".html")) if os.path.isdir(folder) else []
        return ("\n" + tx("## Onaylı tasarım (uymak ZORUNLU)") + "\n"
                + tx("Tasarım sistemi: `{sys_rel}` (renk/tipografi/boşluk belirteçleri ve bileşen örnekleri). Ekran mockup'ları (`{shots}/`): ", sys_rel=sys_rel, shots=shots)
                + (", ".join(screens) or tx("yok")) + ".\n"
                + tx("Bu belirteçleri ve bileşen görünümlerini koddaki stillere aynen aktar; mockup'ta olmayan ekranı tasarım sistemine uyarak kur. Mockup'lardan sapma gerekiyorsa teslimde `questions` alanına yaz.") + "\n"
                + (tx("Claude Design kaynağı: {url}", url=cd_url) + "\n" if cd_url else "")
                + f"```html\n{text}\n```")

    def _hint_files(self, ctx: StepContext) -> List[str]:
        hint = [str(p) for p in (self.issue.get("files_hint") or []) if p]
        # Görevin daha önce yazdığı dosyalar (düzeltme turunda şart)
        for s in ctx.run.steps:
            if s.issue_id == ctx.issue_id and s.status in ("DONE", "FAILED"):
                for a in s.artifacts or []:
                    if a not in hint:
                        hint.append(a)
        if self.kind == "fix":
            # Başarısız çıktıda adı geçen proje dosyaları (traceback'teki kaynak dosyalar gibi)
            from ..verify import failure_excerpt
            excerpt = failure_excerpt(getattr(ctx, "verification", None), limit=12000, project_dir=ctx.project_dir)
            if excerpt:
                norm = excerpt.replace("\\", "/")
                for rel in ctx.project_tree(max_entries=400):
                    if rel in norm and rel not in hint and not rel.startswith("..."):
                        hint.append(rel)
        return hint

    def build_user_prompt(self, ctx: StepContext) -> str:
        parts = [
            tx("# Görev: {title} ({issue} · {key}, adım #{n}", title=self.title, issue=ctx.issue_id, key=self.task_key, n=ctx.order)
            + (tx(", düzeltme turu {n}", n=self.fix_round) if self.kind == "fix" else "") + ")",
            tx("Proje: {name}  |  Hedef klasör: {dir}  |  Rolün: {agent} — {hint}", name=ctx.project_name, dir=ctx.project_dir, agent=self.agent_id, hint=self._role_hint(ctx)),
        ]
        desc = self.issue.get("description")
        if desc:
            parts.append("\n" + tx("## Görev açıklaması") + f"\n{desc}")
        criteria = self.issue.get("acceptance_criteria") or []
        if criteria:
            parts.append("\n" + tx("## Kabul kriterleri (hepsi karşılanmalı)") + "\n" + "\n".join(f"- {c}" for c in criteria))
        refs = [str(a) for a in (self.issue.get("ac_refs") or [])]
        if refs:
            # Kriter kimliklerinin metni sunucudan gelir (ajan/yönetici metin aramaz ya da sormaz); sicil boşsa hikâyelerden geri kurulur
            from .. import sprint as SP
            lines = [f"- {a}: {SP.ac_text(ctx.hub, a) or tx('(metin kayıtlı değil: görevin kabul kriterlerinden ve hikâyeden çıkar, soru sorma)')}" for a in refs]
            parts.append("\n" + tx("## Bu görevin bağlı olduğu kabul kriteri kimlikleri (metinleriyle)") + "\n" + "\n".join(lines))
        try:
            from .. import sprint as _SPR
            if _SPR.cfg(ctx.hub).get("no_tests") and self.agent_id != "QA":
                parts.append(NL + tx("## Test yazımı geçici olarak KAPALI (yönetici kararı)") + NL + tx("Bu görevde yeni test dosyası yazma ve test yazma görevi üstlenme; yalnızca görevin kendisini (kod/ekran/belge) teslim et. Mevcut testler sunucuda koşmaya devam eder; bozma."))
        except Exception:
            pass
        deps = self.issue.get("depends_on") or []
        if deps:
            parts.append("\n" + tx("## Bağımlı olduğu görevler (tamamlandı): ") + ", ".join(str(d) for d in deps))
        if self.agent_id == "FRONTEND_DEV":
            design = self._design_reference(ctx)
            if design:
                parts.append(design)
        if self.ui_design:
            try:
                from ..api_surface import markdown as _api_md
                surface = _api_md(ctx.project_dir, ctx.docs_root)
            except Exception:
                surface = ""
            if surface:
                parts.append(NL + surface)            # backend uçlarından gerekli ekranlar: tasarım ajanı kapsama haritası çıkarır
        try:
            from ..decisions import decisions_context
            dctx = decisions_context(ctx.hub.tech_questions(), ctx.hub.tech_decisions())
        except Exception:
            dctx = ""
        if dctx:
            parts.append("\n" + dctx)

        if self.kind == "fix":
            from ..verify import failure_excerpt
            prev = getattr(ctx, "verification", None)
            excerpt = failure_excerpt(prev, limit=6000, project_dir=ctx.project_dir)     # G1: başarısız testler ad ad + günlüğün SONU
            parts.append("\n" + tx("## Başarısız doğrulama (bunu düzelt)") + "\n" + (excerpt or tx("Doğrulama başarısız oldu; ayrıntı yok.")))
            parts.append(tx("Kural: Yalnızca sorunu çözen dosyaları ver; verdiğin her dosyanın TAM içeriğini ver. Testleri zayıflatma, silme; kök nedeni düzelt."))

        # Mimari bağlamı (bütçeli)
        arch = ctx.read_files_budget(ARCHITECTURE_FILES, total_budget=14000, per_file=7000)
        for rel, content in arch.items():
            parts.append("\n" + tx("## Mimari artefakt: {rel}", rel=rel) + f"\n```\n{content}\n```")

        # Proje ağacı + ilgili dosyalar
        snap = ctx.project_snapshot_md(max_entries=200)
        if snap:
            parts.append("\n" + snap)
        related = ctx.read_files_budget(self._hint_files(ctx), total_budget=26000, per_file=9000)
        for rel, content in related.items():
            parts.append("\n" + tx("## Mevcut dosya: {rel}", rel=rel) + f"\n```\n{content}\n```")

        if self.design:
            from ..testing import design_context
            parts.append(design_context(ctx.hub))
        spec = ctx.spec_text
        if spec and self.kind != "fix":
            from .base import spec_excerpt
            query = " ".join([str(ctx.title), str(ctx.issue.get("description") or ""), *[str(a) for a in (ctx.issue.get("acceptance_criteria") or [])]])
            parts.append(NL + tx("## Müşteri şartnamesi (kısa referans)") + NL + spec_excerpt(spec, query, 6000))
        parts.append(
            "\n" + tx(
                "## Teslim kuralları\n"
                "- Kodu çalışır ve test edilebilir yaz; görevle ilgili birim/bileşen testlerini de `files` içinde ver (testsiz teslim kabul edilmez).\n"
                "- Mevcut bir dosyayı değiştiriyorsan dosyanın TAMAMINI ver (diff/parça değil).\n"
                "- Bağımlılık eklediysen manifesti (requirements.txt / package.json / composer.json) de güncelle.\n"
                "- Sunucu teslimden sonra sözdizimi, build ve test komutlarını koşacak; başarısız olursa düzeltme turu açılır.")
        )
        return ctx.r("\n".join(parts))

    def output_contract(self, ctx: StepContext) -> str:
        base = super().output_contract(ctx)
        extra = ""
        if self.agent_id == "FRONTEND_DEV":
            from ..ui_screens import CONTRACT_HINT
            extra = tx(CONTRACT_HINT)
        if self.ui_design:
            url = str((ctx.hub.get_settings() or {}).get("claude_design_url") or "").strip()
            if self.issue.get("redesign"):
                brief = str(self.issue.get("design_brief") or "").strip()
                return base + self._claude_design_text(url) + "\n" + tx(
                    "Bu adım TASARIM YENİLEME turudur (kod değil): mevcut tasarım yönetici tarafından yetersiz bulundu; öncekini referans al ama daha profesyonel, tutarlı ve tam bir tasarım üret. "
                    "`files` içinde tek dosyalık, dışa bağımlılıksız (JS yok, harici kaynak yok) HTML+CSS ver: (1) `<docs>/design/design-system.html` (yenilenmiş belirteçler ve bileşenler), "
                    "(2) PRD'deki, API sözleşmesindeki ve mevcut istemci yönlendirmesindeki (`route`) HER ekran için `<docs>/design/screens/<kimlik>.html`: gerçekçi içerik; mobil ve masaüstü; "
                    "boş, hata, yükleniyor ve dolu durumları ayrı bölümlerde; erişilebilir (kontrast, odak, 44 px hedef), (3) `<docs>/design/coverage.md`: backend uç grubu → ekran eşlemesi (bağlamdaki 'Backend uç noktaları' bölümüne göre; kapsanmayan uç kalmasın), (4) `<docs>/design/flows.md` ve `<docs>/design/flows.html`: ekran akış haritası — "
                    "her kullanıcı yolculuğu (kayıt/giriş, keşif, katılım, check-in, organizatör, yönetici) için ekran kimlikleri ve aralarındaki geçişler, giriş/çıkış koşulları. "
                    "`payload.design.screens[]` TÜM ekranları (id, title, route, file, state_files) ve `design.flows[]` akışları (id, title, steps: ekran kimlikleri sırası) bildirsin; "
                    "`design.tokens` belirteçleri bildirsin. Onaylı teknoloji yığınına uy. Yönetici onaylamadan frontend bu tasarıma geçmez."
                ) + (("\n\n" + tx("YÖNETİCİ NOTU (öncelikli):") + "\n" + brief) if brief else "")
            return base + self._claude_design_text(url) + "\n" + tx(
                           "Bu adım TASARIM adımıdır (kod değil). `files` içinde tek dosyalık, dışa bağımlılıksız (JS yok, harici kaynak yok) HTML+CSS ver: "
                           "`<docs>/design/design-system.html` (renk/tipografi/boşluk/yarıçap belirteçleri CSS değişkeni olarak, bileşen örnekleri: düğme, form alanı, kart, tablo, gezinme) ve "
                           "her ilk ekran için `<docs>/design/screens/<kimlik>.html` (gerçekçi içerikli, mobil+masaüstü duyarlı). `payload.design.screens[]` ile ekranları (id, title, route, file) ve "
                           "`design.tokens` ile belirteçleri bildir. Onaylı teknoloji yığınına uy (istemci: web/mobil). Yalnızca tasarım sistemi + İLK ekranlar: tüm uygulamayı çizme. "
                           "Yönetici onaylamadan frontend başlamaz.")
        if str(self.issue.get("work_type") or "") == "DECISION_PLAN":
            return base + "\n" + tx("Bu adım YÖNETİCİ KARARINI GÖREVLERE BÖLER (task_key=\"{key}\"). Kod yazma; `payload.backlog[]` üret: her eleman "
                           "{{\"id\":\"T-01\",\"title\":\"...\",\"role\":\"BACKEND_DEV|FRONTEND_DEV|DEVOPS|QA\",\"work_type\":\"FEATURE|SCAFFOLD|DEVOPS|TEST\","
                           "\"description\":\"...\",\"acceptance_criteria\":[\"...\"],\"depends_on\":[\"T-01\"],\"files\":[\"...\"]}}. "
                           "Arayüz/ekran içeren her iş FRONTEND_DEV'e verilir (ekran sözleşmesi screens[] ile). En fazla 12 görev; gereksiz bölme yapma. `files` boş olabilir.",
                           key=self.task_key)
        claim_note = ("" if self.kind != "task" else
                      " " + tx("Görev mevcut kodla ZATEN karşılanıyorsa dosya yeniden yazma: `files` boş bırakıp `payload.already_satisfied` = "
                               "{\"evidence\":[{\"criterion\":\"kabul kriteri metni\",\"test\":\"commit'li test dosyasının yolu\"}]} ver (her kabul kriteri için bir kanıt testi; sunucu o testleri koşar)."))
        return base + "\n" + tx("Bu adım için task_key=\"{key}\"; `files` boş olamaz.", key=self.task_key) + claim_note + extra

    # ------------------------------------------------------------------
    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        if self.design:
            from ..testing import template_design
            cases = template_design(ctx.hub)
            return self.envelope(ctx, {
                "summary": tx("QA, kabul kriterlerinden {n} test case tasarladı (şablon motoru).", n=len(cases)),
                "friendly_dialogue": tx("Test case'leri hazır; QA adımında otomasyonlarıyla koşacak."),
                "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2], "task_key": self.task_key, "testcases": cases, "files": [],
            })
        kind_text = tx("düzeltme turu {n}", n=self.fix_round) if self.kind == "fix" else tx("backlog görevi")
        note = (
            f"# {self.title}\n\n"
            + tx("- Görev: {key} ({issue})", key=self.task_key, issue=ctx.issue_id) + "\n"
            + tx("- Ajan: {agent}", agent=self.agent_id) + "\n"
            + tx("- Tür: {kind}", kind=kind_text) + "\n\n"
            + tx("Bu görev şablon motoruyla işaretlendi; gerçek kod MCP istemcisi (Claude Desktop / Claude Code) tarafından üretilir.") + "\n"
        )
        path = f"<docs>/tasks/{self.task_key}{'_fix' + str(self.fix_round) if self.kind == 'fix' else ''}.md"
        files = [{"path": path, "content": note}]
        files += self._strict_tests(ctx)
        if self._deliberate_failure(ctx):
            # Kuru koşu denemesi (FSSC_DRY_RUN_FAIL_TASK=1): bu görevin teslimi sözdizimi doğrulamasında bilerek kalır → düzeltme limiti → taşıma
            broken = f"src/broken_{self.task_key.lower().replace('-', '_')}.py"
            files.append({"path": broken, "content": "def broken(:\n    pass\n"})
        return self.envelope(ctx, {
            "summary": tx("'{title}' görevi şablon motoruyla tamamlandı (yer tutucu çıktı).", title=self.title)
            if self.kind != "fix" else tx("'{title}' için düzeltme turu {n} şablon motoruyla işaretlendi.", title=self.title, n=self.fix_round),
            "friendly_dialogue": tx("'{title}' teslim edildi; QA doğrulamaya başlayabilir.", title=self.title),
            "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
            "task_key": self.task_key,
            "files": files,
        }, current_file=path)

    def _strict_tests(self, ctx: StepContext) -> List[Dict[str, str]]:
        """Sıkı DoD açıkken (şablon motoru): görevin kabul kriteri kimliklerini anan yer tutucu test; kriterin kanıtı olur (§7.7). Gerçek koşuda testi ajan yazar."""
        try:
            from .. import quality as Q
            if not Q.strict(ctx.hub):
                return []
        except Exception:
            return []
        refs = [str(a) for a in (self.issue.get("ac_refs") or [])]
        key = str(self.task_key).lower().replace("-", "_")
        body = ('"""' + tx("Şablon motoru yer tutucu testi (sıkı DoD) — görev {key}: {refs}.", key=self.task_key, refs=" ".join(refs) or tx("kabul kriteri yok")) + '"""\n\n\n'
                f'def test_{key}_acceptance_placeholder():\n    # {" ".join(refs)}\n    assert True\n')
        return [{"path": f"tests/test_{key}.py", "content": body}]

    def _deliberate_failure(self, ctx: StepContext) -> bool:
        """Yalnızca FSSC_DRY_RUN_FAIL_TASK=1 ve sprint 1'in ilk FEATURE görevi için; yeniden kapsamlanmış iş bozulmaz."""
        import os
        want = os.environ.get("FSSC_DRY_RUN_FAIL_TASK")        # "1" (= sprint 1) ya da bozulacak sprintin numarası
        if not want or getattr(ctx.run, "mode", "legacy") != "sprint" or ctx.record.sprint != int(want):
            return False
        if self.issue.get("work_type") != "FEATURE" or self.issue.get("rescoped_at"):
            return False
        feats = sorted((i for i in ctx.hub.jira_issues.values() if i.get("sprint") == ctx.record.sprint and i.get("work_type") == "FEATURE" and not i.get("deleted")),
                       key=lambda i: int(i.get("order", 0) or 0))
        return bool(feats) and feats[0].get("id") == ctx.issue_id

    def render(self, ctx: StepContext, env: Dict[str, Any]) -> StepResult:
        result = super().render(ctx, env)
        if self.design:
            from ..llm.parsing import StepOutputError
            from ..testing import CaseError, validate_design
            try:
                validate_design(ctx.hub, env.get("payload", {}))
            except CaseError as e:
                raise StepOutputError(str(e), [str(e)])
            return result
        if self.kind == "task" and (ctx.issue or {}).get("design_screen"):
            # Tasarımdan türeyen ekran görevi: "zaten var" ya da yalnızca sözleşme (e2e/screens/*.json) yetmez; mockup'a uyum için arayüz kaynağı değişmeli
            def _changed(f):
                rel = str(f.get("path", ""))
                try:
                    with open(os.path.join(ctx.project_dir, *rel.replace("\\", "/").split("/")), "r", encoding="utf-8") as fh:
                        norm = lambda x: str(x).replace(chr(13) + chr(10), chr(10))
                        return norm(fh.read()) != norm(f.get("content", ""))
                except OSError:
                    return True                                  # yeni dosya
            ui = [f.get("path", "") for f in result.files if str(f.get("path", "")).lower().endswith((".tsx", ".jsx", ".vue", ".svelte", ".css", ".scss")) and _changed(f)]
            if not ui:
                from ..llm.parsing import StepOutputError
                msg = tx("Ekran görevi arayüz kaynağını değiştirmedi: onaylı mockup'ı (`{mock}`) açıp çalışan ekranla karşılaştır; "
                         "ekran bileşeni ve stil dosyalarını (.tsx/.css) mockup'a (düzen, renk, tipografi, boş/hata/yükleniyor/dolu durumlar) uyduracak şekilde güncelleyip teslim et. "
                         "`already_satisfied` ya da yalnızca ekran sözleşmesi bu görevi kapatmaz.", mock=(ctx.issue or {}).get("design_screen") or "<docs>/design/screens")
                raise StepOutputError(msg, [msg])
        claim = env.get("payload", {}).get("already_satisfied")
        if not result.files and self.kind == "task" and isinstance(claim, dict):
            from .. import satisfied as SAT
            result.extra["satisfied_tests"] = SAT.validate_claim(ctx, claim)        # geçersizse StepOutputError: ajan kanıtı düzeltip yeniden gönderir
            result.summary = result.summary + " " + tx("[kanıtla kapanış: {n} test dosyası]", n=len(result.extra['satisfied_tests']))
            return result
        if not result.files:
            from ..llm.parsing import StepOutputError
            raise StepOutputError(tx("Görev teslimi en az bir dosya içermeli (payload.files boş); görev mevcut kodla zaten karşılanıyorsa `payload.already_satisfied` ile kanıt göster."),
                                  [tx("payload.files boş olamaz")])
        payload = env.get("payload", {})
        main = result.events[-1]
        main.payload.update({
            "task_key": self.task_key, "kind": self.kind, "fix_round": self.fix_round,
            "tests_added": payload.get("tests_added") or [], "root_cause": payload.get("root_cause"),
        })
        return result

    def main_event_payload(self, ctx: StepContext, env: Dict[str, Any]) -> Dict[str, Any]:
        return {"files": [f["path"] for f in env["payload"].get("files", [])], "title": self.title}


# ---------------------------------------------------------------------------
# Backlog normalizasyonu (mimari adımının çıktısından)
# ---------------------------------------------------------------------------
VALID_TASK_ROLES = {"BACKEND_DEV", "FRONTEND_DEV", "DESIGNER", "DEVOPS", "QA", "ARCHITECT", "DOCUMENTOR"}
ROLE_ALIASES = {"BACKEND": "BACKEND_DEV", "BACKEND_DEVELOPER": "BACKEND_DEV", "DEVELOPER": "BACKEND_DEV", "DEV": "BACKEND_DEV",
                "FRONTEND": "FRONTEND_DEV", "FRONTEND_DEVELOPER": "FRONTEND_DEV", "UI": "FRONTEND_DEV", "MOBILE": "FRONTEND_DEV",
                "MOBILE_DEV": "FRONTEND_DEV", "E2E_TESTER": "QA", "TESTER": "QA", "DOC": "DOCUMENTOR", "DOCS": "DOCUMENTOR",
                "REPORTER": "DOCUMENTOR", "OPS": "DEVOPS", "DESIGN": "DESIGNER", "UX": "DESIGNER", "UI_DESIGNER": "DESIGNER", "UX_DESIGNER": "DESIGNER"}
WORK_TYPE_DEFAULT_ROLE = {"SCAFFOLD": "BACKEND_DEV", "FEATURE": "BACKEND_DEV", "DESIGN": "DESIGNER", "TEST": "QA", "E2E_SCENARIO": "QA", "DEVOPS": "DEVOPS",
                          "DOCS": "DOCUMENTOR", "BUG": "BACKEND_DEV", "IMPROVEMENT": "BACKEND_DEV", "REFACTOR": "BACKEND_DEV",
                          "TEST_DESIGN": "QA", "SECURITY_TEST": "QA", "PERF_SMOKE": "QA"}
ROLE_DEFAULT_WORK_TYPE = {"QA": "TEST", "DEVOPS": "DEVOPS", "DOCUMENTOR": "DOCS", "DESIGNER": "DESIGN"}


def normalize_backlog(raw: Any, max_tasks: int = 12, custom_roles: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """LLM'den gelen serbest biçimli backlog'u şemaya oturtur; geçersizleri atar, sayıyı sınırlar.

    Rol kuralı (A16): LLM adımı olan her rol görev alabilir; E2E_TESTER ve SCM alamaz — görev QA'ya (E2E_TESTER) ya da iş türünün
    varsayılan rolüne verilir, sessizce geliştiriciye düşmez.
    G6: `custom_roles` (agent_registry.routing_roles) etkin özel ajanlardır: kimliği tam eşleşen görev o ajana gider (takma adlardan ÖNCE);
    rolü bilinmeyen görev, iş türünü yapabilen ve odak sözcüğü görev metninde geçen özel ajana düşer.
    """
    custom_roles = custom_roles or {}
    if not isinstance(raw, list):
        return []
    tasks: List[Dict[str, Any]] = []
    seen: set = set()
    for idx, item in enumerate(raw):
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        if not title:
            continue
        key = str(item.get("id") or item.get("key") or f"T-{idx + 1:02d}").strip().upper()[:24]
        if key in seen:
            key = f"{key}-{idx + 1}"
        seen.add(key)
        work_type = str(item.get("work_type") or item.get("type") or "").upper().strip()
        if work_type not in WORK_TYPE_DEFAULT_ROLE:
            work_type = ""
        role = str(item.get("role") or item.get("assignee") or "").upper().strip()
        if role not in custom_roles:
            role = ROLE_ALIASES.get(role, role)
        if role not in VALID_TASK_ROLES and role not in custom_roles:
            text = " ".join(str(item.get(k) or "") for k in ("title", "name", "description", "summary"))
            from ..agent_registry import match_by_capability
            role = match_by_capability(custom_roles, work_type, text) or WORK_TYPE_DEFAULT_ROLE.get(work_type, "BACKEND_DEV")
        if not work_type and role in custom_roles:
            work_type = "FEATURE" if "FEATURE" in custom_roles[role]["capabilities"] else custom_roles[role]["capabilities"][0]
        work_type = work_type or ROLE_DEFAULT_WORK_TYPE.get(role, "FEATURE")
        criteria = [str(c).strip() for c in (item.get("acceptance_criteria") or item.get("criteria") or []) if str(c).strip()]
        deps = [str(d).strip().upper() for d in (item.get("depends_on") or []) if str(d).strip()]
        files_hint = [str(f).strip().replace("\\", "/") for f in (item.get("files") or item.get("files_hint") or []) if str(f).strip()]
        prio = str(item.get("priority") or "P1").upper()
        if prio not in ("P0", "P1", "P2"):
            prio = "P1"
        tasks.append({
            "task_key": key, "title": title[:160], "role": role, "work_type": work_type,
            "story_ref": str(item.get("story_ref") or item.get("story") or "").strip(),
            "ac_refs": [str(a).strip() for a in (item.get("ac_refs") or []) if str(a).strip()][:10],
            "description": str(item.get("description") or item.get("summary") or "").strip()[:2000],
            "acceptance_criteria": criteria[:10], "depends_on": deps[:10], "files_hint": files_hint[:12], "priority": prio,
        })
    # Bağımlılık sırası: bir görevden önce bağımlı olduğu görevler gelir; aksi halde orijinal sıra korunur (döngü güvenli DFS)
    by_key = {t["task_key"]: t for t in tasks}
    ordered: List[Dict[str, Any]] = []
    placed: set = set()
    visiting: set = set()

    def place(t: Dict[str, Any]) -> None:
        key = t["task_key"]
        if key in placed or key in visiting:
            return
        visiting.add(key)
        for d in t["depends_on"]:
            dep = by_key.get(d)
            if dep is not None:
                place(dep)
        visiting.discard(key)
        placed.add(key)
        ordered.append(t)

    for t in tasks:
        place(t)
    return ordered[:max_tasks]


def normalize_improvements(raw: Any, max_tasks: int = 6, custom_roles: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """PO'nun `improvements[]` listesini backlog görevlerine çevirir (string veya nesne)."""
    items: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return items
    for idx, it in enumerate(raw):
        if isinstance(it, str):
            it = {"title": it}
        if not isinstance(it, dict):
            continue
        it = dict(it)
        it.setdefault("id", f"UAT-{idx + 1:02d}")
        it.setdefault("priority", "P0")
        items.append(it)
    return normalize_backlog(items, max_tasks=max_tasks, custom_roles=custom_roles)


def backlog_to_json(tasks: List[Dict[str, Any]]) -> str:
    return json.dumps(tasks, ensure_ascii=False, indent=2)
