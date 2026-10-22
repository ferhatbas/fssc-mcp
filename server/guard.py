"""Korkuluklar (F6, belge §12): komut izin listesi, komut yalıtımı (konteyner), sır taraması, hata imzası, bitmişlik tanımı (DoD).

Hepsi sunucunun işidir; hiçbir ajan bunları kendi çıktısıyla gevşetemez (§12 madde 2: `.fs-workspace/**` ve `.git/**` altına yazamaz).
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from .i18n import translate as tx
from .proc import hidden

# ---------------------------------------------------------------------------
# Ayarlar: sandbox.mode (host | container), sandbox.command_policy (denylist | allowlist), sandbox.allowlist (yönetici onaylı ek önekler)
# ---------------------------------------------------------------------------
# G4: izin listesi VARSAYILAN politikadır (bilinmeyen araç koşmaz, soru olur); yasak listesi yalnızca geriye uyum için seçilebilir
DEFAULT_SANDBOX: Dict[str, Any] = {"mode": "host", "command_policy": "allowlist", "allowlist": [], "image": ""}
MODES = ("host", "container")
POLICIES = ("denylist", "allowlist")

# Bilinen güvenli komut önekleri (izin listesi politikasında yönetici ek öneklerle genişletir)
DEFAULT_ALLOW_PREFIXES = (
    # Python
    "python -m pytest", "python -m pip install", "python -m uvicorn", "python -m py_compile", "python -m unittest", "python manage.py test",
    "python ", "python3 ", "py ", "pip install", "pytest", "uvicorn", "ruff ", "mypy ", "black ", "flake8 ", "coverage ",
    # Node / web
    "npm install", "npm ci", "npm test", "npm run", "npx playwright", "npx tsc", "npx vite", "npx jest", "npx vitest", "npx eslint", "npx prettier",
    "node ", "yarn ", "pnpm ", "tsc", "jest", "vitest", "eslint", "prettier",
    # PHP / Go / Rust / JVM / .NET
    "composer install", "vendor/bin/phpunit", "vendor\\bin\\phpunit", "php ", "go build", "go test", "go run", "go vet", "go mod", "cargo ", "rustc ",
    "mvn ", "gradle ", "dotnet build", "dotnet test", "dotnet run",
    # Konteyner ve zararsızlar
    "docker build", "docker compose", "docker-compose", "echo ",
)
# Not: izin listesi "hangi araç koşabilir" sorusunu cevaplar; aracın içindeki kod (python -c …) için gerçek yalıtım konteyner kipidir.


def sanitize_sandbox(raw: Any, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    base = fallback if isinstance(fallback, dict) else {}
    out = {**DEFAULT_SANDBOX, **{k: v for k, v in base.items() if k in DEFAULT_SANDBOX}}
    if raw.get("mode") in MODES:
        out["mode"] = raw["mode"]
    if raw.get("command_policy") in POLICIES:
        out["command_policy"] = raw["command_policy"]
    if isinstance(raw.get("allowlist"), list):
        out["allowlist"] = [str(x).strip()[:120] for x in raw["allowlist"] if str(x).strip()][:60]
    if "image" in raw:
        out["image"] = str(raw["image"] or "").strip()[:120]
    return out


def sandbox(hub) -> Dict[str, Any]:
    return sanitize_sandbox((hub.get_settings() or {}).get("sandbox"))


def _split_chain(cmd: str) -> List[str]:
    """`a && b ; c || d | e` zincirini TIRNAK DIŞINDAKİ ayraçlarda böler (G4): `python -c "x; y"` tek komuttur; borunun sağ tarafı da komuttur."""
    parts: List[str] = []
    buf: List[str] = []
    quote: Optional[str] = None
    s = str(cmd or "")
    i = 0
    while i < len(s):
        ch = s[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif s.startswith("&&", i) or s.startswith("||", i):
            parts.append("".join(buf))
            buf = []
            i += 2
            continue
        elif ch in (";", "|", "\n"):
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _strip_cd(cmd: str) -> List[str]:
    """`cd frontend && npm test && …` gibi zincirleri komut parçalarına ayırır (cd önekleri komut sayılmaz)."""
    return [p for p in _split_chain(cmd) if not re.match(r"^cd\s+[\w./\\-]+$", p)]


def _norm(part: str) -> str:
    """Yürütülebilir dosyanın tam yolunu (tırnaklı ya da değil) adına indirger: `"C:\\Py 312\\python.exe" -m pytest` → `python -m pytest`."""
    m = re.match(r'^("([^"]+)"|\S+)\s*(.*)$', part.strip())
    if not m:
        return part.strip()
    exe, rest = (m.group(2) or m.group(1)), m.group(3)
    base = os.path.basename(exe.replace("\\", "/")).lower()
    base = re.sub(r"\.(exe|cmd|bat)$", "", base)
    if base.startswith("python"):
        base = "python"
    return re.sub(r"\s+", " ", f"{base} {rest}").strip()


def command_allowed(hub, cmd: str) -> Tuple[bool, List[str]]:
    """İzin listesi politikasında komutun her parçası bilinen ya da yönetici onaylı bir önekle başlamalı. Dönüş: (izinli_mi, izin_dışı_parçalar)."""
    sb = sandbox(hub)
    if sb["command_policy"] != "allowlist":
        return True, []
    prefixes = [p.lower() for p in (*DEFAULT_ALLOW_PREFIXES, *sb["allowlist"])]
    bad = []
    for part in _strip_cd(cmd):
        n = _norm(part).lower()
        if not any(n.startswith(p) for p in prefixes):
            bad.append(part)
    return (not bad), bad


# ---------------------------------------------------------------------------
# Komut yalıtımı: konteyner
# ---------------------------------------------------------------------------
_IMAGE_FOR = (("package.json", "node:20-slim"), ("composer.json", "composer:2"), ("go.mod", "golang:1.22"), ("pom.xml", "maven:3-eclipse-temurin-21"))


_DOCKER_CACHE: Dict[str, Any] = {"ts": 0.0, "ok": False}
DOCKER_CACHE_TTL_S = 60.0
DOCKER_NEGATIVE_TTL_S = 15.0        # Docker yeni başlatıldıysa kısa sürede fark edilsin


def docker_available(ttl_s: float = DOCKER_CACHE_TTL_S) -> bool:
    """Docker sunucusuna ulaşılıyorsa True (yalnızca istemci yeterli değildir; `docker version` sunucu sürümünü döndürmeli — `docker info`'dan
    çok daha hafiftir, imaj sayısıyla yavaşlamaz). G4: sonuç `ttl_s` boyunca önbelleklenir (olumsuz sonuç daha kısa); `ttl_s=0` taze sorgu."""
    import time as _t
    now = _t.time()
    if ttl_s > 0 and _DOCKER_CACHE["ts"]:
        age = now - _DOCKER_CACHE["ts"]
        if age < (ttl_s if _DOCKER_CACHE["ok"] else min(ttl_s, DOCKER_NEGATIVE_TTL_S)):
            return bool(_DOCKER_CACHE["ok"])
    ok = False
    if shutil.which("docker") is not None:
        try:
            r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=30, **hidden())
            ok = r.returncode == 0 and bool(r.stdout.strip())
        except Exception:
            ok = False
    _DOCKER_CACHE["ts"], _DOCKER_CACHE["ok"] = now, ok
    return ok


def docker_available_fresh() -> bool:
    """Önbelleği atlar (ayar değişikliği gibi kullanıcı eylemlerinde)."""
    _DOCKER_CACHE["ts"] = 0.0
    return docker_available()


def sandbox_image(project_dir: str, configured: str = "") -> str:
    if configured:
        return configured
    from .verify import _manifest_dirs      # kök + alt klasörler + apps/<uygulama>: manifest nerede olursa olsun imaj seçilir
    for sub in _manifest_dirs(project_dir):
        for marker, image in _IMAGE_FOR:
            if os.path.isfile(os.path.join(project_dir, sub, marker)):
                return image
    return "python:3.12-slim"


def find_dockerfile(project_dir: str) -> str:
    """Dockerfile'ın proje köküne göreli yolu: kökte `Dockerfile`, yoksa bir klasörün altında (`devops/Dockerfile`); bulunamazsa ''."""
    if os.path.isfile(os.path.join(project_dir, "Dockerfile")):
        return "Dockerfile"
    try:
        for name in sorted(os.listdir(project_dir)):
            if not name.startswith(".") and name != "node_modules" and os.path.isfile(os.path.join(project_dir, name, "Dockerfile")):
                return f"{name}/Dockerfile"
        dev = os.path.join(project_dir, "devops")
        for sub in sorted(os.listdir(dev)) if os.path.isdir(dev) else []:                   # devops/<uygulama>/Dockerfile (çok uygulamalı düzen)
            if os.path.isfile(os.path.join(dev, sub, "Dockerfile")):
                return f"devops/{sub}/Dockerfile"
    except OSError:
        pass
    return ''


