"""
Hedef proje klasör düzeni (talimat: `medi-gate/meta-repo-setup.md`; yönetici kararı 2026-10-12: tek repo, `apps/ devops/ docs/`).
Kalıcı başvuru belgesi: `docs/klasor-duzeni.md`.

Düzen proje ayarında tanımlanır (`settings.project_layout`); adlar ve rol eşlemesi koda gömülü değildir.

  mode "apps"  Yeni projeler. Kökte yalnızca `apps/<rol>/` (uygulama kodu, her uygulama kendi manifesti ve testleriyle),
               `devops/` (Dockerfile, compose, CI betikleri), `docs/` (insan okur belgeler) ve README/CHANGELOG gibi depo dosyaları bulunur.
  mode "flat"  Eski projeler ve ayar yokken varsayılan: ürün kodu kökte, belge klasörü `docs_root` ayarına göre (FS-docs / docs).
               `sprint.enabled=false` akışı, kuru koşu ve mevcut testler bu kipte aynen çalışır.

Ajan teslimleri iki yoldan düzene sokulur: LLM motorunda teslim DOĞRULANIR (uymayan yol REJECTED, öneri yolla birlikte);
şablon motoru ve sunucu tarafı adımların (E2E, el sıkışma) çıktısı düzene TAŞINIR (uyumlu bir LLM'i taklit eder).
"""

from __future__ import annotations

import fnmatch
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .i18n import translate as tx
from .paths import WORKSPACE_DIR, sanitize_docs_root

MODES = ("apps", "flat")
DEFAULT_ROLES: Dict[str, str] = {"backend": "backend", "web": "web", "mobile": "mobile", "admin": "admin"}
DEFAULT_LAYOUT: Dict[str, Any] = {
    "mode": "apps", "apps_dir": "apps", "devops_dir": "devops", "docs_dir": "docs", "roles": dict(DEFAULT_ROLES), "enforce": True,
}
LAYOUT_SETTING = "project_layout"

# Kökte durabilen depo dosyaları ve platformun kökte aradığı klasörler
ROOT_FILES = ("README.md", "CHANGELOG.md", "CONTRIBUTING.md", "CLAUDE.md", "AGENTS.md", "GEMINI.md", ".gitignore", ".gitattributes",
              ".editorconfig", ".gitlab-ci.yml", ".mcp.json", "LICENSE", "LICENSE.md", "LICENSE.txt")
ROOT_DIRS = (".github",)

# Eski (düz) düzende bilinen klasör adları → mantıksal rol
LEGACY_APP_DIRS = {"frontend": "web", "web": "web", "client": "web", "mobile": "mobile", "admin": "admin",
                   "backend": "backend", "server": "backend", "api": "backend"}
DEVOPS_NAMES = ("dockerfile", "docker-compose.yml", "docker-compose.yaml", ".dockerignore", "jenkinsfile")
DEVOPS_DIRS = ("k8s", "deploy", "terraform", "helm", "ansible", "infra")
# KALICI KURAL (yönetici kararı 2026-10-16): Docker/compose dosyaları düzen kipinden bağımsız YALNIZCA `devops/` altında olur (kökte ya da uygulama klasöründe değil;
# aynı makinedeki başka projelerle çakışmasın, tek yerde toplansın). Varyantlar dahil: Dockerfile.dev, docker-compose.dev.yml, compose.yaml, .dockerignore.
_DOCKER_RX = re.compile(r"^(dockerfile(\..+)?|.+\.dockerfile|\.dockerignore|docker-compose(\..+)?\.ya?ml|compose(\..+)?\.ya?ml|docker-bake(\..+)?\.(hcl|json))$", re.IGNORECASE)


def is_docker_file(p: str) -> bool:
    return bool(_DOCKER_RX.match(str(p).replace("\\", "/").split("/")[-1]))


def docker_suggestion(layout: Dict[str, Any], p: str) -> str:
    """Docker dosyası için `devops/` altındaki yol: uygulama klasöründeki Dockerfile `devops/<uygulama>/Dockerfile` olur, diğerleri `devops/<ad>`."""
    p = _norm(p)
    devops = layout.get("devops_dir") or "devops"
    parts = p.split("/")
    base = parts[-1]
    dockerish = base.lower().startswith("dockerfile") or base.lower().endswith(".dockerfile") or base.lower() == ".dockerignore"
    if len(parts) >= 3 and parts[0] == (layout.get("apps_dir") or "apps") and dockerish:
        return f"{devops}/{parts[1]}/{base}"
    if len(parts) == 2 and dockerish and parts[0] != devops:                          # eski düz düzen: backend/Dockerfile → devops/backend/Dockerfile
        return f"{devops}/{parts[0]}/{base}"
    return f"{devops}/{base}"


