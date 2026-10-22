"""Docker/compose dosyalarını `devops/` altına taşır (kalıcı kural: bkz. `server/layout.py` `docker_violations`).

Ajanlar dosya yazar ama taşıyamaz/silemez; kökte ya da uygulama klasöründe kalmış Docker dosyalarını taşımak sunucu eylemidir.
- Kök `docker-compose*.yml`, `compose*.yml`, `Dockerfile*`, `.dockerignore` → `devops/<ad>`; `apps/<uygulama>/Dockerfile` ve `.dockerignore` → `devops/<uygulama>/<ad>`.
- Taşınan compose dosyasındaki göreli yollar (`build.context`, `dockerfile`, `./x:` hacimleri) yeni konuma göre yeniden yazılır.
- Belgelerdeki (`*.md`) ve spec'lerdeki alıntılanmış dosya adı başvuruları yeni yola çevrilir; çevrilemeyenler `remaining_refs` ile bildirilir.
Hedef zaten varsa o dosya taşınmaz (`conflicts`); hiçbir dosyanın üzerine yazılmaz.
"""
from __future__ import annotations

import os
import posixpath
import re
import shutil
from typing import Any, Dict, List, Optional

from . import layout as LAY
from .i18n import translate as tx

SKIP_DIRS = {"node_modules", ".git", ".fs-workspace", "dist", "build", "coverage", "__pycache__", ".venv", "venv", "vendor"}
MAX_DEPTH = 3


def _walk_docker_files(project_dir: str, devops: str) -> List[str]:
    out: List[str] = []
    base = os.path.abspath(project_dir)
    for dp, dns, fns in os.walk(base):
        rel_dir = os.path.relpath(dp, base).replace("\\", "/")
        depth = 0 if rel_dir == "." else rel_dir.count("/") + 1
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not (depth == 0 and d == devops) and depth < MAX_DEPTH]
        for fn in fns:
            rel = fn if rel_dir == "." else f"{rel_dir}/{fn}"
            if LAY.is_docker_file(rel):
                out.append(rel)
    return sorted(out)


def plan(project_dir: str, layout: Dict[str, Any]) -> Dict[str, Any]:
    devops = (layout.get("devops_dir") or "devops").strip("/")
    moves: List[Dict[str, str]] = []
    conflicts: List[Dict[str, str]] = []
    taken: set = set()
    for rel in _walk_docker_files(project_dir, devops):
        if rel.split("/")[0] == devops:
            continue
        dest = LAY.docker_suggestion(layout, rel)
        if dest in taken or os.path.exists(os.path.join(project_dir, *dest.split("/"))):
            conflicts.append({"from": rel, "to": dest, "reason": tx("hedef zaten var (üzerine yazılmaz; elle birleştirin)")})
            continue
        taken.add(dest)
        moves.append({"from": rel, "to": dest})
    return {"moves": moves, "conflicts": conflicts}


def rewrite_compose(text: str, old_rel: str, new_rel: str, path_map: Dict[str, str]) -> str:
    """Taşınan compose dosyasındaki göreli yolları yeni konuma göre yeniden yazar (servis blokları 2 boşluk girintili anahtarlardır)."""
    old_dir, new_dir = posixpath.dirname(old_rel) or ".", posixpath.dirname(new_rel) or "."

    def norm(p: str) -> str:
        return posixpath.normpath(p)

    blocks = re.split(r"(?m)^(?=  [A-Za-z0-9_.-]+:\s*$)", text)
    out: List[str] = []
    for b in blocks:
        m = re.search(r"(?m)^\s*context:\s*['\"]?([^\s'\"#]+)", b)
        ctx_old = norm(posixpath.join(old_dir, m.group(1))) if m else norm(old_dir)
        ctx_new_val = posixpath.relpath(ctx_old, new_dir)

        def ctx_sub(mm: "re.Match[str]") -> str:
            if mm.group(2).startswith("/") or re.match(r"^[a-z]+://", mm.group(2)):
                return mm.group(0)
            return f"{mm.group(1)}{ctx_new_val}"
        b = re.sub(r"(?m)^(\s*context:\s*)([^\s'\"#]+)", ctx_sub, b)

        def df_sub(mm: "re.Match[str]") -> str:
            old_df = norm(posixpath.join(ctx_old, mm.group(2)))
            new_df = path_map.get(old_df, old_df)
            return f"{mm.group(1)}{posixpath.relpath(new_df, ctx_old)}"
        b = re.sub(r"(?m)^(\s*dockerfile:\s*)([^\s'\"#]+)", df_sub, b)

        def vol_sub(mm: "re.Match[str]") -> str:
            host = mm.group(2)
            if not host.startswith("."):
                return mm.group(0)
            target = norm(posixpath.join(old_dir, host))
            new = posixpath.relpath(target, new_dir)
            return f"{mm.group(1)}{new if new.startswith('.') else './' + new}{mm.group(3)}"
        b = re.sub(r"(?m)^(\s*-\s*)([^\s:'\"#]+)(:)", vol_sub, b)
        out.append(b)
    return "".join(out)


