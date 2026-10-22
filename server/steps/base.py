"""
StepHandler temel sınıfları.

Her adım işleyicisi üç şeyi bilir:
1. Prompt üretimi (`build_user_prompt`, `output_contract`) — MCP istemcisine (Claude Desktop /
   Antigravity) verilecek bağlam ve JSON çıktı sözleşmesi.
2. Şablon çıktısı (`template_output`) — çevrimdışı/demo modunda LLM yerine geçen hazır A2A zarfı.
3. Yorumlama (`render`) — doğrulanmış zarfı artefaktlara, olaylara ve özet bilgiye çevirir.

Dosya yazımı, Jira/kanban güncellemesi ve onay kapısı `server/pipeline.py`'de motor bağımsız yapılır.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..i18n import translate as tx, N_
from ..layout import docs_setting as _docs_setting, is_apps as _is_apps, layout_of as _layout_of, reports_dir as _reports_dir
from ..llm.parsing import StepOutputError
from ..paths import docs_root as _docs_root, resolve_tokens
from ..runs import PipelineRun, StepRecord


def openapi_digest(raw: str, limit: int = 7000) -> str:
    """OpenAPI JSON'unun okunur özeti: her uç nokta (yöntem, yol, özet) ve şema adları. Geçersiz JSON ya da uç nokta yoksa boş döner (çağıran kısaltmaya düşer)."""
    try:
        import json as _json
        doc = _json.loads(raw)
        info = doc.get("info") or {}
        lines = [tx("OpenAPI özeti: {title} v{version} (tam sözleşme proje klasöründeki dosyadadır)", title=info.get('title', ''), version=info.get('version', ''))]
        for path, ops in (doc.get("paths") or {}).items():
            for method, op in (ops or {}).items():
                if isinstance(op, dict):
                    sec = tx(" [yetki]") if op.get("security") else ""
                    lines.append(f"- {method.upper()} {path} — {str(op.get('summary') or op.get('operationId') or '')[:80]}{sec}")
        schemas = list(((doc.get("components") or {}).get("schemas") or {}).keys())
        if schemas:
            lines.append(tx("Şemalar: ") + ", ".join(schemas[:80]))
        return "\n".join(lines)[:limit] if len(lines) > 1 else ""
    except Exception:
        return ""


def spec_excerpt(spec: str, query: str, budget: int) -> str:
    """Şartnamenin görevle ilgili kısmı. Şartname bütçeye sığıyorsa olduğu gibi döner; sığmıyorsa girişi (ilk ~1500 karakter) +
    görev metniyle en çok örtüşen bölümleri bütçe dolana dek alır, kalan bölümlerin başlıklarını listeler (hiçbir şey sessizce kesilmez).
    Her adımda yüzlerce KB şartnameyi taşımak hem istemci bağlamını doldurur hem de ajanın odağını dağıtır."""
    spec = str(spec or "")
    if budget <= 0 or len(spec) <= budget:
        return spec
    import re
    chunks = [c for c in re.split(r"\n(?=#{1,3} )", spec) if c.strip()]
    toks = {w for w in re.findall(r"[\wçğıöşü]{4,}", str(query).lower())}
    head = spec[:1500]
    picked: List[int] = []
    used = len(head)

    def score(ch: str) -> float:
        words = re.findall(r"[\wçğıöşü]{4,}", ch.lower())
        if not words or not toks:
            return 0.0
        return sum(1 for w in words if w in toks) / (len(words) ** 0.5)

    for i in sorted(range(len(chunks)), key=lambda k: -score(chunks[k])):
        if score(chunks[i]) <= 0:
            break
        size = min(len(chunks[i]), 3500)
        if used + size > budget:
            continue
        picked.append(i)
        used += size
    picked.sort()
    body = "\n\n".join(chunks[i][:3500] for i in picked)
    omitted = [chunks[i].split("\n", 1)[0][:70] for i in range(len(chunks)) if i not in picked][:60]
    note = tx("…(şartname {n:,} karakter; aşağıda bu görevle en ilgili bölümler)…", n=len(spec))
    return (f"{head}\n\n{note}\n\n{body}\n\n"
            + tx("[Şartnamenin diğer bölümleri (başlıklar): {titles}]", titles=" | ".join(omitted)) + "\n"
            + tx("[Tam metin projede ve panoda; gerekirse görev açıklamasındaki kriterlere ve ilgili artefaktlara dayan.]"))


