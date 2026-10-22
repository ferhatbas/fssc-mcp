"""
Sunucu tarafı doğrulama (verification) koşucusu.

Bir geliştirme adımı (iskelet, backlog görevi, düzeltme, QA testleri) dosyalarını yazdıktan sonra sunucu
projenin gerçek komutlarını koşar: sözdizimi denetimi, bağımlılık kurulumu, lint/build ve test süiti.
Sonuç nesnel bir karar verir (PASSED / FAILED / SKIPPED) ve çıktı özeti bir sonraki düzeltme adımının
bağlamına eklenir. Komutlar önce mimarın (adım 2) önerdiği `verification` ayarından, yoksa proje
dosyalarından (requirements.txt, package.json, composer.json, go.mod) çıkarsanır.

G1 (gerçek kanıt):
- Python bağımlılıkları FS-SC'nin yorumlayıcısına değil projenin kendi sanal ortamına kurulur
  (`.fs-workspace/venv`, `--system-site-packages` ile host'taki pytest görünür; ayar `python_isolation`: venv | host).
- pytest `-x` ile ilk hatada durmaz (`--maxfail=25`) ve junit XML üretir; başarısız testler ad ad düzeltme bağlamına gider.
- Her komutun TAM çıktısı `.fs-workspace/verify/<etiket>-<ad>.log` dosyasına yazılır; bellekteki kopya kırpılsa da
  düzeltme adımı dosyanın sonunu okur.
- Zaman aşımında yalnızca kabuk değil süreç ağacı öldürülür.

Güvenlik: komutlar kullanıcının makinesinde, proje klasöründe koşar. LLM'den gelen komutlar basit bir yasak listesinden
ve (varsayılan) izin listesinden geçer (`sandbox.command_policy`). `sandbox.mode=container` (G4): kurulum/lint/build/test
tek bir konteynerde koşar (proje /work; kurulum sonraki komutlara kalır; pip/npm önbelleği hacimde); Docker yoksa host'a düşülmez.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from .i18n import translate as tx
from .proc import hidden

VERIFY_TIMEOUT_S = float(os.environ.get("VERIFY_TIMEOUT_S", "300"))
INSTALL_TIMEOUT_S = float(os.environ.get("INSTALL_TIMEOUT_S", "600"))
OUTPUT_LIMIT = int(os.environ.get("VERIFY_OUTPUT_LIMIT", "24000"))

VERIFY_DIR = os.path.join(".fs-workspace", "verify")
VENV_DIR = os.path.join(".fs-workspace", "venv")
JUNIT_NAME = "junit.xml"
ISOLATION_MODES = ("venv", "host")

# Komut sırası: kurulum → sözdizimi → lint → build → test
COMMAND_ORDER = ("install", "syntax", "lint", "build", "test")
COMMAND_KEYS = ("install", "lint", "build", "test", "run", "health_url", "app_url", "client_run", "client_url")   # client_*: web arayüzü (E2E ekran görüntüleri bu adrese alınır)

# LLM kaynaklı komutlar için yasak kalıplar (basit, savunmacı)
_DENY = re.compile(
    r"(rm\s+-rf\s+[/~]|rmdir\s+/s|del\s+/[sq]|format\s+[a-z]:|shutdown|reboot|mkfs|dd\s+if=|:\(\)\s*\{|curl[^|]*\|\s*(ba)?sh|wget[^|]*\|\s*(ba)?sh|>\s*/dev/sd|reg\s+delete|powershell[^\n]*remove-item[^\n]*-recurse)",
    re.I,
)

_IGNORED_DIRS = {"node_modules", ".git", ".venv", "venv", "env", "__pycache__", "dist", "build", ".fs-workspace",
                 ".pytest_cache", ".mypy_cache", "coverage", ".next", "vendor", "target", ".idea", ".vscode"}


def is_command_safe(cmd: str) -> bool:
    cmd = str(cmd or "").strip()
    if not cmd or len(cmd) > 400 or "\n" in cmd:
        return False
    return not _DENY.search(cmd)


def sanitize_verification(raw: Any) -> Dict[str, str]:
    """LLM'den/ayarlardan gelen doğrulama sözlüğünü bilinen anahtarlara ve güvenli komutlara indirger."""
    out: Dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for key in COMMAND_KEYS:
        val = raw.get(key)
        if val is None:
            continue
        val = str(val).strip()
        if not val:
            continue
        if key in ("health_url", "app_url", "client_url"):
            if re.match(r"^https?://", val):
                out[key] = val[:300]
            continue
        if is_command_safe(val):
            out[key] = val
    return out


def _exists(project_dir: str, *parts: str) -> bool:
    return os.path.exists(os.path.join(project_dir, *parts))


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _quote(path: str) -> str:
    return f'"{path}"' if " " in path else path


# ---------------------------------------------------------------------------
# Python yalıtımı: proje başına sanal ortam (G1)
# ---------------------------------------------------------------------------
def venv_python(project_dir: str) -> str:
    """Projenin sanal ortam yorumlayıcısının yolu (var olmayabilir; `ensure_venv` oluşturur)."""
    base = os.path.join(os.path.abspath(project_dir), VENV_DIR)
    return os.path.join(base, "Scripts", "python.exe") if sys.platform.startswith("win") else os.path.join(base, "bin", "python")


def ensure_venv(project_dir: str, timeout_s: float = 180.0) -> Dict[str, Any]:
    """Sanal ortamı yoksa oluşturur (`--system-site-packages`: host'taki pytest/playwright görünür, proje bağımlılıkları host'a bulaşmaz).
    Dönüş: {ok, python, created, error}. Eşzamanlı çağrılarda ikinci çağrı var olanı kullanır."""
    py = venv_python(project_dir)
    if os.path.isfile(py):
        return {"ok": True, "python": py, "created": False, "error": None}
    target = os.path.join(os.path.abspath(project_dir), VENV_DIR)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        r = subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", target], capture_output=True, text=True, timeout=timeout_s, **hidden())
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "python": None, "created": False, "error": tx("venv oluşturulamadı: {err}", err=e)}
    if r.returncode != 0 or not os.path.isfile(py):
        return {"ok": False, "python": None, "created": False, "error": tx("venv oluşturulamadı (çıkış {code}): {out}", code=r.returncode, out=(r.stderr or r.stdout)[-600:])}
    return {"ok": True, "python": py, "created": True, "error": None}


