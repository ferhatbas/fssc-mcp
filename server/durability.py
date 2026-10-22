"""Veri dayanıklılığı: çalışma klasörü ve registry için anlık görüntüler (snapshot), bütünlük kontrolü, geri yükleme.

Neden (saha, 2026-10-14): registry (history/projects_registry.json, git dışı) yeniden oluşunca hub projeyi sıfırdan kaydetti ve
`.fs-workspace` durumunu (Jira, görevler, şartnameler, koşu geçmişi, teknoloji kararları) varsayılanlarla ezdi; geri dönüş yolu yoktu.

Katmanlar:
1. Anlık görüntü: durum dosyaları her sunucu başlangıcında (ilk yazımdan ÖNCE), düzenli aralıkla ve yıkıcı işlemlerden önce
   `<proje>/.fs-workspace/snapshots/<zaman>-<neden>/` altına kopyalanır; içerik değişmediyse yenisi yazılmaz, eskileri budanır.
2. Registry yedeği: `history/backups/` altında dönen kopyalar.
3. Bütünlük kontrolü: bir koleksiyon son anlık görüntülerdeki zirve değerinin yarısından fazla küçüldüyse uyarı üretir (`/api/data/health`).
4. Geri yükleme: seçilen anlık görüntüdeki dosyalar geri yazılır (önce "pre-restore" görüntüsü alınır).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from .i18n import translate as tx, N_
from typing import Any, Dict, List, Optional

SNAPSHOT_DIR = os.path.join(".fs-workspace", "snapshots")
# Çalışma klasöründe makine/koşu durumunu taşıyan dosyalar (events.jsonl yalnızca eklenir; belgeler git'tedir)
STATE_FILES = ("jira_issues.json", "tasks.json", os.path.join("specs", "specs.json"), "settings.json", "sprint_state.json",
               "questions.json", "runs.json", "deliberations.json")
KEEP_SNAPSHOTS = 30
KEEP_REGISTRY_BACKUPS = 10
SHRINK_RATIO = 0.5          # zirvenin yarısından fazla küçülme = uyarı
SHRINK_MIN_PEAK = 5         # küçük koleksiyonlarda uyarı üretme


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _read(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _count(raw: Optional[bytes]) -> Optional[int]:
    """JSON içeriğinin koleksiyon büyüklüğü (dict/list); okunamazsa None."""
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(data, dict):
        # sprint_state / questions gibi sarmalayıcılar: asıl koleksiyonların toplamı
        sizes = [len(v) for v in data.values() if isinstance(v, (dict, list))]
        return sum(sizes) if sizes else len(data)
    return len(data) if isinstance(data, list) else None


def _digest(files: Dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode("utf-8"))
        h.update(hashlib.sha256(files[name]).digest())
    return h.hexdigest()


def snapshots_root(project_dir: str) -> str:
    return os.path.join(os.path.abspath(project_dir), SNAPSHOT_DIR)


def list_snapshots(project_dir: str) -> List[Dict[str, Any]]:
    """Yeniden eskiye: {name, reason, created_at, files, counts}."""
    root = snapshots_root(project_dir)
    out: List[Dict[str, Any]] = []
    try:
        names = sorted(os.listdir(root), reverse=True)
    except OSError:
        return out
    for name in names:
        manifest = _read(os.path.join(root, name, "manifest.json"))
        if manifest is None:
            continue
        try:
            m = json.loads(manifest.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        out.append({"name": name, **m})
    return out


def snapshot_workspace(project_dir: str, reason: str = "auto", keep: int = KEEP_SNAPSHOTS) -> Optional[str]:
    """Durum dosyalarının anlık görüntüsünü alır; dosya yoksa ya da içerik son görüntüyle aynıysa None. Hata asla çağırana yansımaz."""
    try:
        base = os.path.abspath(project_dir)
        files: Dict[str, bytes] = {}
        for rel in STATE_FILES:
            raw = _read(os.path.join(base, ".fs-workspace", rel))
            if raw is not None:
                files[rel.replace("\\", "/")] = raw
        if not files:
            return None
        digest = _digest(files)
        existing = list_snapshots(base)
        if existing and existing[0].get("digest") == digest:
            return None
        safe_reason = "".join(c for c in reason if c.isalnum() or c in "-_")[:24] or "auto"
        name = f"{_ts()}-{safe_reason}"
        dest = os.path.join(snapshots_root(base), name)
        os.makedirs(dest, exist_ok=True)
        counts: Dict[str, Optional[int]] = {}
        for rel, raw in files.items():
            target = os.path.join(dest, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(raw)
            counts[rel] = _count(raw)
        manifest = {"reason": reason, "created_at": datetime.now(timezone.utc).isoformat(), "digest": digest,
                    "files": sorted(files), "counts": counts}
        with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        _prune(base, keep)
        return name
    except Exception:  # noqa: BLE001
        return None


def _prune(project_dir: str, keep: int) -> None:
    """En yeni `keep` görüntüyü tutar; her dosya için zirve (en büyük) değere sahip görüntü de korunur (hasarlı durum iyiyi budamasın)."""
    snaps = list_snapshots(project_dir)
    if len(snaps) <= keep:
        return
    protected = {s["name"] for s in snaps[:keep]}
    peak: Dict[str, tuple] = {}
    for s in snaps:
        for rel, n in (s.get("counts") or {}).items():
            if n is not None and n > peak.get(rel, (-1, ""))[0]:
                peak[rel] = (n, s["name"])
    protected |= {name for _, name in peak.values()}
    for s in snaps:
        if s["name"] not in protected:
            shutil.rmtree(os.path.join(snapshots_root(project_dir), s["name"]), ignore_errors=True)


def integrity_warnings(project_dir: str) -> List[Dict[str, Any]]:
    """Diskteki durum dosyalarını, saklı görüntülerdeki zirveyle karşılaştırır; belirgin küçülme uyarı olur."""
    warnings: List[Dict[str, Any]] = []
    try:
        base = os.path.abspath(project_dir)
        snaps = list_snapshots(base)
        for rel in STATE_FILES:
            rel = rel.replace("\\", "/")
            now = _count(_read(os.path.join(base, ".fs-workspace", *rel.split("/"))))
            best = max(((s.get("counts") or {}).get(rel) or 0, s["name"]) for s in snaps) if snaps else (0, "")
            if now is not None and best[0] >= SHRINK_MIN_PEAK and now < best[0] * SHRINK_RATIO:
                warnings.append({"file": rel, "now": now, "peak": best[0], "snapshot": best[1],
                                 "message": tx("{rel}: {peak} kayıttan {now} kayda düştü; '{snap}' görüntüsünden geri yüklenebilir.", rel=rel, peak=best[0], now=now, snap=best[1])})
    except Exception:  # noqa: BLE001
        pass
    return warnings


def restore_snapshot(project_dir: str, name: str, files: Optional[List[str]] = None) -> List[str]:
    """Seçilen görüntüdeki dosyaları geri yazar (önce 'pre-restore' görüntüsü). Geri yazılan göreli yolları döner."""
    base = os.path.abspath(project_dir)
    src = os.path.join(snapshots_root(base), os.path.basename(name))
    if not os.path.isfile(os.path.join(src, "manifest.json")):
        raise KeyError(name)
    snapshot_workspace(base, "pre-restore")
    restored: List[str] = []
    for rel in STATE_FILES:
        rel = rel.replace("\\", "/")
        if files and rel not in files:
            continue
        raw = _read(os.path.join(src, *rel.split("/")))
        if raw is None:
            continue
        target = os.path.join(base, ".fs-workspace", *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, target)
        restored.append(rel)
    return restored


def backup_registry(registry_path: str, keep: int = KEEP_REGISTRY_BACKUPS) -> Optional[str]:
    """Registry'nin dönen yedeği (`<history>/backups/projects_registry.<zaman>.json`); içerik aynıysa yazılmaz."""
    try:
        raw = _read(registry_path)
        if not raw:
            return None
        folder = os.path.join(os.path.dirname(os.path.abspath(registry_path)), "backups")
        os.makedirs(folder, exist_ok=True)
        names = sorted((n for n in os.listdir(folder) if n.startswith("projects_registry.") and n.endswith(".json")), reverse=True)
        if names and _read(os.path.join(folder, names[0])) == raw:
            return None
        name = f"projects_registry.{_ts()}.json"
        with open(os.path.join(folder, name), "wb") as f:
            f.write(raw)
        for old in names[keep - 1:]:
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
        return name
    except Exception:  # noqa: BLE001
        return None
