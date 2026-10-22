"""Hedef projenin dökümanlarına, test dosyalarına ve commit ayrıntılarına salt-okunur erişim (pano: Dökümanlar, kanıt dosyası, commit penceresi).

Test dosyalarında kodun yanında okunabilir "sözel" senaryo listesi de verilir: describe/it/test başlıkları (JS/TS), `test_*` işlevleri + docstring (Python), `Test*` işlevleri (Go),
@Test yöntemleri (Java). Böylece yazılan test kodunun ne dediği kod okumadan görülür.

Güvenlik: yol proje klasöründen çıkamaz; `.git`, `node_modules`, `.fs-workspace`, gizli dosyalar (`.env*`, anahtarlar) ve ikili dosyalar okunmaz; boyut sınırlıdır.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from .i18n import translate as tx, N_
from .proc import hidden

MAX_READ_BYTES = 400_000
MAX_PATCH_CHARS = 80_000
MAX_LIST = 600
SKIP_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv", ".next", "coverage", ".pytest_cache", ".fs-workspace", "target", "vendor"}
SECRET_RX = re.compile(r"(^\.env(\..*)?$|\.pem$|\.key$|\.p12$|\.pfx$|^id_rsa|^id_ed25519|secrets?\.(json|ya?ml|txt)$|credentials)", re.IGNORECASE)
TEST_RX = re.compile(r"(\.(spec|test)\.[cm]?[jt]sx?$|(^|/)test_[^/]*\.py$|_test\.py$|_test\.go$|Test\.java$|Tests?\.cs$)")
_AC_RX = re.compile(r"\bAC[-_ ]?0*(\d{1,4})\b", re.IGNORECASE)
_SHA_RX = re.compile(r"^[0-9a-fA-F]{4,40}$")


class FileAccessError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def project_dir_of(hub) -> str:
    return (hub.projects.get(hub.active_project_id) or {}).get("path") or hub.default_project_path


def safe_path(project_dir: str, rel: str) -> str:
    """Göreli yolu proje klasörü içinde çözer; dışarı çıkan, yasaklı klasör/gizli dosya yollarını reddeder."""
    rel = str(rel or "").replace("\\", "/").strip().lstrip("/")
    if not rel or rel.startswith("..") or "/../" in f"/{rel}/" or ":" in rel.split("/")[0]:
        raise FileAccessError(tx("Geçersiz yol."))
    parts = [p for p in rel.split("/") if p]
    if any(p in SKIP_DIRS for p in parts[:-1]) or any(p in (".git", "node_modules", ".fs-workspace") for p in parts):
        raise FileAccessError(tx("Bu klasör görüntülenemez."), 403)
    if SECRET_RX.search(parts[-1]):
        raise FileAccessError(tx("Gizli bilgi içerebilecek dosya görüntülenmez."), 403)
    base = os.path.realpath(project_dir)
    full = os.path.realpath(os.path.join(base, *parts))
    if os.path.commonpath([base, full]) != base:
        raise FileAccessError(tx("Yol proje klasörünün dışında."), 403)
    return full


def _category(rel: str) -> str:
    low = rel.lower()
    if "/adr/" in f"/{low}":
        return "ADR"
    if "/meetings/" in f"/{low}":
        return tx("Toplantı")
    if "/sprints/" in f"/{low}":
        return "Sprint"
    if "/tests/" in f"/{low}":
        return tx("Test planı")
    if "/uat/" in f"/{low}":
        return "UAT"
    if "/reports/" in f"/{low}":
        return tx("Rapor")
    return tx("Belge")


def list_documents(hub) -> Dict[str, Any]:
    """Döküman klasörü (docs), proje kökündeki belgeler ve proje genelindeki test dosyaları."""
    from .paths import hub_docs_path
    root = project_dir_of(hub)
    out: Dict[str, Any] = {"project_dir": root, "docs": [], "tests": [], "root": []}
    if not os.path.isdir(root):
        return out
    # Belge klasörü projeye göre değişir (`docs` ya da `FS-docs`); ikisi de varsa ikisi de taranır
    docs_dirs = []
    for rel in (hub_docs_path(hub, "", root).strip("/"), "docs", "FS-docs"):
        full = os.path.join(root, *rel.split("/")) if rel else ""
        if full and os.path.isdir(full) and full not in docs_dirs:
            docs_dirs.append(full)

    def entry(full: str) -> Dict[str, Any]:
        rel = os.path.relpath(full, root).replace("\\", "/")
        st = os.stat(full)
        return {"path": rel, "size": st.st_size, "mtime": st.st_mtime, "category": _category(rel)}

    for docs_abs in docs_dirs:
        for dp, dns, fns in os.walk(docs_abs):
            dns[:] = [d for d in dns if d not in SKIP_DIRS]
            for fn in fns:
                if SECRET_RX.search(fn) or len(out["docs"]) >= MAX_LIST:
                    continue
                if fn.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".pdf", ".rar")):
                    continue
                out["docs"].append(entry(os.path.join(dp, fn)))
    for fn in sorted(os.listdir(root)):
        if fn.lower() in ("readme.md", "claude.md", "agents.md", "changelog.md", "contributing.md") and os.path.isfile(os.path.join(root, fn)):
            out["root"].append(entry(os.path.join(root, fn)))
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in fns:
            rel = os.path.relpath(os.path.join(dp, fn), root).replace("\\", "/")
            if TEST_RX.search(rel) and len(out["tests"]) < MAX_LIST:
                out["tests"].append(entry(os.path.join(dp, fn)))
    for k in ("docs", "tests"):
        out[k].sort(key=lambda e: e["path"])
    return out


def list_dir(hub, rel: str = "") -> Dict[str, Any]:
    """Proje klasöründe tek düzey listeleme (dosya gezgini, tembel açılır). Yasaklı klasörler ve gizli dosyalar listelenmez."""
    root = os.path.realpath(project_dir_of(hub))
    rel = str(rel or "").replace("\\", "/").strip().strip("/")
    full = safe_path(root, rel) if rel else root
    if rel and not os.path.isdir(full):
        raise FileAccessError(tx("Klasör bulunamadı."), 404)
    entries: List[Dict[str, Any]] = []
    try:
        names = sorted(os.listdir(full), key=lambda n: (not os.path.isdir(os.path.join(full, n)), n.lower()))
    except OSError:
        raise FileAccessError(tx("Klasör okunamadı."), 403)
    for n in names:
        fp = os.path.join(full, n)
        isdir = os.path.isdir(fp)
        if n in SKIP_DIRS or n == ".git" or (not isdir and SECRET_RX.search(n)):
            continue
        item: Dict[str, Any] = {"name": n, "path": (f"{rel}/{n}" if rel else n), "type": "dir" if isdir else "file"}
        if not isdir:
            try:
                item["size"] = os.path.getsize(fp)
            except OSError:
                item["size"] = 0
        entries.append(item)
        if len(entries) >= MAX_LIST:
            break
    return {"project_dir": root, "path": rel, "entries": entries}


# ---------------------------------------------------------------------------
# Sözel senaryo çıkarımı
# ---------------------------------------------------------------------------
_JS_SUITE = re.compile(r"^(\s*)(?:describe|context|suite)(?:\.\w+)?\s*\(\s*(['\"`])(.+?)\2")
_JS_CASE = re.compile(r"^(\s*)(?:it|test)(?:\.\w+)?\s*\(\s*(['\"`])(.+?)\2")
_PY_CLASS = re.compile(r"^(\s*)class\s+(Test\w*)")
_PY_DEF = re.compile(r"^(\s*)(?:async\s+)?def\s+(test_\w+)\s*\(")
_GO_FUNC = re.compile(r"^func\s+(Test\w+)\s*\(")
_JAVA_TEST = re.compile(r"^\s*@Test\b")
_JAVA_METHOD = re.compile(r"^\s*(?:public\s+)?(?:void|Task)\s+(\w+)\s*\(")


def _humanize(name: str) -> str:
    s = re.sub(r"^[Tt]est_?", "", name)
    s = re.sub(r"_+", " ", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)).strip()
    return (s[:1].upper() + s[1:]) if s else name


def extract_scenarios(text: str, path: str = "") -> List[Dict[str, Any]]:
    """Test dosyasındaki senaryo başlıkları: [{suite, name, line, doc?}] (en çok 200)."""
    out: List[Dict[str, Any]] = []
    lines = text.splitlines()
    low = path.lower()
    stack: List[tuple] = []                                   # (girinti, ad)
    for i, line in enumerate(lines, start=1):
        if len(out) >= 200:
            break
        if low.endswith((".py",)):
            m = _PY_CLASS.match(line)
            if m:
                stack = [s for s in stack if s[0] < len(m.group(1))] + [(len(m.group(1)), _humanize(m.group(2)))]
                continue
            m = _PY_DEF.match(line)
            if m:
                doc = ""
                nxt = lines[i].strip() if i < len(lines) else ""
                if nxt.startswith(('"""', "'''")):
                    doc = nxt.strip("\"' ").strip()
                out.append({"suite": " › ".join(s[1] for s in stack if s[0] < len(m.group(1))), "name": doc or _humanize(m.group(2)), "line": i})
        elif low.endswith(".go"):
            m = _GO_FUNC.match(line)
            if m:
                out.append({"suite": "", "name": _humanize(m.group(1)), "line": i})
        elif low.endswith(".java"):
            if _JAVA_TEST.match(line) and i < len(lines):
                for nxt in lines[i:i + 3]:
                    mm = _JAVA_METHOD.match(nxt)
                    if mm:
                        out.append({"suite": "", "name": _humanize(mm.group(1)), "line": i + 1})
                        break
        else:
            m = _JS_SUITE.match(line)
            if m:
                ind = len(m.group(1).expandtabs(2))
                stack = [s for s in stack if s[0] < ind] + [(ind, m.group(3))]
                continue
            m = _JS_CASE.match(line)
            if m:
                ind = len(m.group(1).expandtabs(2))
                out.append({"suite": " › ".join(s[1] for s in stack if s[0] < ind), "name": m.group(3), "line": i})
    return out


