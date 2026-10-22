"""Backend uç noktalarının çıkarılması: tasarım ajanına "hangi uçlar var, hangi ekranlar bunları kullanmalı" bilgisini verir.

Kaynaklar (varsa): OpenAPI belgesi (`<docs>/openapi_spec.json`) ve backend kaynak kodundaki yönlendirme bildirimleri
(NestJS `@Controller/@Get...`, Express `router.get(...)`, FastAPI `@app.get(...)`). Mevcut ekran mockup'ları ve istemci ekran dosyaları da listelenir.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Tuple

from .i18n import translate as tx

SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".venv", "venv", "__pycache__", ".fs-workspace", "coverage"}
METHODS = ("get", "post", "put", "patch", "delete")
_NEST_CTRL = re.compile(r"@Controller\(\s*['\"`]([^'\"`]*)['\"`]?\s*\)")
_NEST_ROUTE = re.compile(r"@(Get|Post|Put|Patch|Delete)\(\s*(?:['\"`]([^'\"`]*)['\"`])?\s*\)")
_EXPRESS = re.compile(r"\b(?:router|app)\.(get|post|put|patch|delete)\(\s*['\"`]([^'\"`]+)['\"`]")
_FASTAPI = re.compile(r"@\w+\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]")


def _walk(root: str, exts: Tuple[str, ...], limit: int = 4000):
    n = 0
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if fn.endswith(exts) and ".spec." not in fn and ".test." not in fn:
                n += 1
                if n > limit:
                    return
                yield os.path.join(dp, fn)


def _join(*parts: str) -> str:
    return "/" + "/".join(p.strip("/") for p in parts if p and p.strip("/"))


def from_openapi(path: str) -> List[Tuple[str, str, str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return []
    out = []
    for p, ops in (doc.get("paths") or {}).items():
        for m, op in (ops or {}).items():
            if m.lower() in METHODS and isinstance(op, dict):
                out.append((m.upper(), p, str(op.get("summary") or op.get("operationId") or "")[:70]))
    return out


def from_source(project_dir: str) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    for fp in _walk(project_dir, (".ts", ".js", ".py")):
        try:
            text = open(fp, "r", encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        rel = os.path.relpath(fp, project_dir).replace("\\", "/")
        if fp.endswith(".py"):
            out += [(m.upper(), p, rel) for m, p in _FASTAPI.findall(text)]
            continue
        ctrl = _NEST_CTRL.search(text)
        if ctrl is not None:
            out += [(m.upper(), _join(ctrl.group(1), p or ""), rel) for m, p in _NEST_ROUTE.findall(text)]
        else:
            out += [(m.upper(), p if p.startswith("/") else "/" + p, rel) for m, p in _EXPRESS.findall(text)]
    return out


def collect(project_dir: str, docs_root: str) -> Dict[str, Any]:
    spec = os.path.join(project_dir, *docs_root.replace("\\", "/").split("/"), "openapi_spec.json")
    eps = from_openapi(spec)
    seen = {(m, p) for m, p, _ in eps}
    for m, p, src in from_source(project_dir):
        key = (m, re.sub(r"/:(\w+)", r"/{\1}", p))
        if key not in seen:
            seen.add(key)
            eps.append((key[0], key[1], src))
    shots = os.path.join(project_dir, *docs_root.replace("\\", "/").split("/"), "design", "screens")
    mocks = sorted(n for n in os.listdir(shots) if n.endswith(".html")) if os.path.isdir(shots) else []
    client = []
    for fp in _walk(project_dir, (".tsx", ".jsx", ".vue", ".svelte"), 1500):
        base = os.path.basename(fp)
        if re.search(r"(Screen|Page|View)\.(tsx|jsx|vue|svelte)$", base):
            client.append(os.path.relpath(fp, project_dir).replace("\\", "/"))
    return {"endpoints": eps, "mockups": mocks, "client_screens": sorted(client)}


def markdown(project_dir: str, docs_root: str, limit: int = 6500) -> str:
    """Tasarım görevinin bağlamına girecek bölüm: uç noktalar (ilk yol bölümüne göre gruplu), mevcut mockup'lar ve istemci ekranları."""
    data = collect(project_dir, docs_root)
    eps = data["endpoints"]
    if not eps:
        return ""
    groups: Dict[str, List[str]] = {}
    for m, p, note in eps:
        segs = [s for s in p.split("/") if s and not re.fullmatch(r"v\d+|api", s)]
        groups.setdefault(segs[0] if segs else "/", []).append(f"{m} {p}" + (f" — {note}" if note and not note.endswith((".ts", ".js", ".py")) else ""))
    lines = [tx("## Backend uç noktaları → gerekli ekranlar (sunucu taraması; {n} uç)", n=len(eps)),
             tx("Her uç grubu için kullanıcının göreceği ekran(lar) tasarlanmalı: listeleme/detay/form/durum ekranları ve hata-boş durumları. Mevcut mockup'larla karşılaştır; eksik olanları üret.")]
    for g, items in sorted(groups.items()):
        lines.append(f"- **{g}** ({len(items)}): " + "; ".join(items[:12]) + (" …" if len(items) > 12 else ""))
    lines.append(tx("Mevcut mockup'lar: ") + (", ".join(data["mockups"]) or tx("yok")))
    lines.append(tx("İstemci ekran dosyaları: ") + (", ".join(data["client_screens"][:30]) or tx("yok")))
    lines.append(tx("Teslimde `<docs>/design/coverage.md` yaz: her uç grubu → ekran kimliği/kimlikleri (ya da 'ekran gerekmez' + gerekçe); kapsanmayan uç kalmasın."))
    return "\n".join(lines)[:limit]