@dataclass
class StepContext:
    hub: Any
    run: PipelineRun
    record: StepRecord
    issue: Dict[str, Any]
    project_dir: str
    trace_id: str
    prompt_text: str
    spec_text: str = ""
    lang: str = "tr"

    @property
    def project_name(self) -> str:
        return os.path.basename(self.project_dir.rstrip("/\\")) or "project"

    @property
    def docs_root(self) -> str:
        """Bu projenin belge klasörü (`FS-docs`, eski düzende `docs`); bkz. server/paths.py."""
        try:
            setting = _docs_setting(self.hub.get_settings())
        except Exception:
            setting = None
        return _docs_root(self.project_dir, setting)

    @property
    def reports_dir(self) -> str:
        """E2E özeti gibi çıktıların klasörü: düz düzende `reports`, apps düzeninde `<docs>/reports`."""
        try:
            lay = _layout_of(self.hub)
        except Exception:
            lay = None
        return _reports_dir(lay, self.docs_root)

    def r(self, value: Any) -> Any:
        """`<docs>` ve `<reports>` belirteçlerini bu projenin klasörleriyle çözer (metin/liste/sözlük)."""
        return resolve_tokens(value, self.docs_root, {"<reports>": self.reports_dir})

    @property
    def order(self) -> int:
        return self.record.order

    @property
    def issue_id(self) -> str:
        return self.record.issue_id

    @property
    def title(self) -> str:
        return self.issue.get("title", f"Task {self.order}")
    def read_artifact(self, relative_path: str, max_chars: int = 12000) -> Optional[str]:
        """Önceki adımların proje diskine yazdığı bir dosyayı okur (yoksa None)."""
        path = os.path.join(self.project_dir, self.r(relative_path))
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                data = f.read()
            if len(data) > max_chars and relative_path.endswith("openapi_spec.json"):
                digest = openapi_digest(data)
                if digest:
                    return digest                      # sözleşmenin ortasından kesmek yerine tüm uç noktaların özeti (tam dosya projede)
            return data[:max_chars] + (tx("\n... (kısaltıldı)") if len(data) > max_chars else "")
        except Exception:
            return None

    def prior_artifacts(self, relative_paths: List[str]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for rel in relative_paths:
            content = self.read_artifact(rel)
            if content is not None:
                out[self.r(rel)] = content
        return out

    # ------------------------------------------------------------------
    # Tam yaşam döngüsü yardımcıları: proje ağacı, bütçeli dosya okuma, koşu özeti
    # ------------------------------------------------------------------
    IGNORED_DIRS = {"node_modules", ".git", ".venv", "venv", "env", "__pycache__", "dist", "build", ".fs-workspace",
                    ".pytest_cache", ".mypy_cache", "coverage", ".next", "vendor", "target", ".idea", ".vscode", ".pytest_data"}

    def project_tree(self, max_entries: int = 220, max_depth: Optional[int] = None) -> List[str]:
        """Proje klasörünün (gürültü dizinleri hariç) göreli dosya listesi; sınırlı sayıda. apps düzeninde `apps/<uygulama>/` iki seviye ekler."""
        if max_depth is None:
            try:
                max_depth = 6 if _is_apps(_layout_of(self.hub)) else 4
            except Exception:
                max_depth = 4
        root = self.project_dir
        if not root or not os.path.isdir(root):
            return []
        out: List[str] = []
        for cur, dirs, files in os.walk(root):
            rel_dir = os.path.relpath(cur, root)
            depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
            dirs[:] = sorted(d for d in dirs if d not in self.IGNORED_DIRS and not d.startswith(".")) if depth < max_depth else []
            for f in sorted(files):
                if f.startswith(".") and f not in (".env.example", ".gitignore"):
                    continue
                rel = f if rel_dir == "." else os.path.join(rel_dir, f)
                out.append(rel.replace("\\", "/"))
                if len(out) >= max_entries:
                    out.append(tx("... (liste {n} girdide kesildi)", n=max_entries))
                    return out
        return out

    def read_files_budget(self, relative_paths: List[str], total_budget: int = 24000, per_file: int = 9000) -> Dict[str, str]:
        """Birden çok dosyayı toplam karakter bütçesine sadık kalarak okur (var olanlar)."""
        out: Dict[str, str] = {}
        remaining = total_budget
        for rel in relative_paths:
            if remaining <= 400:
                break
            content = self.read_artifact(rel, max_chars=min(per_file, remaining))
            if content is None:
                continue
            out[self.r(rel)] = content
            remaining -= len(content)
        return out

    def project_snapshot_md(self, max_entries: int = 160) -> str:
        """Mevcut proje durumunun (var olan proje / önceki adımlar) Markdown özeti."""
        tree = self.project_tree(max_entries=max_entries)
        if not tree:
            return ""
        lines = [tx("## Proje klasörü ({n} dosya) — var olan dosyaları dikkate al, üzerine yazacaksan TAM içerik ver", n=len(tree)), "```"]
        lines.extend(tree)
        lines.append("```")
        heads = self.read_files_budget(["README.md", "CLAUDE.md", "GEMINI.md", "AGENTS.md"], total_budget=3500, per_file=1800)
        for rel, content in heads.items():
            from ..project_bootstrap import strip_block
            content = strip_block(content).strip()
            if not content:
                continue
            lines.append("\n" + tx("### {rel} (özet)", rel=rel) + f"\n```\n{content}\n```")
        return "\n".join(lines)

    def run_summary_md(self, recent: int = 15, max_failed: int = 20) -> str:
        """Koşunun o ana kadarki adımlarının kısa tablosu. Uzun koşuda (yüzlerce adım) tamamı bağlamı doldurur: başarısız/reddedilen adımlar (en çok `max_failed`) ve
        son `recent` adım satır satır, öncekiler tür/ajan sayımları olarak özetlenir (hiçbir şey sessizce atılmaz: sayım ve atlanan aralık yazılır)."""
        done = [s for s in self.run.steps if s.status in ("DONE", "FAILED", "REJECTED")]
        if not done:
            return ""

        def row(s) -> str:
            ver = (s.verification or {}).get("status") if s.verification else "-"
            return (f"| #{s.order}{tx(' (düzeltme {n})', n=s.fix_round) if s.fix_round else ''} | {s.role} | {s.kind} | {s.status} | {ver} | {s.commit or '-'} | "
                    f"{(s.summary or '')[:70]} |")
        tail = done[-recent:]
        head = done[:-recent] if len(done) > recent else []
        failed = [s for s in head if s.status in ("FAILED", "REJECTED")][-max_failed:]
        shown = failed + tail
        lines = [tx("## Koşu özeti (bu ana kadar: {done} adım bitti, {failed} başarısız/reddedildi)", done=len(done), failed=sum(1 for s in done if s.status != 'DONE'))]
        if head:
            from collections import Counter
            by_kind = Counter(f"{s.kind}/{s.role}" for s in head)
            commits = sum(1 for s in head if s.commit)
            lines.append(tx("Önceki {n} adım (#{first}–#{last}): ", n=len(head), first=head[0].order, last=head[-1].order)
                         + ", ".join(f"{k} ×{v}" for k, v in by_kind.most_common(8))
                         + tx("; {commits} commit. Başarısız/reddedilenler ve son {tail} adım aşağıda.", commits=commits, tail=len(tail)))
        lines += [tx("| Adım | Ajan | Tür | Durum | Doğrulama | Commit | Özet |"), "|---|---|---|---|---|---|---|"]
        lines += [row(s) for s in shown]
        return chr(10).join(lines)

    @staticmethod
    def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        return datetime.now(timezone.utc).strftime(fmt)


@dataclass
class StepPrompt:
    system_prompt: str
    user_context: str
    output_contract: str
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepEvent:
    from_agent: str
    to_agent: str
    action: str
    status: str = "SUCCESS"
    payload: Dict[str, Any] = field(default_factory=dict)
    current_file: Optional[str] = None
    tokens_used: int = 0
    friendly_dialogue: Optional[str] = None
    thinking: Optional[str] = None
    what_doing: Optional[str] = None
    what_next: Optional[str] = None
    pause_after_s: float = 0.0


@dataclass
class StepResult:
    summary: str
    action: str
    next_agent_id: Optional[str]
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)
    tokens: int = 0
    status: str = "SUCCESS"
    events: List[StepEvent] = field(default_factory=list)
    files: List[Dict[str, str]] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)