def wrap_for_container(cmd: str, project_dir: str, image: str = "") -> str:
    """Komutu `docker run --rm` içine alır: proje klasörü /work olarak bağlanır; ağ açık kalır (bağımlılık kurulumu için), ev dizini yazılabilir değildir."""
    img = sandbox_image(project_dir, image)
    return (f"docker run --rm -v {shlex.quote(os.path.abspath(project_dir))}:/work -w /work --cap-drop ALL --security-opt no-new-privileges "
            f"{img} sh -c {shlex.quote(cmd)}")


def _project_digest(project_dir: str, n: int = 8) -> str:
    return hashlib.sha1(os.path.abspath(project_dir).encode()).hexdigest()[:n]


def _http_status(url: str, timeout: float = 3.0) -> Optional[int]:
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "fssc-container-verify"}), timeout=timeout) as resp:
            return int(resp.status)
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None)
        return int(code) if isinstance(code, int) else None


def container_verify(project_dir: str, health_url: str = "", timeout_s: float = 600.0, health_timeout_s: float = 60.0) -> Dict[str, Any]:
    """Sprint kapanışı (§7.7): DevOps dosyaları değiştiyse imaj build edilir; `health_url` verilmişse konteyner GERÇEKTEN başlatılır
    (adresteki port eşlenir) ve sağlık adresi 2xx/3xx ya da 401/403 dönmeli (G4). Docker yoksa SKIPPED döner (kapanışı engellemez)."""
    if not docker_available():
        return {"status": "SKIPPED", "reason": tx("Docker kullanılamıyor")}
    dockerfile = find_dockerfile(project_dir)
    if not dockerfile:
        return {"status": "SKIPPED", "reason": tx("Dockerfile yok")}
    digest = _project_digest(project_dir)
    tag = "fssc-verify:" + digest
    try:
        b = subprocess.run(["docker", "build", "-q", "-t", tag, "-f", dockerfile, "."], cwd=project_dir, capture_output=True, text=True, timeout=timeout_s, **hidden())
    except Exception as e:  # noqa: BLE001
        return {"status": "FAILED", "reason": tx("docker build çalışmadı: {err}", err=e)}
    if b.returncode != 0:
        return {"status": "FAILED", "reason": tx("docker build başarısız"), "output": (b.stderr or b.stdout)[-1500:]}
    if not health_url:
        return {"status": "PASSED", "reason": tx("imaj build edildi (sağlık adresi verilmedi; konteyner başlatılmadı)"), "image": tag}
    from urllib.parse import urlsplit
    import time as _t
    parts = urlsplit(health_url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    name = f"fssc-health-{digest}"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30, **hidden())
    try:
        r = subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-p", f"{port}:{port}", tag], capture_output=True, text=True, timeout=60, **hidden())
    except Exception as e:  # noqa: BLE001
        return {"status": "FAILED", "reason": tx("konteyner başlatılamadı: {err}", err=e), "image": tag}
    if r.returncode != 0:
        return {"status": "FAILED", "reason": tx("konteyner başlatılamadı"), "output": (r.stderr or r.stdout)[-1200:], "image": tag}
    last: Optional[int] = None
    try:
        deadline = _t.time() + health_timeout_s
        while True:
            last = _http_status(health_url)
            if last is not None and (last < 400 or last in (401, 403)):
                return {"status": "PASSED", "reason": tx("imaj build edildi; konteyner ayakta, sağlık HTTP {status}", status=last), "image": tag, "health_status": last}
            if _t.time() >= deadline:
                break
            _t.sleep(1.0)
        logs = subprocess.run(["docker", "logs", "--tail", "40", name], capture_output=True, text=True, timeout=30, **hidden())
        return {"status": "FAILED", "image": tag,
                "reason": tx("konteyner {sec} sn içinde {url} adresinde sağlıklı yanıt vermedi", sec=int(health_timeout_s), url=health_url)
                + (tx(" (son yanıt HTTP {status})", status=last) if last is not None else tx(" (bağlantı kurulamadı)")),
                "output": ((logs.stdout or "") + (logs.stderr or ""))[-1500:]}
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30, **hidden())