def _update_references(project_dir: str, moves: List[Dict[str, str]]) -> Dict[str, Any]:
    """`*.md` ve `*.spec.ts` içindeki eski yol başvurularını yeni yola çevirir; çevrilemeyen başvuruları döner."""
    changed: List[str] = []
    base = os.path.abspath(project_dir)
    names = {os.path.basename(m["from"]): m for m in moves}
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and d != "devops"]
        for fn in fns:
            if not (fn.endswith(".md") or fn.endswith(".spec.ts")):
                continue
            path = os.path.join(dp, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            new = text
            for mv in moves:
                old, dest = mv["from"], mv["to"]
                new = re.sub(rf"(?<![\w/.-]){re.escape(old)}", dest, new)            # tam yol (apps/backend/Dockerfile)
                if "/" not in old:                                                      # kök dosya adı: yalnızca yolsuz kullanımlar
                    new = re.sub(rf"(?<![\w/.-]){re.escape(old)}(?![\w.-])", dest, new)
            if new != text:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(new)
                changed.append(os.path.relpath(path, base).replace("\\", "/"))
    # Çevrilemeyen başvurular: taşınan dosyanın adını anan ama yeni yolu içermeyen spec/md dosyaları
    remaining: List[str] = []
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and d != "devops"]
        for fn in fns:
            if not (fn.endswith(".md") or fn.endswith(".spec.ts")):
                continue
            path = os.path.join(dp, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            for name, mv in names.items():
                if re.search(rf"(?<![\w/.-]){re.escape(name)}(?![\w.-])", text) and mv["to"] not in text:
                    remaining.append(os.path.relpath(path, base).replace("\\", "/"))
                    break
    return {"updated": sorted(set(changed)), "remaining_refs": sorted(set(remaining))}


def apply(project_dir: str, layout: Dict[str, Any]) -> Dict[str, Any]:
    p = plan(project_dir, layout)
    base = os.path.abspath(project_dir)
    path_map = {m["from"]: m["to"] for m in p["moves"]}
    moved: List[Dict[str, str]] = []
    for mv in p["moves"]:
        src, dst = os.path.join(base, *mv["from"].split("/")), os.path.join(base, *mv["to"].split("/"))
        if not os.path.isfile(src):
            continue
        # compose ise içeriği yeni konuma göre yeniden yaz; sonra taşı
        if re.match(r"^(docker-)?compose", os.path.basename(mv["from"]), re.IGNORECASE):
            with open(src, "r", encoding="utf-8") as f:
                text = f.read()
            new_text = rewrite_compose(text, mv["from"], mv["to"], path_map)
            if new_text != text:
                with open(src, "w", encoding="utf-8", newline="") as f:
                    f.write(new_text)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        moved.append(mv)
    refs = _update_references(project_dir, moved) if moved else {"updated": [], "remaining_refs": []}
    return {"moved": moved, "conflicts": p["conflicts"], **refs}