ENVELOPE_CONTRACT = N_("""Yanıtını YALNIZCA tek bir ```json bloğu olarak ver; blok dışında hiçbir metin yazma.
Zarf (A2A):
{
  "trace_id": "<verilen trace_id>",
  "from_agent": "<AJAN_ID>",
  "to_agent": "<SONRAKİ_AJAN_ID>",
  "intent": "<AKSİYON>",
  "status": "SUCCESS" | "FAILED",
  "payload": {
    "summary": "1-3 cümlelik, teknik olmayan Türkçe özet",
    "friendly_dialogue": "Sonraki ajana samimi, insansı bir el sıkışma cümlesi",
    "thinking": "Bu adımda ne yapacağının (amaç ve yaklaşım) 1-2 cümlelik kısa plan notu",
    "what_doing": "Şu an ne yapıyor (kısa)",
    "what_next": "Sonraki ajanın ne yapması bekleniyor (kısa)",
    "files": [ { "path": "proje köküne göreli yol", "content": "dosyanın TAM içeriği" } ],
    ... (rol için istenen ek alanlar aşağıda)
  },
  "metadata": { "tokens_used": <tahmini toplam token>, "current_file": "<ana dosya yolu>" }
}
Kurallar: `files[].path` yalnızca proje kökü altında göreli olmalı ('..' yasak; `.git/` ve `.fs-workspace/` altına yazılamaz). Dosyaları KENDİN yazma; içeriği `files` içinde ver, sunucu diske yazar.""")