def _py(project_dir: Optional[str] = None, isolation: str = "host") -> str:
    """Komutlarda kullanılacak Python: yalıtım `venv` ise projenin sanal ortamı, değilse FS-SC'yi çalıştıran yorumlayıcı."""
    if isolation == "venv" and project_dir:
        return _quote(venv_python(project_dir))
    exe = sys.executable or "python"
    return _quote(exe)


def _cd_prefix(sub: str) -> str:
    return f"cd {sub} && " if sub and sub != "." else ""


def _cd_back(sub: str) -> str:
    """`apps/backend` → `../..`: `cd apps/backend`'in tersi."""
    return "/".join([".."] * len([p for p in str(sub).replace("\\", "/").split("/") if p and p != "."]))


def _chain(parts: List[Any]) -> str:
    """Klasör başına komutları tek zincire birleştirir. `cd` kabukta kalıcı olduğundan, sonrasında başka komut gelen her alt klasör
    parçası köke döner (`cd apps/backend && npm test && cd ../.. && cd apps/web && npm test`); yoksa ikinci `cd apps/web` yanlış yerden çözülürdü."""
    out: List[str] = []
    for i, (sub, cmd) in enumerate(parts):
        seg = f"{_cd_prefix(sub)}{cmd}"
        if sub and sub != "." and i < len(parts) - 1:
            seg += f" && cd {_cd_back(sub)}"
        out.append(seg)
    return " && ".join(out)


APP_CONTAINER_DIRS = ("apps", "packages", "services")      # içindeki her klasör ayrı bir uygulamadır (apps/backend, apps/web ...)


def _manifest_dirs(project_dir: str, app_roots: Any = ()) -> List[str]:
    """Kök + bir seviye alt klasörler (frontend/, backend/ gibi) + uygulama kök klasörlerinin (apps/ ...) altındaki uygulamalar — manifest aranacak yerler."""
    dirs = ["."]
    containers = set(APP_CONTAINER_DIRS) | set(app_roots or ())
    try:
        for name in sorted(os.listdir(project_dir)):
            if name in _IGNORED_DIRS or name.startswith("."):
                continue
            if os.path.isdir(os.path.join(project_dir, name)):
                dirs.append(name)
                if name in containers:
                    inner = os.path.join(project_dir, name)
                    for child in sorted(os.listdir(inner)):
                        if child not in _IGNORED_DIRS and not child.startswith(".") and os.path.isdir(os.path.join(inner, child)):
                            dirs.append(f"{name}/{child}")
    except OSError:
        pass
    return dirs


def _has_tests(project_dir: str, sub: str) -> bool:
    base = os.path.join(project_dir, sub)
    if os.path.isdir(os.path.join(base, "tests")) or os.path.isdir(os.path.join(base, "test")):
        return True
    try:
        for name in os.listdir(base):
            if (name.startswith("test_") or name.endswith("_test.py")) and name.endswith(".py"):
                return True
    except OSError:
        pass
    return False


def junit_path(project_dir: str) -> str:
    return os.path.join(os.path.abspath(project_dir), VERIFY_DIR, JUNIT_NAME)


def pytest_command(project_dir: str, sub: str = ".", isolation: str = "host", cd: bool = True) -> str:
    """pytest: ilk hatada DURMAZ (düzeltme adımı tüm başarısız testleri görsün), junit XML üretir. `cd=False`: klasör önekini çağıran ekler."""
    py = _py(project_dir, isolation)
    return f"{_cd_prefix(sub) if cd else ''}{py} -m pytest -q --no-header -p no:cacheprovider --maxfail=25 --junitxml={_quote(junit_path(project_dir))}"


def _tsc_available(base: str) -> bool:
    bin_dir = os.path.join(base, "node_modules", ".bin")
    return os.path.isfile(os.path.join(base, "tsconfig.json")) and (os.path.isfile(os.path.join(bin_dir, "tsc")) or os.path.isfile(os.path.join(bin_dir, "tsc.cmd")))


def infer_commands(project_dir: str, isolation: str = "host", app_roots: Any = ()) -> Dict[str, str]:
    """Proje dosyalarından kurulum/lint/test/build komutlarını çıkarsar (yalnızca mevcut araçlar için). `app_roots`: apps düzeninin uygulama kök klasörü.
    Birden çok klasörde manifest varsa komutlar `cd <klasör> && ... && cd <geri> && cd <diğer klasör> && ...` zinciriyle birleşir."""
    cmds: Dict[str, List[Any]] = {"install": [], "lint": [], "build": [], "test": []}
    py = _py(project_dir, isolation)
    for sub in _manifest_dirs(project_dir, app_roots):
        base = os.path.join(project_dir, sub)
        has_py_manifest = os.path.isfile(os.path.join(base, "requirements.txt")) or os.path.isfile(os.path.join(base, "pyproject.toml"))
        if os.path.isfile(os.path.join(base, "requirements.txt")):
            cmds["install"].append((sub, f"{py} -m pip install -q -r requirements.txt"))
        if os.path.isfile(os.path.join(base, "pyproject.toml")) and not os.path.isfile(os.path.join(base, "requirements.txt")):
            cmds["install"].append((sub, f"{py} -m pip install -q -e ."))
        if has_py_manifest and shutil.which("ruff"):
            cmds["lint"].append((sub, "ruff check ."))
        if has_py_manifest and _has_tests(project_dir, sub):
            cmds["test"].append((sub, pytest_command(project_dir, sub, isolation, cd=False)))
        pkg = _read_json(os.path.join(base, "package.json")) if os.path.isfile(os.path.join(base, "package.json")) else None
        if pkg is not None and shutil.which("npm"):
            scripts = pkg.get("scripts") or {}
            cmds["install"].append((sub, "npm install --silent --no-audit --no-fund"))
            if scripts.get("lint"):
                cmds["lint"].append((sub, "npm run lint --silent"))
            if _tsc_available(base):
                cmds["lint"].append((sub, "npx tsc --noEmit"))
            if scripts.get("build"):
                cmds["build"].append((sub, "npm run build --silent"))
            test_script = str(scripts.get("test") or "")
            if test_script and "no test specified" not in test_script:
                cmds["test"].append((sub, "npm test --silent"))
        if os.path.isfile(os.path.join(base, "composer.json")) and shutil.which("composer"):
            cmds["install"].append((sub, "composer install -q --no-interaction"))
            if os.path.isfile(os.path.join(base, "phpunit.xml")) or os.path.isfile(os.path.join(base, "phpunit.xml.dist")):
                cmds["test"].append((sub, os.path.join("vendor", "bin", "phpunit")))
        if os.path.isfile(os.path.join(base, "go.mod")) and shutil.which("go"):
            cmds["build"].append((sub, "go build ./..."))
            cmds["test"].append((sub, "go test ./..."))
    return {k: _chain(v) for k, v in cmds.items() if v}