def docker_violations(layout: Dict[str, Any], paths: Iterable[str]) -> List[str]:
    """`devops/` dışına yazılmak istenen Docker/compose dosyaları için okunur hata iletileri (her düzen kipinde geçerli)."""
    devops = (layout.get("devops_dir") or "devops").strip("/")
    out: List[str] = []
    for raw in paths:
        p = _norm(raw)
        if p and is_docker_file(p) and p.split("/")[0] != devops:
            out.append(tx("{path}: Docker/compose dosyaları yalnızca `{devops}/` altında olur (kökte ya da uygulama klasöründe değil). Önerilen yol: `{suggestion}`. "
                          "compose'ta build context depo köküne göre verilir (`context: ..`, `dockerfile: {devops}/<uygulama>/Dockerfile`).",
                          path=p, devops=devops, suggestion=docker_suggestion(layout, p)))
    return out


def devops_rule_section(layout: Dict[str, Any], project_id: str = "") -> str:
    """Her kod/belge adımının bağlamına eklenen kalıcı Docker/dağıtım kuralı (düzen kipinden bağımsız)."""
    devops = layout.get("devops_dir") or "devops"
    pid = project_id or "<proje_id>"
    return (
        tx("## Docker ve dağıtım dosyaları (KALICI KURAL — düzen kipinden bağımsız)\n"
           "- Dockerfile*, docker-compose*.yml, compose*.yml, .dockerignore ve CI/CD betikleri YALNIZCA `{devops}/` altına yazılır; kökte, `apps/<uygulama>/` içinde ya da başka yerde OLAMAZ "
           "(aynı makinedeki başka projelerle çakışmasın, tek yerde toplansın). Uymayan teslim sunucuca geri çevrilir.\n"
           "- Yapı: tek uygulama için `{devops}/Dockerfile`, birden çok uygulama için `{devops}/<uygulama>/Dockerfile`; compose `{devops}/docker-compose.yml` "
           "(`docker-compose.dev.yml` gibi varyantlar da `{devops}/` altında).\n"
           "- Yollar depo köküne göre: compose `build.context: ..`, `dockerfile: {devops}/<uygulama>/Dockerfile`; kaynağı bind-mount etme, imaja kopyala.\n"
           "- Çakışma önleme: compose'ta `name: {pid}`; container, ağ ve hacim adları `{pid}-` önekiyle; host portu yöneticinin verdiği değerdir (yoksa soru aç), "
           "uygulamanın kod içindeki varsayılan portunu değiştirme; karar ve komutlar `{devops}/README.md` ya da RUNBOOK'a yazılır.",
           devops=devops, pid=pid)
    )


# ---------------------------------------------------------------------------
# Ayar modeli
# ---------------------------------------------------------------------------
def _segment(value: Any, default: str) -> str:
    """Tek klasör adı: harf/rakam/`._-`; boşluk, eğik çizgi, `..`, `.git` ve `.fs-workspace` geçersizdir."""
    if isinstance(value, str):
        v = value.strip()
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", v) and v.lower() not in {".git", WORKSPACE_DIR.lower()} and not v.endswith("."):
            return v
    return default