class StepHandler:
    """Bir Jira adımının davranışı. Alt sınıflar sınıf niteliklerini ve üç metodu doldurur."""

    order: int = 0
    agent_id: str = "PM"
    next_agent_id: Optional[str] = None
    action: str = "COMPLETED"
    critical: bool = False
    server_side: bool = False
    estimated_tokens: int = 200
    title: str = ""
    # (thinking, what_doing, what_next) — START_THINKING olayı için
    thinking: tuple = (N_("Görevi analiz ediyorum."), N_("Görev üzerinde çalışıyor"), N_("Sonraki adıma devredecek"))

    def thinking_for(self, ctx: "StepContext") -> tuple:
        """START_THINKING olayının (düşünce, ne yapıyor, sırada) metni; sprint kipi gibi bağlama göre işleyici geçersiz kılabilir.
        Sınıf düzeyindeki (N_ ile işaretli) demet çağrı anında çevrilir; örnekte (`__init__`) zaten çevrilmiş kurulan demet olduğu gibi döner."""
        own = self.__dict__.get("thinking")
        if own is not None:
            return own
        return tuple(tx(t) for t in self.thinking)

    def display_title(self, ctx: "StepContext") -> str:
        """Canlı akışta ve olaylarda görünen görev başlığı (varsayılan: Jira maddesinin başlığı)."""
        return ctx.title
    # Rol için istenen ek payload alanları (dokümantasyon amaçlı JSON şeması metni)
    payload_schema: Dict[str, Any] = {}
    # Kullanıcı bağlamına eklenecek önceki artefakt dosyaları
    prior_files: List[str] = []
    # Tam yaşam döngüsü: adımdan sonra sunucu doğrulaması (test/build) ve SCM commit'i koşsun mu
    verify_after: bool = False
    commit_after: bool = False
    # Bu belgeler olmadan teslim kabul edilmez: (belirteçli yol, en az karakter). Boş/sahte teslim adımı bitirmesin (saha notu D1)
    required_files: tuple = ()
    # Kullanıcı bağlamına girecek şartname bütçesi (karakter): aşılırsa görevle ilgili bölümler seçilir. None = tamamı (PM / Mimar şartnameyi bütünüyle okur)
    spec_budget: Optional[int] = 6000

    # ------------------------------------------------------------------
    # Prompt üretimi
    # ------------------------------------------------------------------
    def build_user_prompt(self, ctx: StepContext) -> str:
        parts = [
            tx("# Görev: {title} (Jira {issue}, adım #{n})", title=ctx.title, issue=ctx.issue_id, n=ctx.order),
            tx("Proje: {name}  |  Hedef klasör: {dir}", name=ctx.project_name, dir=ctx.project_dir),
            tx("Talep / özellik: {prompt}", prompt=ctx.prompt_text),
        ]
        desc = ctx.issue.get("description")
        if desc:
            parts.append("\n" + tx("## Görev açıklaması") + f"\n{desc}")
        criteria = ctx.issue.get("acceptance_criteria") or []
        if criteria:
            parts.append("\n" + tx("## Kabul kriterleri") + "\n" + "\n".join(f"- {c}" for c in criteria))
        try:
            from ..decisions import decisions_context
            dctx = decisions_context(ctx.hub.tech_questions(), ctx.hub.tech_decisions())
        except Exception:
            dctx = ""
        if dctx:
            parts.append("\n" + dctx)
        if ctx.spec_text:
            spec = ctx.spec_text if self.spec_budget is None else spec_excerpt(ctx.spec_text, f"{ctx.title} {desc or ''} {' '.join(criteria)}", self.spec_budget)
            parts.append("\n" + tx("## Müşteri toplantı notları ve şartname") + f"\n{spec}")
        prior = ctx.prior_artifacts(self.prior_files)
        for rel, content in prior.items():
            parts.append("\n" + tx("## Önceki artefakt: {rel}", rel=rel) + f"\n```\n{content}\n```")
        extra = self.extra_user_context(ctx)
        if extra:
            parts.append("\n" + extra)
        return "\n".join(parts)

    def extra_user_context(self, ctx: StepContext) -> str:
        return ""

    def output_contract(self, ctx: StepContext) -> str:
        schema = json.dumps(self.payload_schema, ensure_ascii=False, indent=2) if self.payload_schema else "{}"
        note = ""
        try:
            from ..decisions import is_answered
            if self.order >= 2 and is_answered(ctx.hub.tech_decisions()):
                note = "\n" + tx("Not: `files` listesindeki yollar örnektir; kullanıcının teknoloji kararlarına uygun dosya adları ve "
                                 "dizin yapısı kullan (ör. PHP seçildiyse src/*.php ve composer.json, Node seçildiyse src/*.ts ve package.json).")
        except Exception:
            note = ""
        return (
            f"{tx(ENVELOPE_CONTRACT)}\n\n"
            + tx("Bu adım için: from_agent=\"{agent}\", to_agent=\"{to}\", intent=\"{intent}\".", agent=self.agent_id, to=self.next_agent_id or 'PM', intent=self.action) + "\n"
            + tx("payload içinde ayrıca şu alanları doldur:") + f"\n{schema}{note}"
        )

    # ------------------------------------------------------------------
    # Şablon (çevrimdışı) çıktısı
    # ------------------------------------------------------------------
    def envelope(self, ctx: StepContext, payload: Dict[str, Any], tokens: Optional[int] = None,
                 current_file: Optional[str] = None, status: str = "SUCCESS") -> Dict[str, Any]:
        payload = ctx.r(payload)
        current_file = ctx.r(current_file)
        files = payload.get("files") or []
        return {
            "trace_id": ctx.trace_id,
            "from_agent": self.agent_id,
            "to_agent": self.next_agent_id or "PM",
            "intent": self.action,
            "status": status,
            "payload": payload,
            "metadata": {
                "tokens_used": tokens if tokens is not None else self.estimated_tokens,
                "current_file": current_file or (files[0]["path"] if files else None),
            },
        }

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Yorumlama
    # ------------------------------------------------------------------
    def missing_required_files(self, ctx: StepContext, files: List[Dict[str, Any]]) -> List[str]:
        """`required_files` içinde teslimde bulunmayan, boş ya da (JSON ise) ayrıştırılamayan belgelerin hata iletileri."""
        if not self.required_files or getattr(ctx.record, "kind", "phase") != "phase":
            return []                                             # yalnızca faz teslimi; devam (structure) ve düzeltme adımları belge yazmaz
        def norm(p: Any) -> str:
            return str(p).replace("\\", "/").lstrip("./").lower()
        have = {norm(ctx.r(str(f["path"]))): str(f.get("content") or "") for f in (files or []) if isinstance(f, dict) and f.get("path")}
        by_name = {p.rsplit("/", 1)[-1]: c for p, c in have.items()}           # belge klasörü adı farklı yazılmışsa (docs/ ~ FS-docs/) dosya adıyla eşleşir
        problems: List[str] = []
        for token_path, min_chars in self.required_files:
            want = ctx.r(token_path)
            content = have.get(norm(want), by_name.get(norm(want).rsplit("/", 1)[-1]))
            if content is None:
                problems.append(tx("Gerekli belge teslimde yok: {want} (payload.files içinde tam içeriğiyle ver).", want=want))
            elif len(content.strip()) < min_chars:
                problems.append(tx("{want} boş: dosyanın tam içeriğini ver.", want=want) if min_chars <= 1
                                else tx("{want} çok kısa (en az {n} karakter beklenir).", want=want, n=min_chars))
            elif want.lower().endswith(".json"):
                try:
                    json.loads(content)
                except ValueError:
                    problems.append(tx("{want} geçerli JSON değil.", want=want))
        return problems

    def render(self, ctx: StepContext, env: Dict[str, Any]) -> StepResult:
        payload = env.get("payload", {})
        files = payload.get("files", [])
        missing = self.missing_required_files(ctx, files)
        if missing:
            raise StepOutputError(missing[0], missing)
        artifacts = [self.artifact_from_file(f) for f in files]
        tokens = int(env.get("metadata", {}).get("tokens_used") or self.estimated_tokens)
        current_file = env.get("metadata", {}).get("current_file") or (files[0]["path"] if files else None)
        main_event = StepEvent(
            from_agent=env.get("from_agent", self.agent_id),
            to_agent=env.get("to_agent", self.next_agent_id or "PM"),
            action=env.get("intent", self.action),
            status=env.get("status", "SUCCESS"),
            payload={"order": ctx.order, "task_id": ctx.issue_id, **ctx.r(self.main_event_payload(ctx, env))},
            current_file=current_file,
            tokens_used=tokens,
            friendly_dialogue=payload.get("friendly_dialogue"),
            thinking=payload.get("thinking"),
            what_doing=payload.get("what_doing"),
            what_next=payload.get("what_next"),
        )
        return StepResult(
            summary=payload.get("summary", tx("{agent} adımı tamamlandı.", agent=self.agent_id)),
            action=env.get("intent", self.action),
            next_agent_id=env.get("to_agent", self.next_agent_id),
            artifacts=artifacts,
            tokens=tokens,
            status=env.get("status", "SUCCESS"),
            events=[main_event],
            files=files,
        )

    def main_event_payload(self, ctx: StepContext, env: Dict[str, Any]) -> Dict[str, Any]:
        payload = env.get("payload", {})
        return {"files": [f["path"] for f in payload.get("files", [])]}

    @staticmethod
    def artifact_from_file(f: Dict[str, str]) -> Dict[str, Any]:
        path = f["path"]
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        type_map = {"md": "markdown", "json": "json", "py": "python", "ts": "typescript", "tsx": "typescript",
                    "yml": "yaml", "yaml": "yaml", "js": "javascript", "html": "html", "css": "css"}
        kind = type_map.get(ext, "dockerfile" if name.lower() == "dockerfile" else (ext or "text"))
        return {"name": name, "path": path, "type": kind, "content": f["content"]}