# Kökte çalışacak biçimde yazılmış (cd yok) araç komutları: yalnızca sunucunun çıkarsama bildiği araçlar düzene uyarlanır
_ROOT_BOUND_TOOLS = {"python", "py", "pip", "pytest", "ruff", "npm", "npx", "yarn", "pnpm", "node", "composer", "phpunit", "go"}
_HAS_CD = re.compile(r"(?i)(?:^|[;&|]\s*)(?:cd|pushd)\s|--prefix\b|--cwd\b|--directory\b|\s-C\s")


def _first_tool(cmd: str) -> str:
    """Komutun ilk sözcüğündeki aracın adı: `"C:/Py 312/python.exe" -m pytest` → `python`, `python3.12` → `python`."""
    m = re.match(r'^\s*(?:"([^"]+)"|(\S+))', str(cmd))
    exe = (m.group(1) or m.group(2)) if m else ""
    base = re.sub(r"\.(exe|cmd|bat)$", "", os.path.basename(exe.replace("\\", "/")).lower())
    return re.sub(r"[\d.]+$", "", base) if base.startswith(("python", "pip")) else base


PY_MANIFESTS = ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile")
ROOT_PROJECT_FILES = PY_MANIFESTS + ("package.json", "composer.json", "go.mod", "pom.xml", "build.gradle", "Cargo.toml", "Makefile", "phpunit.xml")


def root_has_project_files(project_dir: str) -> bool:
    """Depo kökünde komutların bağlanacağı bir manifest/Makefile ya da test klasörü var mı? (apps düzeninde yoktur.)"""
    try:
        if any(os.path.isfile(os.path.join(project_dir, n)) for n in ROOT_PROJECT_FILES):
            return True
        return _has_tests(project_dir, ".")
    except OSError:
        return False


def adapt_saved_commands(saved: Dict[str, str], inferred: Dict[str, str], project_dir: str) -> Dict[str, str]:
    """Kayıtlı (mimar / şablon / kullanıcı) komutlar kökte koşacak biçimdeyse ama depo kökünde hiç proje dosyası yoksa (apps/ düzeni:
    manifestler `apps/backend` gibi alt klasörlerde), komut kökte çalışamaz (`requirements.txt` bulunamaz, `import src` çözülmez).
    O anahtar için sunucunun proje dosyalarından çıkardığı `cd`'li komut kullanılır; karşılığı yoksa (manifest henüz yazılmamış) komut atlanır.
    `cd`/`--prefix` içeren ve araç olmayan (make, bash ...) komutlara dokunulmaz."""
    if not saved or root_has_project_files(project_dir):
        return dict(saved or {})
    out: Dict[str, str] = {}
    for key, cmd in saved.items():
        if key not in ("install", "lint", "build", "test") or _HAS_CD.search(cmd) or _first_tool(cmd) not in _ROOT_BOUND_TOOLS:
            out[key] = cmd
        elif inferred.get(key):
            out[key] = inferred[key]
    return out


def effective_commands(project_dir: str, isolation: str, saved: Any, app_roots: Any = ()) -> Dict[str, str]:
    """Çalışacak komutlar: proje dosyalarından çıkarsananlar + kayıtlı olanlar (kayıtlı kazanır; kökte çalışamayacak olanlar düzene uyarlanır)."""
    inferred = infer_commands(project_dir, isolation, app_roots)
    clean = {k: v for k, v in sanitize_verification(saved).items() if k in ("install", "lint", "build", "test")}
    return {**inferred, **adapt_saved_commands(clean, inferred, project_dir)}


def has_python_project(project_dir: str, files_written: Optional[List[str]] = None, max_depth: int = 4) -> bool:
    """Projede Python var mı? Yazılan bir `.py` dosyası ya da (en çok 4 seviye) bir Python manifesti / `.py` dosyası.
    Node/Go/PHP projesi için boş bir sanal ortam kurulmaz ve "yalıtım: venv" yazılmaz (saha notu C3)."""
    if any(str(f).lower().endswith(".py") for f in (files_written or [])):
        return True
    root = os.path.abspath(project_dir)
    seen = 0
    try:
        for cur, dirs, files in os.walk(root):
            depth = 0 if cur == root else cur[len(root):].count(os.sep)
            dirs[:] = [d for d in dirs if d not in _IGNORED_DIRS and not d.startswith(".")] if depth < max_depth else []
            for name in files:
                if name in PY_MANIFESTS or name.endswith(".py"):
                    return True
            seen += len(files)
            if seen > 5000:
                break
    except OSError:
        pass
    return False