# ---------------------------------------------------------------------------
# G4: tek konteynerde doğrulama oturumu — kurulum sonraki komutlara kalır; pip/npm önbelleği adlandırılmış hacimde;
# komutlar proje içindeki bir kabuk betiğiyle koşar (Windows/sh alıntılama sorunu yok)
# ---------------------------------------------------------------------------
def container_name(project_dir: str) -> str:
    return "fssc-verify-" + _project_digest(project_dir, 10)


def container_start_cmd(project_dir: str, image: str = "") -> str:
    """Bekleyen (sleep) bir konteyner açar: proje /work, pip/npm önbellekleri hacimde, yetkiler düşük, ağ açık (bağımlılık kurulumu için)."""
    img = sandbox_image(project_dir, image)
    mount = os.path.abspath(project_dir) + ":/work"
    return (f'docker run -d --rm --name {container_name(project_dir)} -v "{mount}" -v fssc-pip-cache:/root/.cache/pip -v fssc-npm-cache:/root/.npm '
            f"-w /work --cap-drop ALL --security-opt no-new-privileges {img} sleep 7200")


def container_exec_cmd(project_dir: str, script_rel: str) -> str:
    return f"docker exec {container_name(project_dir)} sh -e /work/{script_rel.replace(chr(92), '/').lstrip('/')}"