def _header_summary(text: str) -> str:
    """Dosya başındaki açıklama yorumu (varsa): testin amacını anlatan ilk blok."""
    lines = text.splitlines()[:25]
    block: List[str] = []
    in_block = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("/*"):
            in_block = True
        if in_block:
            block.append(s.strip("/* ").strip())
            if s.endswith("*/"):
                break
        elif s.startswith(("//", "#")) and not s.startswith("#!"):
            block.append(s.lstrip("/# ").strip())
        elif s.startswith(('"""', "'''")):
            block.append(s.strip("\"' "))
            break
        elif s and not s.startswith(("import ", "from ", "const ", "using ", "package ")):
            if block:
                break
        elif block:
            break
    return " ".join(b for b in block if b)[:600]


def read_document(hub, rel: str) -> Dict[str, Any]:
    root = project_dir_of(hub)
    full = safe_path(root, rel)
    if not os.path.isfile(full):
        raise FileAccessError(tx("Dosya bulunamadı."), 404)
    size = os.path.getsize(full)
    with open(full, "rb") as f:
        raw = f.read(MAX_READ_BYTES + 1)
    if b"\x00" in raw[:4096]:
        raise FileAccessError(tx("İkili dosya görüntülenemez."), 415)
    truncated = len(raw) > MAX_READ_BYTES
    text = raw[:MAX_READ_BYTES].decode("utf-8", errors="replace")
    relp = os.path.relpath(full, os.path.realpath(root)).replace("\\", "/")
    is_test = bool(TEST_RX.search(relp))
    acs = sorted({f"AC-{int(m.group(1))}" for m in _AC_RX.finditer(text)}, key=lambda a: int(a[3:]))
    return {"path": relp, "size": size, "truncated": truncated, "lines": text.count("\n") + 1, "content": text, "is_test": is_test,
            "scenarios": extract_scenarios(text, relp) if is_test else [], "ac_refs": acs, "summary": _header_summary(text) if is_test else ""}


