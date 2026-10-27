"""Hedef projeyi Claude'un doğrudan açabileceği hale getirir: `.mcp.json` + `CLAUDE.md` içindeki işaretli FS-SC bloğu.

Proje her bağlandığında (`POST /api/projects/add`) yeniden yazılır; FS-SC deposu taşınsa bile bir sonraki bağlanışta yollar düzelir.
`.mcp.json` makineye özel yol taşır: `.gitignore`'a girer (scm.FSSC_IGNORE_LINES). `CLAUDE.md` bloğu yol içermez, commit'lenebilir.
Blok ajan bağlamından süzülür (`strip_block`): ajanlar kendilerine yazılmış sürücü talimatını okumasın.
"""

import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict

from .config import SERVER_PORT
from .i18n import translate as tx, N_
from .proc import hidden

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BEGIN = "<!-- fssc:begin -->"
END = "<!-- fssc:end -->"
_BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.DOTALL)


def mcp_config() -> Dict[str, Any]:
    return {"mcpServers": {"fssc-visual-observer": {
        "command": sys.executable, "args": ["-m", "server.main", "--mode", "stdio"], "cwd": REPO_ROOT,
        "env": {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "OBSERVER_PORT": str(SERVER_PORT), "PYTHONPATH": REPO_ROOT},
    }}}


TMP_RULE = N_("**Geçici dosyalar:** zarf/betik/ara JSON gibi geçici dosyaları (build_step_*.js, submit_*.js, step_*.json ...) proje köküne yazma; "
            "yalnızca `.fs-workspace/tmp/` altına yaz (git'e girmez). Kökte kalanları sunucu oraya taşır.")
TMP_DIR = ".fs-workspace/tmp"
_STRAY = re.compile(r"^(?:(?:build_step|complete_build_step|build|complete_build|submit|step|envelope)[_.-]?[A-Za-z_.-]*[0-9][A-Za-z0-9_.-]*|step_data)\.(?:js|mjs|cjs|py|ps1|sh|json)$", re.I)


def rehome_misplaced_contracts(project_dir: str) -> list:
    """Eski düzen hatası: `e2e/screens/*.json` ekran sözleşmeleri uygulama klasörüne (`apps/web/e2e/screens/`) taşınmıştı, oysa sunucu bunları proje kökünde okur.
    Yanlış yerdekini köke taşır (köktekinden yeniyse üzerine yazar, değilse siler) ve boş kalan klasörü kaldırır."""
    moved = []
    root = os.path.abspath(project_dir)
    apps = os.path.join(root, "apps")
    if not os.path.isdir(apps):
        return moved
    dest_dir = os.path.join(root, "e2e", "screens")
    for app in os.listdir(apps):
        src_dir = os.path.join(apps, app, "e2e", "screens")
        if not os.path.isdir(src_dir):
            continue
        for fn in os.listdir(src_dir):
            if not fn.endswith(".json"):
                continue
            src, dst = os.path.join(src_dir, fn), os.path.join(dest_dir, fn)
            try:
                os.makedirs(dest_dir, exist_ok=True)
                if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
                    os.replace(src, dst)
                else:
                    os.remove(src)
                moved.append(fn)
            except OSError:
                continue
        for d in (src_dir, os.path.dirname(src_dir)):
            try:
                os.rmdir(d)
            except OSError:
                pass
    return moved


def sweep_stray_root_files(project_path: str) -> list:
    """Ajanın proje köküne bıraktığı geçici betik/zarf dosyalarını `.fs-workspace/tmp/` altına taşır (git'te izlenenlere dokunmaz)."""
    root = os.path.abspath(project_path)
    moved = []
    rehome_misplaced_contracts(root)
    try:
        names = os.listdir(root)
    except OSError:
        return moved
    for n in names:
        src = os.path.join(root, n)
        if not os.path.isfile(src) or not _STRAY.match(n) or n in ("package.json", "tsconfig.json"):
            continue
        try:
            tracked = subprocess.run(["git", "ls-files", "--error-unmatch", n], cwd=root, capture_output=True, **hidden()).returncode == 0
        except Exception:
            tracked = True
        if tracked:                                  # önceki commit'lere girmiş geçici dosya: izlemeden çıkar (dosya taşınır, commit silmeyi kaydeder)
            try:
                subprocess.run(["git", "rm", "-q", "--cached", "--", n], cwd=root, capture_output=True, **hidden())
            except Exception:
                continue
        if time.time() - os.path.getmtime(src) < 180:      # izli ya da az önce yazılmış (ajan hâlâ çalıştırıyor olabilir) dosyaya dokunma
            continue
        dst_dir = os.path.join(root, *TMP_DIR.split("/"))
        os.makedirs(dst_dir, exist_ok=True)
        try:
            os.replace(src, os.path.join(dst_dir, n))
            moved.append(n)
        except OSError:
            pass
    return moved


