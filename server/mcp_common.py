"""MCP araçlarının ortak, hafif yardımcıları (hub/FastAPI yüklemeden): hem `server.main` hem `server.stdio_proxy` kullanır."""

import json
from typing import Any, Dict, Optional

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from .engine.errors import RunsApiError
from .i18n import translate as tx, N_

# İş döngüsü araçlarını LocalRunsApi zaten ayrıntılı kaydeder (adım/ajan bilgisiyle); çifte kayıt olmasın
_PULL_LOOP_TOOLS = {"get_next_step", "submit_step_result", "wait_for_approval", "report_thinking"}
_LOG_ARG_KEYS = ("run_id", "project_id", "question_id", "session_id", "agent_id", "client_name", "steps", "status")


def _outcome_of(result: Any) -> str:
    """Araç sonucunun kısa özeti (günlükte 'sonuç' sütunu)."""
    for attr in ("status", "run_status"):
        value = getattr(result, attr, None) if not isinstance(result, dict) else result.get(attr)
        if isinstance(value, str) and value:
            return value[:60]
    if isinstance(result, str):
        first = (result.strip().splitlines() or ["OK"])[0][:80]
        # JSON metni döndüren araçlarda ilk satır ('{', '[') bir durum değildir
        return "OK" if first[:1] in ("{", "[") else first
    return "OK"


def _plain_result(result: Any) -> Any:
    """Araç sonucunu günlüğe yazılabilir hale getirir (pydantic → dict)."""
    if result is None or isinstance(result, (str, int, float, bool, dict, list)):
        return result
    dump = getattr(result, "model_dump", None)
    try:
        return dump() if callable(dump) else str(result)
    except Exception:
        return str(result)


def _client_info(ctx: Optional[Context], client_name: str = "") -> Dict[str, str]:
    """MCP oturumundaki istemci kimliği (Claude Desktop, Antigravity...) — yoksa argüman."""
    name, version = "", ""
    try:
        params = ctx.session.client_params if ctx is not None else None
        info = getattr(params, "client_info", None) if params is not None else None
        if info is not None:
            name = getattr(info, "name", "") or ""
            version = getattr(info, "version", "") or ""
    except Exception:
        pass
    name = name or client_name or ""
    return {"name": name, "version": version} if name else {}


def _tool_error(e: RunsApiError) -> ToolError:
    extra = {k: v for k, v in e.extra.items() if k != "error"}
    return ToolError(f"{e.message}" + (f" | {json.dumps(extra, ensure_ascii=False)}" if extra else ""))


def run_software_company_prompt(project_id: str = "", steps: str = "1-10") -> str:
    """`run_software_company` isteminin metni."""
    return tx("""FS-SC yazılım şirketi pipeline'ını çalıştır. Proje: {project} — Adımlar: {steps}.

Döngü:
0. Bir görev/todo aracın varsa (Claude Code: TodoWrite) koşunun adımları için birer madde aç ("Adım N: AJAN — başlık"); her adımı başlarken in_progress, submit sonrası completed yap.
   Koşu dinamiktir: sunucu mimari adımından sonra backlog görevlerini, doğrulama kalınca düzeltme adımlarını ve PO reddinde iyileştirme turunu ekler —
   `submit_step_result` yanıtındaki `inserted_steps`/`total_steps` artınca yeni maddeler aç.
1. `start_pipeline_run(project_id="{project_id}", steps=[{steps_list}])` çağır (boş liste = 1-10 tamamı). run_id'yi sakla.
2. `get_next_step(run_id)` çağır (`progress`, `kind`, `todo_title` alanları görev listesi içindir).
   - status == "STEP": `system_prompt` içindeki rolü üstlen, `user_context`'i oku; önce `report_thinking(run_id, agent_id, "<ne yapacağını anlatan 1-2 cümlelik plan notu>")` gönder;
     sonra YALNIZCA `output_contract`'taki JSON zarfını üret ve `submit_step_result(run_id, order, result_json)` çağır.
     kind == "task": mimarın backlog görevi — kabul kriterlerini karşılayan kodu ve testlerini yaz. kind == "fix": aynı görevin düzeltme turu —
     `user_context`'teki başarısız test/build çıktısını kök nedeninden çöz, testleri zayıflatma.
   - status == "WAITING_APPROVAL": kullanıcı dashboard'dan onaylayana kadar `wait_for_approval(run_id)` çağır (STILL_WAITING geldikçe tekrar).
   - status == "RUN_COMPLETE" veya "CANCELLED": döngüyü bitir ve kısa bir özet ver.
3. `submit_step_result` sonucu:
   - "REJECTED": `validation_errors`'a göre JSON'u düzelt ve aynı order ile tekrar gönder.
   - "NEXT": 2. adıma dön (`verification` alanı sunucunun test/build sonucudur; `fix_requested` true ise sıradaki adım aynı order'ın düzeltmesidir).
     "WAITING_APPROVAL": onay bekle. "RUN_COMPLETE": bitir.
Kurallar: Dosyaları kendin yazma (içerikleri payload.files içinde TAM ver, parça değil); zarf dışında metin üretme; her adımda ajanın rolüne sadık kal;
teknoloji kararlarına uy; kullanıcıya yalnızca adım geçişlerinde tek satırlık durum bildir (doğrulama sonucu ve commit varsa onu da söyle).""", project=project_id or tx("(dashboard'daki aktif proje)"), project_id=project_id, steps=steps,
              steps_list=steps.replace('-', ',') if '-' not in steps else '')