# ---------------------------------------------------------------------------
# Commit ayrıntısı
# ---------------------------------------------------------------------------
def _git(root: str, args: List[str], timeout: float = 20.0) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       stdin=subprocess.DEVNULL, **hidden())
    if r.returncode != 0:
        raise FileAccessError((r.stderr or r.stdout or tx("git hatası")).strip()[:300], 404)
    return r.stdout


def commit_detail(hub, sha: str) -> Dict[str, Any]:
    if not _SHA_RX.match(str(sha or "")):
        raise FileAccessError(tx("Geçersiz commit kimliği."))
    root = project_dir_of(hub)
    if not os.path.isdir(os.path.join(root, ".git")):
        raise FileAccessError(tx("Proje bir git deposu değil."), 404)
    head = _git(root, ["show", "-s", "--format=%H%x1f%an%x1f%aI%x1f%s%x1f%b", sha]).rstrip("\n").split("\x1f")
    numstat = _git(root, ["show", "--numstat", "--format=", sha])
    files: List[Dict[str, Any]] = []
    for ln in numstat.splitlines():
        parts = ln.split("\t")
        if len(parts) == 3:
            add, dele, name = parts
            files.append({"path": name, "added": int(add) if add.isdigit() else None, "deleted": int(dele) if dele.isdigit() else None})
    patch = _git(root, ["show", "--format=", "--patch", "--no-color", "-U3", sha], timeout=30.0)
    truncated = len(patch) > MAX_PATCH_CHARS
    m = re.search(r"\(([A-Za-z]+-\d+)\)", head[3] if len(head) > 3 else "")
    return {"sha": head[0][:40], "short": head[0][:7], "author": head[1] if len(head) > 1 else "", "date": head[2] if len(head) > 2 else "",
            "subject": head[3] if len(head) > 3 else "", "body": (head[4] if len(head) > 4 else "").strip(), "issue": m.group(1).upper() if m else None,
            "files": files, "added": sum(f["added"] or 0 for f in files), "deleted": sum(f["deleted"] or 0 for f in files),
            "patch": patch[:MAX_PATCH_CHARS], "truncated": truncated}