def claude_block(project_id: str) -> str:
    return tx("""{BEGIN}
## FS-SC pipeline (otomatik bölüm — elle düzenleme, her proje bağlanışında yeniden yazılır)
Bu klasör FS-SC projesidir (`project_id`: `{project_id}`). Pipeline'ı bu klasörden çalıştır; MCP sunucusu `fssc-visual-observer` (`.mcp.json`).
"pipeline'ı çalıştır" denince:
1. `start_pipeline_run(project_id="{project_id}", steps=[...])` (boş `steps` = 1-10). `RESUMED`/`EXISTING` gelirse aynı işi yeniden başlatma.
2. Döngü: `get_next_step(run_id)` → `STEP` ise `system_prompt` rolünü üstlen, `report_thinking` gönder, yalnızca `output_contract` JSON zarfını
   `submit_step_result(run_id, order, result_json)` ile ver. `WAITING_APPROVAL` → `wait_for_approval`; `PAUSED` aynı; `RUN_COMPLETE`/`CANCELLED` → bitir.
3. `REJECTED` → `validation_errors`'a göre düzeltip aynı order ile tekrar gönder. `inserted_steps > 0` ise yeni görev maddeleri aç.
Kurallar: dosyaları kendin yazma (içeriği `payload.files[].content` içinde tam ver), komut koşma (doğrulamayı sunucu yapar), zarf dışında metin üretme,
"Yönetici notları" öncelikli talimattır, kullanıcıya yalnızca adım geçişlerinde tek satır bildir.
**Docker:** Dockerfile/compose/CI dosyaları yalnızca `devops/` altında olur (kökte ya da uygulama klasöründe değil); sunucu aksini reddeder.
**Yeni kütüphane:** onaylı listede olmayan kütüphane gerekirse adımı durdurma, sohbette onay isteme; manifesti teslime koy, sunucu yöneticiye panodan soru (D-n) açar (sohbet onayı FS-SC'ye işlemez).
**Soru sorma:** sohbette "devam edeyim mi / sürdüreyim mi / onaylıyor musun" diye sorma; belirsizlikte makul varsayımla ilerle, varsayımı teslimdeki `summary`/`questions` alanına yaz.
**Durma:** koşu `RUN_COMPLETE`/`CANCELLED`/`WAITING_APPROVAL`/`BLOCKED`/`SESSION_BOUNDARY` olana kadar döngüyü sürdür; `submit_step_result` `NEXT` dönünce hemen `get_next_step` çağır,
"devam edeyim mi?" diye sorma, adım sayısı arttı ya da doğrulama çıktısı kesik geldi diye durma (bunlar durma nedeni değildir; sunucu kayıtlarını tutar).
Koşu kopmasına karşı: oturumun başında `get_runner_schedule` çağır; zamanlanmış görev araçların varsa FS-SC için tek görevi `interval_minutes` aralığıyla kur/güncelle (ayrıntı FS-SC deposundaki CLAUDE.md, madde 8).
Dashboard: http://127.0.0.1:{SERVER_PORT}
{END}
""", BEGIN=BEGIN, END=END, project_id=project_id, SERVER_PORT=SERVER_PORT).replace(END, tx(TMP_RULE) + "\n" + END, 1)


def strip_block(text: str) -> str:
    """Ajan bağlamı için FS-SC sürücü bloğunu çıkarır."""
    return _BLOCK_RE.sub("", text or "")


def _write_if_changed(path: str, content: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            if f.read() == content:
                return False
    except OSError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return True


def bootstrap_project(project_path: str, project_id: str) -> Dict[str, Any]:
    """Idempotent: `.mcp.json` tümüyle FS-SC'nindir (yeniden yazılır); CLAUDE.md'de yalnızca işaretli blok eklenir/güncellenir."""
    root = os.path.abspath(project_path)
    changed = []
    if _write_if_changed(os.path.join(root, ".mcp.json"), json.dumps(mcp_config(), ensure_ascii=False, indent=2) + "\n"):
        changed.append(".mcp.json")

    # Antigravity (Gemini): aynı MCP ayarı `.agents/mcp_config.json`, aynı kural bloğu GEMINI.md içinde (Claude ile Antigravity aynı klasörde dönüşümlü kullanılabilir)
    ag_dir = os.path.join(root, ".agents")
    os.makedirs(ag_dir, exist_ok=True)
    if _write_if_changed(os.path.join(ag_dir, "mcp_config.json"), json.dumps(mcp_config(), ensure_ascii=False, indent=2) + "\n"):
        changed.append(".agents/mcp_config.json")

    try:                                          # .fs-workspace/tmp/ ve kök geçici desenleri git dışı (ilk commit'i beklemeden)
        from .scm import ensure_gitignore
        if os.path.isdir(os.path.join(root, '.git')) and ensure_gitignore(root):
            changed.append('.gitignore')
    except Exception:
        pass
    os.makedirs(os.path.join(root, *TMP_DIR.split("/")), exist_ok=True)      # ajan geçici dosyaları için hazır klasör
    if sweep_stray_root_files(root):
        changed.append(TMP_DIR)
    block = claude_block(project_id)
    for name in ("CLAUDE.md", "GEMINI.md"):
        md_path = os.path.join(root, name)
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                existing = f.read()
        except OSError:
            existing = ""
        if BEGIN in existing and END in existing:
            new = _BLOCK_RE.sub(lambda _m: block, existing, count=1)
        elif existing.strip():
            new = existing.rstrip("\n") + "\n\n" + block
        else:
            new = f"# {project_id}\n\n" + block
        if _write_if_changed(md_path, new):
            changed.append(name)

    gi_path = os.path.join(root, ".gitignore")
    try:
        with open(gi_path, "r", encoding="utf-8") as f:
            gi = f.read()
    except OSError:
        gi = ""
    have = {ln.strip() for ln in gi.splitlines()}
    missing = [ln for ln in (".mcp.json", ".agents/mcp_config.json") if ln not in have]
    if missing:
        if _write_if_changed(gi_path, (gi.rstrip("\n") + "\n" if gi.strip() else "") + "\n".join(missing) + "\n"):
            changed.append(".gitignore")
    return {"changed": changed}