def sanitize_layout(raw: Any, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ayar değerini doğrular; geçersiz alan `fallback`te (yoksa varsayılanda) kalır, bilinmeyen anahtarlar atılır."""
    raw = raw if isinstance(raw, dict) else {}
    base = {**DEFAULT_LAYOUT, **{k: v for k, v in (fallback or {}).items() if k in DEFAULT_LAYOUT}}
    out: Dict[str, Any] = {"mode": base["mode"] if raw.get("mode") not in MODES else raw["mode"],
                           "apps_dir": _segment(raw.get("apps_dir"), _segment(base["apps_dir"], DEFAULT_LAYOUT["apps_dir"])),
                           "devops_dir": _segment(raw.get("devops_dir"), _segment(base["devops_dir"], DEFAULT_LAYOUT["devops_dir"])),
                           "docs_dir": sanitize_docs_root(raw.get("docs_dir")) or sanitize_docs_root(base["docs_dir"]) or DEFAULT_LAYOUT["docs_dir"],
                           "enforce": bool(raw.get("enforce", base["enforce"]))}
    roles_in = raw.get("roles") if isinstance(raw.get("roles"), dict) else base.get("roles") or DEFAULT_ROLES
    roles: Dict[str, str] = {}
    for key, folder in list(roles_in.items())[:12]:
        k = str(key).strip().lower()
        if re.fullmatch(r"[a-z][a-z0-9_]{0,23}", k):
            roles[k] = _segment(folder, k)
    out["roles"] = roles or dict(DEFAULT_ROLES)
    # Üç kök klasör birbirinden farklı olmalı (büyük/küçük harf duyarsız); çakışan varsayılana döner
    seen: Dict[str, str] = {}
    for key in ("apps_dir", "devops_dir", "docs_dir"):
        top = out[key].split("/")[0].lower()
        if top in seen:
            out[key] = DEFAULT_LAYOUT[key]
            top = out[key].split("/")[0].lower()
        seen[top] = key
    return out


def flat_layout() -> Dict[str, Any]:
    return {**DEFAULT_LAYOUT, "mode": "flat", "enforce": False, "roles": dict(DEFAULT_ROLES)}


def layout_of(source: Any = None) -> Dict[str, Any]:
    """`source`: hub (`get_settings`), ayar sözlüğü ya da None. Ayar yoksa FLAT (eski projeler aynen çalışır)."""
    settings: Any = None
    if source is not None:
        try:
            settings = source.get_settings() if hasattr(source, "get_settings") else source
        except Exception:
            settings = None
    raw = settings.get(LAYOUT_SETTING) if isinstance(settings, dict) else None
    return sanitize_layout(raw) if isinstance(raw, dict) else flat_layout()


def is_apps(layout: Optional[Dict[str, Any]]) -> bool:
    return bool(layout) and layout.get("mode") == "apps"


def docs_setting(settings: Optional[Dict[str, Any]]) -> Any:
    """`paths.docs_root`a verilecek ayar: apps düzeninde düzenin belge klasörü, düz düzende `docs_root` ayarı."""
    lay = layout_of(settings or {})
    return lay["docs_dir"] if is_apps(lay) else (settings or {}).get("docs_root")


def default_layout_for(project_dir: str) -> Dict[str, Any]:
    """Yeni (boş) klasör → apps düzeni; içinde FS-SC durumu ya da ürün dosyaları olan klasör → düz (dayatılmaz, göçle geçilir)."""
    markers = (WORKSPACE_DIR, "package.json", "src", "pyproject.toml", "requirements.txt", "composer.json", "go.mod", "pom.xml",
               "frontend", "backend", "Dockerfile")
    try:
        if project_dir and any(os.path.exists(os.path.join(project_dir, m)) for m in markers):
            return flat_layout()
    except OSError:
        pass
    return sanitize_layout({})


# ---------------------------------------------------------------------------
# Yol kuralları
# ---------------------------------------------------------------------------
def _norm(rel: str) -> str:
    return str(rel or "").replace("\\", "/").strip().lstrip("/")


def app_folder(layout: Dict[str, Any], role_key: str) -> str:
    """`apps/backend`: mantıksal rolün (backend, web, mobile ...) deponun kökünden göreli klasörü."""
    return f"{layout['apps_dir']}/{layout['roles'].get(role_key, role_key)}"


def app_roots(layout: Optional[Dict[str, Any]]) -> Tuple[str, ...]:
    """Doğrulama komutlarının manifest arayacağı uygulama kök klasörleri (`apps`)."""
    return (layout["apps_dir"],) if is_apps(layout) else ()


def role_key_for(agent_role: str) -> str:
    """Teslimi yazan ajanın hangi uygulama klasörüne yazdığı (mantıksal rol): FRONTEND_DEV → web, mobil/özel roller adından, varsayılan backend."""
    r = (agent_role or "").upper()
    if r == "DEVOPS":
        return "devops"
    if "MOBILE" in r or "FLUTTER" in r or "ANDROID" in r or "IOS" in r:
        return "mobile"
    if "ADMIN" in r:
        return "admin"
    if "FRONT" in r or r in ("WEB_DEV", "UI_DEV"):
        return "web"
    return "backend"


def reports_dir(layout: Optional[Dict[str, Any]], docs_root: str) -> str:
    """E2E özeti gibi çıktıların klasörü: düz düzende `reports`, apps düzeninde `<docs>/reports`."""
    return f"{docs_root}/reports" if is_apps(layout) else "reports"


def _is_docs(p: str, docs_root: str) -> bool:
    return p == docs_root or p.startswith(docs_root + "/")


def _is_license(name: str) -> bool:
    return fnmatch.fnmatch(name, "LICENSE*")


def _is_root_file(p: str) -> bool:
    if "/" in p:
        return p.split("/")[0] in ROOT_DIRS
    return p in ROOT_FILES or _is_license(p)


def _is_devops_file(p: str) -> bool:
    base = p.split("/")[-1].lower()
    first = p.split("/")[0].lower()
    return base in DEVOPS_NAMES or base.startswith("dockerfile") or is_docker_file(base) or first in DEVOPS_DIRS


def relocate(layout: Dict[str, Any], rel: str, agent_role: str, docs_root: str) -> str:
    """Düzene uymayan yolu düzene taşır (şablon motoru / sunucu çıktısı ve hata mesajındaki öneri). Zaten uyumluysa aynen döner."""
    p = _norm(rel)
    if not is_apps(layout) or not p:
        return p
    first = p.split("/")[0]
    if _is_docs(p, docs_root) or first == layout["devops_dir"] or _is_root_file(p):
        return p
    if first == layout["apps_dir"] and not violations(layout, [p], docs_root):
        return p
    if first == "reports":
        return f"{docs_root}/{p}"
    if _is_devops_file(p):
        return f"{layout['devops_dir']}/{p}"
    if first.lower() in LEGACY_APP_DIRS and "/" in p:
        return f"{app_folder(layout, LEGACY_APP_DIRS[first.lower()])}/{p.split('/', 1)[1]}"
    key = role_key_for(agent_role)
    if key == "devops":
        return f"{layout['devops_dir']}/{p}"
    return f"{app_folder(layout, key)}/{p}"


def violations(layout: Dict[str, Any], paths: Iterable[str], docs_root: str, agent_role: str = "") -> List[str]:
    """Düzene uymayan yollar için okunur hata iletileri (öneri yoluyla); düzen düzse ya da her şey uyumluysa boş."""
    if not is_apps(layout):
        return []
    role_dirs = set(layout["roles"].values())
    out: List[str] = []
    for raw in paths:
        p = _norm(raw)
        if not p:
            continue
        first = p.split("/")[0]
        if _is_docs(p, docs_root) or first == layout["devops_dir"] or _is_root_file(p):
            continue
        if first == layout["apps_dir"]:
            parts = p.split("/")
            if len(parts) >= 3 and parts[1] in role_dirs:
                continue
            out.append(tx("{path}: `{apps}/` altında tanımlı bir uygulama klasörü gerekir ({roles}); "
                          "dosyalar `{apps}/<uygulama>/...` biçiminde olmalı.",
                          path=p, apps=layout['apps_dir'], roles=', '.join(sorted(role_dirs))))
            continue
        suggestion = relocate(layout, p, agent_role, docs_root)
        out.append(tx("{path}: kökte ürün dosyası olamaz (kökte yalnızca `{apps}/`, `{devops}/`, `{docs}/` ve README/CHANGELOG gibi "
                      "depo dosyaları bulunur). Önerilen yol: `{suggestion}`.",
                      path=p, apps=layout['apps_dir'], devops=layout['devops_dir'], docs=docs_root, suggestion=suggestion))
    return out


def relocate_envelope(layout: Dict[str, Any], envelope: Dict[str, Any], agent_role: str, docs_root: str, resolve=None) -> int:
    """Zarftaki `payload.files[].path` ve `metadata.current_file` yollarını düzene taşır (yerinde); taşınan dosya sayısını döner."""
    if not is_apps(layout) or not isinstance(envelope, dict):
        return 0
    resolve = resolve or (lambda v: v)
    moved = 0
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    for f in payload.get("files") or []:
        if isinstance(f, dict) and f.get("path"):
            new = relocate(layout, resolve(f["path"]), agent_role, docs_root)
            if new != _norm(resolve(f["path"])):
                moved += 1
            f["path"] = new
    meta = envelope.get("metadata") if isinstance(envelope.get("metadata"), dict) else None
    if meta and meta.get("current_file"):
        meta["current_file"] = relocate(layout, resolve(meta["current_file"]), agent_role, docs_root)
    return moved


def relocate_hints(layout: Dict[str, Any], hints: List[str], agent_role: str, docs_root: str) -> List[str]:
    """Mimarın dosya ipuçlarını düzene uydurur (kökteki `src/x.ts` → `apps/backend/src/x.ts`)."""
    if not is_apps(layout):
        return list(hints)
    return [relocate(layout, h, agent_role, docs_root) for h in hints]


# ---------------------------------------------------------------------------
# Ajan istemi
# ---------------------------------------------------------------------------
def prompt_section(layout: Dict[str, Any], docs_root: str) -> str:
    """Kod ve belge üreten adımların bağlamına eklenen düzen kuralı (rol promptlarındaki örnek yolların önüne geçer)."""
    if not is_apps(layout):
        return ""
    apps, devops = layout["apps_dir"], layout["devops_dir"]
    roles = "; ".join(f"{k} → `{apps}/{v}/`" for k, v in layout["roles"].items())
    example = app_folder(layout, "backend")
    return (
        tx("## Proje klasör düzeni (ZORUNLU — rol promptundaki örnek yolların önüne geçer)\n"
           "Depo tek git deposudur ve kökte YALNIZCA şunlar bulunur:\n"
           "- `{apps}/<uygulama>/` — uygulama kodu; her uygulama kendi klasöründe, kendi manifesti (package.json, pyproject.toml, composer.json ...), "
           "`src/` ve testleriyle birlikte. Uygulama klasörleri: {roles}.\n"
           "- `{devops}/` — Dockerfile, docker-compose, CI/CD ve dağıtım betikleri.\n"
           "- `{docs}/` — insan okur belgeler (PRD.md, ARCHITECTURE.md, openapi_spec.json, adr/, meetings/, sprints/ ...).\n"
           "- Kökte yalnızca README.md, CHANGELOG.md, LICENSE, CLAUDE.md, .gitignore gibi depo dosyaları.\n"
           "`files[].path`, backlog `files` ve `files_hint` alanları bu düzene uymalıdır; kökte `src/`, `tests/`, `package.json`, `Dockerfile` YAZMA "
           "(örn. `{example}/src/main.ts`, `{example}/package.json`, `{devops}/Dockerfile`). ",
           apps=apps, roles=roles, devops=devops, docs=docs_root, example=example)
        + (tx("Uymayan teslim sunucuca reddedilir (öneri yolu hata iletisinde verilir). ") if layout.get("enforce") else "")
        + tx("Doğrulama ve çalıştırma komutları deponun KÖKÜNDEN koşar: bir uygulamanın komutları için `cd {example} && npm test` biçimini kullan; "
             "`verification.run` da aynı biçimde (`cd uygulama && node dist/main.js`) verilir.", example=example)
    )


# ---------------------------------------------------------------------------
# Mevcut durum ve taşıma planı (düz → apps)
# ---------------------------------------------------------------------------
_KEEP_ROOT = {".git", WORKSPACE_DIR}
_PRODUCT_NOISE = {"node_modules", "dist", "build", "coverage", ".next", "vendor", "target", "__pycache__", ".venv", "venv", ".pytest_cache"}


def _is_placeholder_dir(path: str) -> bool:
    """İçinde yalnızca `.gitkeep` (ya da hiçbir şey) bulunan klasör: yer tutucu; planda "boş" diye işaretlenir (yine de mimarın yapısını korumak için taşınır)."""
    if not os.path.isdir(path):
        return False
    for _cur, _dirs, files in os.walk(path):
        if any(f != ".gitkeep" for f in files):
            return False
    return True


def detect_app_role(project_dir: str, base: str = "") -> str:
    """Kökteki (ya da klasördeki) manifestten uygulamanın rolünü çıkarır: react/vite/next/vue → web, react-native/expo → mobile, aksi backend."""
    path = os.path.join(project_dir, base, "package.json") if base else os.path.join(project_dir, "package.json")
    try:
        import json
        with open(path, "r", encoding="utf-8") as fh:
            pkg = json.load(fh)
        deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
        if any(k in deps for k in ("react-native", "expo")):
            return "mobile"
        if any(k in deps for k in ("@nestjs/core", "express", "fastify", "koa", "hono")):
            return "backend"
        if any(k in deps for k in ("react", "vite", "next", "vue", "svelte", "@angular/core")):
            return "web"
    except Exception:
        pass
    return "backend"


def plan_migration(project_dir: str, layout: Dict[str, Any]) -> Dict[str, Any]:
    """Düz düzendeki projeyi `layout`a taşıma planı (hiçbir şeyi değiştirmez).
    Dönüş: {moves: [{from, to, kind}], skipped: [...], conflicts: [...], root_role}. `to` mevcutsa çakışmadır (taşınmaz)."""
    moves: List[Dict[str, str]] = []
    skipped: List[str] = []
    conflicts: List[str] = []
    root_role = detect_app_role(project_dir)
    docs_dir = layout["docs_dir"]
    try:
        names = sorted(os.listdir(project_dir))
    except OSError:
        names = []
    for name in names:
        low = name.lower()
        if name in _KEEP_ROOT or name in ROOT_FILES or name in ROOT_DIRS or _is_license(name):
            continue
        if low in (layout["apps_dir"].lower(), layout["devops_dir"].lower()):
            skipped.append(name)                  # hedef klasör zaten var (yarım kalmış göç ya da elle kurulmuş): içeriğine dokunulmaz
            continue
        if name in ("FS-docs", "docs"):
            if name == docs_dir:
                continue                          # belge klasörü zaten hedef adında
            kind, dest = "docs", docs_dir
        elif name == "reports":
            kind, dest = "reports", f"{docs_dir}/reports"
        elif low in DEVOPS_NAMES or low.startswith("dockerfile") or is_docker_file(low) or low in DEVOPS_DIRS:
            kind, dest = "devops", f"{layout['devops_dir']}/{name}"
        elif low in LEGACY_APP_DIRS and os.path.isdir(os.path.join(project_dir, name)):
            kind, dest = "app", app_folder(layout, LEGACY_APP_DIRS[low])
        else:
            kind, dest = "app", f"{app_folder(layout, root_role)}/{name}"
        if os.path.exists(os.path.join(project_dir, dest)):
            conflicts.append(tx("{name} → {dest}: hedef zaten var (birleştirilmez; elle taşıyın)", name=name, dest=dest))
            continue
        moves.append({"from": name, "to": dest, "kind": kind, "empty": _is_placeholder_dir(os.path.join(project_dir, name))})
    return {"moves": moves, "skipped": skipped, "conflicts": conflicts, "root_role": root_role, "layout": layout}


def path_rewrites(plan: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Taşıma planından yol öneki yeniden yazım tablosu (eski önek, yeni önek): kayıtlı Jira ipuçları, artefakt yolları ve belge bağlantıları için."""
    pairs: List[Tuple[str, str]] = []
    for m in plan.get("moves") or []:
        pairs.append((m["from"].replace("\\", "/"), m["to"].replace("\\", "/")))
    pairs.sort(key=lambda kv: len(kv[0]), reverse=True)
    return pairs


def rewrite_path(path: str, pairs: List[Tuple[str, str]]) -> str:
    """`src/main.ts` → `apps/backend/src/main.ts` (öneke göre; tam eşleşme ya da `önek/` ile başlayan yollar)."""
    p = _norm(path)
    for old, new in pairs:
        if p == old or p.startswith(old + "/"):
            return new + p[len(old):]
    return path


def prefix_verification(verification: Dict[str, Any], folder: str) -> Dict[str, Any]:
    """Kayıtlı doğrulama komutlarının başına `cd <klasör> && ` ekler (manifest klasöre taşındı); zaten `cd` ile başlayanlar ve adresler değişmez."""
    out: Dict[str, Any] = {}
    for key, val in (verification or {}).items():
        if key in ("health_url", "app_url") or not isinstance(val, str) or not val.strip() or val.strip().lower().startswith("cd "):
            out[key] = val
        else:
            out[key] = f"cd {folder} && {val.strip()}"
    return out


def describe(layout: Dict[str, Any], project_dir: str) -> Dict[str, Any]:
    """Ayar kartı için: düzen, kökteki girdilerin düzene uyumu ve (düz düzende) taşıma planı özeti."""
    info: Dict[str, Any] = {"layout": layout, "docs_root": layout["docs_dir"] if is_apps(layout) else None, "project_dir": project_dir}
    try:
        root_entries = sorted(n for n in os.listdir(project_dir) if n not in _KEEP_ROOT)
    except OSError:
        root_entries = []
    if is_apps(layout):
        allowed = {layout["apps_dir"], layout["devops_dir"], layout["docs_dir"].split("/")[0], *ROOT_FILES, *ROOT_DIRS}
        info["root_extra"] = [n for n in root_entries if n not in allowed and not _is_license(n)]
        info["compliant"] = not info["root_extra"]
    else:
        plan = plan_migration(project_dir, {**DEFAULT_LAYOUT, "roles": dict(DEFAULT_ROLES)})
        info["compliant"] = None
        info["migration_preview"] = {"moves": plan["moves"], "conflicts": plan["conflicts"], "root_role": plan["root_role"]}
    return info