def container_stop_cmd(project_dir: str) -> str:
    return f"docker rm -f {container_name(project_dir)}"


_HOST_PY_RX = re.compile(
    r'"[^"]*[\\/]python(?:\d+(?:\.\d+)?)?(?:\.exe)?"'                                   # tırnaklı tam yol
    r'|(?<![\w"])[A-Za-z]:[\\/][^\s"]*python(?:\d+(?:\.\d+)?)?(?:\.exe)?(?=\s|$)'        # Windows tam yol
    r'|(?<![\w"])/[^\s"]*/python(?:\d+(?:\.\d+)?)?(?=\s|$)'                             # POSIX tam yol
)


def containerize_command(cmd: str, project_dir: str) -> str:
    """Host'a özgü parçaları konteyner karşılığına çevirir: host/venv Python yolu → `python`, proje kökü (her iki eğik çizgi) → `/work`."""
    out = _HOST_PY_RX.sub("python", str(cmd or ""))
    base = os.path.abspath(project_dir)
    fwd = base.replace("\\", "/")
    for variant in (f'"{base}"', f'"{fwd}"', base, fwd):
        out = out.replace(variant, "/work")
    if "/work" in out:
        out = out.replace("\\", "/")
    return out


# ---------------------------------------------------------------------------
# Sır taraması (§12 madde 4) ve maskeleme
# ---------------------------------------------------------------------------
_SECRET_PATTERNS = [
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("API_KEY", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("ASSIGNED_SECRET", re.compile(r"(?i)\b(?:api[_-]?key|secret|passwd|password|token|client[_-]?secret)\b\s*[:=]\s*['\"]([^'\"\s]{8,})['\"]")),
]
_SECRET_IGNORE_VALUES = re.compile(r"(?i)^(?:x{4,}|\*{4,}|changeme|change_me|your[_-].*|<.*>|\$\{.*\}|example.*|test.*|dummy.*|placeholder.*|secret)$")
_SCAN_SKIP_DIRS = {".git", ".fs-workspace", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "vendor"}
_SCAN_SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff", ".woff2", ".ttf", ".lock", ".pyc"}


# Yazım anında (teslim diske inmeden) reddedilen yüksek güvenli kalıplar; atanmış parola/secret kalıbı commit öncesi ikinci ağda kalır
HIGH_CONFIDENCE_KINDS: Tuple[str, ...] = ("PRIVATE_KEY", "AWS_ACCESS_KEY", "GITHUB_TOKEN", "API_KEY", "SLACK_TOKEN")
_TOKEN_PREFIX_RX = re.compile(r"^(?:AKIA|gh[pousr]_|sk-|xox[abprs]-)")


def _placeholder_like(kind: str, value: str) -> bool:
    """`AKIAXXXXXXXXXXXXXXXX`, `sk-xxxxxxxxxxxxxxxxxxxx`, `password: "changeme"` gibi belge/örnek yer tutucuları bulgu sayılmaz."""
    if kind == "PRIVATE_KEY":
        return False
    body = _TOKEN_PREFIX_RX.sub("", str(value))
    if kind == "ASSIGNED_SECRET" and _SECRET_IGNORE_VALUES.match(body):
        return True
    return bool(body) and len(set(body)) == 1


def scan_text(text: str, name: str = "") -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for lineno, line in enumerate(str(text).splitlines(), 1):
        for kind, rx in _SECRET_PATTERNS:
            m = rx.search(line)
            if not m:
                continue
            value = m.group(1) if (m.groups() and m.group(1)) else m.group(0)
            if _placeholder_like(kind, value):
                continue
            findings.append({"file": name, "line": lineno, "kind": kind, "preview": mask(value)})
            break
    return findings


def scan_delivery(files: Any, kinds: Tuple[str, ...] = HIGH_CONFIDENCE_KINDS) -> List[Dict[str, Any]]:
    """G4 (§12 madde 4): ajan tesliminin `payload.files[]` içeriğini diske yazılmadan ÖNCE tarar. Yalnızca yüksek güvenli kalıplar
    (gerçek bir teslim yanlış pozitifle reddedilmesin); atanmış parola/secret kalıpları commit öncesi taramada yakalanır."""
    out: List[Dict[str, Any]] = []
    for f in (files if isinstance(files, list) else []):
        if not isinstance(f, dict):
            continue
        rel = str(f.get("path", "")).replace("\\", "/")
        if os.path.splitext(rel)[1].lower() in _SCAN_SKIP_EXT:
            continue
        out += [x for x in scan_text(str(f.get("content", "")), rel) if x["kind"] in kinds]
    return out


def mask(value: str) -> str:
    v = str(value)
    return v[:2] + "*" * max(4, len(v) - 4) + v[-2:] if len(v) > 6 else "*" * len(v)


def redact(text: str) -> str:
    """Tutanak ve bağlam metinlerinde sır değerlerini maskeler (şartnamedeki gizli değerler tutanağa kopyalanmaz)."""
    out = str(text)
    for kind, rx in _SECRET_PATTERNS:
        if kind == "ASSIGNED_SECRET":
            out = rx.sub(lambda m: m.group(0).replace(m.group(1), mask(m.group(1))) if not _SECRET_IGNORE_VALUES.match(m.group(1)) else m.group(0), out)
        else:
            out = rx.sub(lambda m: mask(m.group(0)), out)
    return out


_TEST_PATH_RX = re.compile(
    r"(?i)(?:^|/)(?:tests?|__tests__|specs?|fixtures?|__mocks__|mocks?|e2e)(?:/|$)|(?:^|/)conftest\.py$|(?:^|/)test_[^/]*$|\.(?:test|spec)\.[a-z0-9]+$|_test\.[a-z0-9]+$")


def is_test_path(rel: str) -> bool:
    """Test/örnek veri dosyası mı (tests/, __tests__/, fixtures/, *.spec.ts, test_*.py, conftest.py ...)? `contest.ts`, `latest.py` gibi adlar eşleşmez."""
    return bool(_TEST_PATH_RX.search(str(rel).replace("\\", "/")))


def scan_files(project_dir: str, rel_paths: List[str]) -> List[Dict[str, Any]]:
    """Commit edilecek dosyalar. `.env*` zaten .gitignore'dadır; yine de içeriği taranmaz (commit'lenmez).
    Test/örnek veri dosyalarında yalnızca yüksek güvenli kalıplar (özel anahtar, AWS/GitHub/Slack belirteci) bulgudur: testlerin sahte
    `password: 'Sifre-12345'` değerleri commit'i durdurup düzeltme turu yemez (saha notu C1)."""
    findings: List[Dict[str, Any]] = []
    for rel in rel_paths:
        parts = rel.replace("\\", "/").split("/")
        base = parts[-1]
        if any(p in _SCAN_SKIP_DIRS for p in parts[:-1]) or os.path.splitext(base)[1].lower() in _SCAN_SKIP_EXT or base.startswith(".env"):
            continue
        path = os.path.join(project_dir, *parts)
        if not os.path.isfile(path) or os.path.getsize(path) > 512_000:
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                found = scan_text(fh.read(), rel)
        except Exception:
            continue
        findings += [x for x in found if x["kind"] in HIGH_CONFIDENCE_KINDS] if is_test_path(rel) else found
    return findings


# ---------------------------------------------------------------------------
# Döngü kırıcı (§12 madde 6): hata imzası
# ---------------------------------------------------------------------------
def error_signature(verification: Optional[Dict[str, Any]]) -> str:
    """Başarısız komutun çıktısından kaba bir imza: sayılar, yollar ve zaman damgaları atılır. Aynı imza art arda görülürse tur harcanmaz."""
    if not verification or verification.get("status") != "FAILED":
        return ""
    failed = next((r for r in verification.get("results", []) if r.get("status") == "FAILED"), None)
    if not failed:
        return ""
    out = str(failed.get("output") or "")
    lines = [l for l in out.splitlines() if re.search(r"(?i)error|assert|exception|failed|fail:|cannot|undefined|not found|syntax", l)] or out.splitlines()[-3:]
    text = " ".join(lines[-6:])
    text = re.sub(r"[A-Za-z]:\\[^\s:]+|/[\w./-]+", "<yol>", text)
    text = re.sub(r"0x[0-9a-f]+|\d+(\.\d+)?", "<n>", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha1((str(failed.get("name")) + "|" + text).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Bitmişlik tanımı (§7.7)
# ---------------------------------------------------------------------------
def tests_ran(verification: Optional[Dict[str, Any]]) -> bool:
    """En az bir test gerçekten koştu ve geçti mi? ("hiç test yok" pytest 5 → SKIPPED; bitmiş saymaz)"""
    return any(r.get("name") == "test" and r.get("status") == "PASSED" and not r.get("noop") for r in (verification or {}).get("results", []))


NON_CODE_EXTENSIONS = (".md", ".txt", ".rst", ".adoc", ".yml", ".yaml", ".sh", ".dockerignore", ".gitignore", ".example")


def _non_code(path: str) -> bool:
    low = str(path).replace("\\", "/").lower()
    return low.endswith(NON_CODE_EXTENSIONS) or os.path.basename(low).startswith("dockerfile")


def docs_only(written: List[str]) -> bool:
    """Teslimde yalnızca belge / altyapı yapılandırması (md, yml, sh, Dockerfile...) varsa True: bu dosyalar için çalıştırılacak birim testi yoktur."""
    return bool(written) and all(_non_code(w) for w in written)


def test_not_needed(verification: Optional[Dict[str, Any]], written: List[str]) -> bool:
    """Test koşmadı AMA gerekmiyordu: değişiklik yalnızca belge ve doğrulamadaki test komutu boş yer tutucuydu (gerçek test koştu sayılmaz, DoD bunu açıkça belirtir)."""
    return docs_only(written) and any(r.get("name") == "test" and r.get("noop") for r in (verification or {}).get("results", []))


def task_dod(verification: Optional[Dict[str, Any]], commit_status: str, pending_fix: bool, auto_commit: bool = True, written: Optional[List[str]] = None,
             waive_tests: bool = False) -> List[Dict[str, Any]]:
    """Bir görevin bitmiş sayılma koşulları: 1) doğrulama PASSED  2) test koştu ve geçti  3) teslim commit'lendi  4) bekleyen düzeltme yok."""
    v = verification or {}
    return [
        {"key": "verification_passed", "ok": v.get("status") == "PASSED", "text": tx("Doğrulama PASSED döndü (SKIPPED bitmiş saymaz)")},
        {"key": "tests_ran", "ok": tests_ran(v) or test_not_needed(v, written or []) or waive_tests,
         "text": (tx("Test gerekmedi: yalnızca belge/altyapı yapılandırması değişti (boş test komutu 'test koştu' sayılmaz)") if (not tests_ran(v) and test_not_needed(v, written or []))
                  else tx("En az bir test gerçekten koştu ve geçti (hiç test yok bitmiş saymaz)"))},
        {"key": "committed", "ok": (commit_status in ("COMMITTED", "NOTHING")) or not auto_commit, "text": tx("Teslim commit'lendi")},
        {"key": "no_pending_fix", "ok": not pending_fix, "text": tx("Bekleyen düzeltme turu yok")},
    ]


_AC_RX = re.compile(r"(?i)(?<![A-Za-z])AC[-_ ]?(\d{1,5})(?!\d)")
_TEST_FILE_RX = re.compile(r"(?i)(^|/)(tests?|__tests__|e2e|spec)/|(^|/)test_[^/]+\.py$|[^/]+_test\.(py|go)$|\.(test|spec)\.[jt]sx?$|Test\.php$")


def ac_mentions(project_dir: str) -> Dict[str, List[str]]:
    """Test dosyalarında anılan kabul kriteri kimlikleri → o kriteri anan dosyalar (`# AC-12`, `test_ac12_…`, senaryo ac_refs). Anma kanıt DEĞİLDİR."""
    found: Dict[str, List[str]] = {}
    if not project_dir or not os.path.isdir(project_dir):
        return found
    for cur, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _SCAN_SKIP_DIRS and not d.startswith(".")]
        for f in files:
            rel = os.path.relpath(os.path.join(cur, f), project_dir).replace("\\", "/")
            if not _TEST_FILE_RX.search(rel) or os.path.splitext(f)[1].lower() in _SCAN_SKIP_EXT:
                continue
            try:
                with open(os.path.join(cur, f), "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read(400_000)
            except Exception:
                continue
            for m in _AC_RX.finditer(rel + "\n" + text):
                found.setdefault(f"AC-{int(m.group(1))}", [])
                if rel not in found[f"AC-{int(m.group(1))}"]:
                    found[f"AC-{int(m.group(1))}"].append(rel)
    return found


def ac_evidence(project_dir: str, junit: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
    """Kabul kriteri → kanıt (G1): junit'te GEÇEN ve adında kimliği taşıyan bir test (`test_ac12_…`) ya da kimliği anan ve junit'te hiç
    başarısız testi olmayan (en az bir geçen) test dosyası. junit yoksa (test komutu hiç koşmadıysa) yalnızca anma döner; sıkı DoD
    yine gerçek bir test koşusu ister, bu yüzden anma tek başına kabule yetmez."""
    found = ac_mentions(project_dir)
    if junit is None:
        try:
            from .verify import junit_path, junit_results
            junit = junit_results(junit_path(project_dir))
        except Exception:
            junit = None
    if not junit:
        return found
    per_file: Dict[str, Dict[str, int]] = {}
    passed_by_name: Dict[str, List[str]] = {}
    for c in junit.get("cases", []):
        slot = per_file.setdefault(str(c.get("file") or ""), {"passed": 0, "failed": 0})
        if c.get("status") == "passed":
            slot["passed"] += 1
        elif c.get("status") in ("failed", "error"):
            slot["failed"] += 1
        for m in _AC_RX.finditer(str(c.get("name") or "")):
            if c.get("status") == "passed":
                passed_by_name.setdefault(f"AC-{int(m.group(1))}", []).append(str(c.get("id")))
    out: Dict[str, List[str]] = {}
    for ac, files in found.items():
        ok = [f for f in files if per_file.get(f, {}).get("passed", 0) > 0 and per_file.get(f, {}).get("failed", 0) == 0]
        if ok:
            out[ac] = ok
    for ac, ids in passed_by_name.items():
        out.setdefault(ac, [])
        out[ac] += [i for i in ids if i not in out[ac]]
    return out