def syntax_checks(project_dir: str, files: List[str], isolation: str = "host") -> List[Dict[str, Any]]:
    """Yazılan dosyalar için hızlı sözdizimi denetimleri (py_compile, node --check, php -l, json). TypeScript `tsc --noEmit` lint adımındadır."""
    results: List[Dict[str, Any]] = []
    py = _py(project_dir, isolation)
    for rel in files:
        path = os.path.join(project_dir, rel)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(rel)[1].lower()
        if ext == ".json":
            t0 = time.time()
            try:
                with open(path, "r", encoding="utf-8") as f:
                    json.load(f)
                results.append({"name": f"json:{rel}", "cmd": "json.load", "exit_code": 0, "duration_ms": int((time.time() - t0) * 1000), "output": ""})
            except Exception as e:
                results.append({"name": f"json:{rel}", "cmd": "json.load", "exit_code": 1, "duration_ms": int((time.time() - t0) * 1000), "output": str(e)[:OUTPUT_LIMIT]})
        elif ext == ".py":
            results.append({"name": f"py_compile:{rel}", "cmd": f"{py} -m py_compile \"{rel}\"", "pending": True})
        elif ext in (".js", ".mjs", ".cjs") and shutil.which("node"):
            results.append({"name": f"node --check:{rel}", "cmd": f"node --check \"{rel}\"", "pending": True})
        elif ext == ".php" and shutil.which("php"):
            results.append({"name": f"php -l:{rel}", "cmd": f"php -l \"{rel}\"", "pending": True})
    return results


def subprocess_env(project_dir: Optional[str] = None, isolation: str = "host") -> Dict[str, str]:
    """
    Alt süreç ortamı. Yalıtım `venv` ise projenin sanal ortamı PATH'in başına gelir (`python`/`pip`/`pytest` oraya çözülür);
    değilse FS-SC'yi çalıştıran yorumlayıcının klasörü (makinede birden çok Python varsa belirsizlik kalkar).
    """
    env = {**os.environ, "CI": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "NO_COLOR": "1", "FORCE_COLOR": "0"}
    if isolation == "venv" and project_dir and os.path.isfile(venv_python(project_dir)):
        venv_root = os.path.join(os.path.abspath(project_dir), VENV_DIR)
        parts = [os.path.dirname(venv_python(project_dir))]
        env["VIRTUAL_ENV"] = venv_root
        env.pop("PYTHONHOME", None)
    else:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        scripts = os.path.join(exe_dir, "Scripts" if sys.platform.startswith("win") else "bin")
        parts = [p for p in (exe_dir, scripts) if os.path.isdir(p)]
    env["PATH"] = os.pathsep.join(parts + [env.get("PATH", "")])
    return env


def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Zaman aşımında süreç AĞACINI öldürür (yalnızca kabuk değil: pytest/npm/node alt süreçleri de)."""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=30, **hidden())
        else:
            import signal
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


_COMMAND_ENV: contextvars.ContextVar[Optional[Dict[str, str]]] = contextvars.ContextVar("fssc_verify_env", default=None)


async def run_command(cmd: str, cwd: str, timeout_s: float, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Tek bir kabuk komutunu koşar; çıktıyı kırpar; zaman aşımında süreç ağacını öldürür.
    Ortam: açıkça verilen `env`, yoksa `run_verification`'ın bağlam değişkeni (yalıtım), yoksa host ortamı."""
    t0 = time.time()
    env = env or _COMMAND_ENV.get() or subprocess_env()
    kwargs: Dict[str, Any] = hidden()                  # Windows: pencere açma (komutun alt süreçleri gizli konsolu devralır)
    if not sys.platform.startswith("win"):
        kwargs["start_new_session"] = True
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=cwd, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, **kwargs,
        )
    except Exception as e:  # noqa: BLE001
        return {"cmd": cmd, "exit_code": 127, "duration_ms": 0, "output": tx("Komut başlatılamadı: {err}", err=e), "timed_out": False}
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        timed_out = False
    except asyncio.TimeoutError:
        timed_out = True
        _kill_tree(proc)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except Exception:
            out = b""
    text = (out or b"").decode("utf-8", errors="replace")
    full_len = len(text)
    if full_len > OUTPUT_LIMIT:
        text = text[:OUTPUT_LIMIT // 3] + tx("\n... (kırpıldı) ...\n") + text[-(OUTPUT_LIMIT - OUTPUT_LIMIT // 3):]
    code = -1 if timed_out else (proc.returncode if proc.returncode is not None else -1)
    res = {"cmd": cmd, "exit_code": code, "duration_ms": int((time.time() - t0) * 1000), "output": text.strip(), "timed_out": timed_out}
    if timed_out:
        res["output"] = (res["output"] + tx("\n[FS-SC] Zaman aşımı ({sec} sn): süreç ağacı öldürüldü.", sec=int(timeout_s))).strip()
    return res


def _classify(name: str, res: Dict[str, Any]) -> str:
    code = res.get("exit_code")
    if code == 0:
        return "PASSED"
    # pytest 5 = hiç test toplanmadı → başarısızlık değil
    if name == "test" and code == 5:
        return "SKIPPED"
    return "FAILED"


# ---------------------------------------------------------------------------
# junit XML (pytest --junitxml): test bazında sonuç → düzeltme bağlamı ve AC kanıtı
# ---------------------------------------------------------------------------
def junit_results(path: str) -> Optional[Dict[str, Any]]:
    """{total, passed, failed, errors, skipped, cases: [{id, file, name, status, message}]}; dosya yoksa None."""
    if not path or not os.path.isfile(path):
        return None
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(path).getroot()
    except Exception:
        return None
    cases: List[Dict[str, Any]] = []
    for tc in root.iter("testcase"):
        classname = tc.get("classname") or ""
        name = tc.get("name") or ""
        file_attr = tc.get("file") or ""
        rel = file_attr.replace("\\", "/") if file_attr else (classname.replace(".", "/") + ".py" if classname else "")
        status, message = "passed", ""
        for child in tc:
            tag = child.tag.lower()
            if tag in ("failure", "error", "skipped"):
                status = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                message = (child.get("message") or (child.text or "").strip())[:400]
                break
        cases.append({"id": f"{rel}::{name}" if rel else name, "file": rel, "name": name, "status": status, "message": message})
    counts = {"total": len(cases), "passed": sum(1 for c in cases if c["status"] == "passed"), "failed": sum(1 for c in cases if c["status"] == "failed"),
              "errors": sum(1 for c in cases if c["status"] == "error"), "skipped": sum(1 for c in cases if c["status"] == "skipped")}
    return {**counts, "cases": cases}


def _write_log(log_dir: Optional[str], tag: str, name: str, res: Dict[str, Any]) -> Optional[str]:
    """Komutun TAM çıktısını dosyaya yazar; dönüş: proje köküne göreli yol (ya da None)."""
    if not log_dir:
        return None
    try:
        os.makedirs(log_dir, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{tag}-{name}")[:120] or "verify"
        path = os.path.join(log_dir, f"{safe}.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"$ {res.get('cmd')}\n# exit={res.get('exit_code')} duration_ms={res.get('duration_ms')} timed_out={res.get('timed_out')}\n\n")
            f.write(str(res.get("output_full") if res.get("output_full") is not None else res.get("output") or ""))
        return path
    except Exception:
        return None


async def run_verification(
    project_dir: str,
    commands: Dict[str, str],
    files_written: Optional[List[str]] = None,
    do_install: bool = True,
    sandbox: Optional[Dict[str, Any]] = None,
    command_filter=None,
    isolation: str = "host",
    log_dir: Optional[str] = None,
    tag: str = "",
    changed_only: bool = False,
    light: bool = False,
) -> Dict[str, Any]:
    """Doğrulama paketini koşar (komut ortamı bağlam değişkeniyle taşınır; `run_command` imzası eski çağıranlar için değişmez).
    `changed_only`: artımlı kip — jest yalnızca değişen dosyalarla ilgili testleri koşar, yalnızca test eklendiyse build atlanır.
    `light`: hafif kip (artımlı kipte) — build de atlanır; build her 5. adımdaki tam doğrulamada ve sprint kapanışında koşar."""
    token = _COMMAND_ENV.set(None)
    try:
        out = await _run_verification_impl(project_dir, commands, files_written, do_install, sandbox, command_filter, isolation, log_dir, tag, changed_only, light)
        out.setdefault("scope", "full")
        return out
    finally:
        _COMMAND_ENV.reset(token)


async def _run_verification_impl(
    project_dir: str,
    commands: Dict[str, str],
    files_written: Optional[List[str]] = None,
    do_install: bool = True,
    sandbox: Optional[Dict[str, Any]] = None,
    command_filter=None,
    isolation: str = "host",
    log_dir: Optional[str] = None,
    tag: str = "",
    changed_only: bool = False,
    light: bool = False,
) -> Dict[str, Any]:
    """
    Doğrulama paketini koşar. Dönüş:
    {status: PASSED|FAILED|SKIPPED, results: [{name, cmd, exit_code, duration_ms, output, status, log_file?}], summary: str,
     failed_step: name|None, ran_install: bool, tests: {...}|None, failed_tests: [...], isolation: str}
    `isolation` sonuçta host | venv | container (konteyner kipinde venv kurulmaz; yalıtım konteynerin kendisidir).
    """
    results: List[Dict[str, Any]] = []
    isolation = isolation if isolation in ISOLATION_MODES else "host"
    container_on = bool(sandbox and sandbox.get("mode") == "container")
    label = "container" if container_on else isolation
    tag = tag or time.strftime("%Y%m%d-%H%M%S")
    if log_dir is None:
        log_dir = os.path.join(os.path.abspath(project_dir), VERIFY_DIR)

    def _fail(step: str) -> Dict[str, Any]:
        return {"status": "FAILED", "results": results, "failed_step": step, "ran_install": False, "isolation": label,
                "summary": _summary("FAILED", results, step), "tests": None, "failed_tests": []}

    # 0) Python yalıtımı: sanal ortam (bir kez oluşturulur) — konteyner kipinde gereksiz
    host_isolation = "host" if container_on else isolation
    if host_isolation == "venv" and not await asyncio.to_thread(has_python_project, project_dir, files_written):
        host_isolation = label = "none"            # Python yok (Node/Go/PHP projesi): boş sanal ortam kurulmaz
    if host_isolation == "venv":
        venv = await asyncio.to_thread(ensure_venv, project_dir)
        if not venv["ok"]:
            results.append({"name": "venv", "cmd": f"{sys.executable} -m venv --system-site-packages {VENV_DIR}", "exit_code": 1, "duration_ms": 0,
                            "output": venv["error"], "status": "FAILED"})
            return _fail("venv")
    _COMMAND_ENV.set(subprocess_env(project_dir, host_isolation))

    # 1) Sözdizimi denetimleri (hızlı, her zaman; host'ta — yalnızca derleme, kod çalıştırmaz)
    failed: Optional[str] = None
    for chk in syntax_checks(project_dir, files_written or [], host_isolation):
        if chk.pop("pending", False):
            res = await run_command(chk["cmd"], project_dir, 60.0)
            chk.update(res)
        chk["status"] = "PASSED" if chk.get("exit_code") == 0 else "FAILED"
        results.append(chk)
        if chk["status"] == "FAILED" and failed is None:
            failed = chk["name"]
    if failed:
        return _fail(failed)

    # 2) Komutlar — PASSED yalnızca gerçek bir lint/build/test komutu geçtiyse; sadece sözdizimi/kurulum → SKIPPED
    junit_file = junit_path(project_dir)
    container_started = False
    if container_on:
        from . import guard as G
        if not G.docker_available():
            results.append({"name": "container", "cmd": "docker info", "exit_code": 126, "duration_ms": 0, "timed_out": False, "status": "FAILED",
                            "output": tx("sandbox.mode=container ama Docker kullanılamıyor; komutlar host'ta KOŞTURULMADI.")})
            return _fail("container")
        await run_command(G.container_stop_cmd(project_dir), project_dir, 60.0)          # bayat oturum varsa kapat
        start = await run_command(G.container_start_cmd(project_dir, (sandbox or {}).get("image", "")), project_dir, 180.0)
        if start.get("exit_code") != 0:
            results.append({**start, "name": "container", "status": "FAILED",
                            "output": tx("Konteyner başlatılamadı: ") + str(start.get("output"))[-1200:]})
            return _fail("container")
        container_started = True
    try:
        return await _run_commands(project_dir, commands, do_install, command_filter, container_on, junit_file, log_dir, tag, results, label,
                                   files_written if changed_only else None, light)
    finally:
        if container_started:
            from . import guard as G
            await run_command(G.container_stop_cmd(project_dir), project_dir, 60.0)


_PYTEST_SEGMENT = re.compile(r"(\bpytest\b[^&|;\n]*)")


_NPM_TEST = re.compile(r"cd\s+(?P<sub>[^\s&]+)\s*&&\s*npm test --silent")
_JS_FILE = re.compile(r"\.[cm]?[jt]sx?$", re.IGNORECASE)
_TEST_ONLY = re.compile(r"(\.(spec|test)\.[cm]?[jt]sx?$|(^|/)test_[^/]*\.py$|_test\.py$|_test\.go$|(^|/)__tests__/|(^|/)tests?/)", re.IGNORECASE)


def only_test_files(files: List[str]) -> bool:
    """Teslimdeki tüm dosyalar test dosyası mı? (yalnızca test eklendiyse build yeniden koşmaz)"""
    return bool(files) and all(_TEST_ONLY.search(str(f).replace("\\", "/")) for f in files)


_SPEC_FILE = re.compile(r"\.(spec|test)\.[cm]?[jt]sx?$", re.IGNORECASE)
_GENERIC_STEMS = {"index", "main", "app", "module", "setup", "types", "type", "utils", "util", "common", "config", "dto", "entity"}


def _all_specs(base: str) -> List[str]:
    """Uygulama klasöründeki tüm spec dosyaları (klasöre göre göreli, `/` ayraçlı)."""
    out: List[str] = []
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d not in _IGNORED_DIRS and not d.startswith(".")]
        for fn in fns:
            if _SPEC_FILE.search(fn):
                out.append(os.path.relpath(os.path.join(dp, fn), base).replace("\\", "/"))
    return sorted(out)


def select_specs(specs: List[str], changed: List[str]) -> List[str]:
    """Değişen dosyalar için "gerekli testler": değişen spec'in kendisi; değişen kaynak için aynı klasördeki spec'ler ve adını (kök sözcüğünü) anan spec'ler.
    Geçişli ilişki (`--findRelatedTests`) bilerek kullanılmaz: main/app.module/controller gibi merkez dosyalar neredeyse tüm paketi çekiyordu (adım #95: 229 sn)."""
    picked: set = set()
    spec_set = set(specs)
    for c in changed:
        if _SPEC_FILE.search(c):
            if c in spec_set:
                picked.add(c)
            continue
        d = os.path.dirname(c)
        stem = re.split(r"[.\-_]", os.path.basename(c))[0].lower()
        for sp in specs:
            if os.path.dirname(sp) == d or (len(stem) >= 4 and stem not in _GENERIC_STEMS and stem in os.path.basename(sp).lower()):
                picked.add(sp)
    return sorted(picked)


def is_noop_test(cmd: str) -> bool:
    """Komut yalnızca "değişiklik yok, testi atla" yer tutucularından (`cd x && node -e "process.exit(0)"`) oluşuyorsa True: gerçek test koşmamıştır."""
    parts = [p.strip() for p in re.split(r"&&", str(cmd or "")) if p.strip()]
    return bool(parts) and all(p.startswith("cd ") or p == 'node -e "process.exit(0)"' for p in parts) and any(p.startswith("node -e") for p in parts)


def scoped_test_command(cmd: str, written: List[str], project_dir: str) -> Optional[str]:
    """Artımlı doğrulama: jest komutunu yalnızca değişen dosyalarla ilgili spec'lere daraltır (`--runTestsByPath`; bkz. `select_specs`).
    Daraltılamıyorsa (jest dışı, `cd` yok, eşleşen spec yok) None döner ve tam paket koşar. Değişikliği olmayan uygulamanın testi atlanır."""
    if "npm test --silent" not in cmd:
        return None
    changed = [str(w).replace("\\", "/") for w in written]
    fell_back = False

    def rep(m: "re.Match[str]") -> str:
        nonlocal fell_back
        sub = m.group("sub").replace("\\", "/").rstrip("/")
        files = [c[len(sub) + 1:] for c in changed if c.startswith(sub + "/") and _JS_FILE.search(c)]
        if not files:
            return f'cd {sub} && node -e "process.exit(0)"'            # bu uygulamada değişiklik yok: testi atlanır
        picked = select_specs(_all_specs(os.path.join(project_dir, *sub.split("/"))), files)
        if not picked:
            fell_back = True                                          # eşleşen spec yok: bu uygulama için tam paket
            return m.group(0)
        return f"cd {sub} && npm test --silent -- --runTestsByPath " + " ".join(_quote(f) for f in picked)
    out = _NPM_TEST.sub(rep, cmd)
    return out if out != cmd and not fell_back else None


def with_junit(cmd: str, junit_file: str) -> str:
    """`pytest` çağrısına `--junitxml` ekler (zaten varsa dokunmaz): bayat olmayan junit, test/AC kanıtının ve test case sonuçlarının kaynağıdır.
    Zincirde (`cd x && python -m pytest -q && ...`) yalnızca pytest parçasına eklenir."""
    if "--junitxml" in cmd or not re.search(r"\bpytest\b", cmd):
        return cmd
    def add(m):
        core = m.group(1).rstrip()
        return f"{core} --junitxml={_quote(junit_file)}{m.group(1)[len(core):]}"      # sondaki boşluk (`&&` öncesi) korunur
    return _PYTEST_SEGMENT.sub(add, cmd, count=1)


INSTALL_CACHE_REL = ".fs-workspace/verify-install.json"
_MANIFESTS = ("package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "requirements.txt", "pyproject.toml", "poetry.lock",
              "composer.json", "composer.lock")


def planned_commands(project_dir: str, commands: Dict[str, str], do_install: bool, changed_only: bool, written: List[str], light: bool) -> Dict[str, str]:
    """Bu doğrulamada GERÇEKTEN koşacak komutlar (panoya gösterilen plan): atlanan kurulum (önbellek) ve build yazılmaz, artımlı test daraltılmış hâliyle yazılır."""
    out: Dict[str, str] = {}
    for name in COMMAND_ORDER:
        cmd = (commands or {}).get(name)
        if name == "syntax" or not cmd:
            continue
        if name == "install":
            if not do_install:
                continue
            sig = install_signature(project_dir, cmd)
            if sig and _install_cache(project_dir).get(cmd, {}).get("sig") == sig:
                continue
        if name == "build" and changed_only and (light or only_test_files(written)):
            continue
        if name == "test" and changed_only:
            cmd = scoped_test_command(cmd, written, project_dir) or cmd
        out[name] = cmd
    return out


def install_signature(project_dir: str, cmd: str) -> Optional[str]:
    """Kurulum komutunun çalışacağı klasörlerdeki bağımlılık bildirimlerinin özeti. Bağımlılık klasörü (node_modules/vendor) yoksa ya da bildirim yoksa None:
    kurulum atlanamaz. Aynı özet = bağımlılıklar değişmedi, her adımda yeniden kurmaya gerek yok."""
    import hashlib
    dirs = [d for d in re.findall(r"cd\s+([^\s&;|]+)\s*&&", cmd) if not d.startswith("..") and not os.path.isabs(d)] or ["."]
    h = hashlib.sha1()
    found = False
    for d in dirs:
        base = os.path.join(os.path.abspath(project_dir), *d.replace("\\", "/").split("/"))
        for m in _MANIFESTS:
            p = os.path.join(base, m)
            if os.path.isfile(p):
                found = True
                h.update(f"{d}/{m}".encode())
                with open(p, "rb") as f:
                    h.update(f.read())
        if os.path.isfile(os.path.join(base, "package.json")) and not os.path.isdir(os.path.join(base, "node_modules")):
            return None
        if os.path.isfile(os.path.join(base, "composer.json")) and not os.path.isdir(os.path.join(base, "vendor")):
            return None
    return h.hexdigest() if found else None


def _install_cache(project_dir: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(project_dir, *INSTALL_CACHE_REL.split("/")), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _install_cache_store(project_dir: str, cmd: str, sig: str) -> None:
    data = _install_cache(project_dir)
    data[cmd] = {"sig": sig}
    path = os.path.join(project_dir, *INSTALL_CACHE_REL.split("/"))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


async def _run_commands(project_dir: str, commands: Dict[str, str], do_install: bool, command_filter, container_on: bool, junit_file: str,
                        log_dir: Optional[str], tag: str, results: List[Dict[str, Any]], label: str,
                        incremental_files: Optional[List[str]] = None, light: bool = False) -> Dict[str, Any]:
    status = "SKIPPED"
    scope = "full"
    test_only = incremental_files is not None and only_test_files(incremental_files)
    failed: Optional[str] = None
    ran_install = False
    tests: Optional[Dict[str, Any]] = None
    failed_tests: List[Dict[str, Any]] = []
    for name in COMMAND_ORDER:
        if name == "syntax":
            continue
        cmd = (commands or {}).get(name)
        if not cmd:
            continue
        if name == "install":
            if not do_install:
                continue
            sig = None if container_on else install_signature(project_dir, cmd)
            if sig and _install_cache(project_dir).get(cmd, {}).get("sig") == sig:
                results.append({"name": "install", "cmd": cmd, "exit_code": 0, "duration_ms": 0, "status": "PASSED", "cached": True,
                                "output": tx("Bağımlılık bildirimi değişmedi; kurulum atlandı (önbellek).")})
                continue
            ran_install = True
        if command_filter is not None:
            ok, bad = command_filter(cmd)
            if not ok:
                # İzin listesi dışı komut koşmaz (§12 madde 1): sonuç SKIPPED, ayrıca bir soru açılır
                results.append({"name": name, "cmd": cmd, "exit_code": None, "duration_ms": 0, "status": "SKIPPED",
                                "output": tx("İzin listesi dışı komut parçası: ") + "; ".join(bad)[:300]})
                continue
        if incremental_files is not None and name == "build" and (test_only or light):
            continue                                   # yalnızca test eklendi ya da hafif kip: build tam doğrulamaya (her 5. adım, faz, sprint sonu) kalır
        full_cmd = cmd
        if incremental_files is not None and name == "test":
            narrowed = scoped_test_command(cmd, incremental_files, project_dir)
            if narrowed:
                cmd, scope = narrowed, "incremental"
        if name == "test" and not container_on:
            cmd = with_junit(cmd, junit_file)         # mimar/şablonun yazdığı çıplak pytest de junit üretsin (case ve kriter kanıtı junit'ten gelir)
        shown_cmd = cmd
        noop_test = name == "test" and is_noop_test(cmd)
        if container_on:
            # G4: komut, proje içindeki bir kabuk betiğiyle konteynerde koşar (kurulum sonraki komutlara kalır; alıntılama derdi yok)
            from . import guard as G
            inner = G.containerize_command(cmd, project_dir)
            fname = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{tag}-{name}")[:100] + ".sh"
            script_abs = os.path.join(os.path.abspath(project_dir), VERIFY_DIR, fname)
            os.makedirs(os.path.dirname(script_abs), exist_ok=True)
            with open(script_abs, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("#!/bin/sh\nset -e\n" + inner + "\n")
            shown_cmd = f"[container] {inner}"
            cmd = G.container_exec_cmd(project_dir, (VERIFY_DIR + "/" + fname).replace("\\", "/"))
        if name == "test" and os.path.isfile(junit_file):
            try:
                os.remove(junit_file)      # bayat sonuç yeni koşuya karışmasın
            except OSError:
                pass
        res = await run_command(cmd, project_dir, INSTALL_TIMEOUT_S if name == "install" else VERIFY_TIMEOUT_S)
        if name == "test" and scope == "incremental" and res.get("exit_code") not in (0, None) and "No tests found" in str(res.get("output") or ""):
            # değişen dosyayla ilişkili test bulunamadı: tam paket koşar (testsiz teslim "geçti" sayılmasın)
            cmd, scope = full_cmd, "full"
            if not container_on:
                cmd = with_junit(cmd, junit_file)
            res = await run_command(cmd, project_dir, VERIFY_TIMEOUT_S)
        res["name"] = name
        res["cmd"] = shown_cmd
        res["status"] = _classify(name, res)
        if noop_test:
            res["noop"] = True                         # hiçbir test koşmadı (değişen kodda test gerektiren dosya yok): "test geçti" sayılmaz
        log_file = _write_log(log_dir, tag, name, res)
        if log_file:
            res["log_file"] = os.path.relpath(log_file, project_dir).replace("\\", "/")
        if name == "test":
            tests = junit_results(junit_file)
            if tests:
                failed_tests = [{"id": c["id"], "message": c["message"]} for c in tests["cases"] if c["status"] in ("failed", "error")][:50]
                res["tests"] = {k: tests[k] for k in ("total", "passed", "failed", "errors", "skipped")}
        results.append(res)
        if name == "install" and res["status"] == "PASSED" and not container_on:
            new_sig = install_signature(project_dir, full_cmd)
            if new_sig:
                _install_cache_store(project_dir, full_cmd, new_sig)
        if res["status"] == "FAILED":
            failed = name
            status = "FAILED"
            break
        if res["status"] == "PASSED" and name != "install":
            status = "PASSED"
    return {"status": status, "results": results, "failed_step": failed, "ran_install": ran_install, "isolation": label, "scope": scope,
            "summary": _summary(status, results, failed), "tests": ({k: tests[k] for k in ("total", "passed", "failed", "errors", "skipped")} if tests else None),
            "failed_tests": failed_tests}



def _summary(status: str, results: List[Dict[str, Any]], failed: Optional[str]) -> str:
    names = []
    for r in results:
        mark = "✓" if r.get("status") == "PASSED" else ("−" if r.get("status") == "SKIPPED" else "✗")
        label = f"{r.get('name')}:{tx('−(test gerekmedi)') if r.get('noop') else mark}"
        t = r.get("tests")
        if r.get("name") == "test" and isinstance(t, dict):
            label += tx(" ({n} geçti", n=t.get('passed', 0)) + (tx(", {n} kaldı", n=t.get('failed', 0) + t.get('errors', 0)) if (t.get("failed", 0) + t.get("errors", 0)) else "") + ")"
        names.append(label)
    head = tx("Doğrulama {status}", status=status) + (tx(" ({step} başarısız)", step=failed) if failed else (tx(" (test/build komutu yok; yalnızca sözdizimi)") if status == "SKIPPED" and results else ""))
    return head + (": " + ", ".join(names) if names else tx(": koşacak komut yok"))


def _log_tail(project_dir: Optional[str], rel: Optional[str], limit: int) -> str:
    if not project_dir or not rel:
        return ""
    try:
        with open(os.path.join(project_dir, rel), "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
        return data[-limit:]
    except OSError:
        return ""


def failure_excerpt(verification: Optional[Dict[str, Any]], limit: int = 3500, project_dir: Optional[str] = None) -> str:
    """Düzeltme adımının bağlamı için: başarısız testlerin listesi (junit) + başarısız komutun çıktısının SONU (özet satırları orada)."""
    if not verification:
        return ""
    parts: List[str] = []
    failed_tests = verification.get("failed_tests") or []
    if failed_tests:
        parts.append(tx("Başarısız testler (junit):\n") + "\n".join(f"- {t.get('id')}: {str(t.get('message') or '')[:200]}" for t in failed_tests[:15]))
    for r in verification.get("results", []):
        if r.get("status") == "FAILED":
            out = _log_tail(project_dir, r.get("log_file"), limit) or str(r.get("output") or "").strip()
            if len(out) > limit:
                out = out[:limit // 3] + tx("\n... (kırpıldı) ...\n") + out[-(limit - limit // 3):]
            parts.append(tx("Komut: `{cmd}` (çıkış kodu {code}{timeout})", cmd=r.get('cmd'), code=r.get('exit_code'), timeout=tx(", zaman aşımı") if r.get('timed_out') else "")
                         + (tx(" — tam günlük: {log}", log=r.get('log_file')) if r.get("log_file") else "") + f"\n```\n{out}\n```")
            break
    return "\n\n".join(parts)


def public_summary(verification: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """MCP istemcisine/panoya dönecek kısa özet (büyük çıktılar kırpılır; tam günlük dosya yolunda)."""
    if not verification:
        return None
    return {
        "status": verification.get("status"),
        "summary": verification.get("summary", ""),
        "failed_step": verification.get("failed_step"),
        "isolation": verification.get("isolation"),
        "scope": verification.get("scope", "full"),
        "tests": verification.get("tests"),
        "failed_tests": list(verification.get("failed_tests") or [])[:25],
        "results": [
            {"name": r.get("name"), "status": r.get("status"), "exit_code": r.get("exit_code"), "duration_ms": r.get("duration_ms"),
             "cmd": r.get("cmd"), "output": (str(r.get("output") or "")[:1500]), "log_file": r.get("log_file"), "tests": r.get("tests"), "noop": bool(r.get("noop"))}
            for r in verification.get("results", [])
        ],
    }
