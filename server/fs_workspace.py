"""
Proje Bazlı .fs-workspace ve Ajan Markdown (Prompt/Hafıza) Yönetim Modülü.
Her projenin kendi kök dizininde izole çalışma alanı oluşturur:
- .fs-workspace/agents/<agent_id>.md (Aktif Prompt ve Kurallar)
- .fs-workspace/agents/history/<agent_id>/ (Git-Tree Versiyon Snapshot'ları ve versions.json)
- .fs-workspace/jira_issues.json (Proje Görevleri/Ticketları)
- .fs-workspace/tasks.json (Kanban Görevleri)
- .fs-workspace/specs/specs.json (Müşteri Şartname ve Görüşme Notları)
- .fs-workspace/settings.json (Proje Ayarları ve Durum)
"""

import os
import json
import hashlib
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import i18n as I18N
from .i18n import translate as tx, N_

GLOBAL_PROMPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agents", "prompts"))

ROLE_TO_PROMPT_MAP = {
    "PM": "pm.md",
    "ARCHITECT": "architect.md",
    "DEVELOPER": "developer.md",
    "BACKEND_DEV": "developer.md",
    "FRONTEND_DEV": "developer.md",
    "DESIGNER": "designer.md",
    "QA": "qa.md",
    "E2E_TESTER": "e2e_tester.md",
    "SCRUM_MASTER": "scrum_master.md",
    "DEVOPS": "devops.md",
    "PO": "po.md",
    "REPORTER": "reporter.md",
    "DOCUMENTOR": "documentor.md",
    "SCM": "scm.md",
}

# Kanonik prompt dili; istenen dilde dosya yoksa buna düşülür
FALLBACK_PROMPT_LANG = "tr"


def get_workspace_dir(project_path: str) -> str:
    """Projenin .fs-workspace kök dizin yolunu döner."""
    return os.path.join(os.path.abspath(project_path), ".fs-workspace")


def ensure_fs_workspace(project_path: str) -> str:
    """Proje kök dizininde .fs-workspace yapısını garanti eder ve oluşturur."""
    ws_dir = get_workspace_dir(project_path)
    agents_dir = os.path.join(ws_dir, "agents")
    history_dir = os.path.join(agents_dir, "history")
    specs_dir = os.path.join(ws_dir, "specs")
    specs_files_dir = os.path.join(specs_dir, "files")

    os.makedirs(agents_dir, exist_ok=True)
    os.makedirs(history_dir, exist_ok=True)
    os.makedirs(specs_files_dir, exist_ok=True)
    return ws_dir


DEFAULT_PROMPT_LANG = os.environ.get("AGY_PROMPT_LANG", "tr")

# Ajan istem kopyasının projeye özgü bölümü: başlık proje diline göre yazılır, ama bölüm ARANIRKEN her dildeki biçimi kabul edilir
# (proje dili sonradan değişse de mevcut kopyadaki bölüm bulunur).
_LEARN_PREFIX = N_("## 🧠 Öğrenilen Dersler")


def _learn_index(text: str) -> int:
    """Öğrenilen Dersler bölümünün (herhangi bir dildeki başlığıyla) ilk konumu; yoksa -1."""
    found = [i for i in (text.find(v) for v in I18N.variants(_LEARN_PREFIX)) if i != -1]
    return min(found) if found else -1


def get_standard_prompt_path(role: str, lang: Optional[str] = None) -> str:
    """Role karşılık gelen global standart prompt dosyasının yolunu döner (örn: agents/prompts/tr/pm.md)."""
    filename = ROLE_TO_PROMPT_MAP.get(role.upper(), "developer.md")
    target_lang = lang or DEFAULT_PROMPT_LANG

    # 1. Öncelik: İstenen dil klasörü (agents/prompts/tr/pm.md veya agents/prompts/en/pm.md)
    lang_path = os.path.join(GLOBAL_PROMPTS_DIR, target_lang, filename)
    if os.path.isfile(lang_path):
        return lang_path

    # 2. Öncelik: Kanonik dil klasörü (tr/)
    fallback_path = os.path.join(GLOBAL_PROMPTS_DIR, FALLBACK_PROMPT_LANG, filename)
    if os.path.isfile(fallback_path):
        return fallback_path

    # 3. Öncelik: Kök klasör (eski yerleşim)
    root_path = os.path.join(GLOBAL_PROMPTS_DIR, filename)
    if os.path.isfile(root_path):
        return root_path

    return lang_path


def get_standard_prompt_content(role: str, lang: Optional[str] = None) -> str:
    """Global standart prompt içeriğini okur."""
    path = get_standard_prompt_path(role, lang=lang)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return tx("""# {role} - Şirket Standardı Sistem Promptu
## Persona ve Sorumluluklar
Bu ajan {role} rolünde görev yapmaktadır.

## Proje Kuralları ve Standartlar
- Kod ve mimari kurallarına uygun geliştirme yapın.
- Edge case ve hata durumlarını kontrol edin.
""", lang=lang, role=role)


def _get_history_info(project_path: str, agent_id: str) -> tuple[str, List[Dict[str, Any]]]:
    """Ajanın versiyon geçmişi klasörünü ve versions.json listesini döner."""
    ws_dir = ensure_fs_workspace(project_path)
    agent_hist_dir = os.path.join(ws_dir, "agents", "history", agent_id)
    os.makedirs(agent_hist_dir, exist_ok=True)
    versions_file = os.path.join(agent_hist_dir, "versions.json")

    versions = []
    if os.path.isfile(versions_file):
        try:
            with open(versions_file, "r", encoding="utf-8") as f:
                versions = json.load(f)
        except Exception:
            versions = []
    return agent_hist_dir, versions


def _project_language(project_path: str) -> str:
    """Projenin `.fs-workspace/settings.json` dosyasındaki `project_language` (yoksa ortam varsayılanı)."""
    try:
        with open(os.path.join(project_path, ".fs-workspace", "settings.json"), "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        lang = str(data.get("project_language") or (data.get("settings") or {}).get("project_language") or "").strip().lower()
        if lang in ("tr", "en"):
            return lang
    except Exception:
        pass
    return DEFAULT_PROMPT_LANG


def get_agent_markdown_info(project_path: str, agent_id: str, role: str = "DEVELOPER") -> Dict[str, Any]:
    """
    Ajanın projedeki aktif Markdown dosyasını, versiyon geçmişini ve meta bilgilerini döner.
    Eğer henüz yoksa, global standarttan otomatik olarak kalıtıp (v1) oluşturur.
    """
    ws_dir = ensure_fs_workspace(project_path)
    agent_md_path = os.path.join(ws_dir, "agents", f"{agent_id}.md")
    agent_hist_dir, versions = _get_history_info(project_path, agent_id)

    # Eğer projedeki dosya henüz yoksa standarttan kalıt
    if not os.path.isfile(agent_md_path) or not versions:
        project_lang = _project_language(project_path)         # proje dili (settings.project_language): kopya proje dilindeki standarttan kalıtılır
        standard_content = get_standard_prompt_content(role, lang=project_lang)
        now = datetime.now(timezone.utc).isoformat()
        learn_heading = tx("## 🧠 Öğrenilen Dersler ve Proje Tecrübeleri (Learnings & Memory)", lang=project_lang)
        learn_first = tx("- *Ajan bu projede görev yaptıkça ve kurallar eklendikçe burada yeni tecrübeler birikir.*", lang=project_lang)

        # Projeye özel ön başlık ve öğrenilen tecrübeler bölümü ekle
        initial_content = f"""---
agent_id: {agent_id}
role: {role}
version: 1
parent_standard: agents/prompts/{ROLE_TO_PROMPT_MAP.get(role.upper(), "developer.md")}
inherited_at: {now}
updated_at: {now}
project_scope: {os.path.basename(os.path.abspath(project_path))}
---

{standard_content}

---

{learn_heading}
{learn_first}
"""
        # Aktif dosyayı yaz
        with open(agent_md_path, "w", encoding="utf-8") as f:
            f.write(initial_content)

        # v1 versiyon snapshot'ını kaydet
        v1_file = os.path.join(agent_hist_dir, "v1.md")
        with open(v1_file, "w", encoding="utf-8") as f:
            f.write(initial_content)

        content_hash = hashlib.md5(initial_content.encode("utf-8")).hexdigest()[:8]
        versions = [{
            "version_id": "v1",
            "order": 1,
            "created_at": now,
            "author": "System (Standard Inheritance)",
            "commit_message": tx("Global standart şablondan ({name}) kalıtıldı.", lang=project_lang, name=ROLE_TO_PROMPT_MAP.get(role.upper(), 'standard')),
            "file_name": "v1.md",
            "hash": content_hash
        }]
        with open(os.path.join(agent_hist_dir, "versions.json"), "w", encoding="utf-8") as f:
            json.dump(versions, f, ensure_ascii=False, indent=2)

    with open(agent_md_path, "r", encoding="utf-8") as f:
        active_content = f.read()

    current_v = versions[-1]["version_id"] if versions else "v1"

    return {
        "agent_id": agent_id,
        "role": role,
        "current_version": current_v,
        "active_content": active_content,
        "versions": list(reversed(versions)),  # En yeniden en eskiye sıralı
        "file_path": agent_md_path,
        "parent_standard": ROLE_TO_PROMPT_MAP.get(role.upper(), "developer.md"),
        "total_versions": len(versions)
    }


def save_agent_markdown(
    project_path: str,
    agent_id: str,
    role: str,
    content: str,
    commit_message: str,
    author: str = "User"
) -> Dict[str, Any]:
    """
    Ajanın projedeki Markdown dosyasını günceller ve Git-Tree mantığıyla yeni bir versiyon commit'ler.
    """
    ws_dir = ensure_fs_workspace(project_path)
    agent_md_path = os.path.join(ws_dir, "agents", f"{agent_id}.md")
    agent_hist_dir, versions = _get_history_info(project_path, agent_id)

    next_order = len(versions) + 1
    new_version_id = f"v{next_order}"
    now = datetime.now(timezone.utc).isoformat()
    content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()[:8]

    # Aktif dosyayı güncelle
    with open(agent_md_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Snapshot dosyasını kaydet
    snapshot_file = os.path.join(agent_hist_dir, f"{new_version_id}.md")
    with open(snapshot_file, "w", encoding="utf-8") as f:
        f.write(content)

    # Versiyon kaydını ekle
    version_entry = {
        "version_id": new_version_id,
        "order": next_order,
        "created_at": now,
        "author": author,
        "commit_message": commit_message.strip() or tx("Versiyon {version} güncellemesi", lang=_project_language(project_path), version=new_version_id),
        "file_name": f"{new_version_id}.md",
        "hash": content_hash
    }
    versions.append(version_entry)

    with open(os.path.join(agent_hist_dir, "versions.json"), "w", encoding="utf-8") as f:
        json.dump(versions, f, ensure_ascii=False, indent=2)

    return get_agent_markdown_info(project_path, agent_id, role)


def restore_agent_version(
    project_path: str,
    agent_id: str,
    role: str,
    target_version_id: str,
    author: str = "User"
) -> Dict[str, Any]:
    """
    Ajanın Markdown dosyasını geçmiş bir versiyona geri döndürür (Rollback) ve yeni bir restore commit'i oluşturur.
    """
    ws_dir = ensure_fs_workspace(project_path)
    agent_hist_dir, versions = _get_history_info(project_path, agent_id)

    target_entry = next((v for v in versions if v.get("version_id") == target_version_id), None)
    if not target_entry:
        raise ValueError(tx("Versiyon bulunamadı: {version}", lang=_project_language(project_path), version=target_version_id))

    snapshot_path = os.path.join(agent_hist_dir, target_entry["file_name"])
    if not os.path.isfile(snapshot_path):
        raise FileNotFoundError(tx("Versiyon snapshot dosyası bulunamadı: {path}", lang=_project_language(project_path), path=snapshot_path))

    with open(snapshot_path, "r", encoding="utf-8") as f:
        restored_content = f.read()

    # Yeni bir restore commit'i olarak kaydet
    msg = tx("Geri Yükleme (Rollback): '{version}' versiyonuna dönüldü.", lang=_project_language(project_path), version=target_version_id)
    return save_agent_markdown(
        project_path=project_path,
        agent_id=agent_id,
        role=role,
        content=restored_content,
        commit_message=msg,
        author=f"{author} (Restore)"
    )


def inherit_from_standard(
    project_path: str,
    agent_id: str,
    role: str,
    author: str = "User"
) -> Dict[str, Any]:
    """
    Ajanı global standart şablonla yeniden eşitler ve yeni bir versiyon olarak kaydeder.
    """
    project_lang = _project_language(project_path)
    standard_content = get_standard_prompt_content(role, lang=project_lang)
    now = datetime.now(timezone.utc).isoformat()
    project_name = os.path.basename(os.path.abspath(project_path))

    # Mevcut tecrübeleri korumaya çalış
    info = get_agent_markdown_info(project_path, agent_id, role)
    current_content = info.get("active_content", "")
    learnings_section = ""
    if _learn_index(current_content) != -1:
        learnings_section = current_content[_learn_index(current_content):]
    learn_fallback = tx("## 🧠 Öğrenilen Dersler ve Proje Tecrübeleri (Learnings & Memory)\\n- *Global standart yeniden eşitlendi.*", lang=project_lang)

    new_content = f"""---
agent_id: {agent_id}
role: {role}
parent_standard: agents/prompts/{ROLE_TO_PROMPT_MAP.get(role.upper(), "developer.md")}
re_inherited_at: {now}
project_scope: {project_name}
---

{standard_content}

---

{learnings_section if learnings_section else learn_fallback}
"""

    return save_agent_markdown(
        project_path=project_path,
        agent_id=agent_id,
        role=role,
        content=new_content,
        commit_message=tx("Global standart şablondan ({name}) yeniden kalıtıldı.", lang=project_lang, name=ROLE_TO_PROMPT_MAP.get(role.upper())),
        author=author
    )


def promote_to_global(project_path: str, agent_id: str, role: str) -> Dict[str, Any]:
    """
    Projedeki ajanın Markdown kurallarını ve tecrübelerini şirketin global standardına (agents/prompts/<role>.md) terfi ettirir.
    Mevcut global şablonu backup klasöründe güvenle yedekler.
    """
    info = get_agent_markdown_info(project_path, agent_id, role)
    project_content = info.get("active_content", "")
    if not project_content.strip():
        raise ValueError(tx("Terfi ettirilecek ajan içeriği boş.", lang=_project_language(project_path)))

    standard_filename = ROLE_TO_PROMPT_MAP.get(role.upper(), f"{role.lower()}.md")
    # Hedef: yükleyicinin okuduğu dil klasörü (agents/prompts/<lang>/), kök değil
    lang_dir = os.path.join(GLOBAL_PROMPTS_DIR, DEFAULT_PROMPT_LANG)
    os.makedirs(lang_dir, exist_ok=True)
    target_global_path = os.path.join(lang_dir, standard_filename)

    # Eski global şablonu yedekle (proje .fs-workspace'i altında; depo ağacını kirletmez)
    backup_dir = os.path.join(get_workspace_dir(project_path), "promotions")
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"{standard_filename}_{timestamp}.bak.md")

    if os.path.isfile(target_global_path):
        with open(target_global_path, "r", encoding="utf-8") as f:
            old_global = f.read()
        with open(backup_file, "w", encoding="utf-8") as f:
            f.write(old_global)

    # Proje meta verisi (YAML ön başlık) ve proje tecrübeleri şirket standardına girmez
    promoted = strip_project_sections(project_content)

    with open(target_global_path, "w", encoding="utf-8") as f:
        f.write(promoted)

    return {
        "status": "PROMOTED",
        "standard_file": standard_filename,
        "global_path": target_global_path,
        "backup_path": backup_file,
        "promoted_from_project": project_path,
        "agent_id": agent_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def strip_project_sections(content: str) -> str:
    """Baştaki YAML ön başlığı ve '🧠 Öğrenilen Dersler' bölümünü (projeye özgü) kaldırır."""
    import re as _re
    text = _re.sub(r"\A---\r?\n.*?\r?\n---\r?\n+", "", content, count=1, flags=_re.S)
    idx = _learn_index(text)
    if idx != -1:
        text = text[:idx].rstrip()
        # bölümden hemen önceki ayraç çizgisini de kaldır
        text = _re.sub(r"\n---\s*\Z", "", text).rstrip()
    return text.rstrip() + "\n"


def record_agent_learning(
    project_path: str,
    agent_id: str,
    role: str,
    learning_note: str,
    task_title: str
) -> Optional[Dict[str, Any]]:
    """
    Ajan görev tamamladığında edindiği tecrübeyi .fs-workspace/agents/<agent_id>.md içine otonom ekler.
    """
    try:
        info = get_agent_markdown_info(project_path, agent_id, role)
        content = info.get("active_content", "")
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        
        new_bullet = f"\n- **[{now_str} - {task_title}]**: {learning_note.strip()}"
        
        if _learn_index(content) != -1:
            content += new_bullet
        else:
            content += f"\n\n---\n\n{tx('## 🧠 Öğrenilen Dersler ve Proje Tecrübeleri (Learnings & Memory)', lang=_project_language(project_path))}{new_bullet}\n"

        return save_agent_markdown(
            project_path=project_path,
            agent_id=agent_id,
            role=role,
            content=content,
            commit_message=tx("🧠 Otonom Öğrenim: {title} tecrübesi hafızaya eklendi.", lang=_project_language(project_path), title=task_title),
            author="Autonomous Agent (Self-Learning)"
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Proje Genel Durumunu .fs-workspace ile Senkronize Etme
# ---------------------------------------------------------------------------
def build_workspace_files(project_path: str, project_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Projenin .fs-workspace dizinine yazılacak dosyaları {mutlak_yol: json_metni} olarak üretir.
    Serileştirme çağıranın (event loop) tarafında yapılır; yazım `write_files_atomic` ile
    bir iş parçacığında gerçekleştirilebilir.
    """
    ws_dir = ensure_fs_workspace(project_path)
    settings = {
        "id": project_data.get("id"),
        "name": project_data.get("name"),
        "path": project_path,
        "last_active": project_data.get("last_active", datetime.now(timezone.utc).isoformat()),
        "stats": project_data.get("stats", {}),
        "test_profiles": project_data.get("test_profiles", []),
        "playwright_reports": project_data.get("playwright_reports", []),
        "model_config": project_data.get("model_config", {
            "provider": "gemini",
            "model_id": "gemini-2.5-pro",
            "temperature": 0.2,
            "max_tokens": 8192
        }),
        # Motor / onay modu / hız (Faz B-C ayarları)
        "settings": project_data.get("settings", {}),
    }
    files = {
        os.path.join(ws_dir, "jira_issues.json"): json.dumps(project_data.get("jira_issues", {}), ensure_ascii=False, indent=2),
        os.path.join(ws_dir, "tasks.json"): json.dumps(project_data.get("tasks", {}), ensure_ascii=False, indent=2),
        os.path.join(ws_dir, "specs", "specs.json"): json.dumps(project_data.get("uploaded_specs", []), ensure_ascii=False, indent=2),
        os.path.join(ws_dir, "settings.json"): json.dumps(settings, ensure_ascii=False, indent=2),
    }
    if project_data.get("question_store"):
        files[os.path.join(ws_dir, "questions.json")] = json.dumps(project_data["question_store"], ensure_ascii=False, indent=2)
    if project_data.get("sprint_state"):
        files[os.path.join(ws_dir, "sprint_state.json")] = json.dumps(project_data["sprint_state"], ensure_ascii=False, indent=2)
    ver = (project_data.get("settings") or {}).get("verification")
    if isinstance(ver, dict) and ver:
        # Mimar/DevOps'un önerdiği çalıştırma ve doğrulama komutları: git'e giren yedek (settings.json makine durumudur ve sıfırlanabilir)
        files[os.path.join(ws_dir, "verification.json")] = json.dumps(ver, ensure_ascii=False, indent=2)
    if project_data.get("deliberation"):
        files[os.path.join(ws_dir, "deliberations.json")] = json.dumps(project_data["deliberation"], ensure_ascii=False, indent=2)
    if "runs" in project_data:
        files[os.path.join(ws_dir, "runs.json")] = json.dumps(project_data.get("runs") or [], ensure_ascii=False, indent=2)
    return files


SHRINK_GUARD_MIN_BYTES = 20_000
SHRINK_GUARD_RATIO = 0.2


def _keep_if_shrunk(path: str, new_size: int) -> None:
    """Dolu bir dosya çok küçük (varsayılan/boş) içerikle ezilecekse eskisini `<dosya>.shrunk.bak` olarak sakla
    (registry yeniden oluşunca boş durum çalışma klasörünü ezmişti; geri dönüş yolu kalsın). Yazımı engellemez."""
    try:
        old_size = os.path.getsize(path)
        if old_size >= SHRINK_GUARD_MIN_BYTES and new_size < old_size * SHRINK_GUARD_RATIO:
            shutil.copyfile(path, path + ".shrunk.bak")
    except OSError:
        pass


def write_files_atomic(files: Dict[str, str], backup: Optional[set] = None) -> None:
    """Her dosyayı önce `.tmp` olarak yazıp `os.replace` ile atomik değiştirir (yarım dosya kalmaz).
    `backup` içindeki yollar için önceki sağlam dosya `.bak` olarak saklanır (G3: bozuk kayıt dosyasından kurtarma)."""
    for path, content in files.items():
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        if backup and path in backup and os.path.isfile(path):
            try:
                shutil.copyfile(path, path + ".bak")
            except OSError:
                pass
        _keep_if_shrunk(path, len(content.encode("utf-8")))
        os.replace(tmp_path, path)


def sync_project_to_workspace(project_path: str, project_data: Dict[str, Any]):
    """Tüm Jira görevlerini, şartnameleri ve ayarları projenin .fs-workspace dizinine senkron kaydeder."""
    try:
        write_files_atomic(build_workspace_files(project_path, project_data))
    except Exception:
        pass


def load_project_from_workspace(project_path: str) -> Optional[Dict[str, Any]]:
    """Eğer projenin .fs-workspace dizini varsa oradaki güncel verileri okur."""
    try:
        ws_dir = get_workspace_dir(project_path)
        if not os.path.isdir(ws_dir):
            return None

        result: Dict[str, Any] = {}

        # Jira
        jira_file = os.path.join(ws_dir, "jira_issues.json")
        if os.path.isfile(jira_file):
            with open(jira_file, "r", encoding="utf-8") as f:
                result["jira_issues"] = json.load(f)

        # Tasks
        tasks_file = os.path.join(ws_dir, "tasks.json")
        if os.path.isfile(tasks_file):
            with open(tasks_file, "r", encoding="utf-8") as f:
                result["tasks"] = json.load(f)

        # Specs
        specs_file = os.path.join(ws_dir, "specs", "specs.json")
        if os.path.isfile(specs_file):
            with open(specs_file, "r", encoding="utf-8") as f:
                result["uploaded_specs"] = json.load(f)

        # Soru kuyruğu (F4)
        questions_file = os.path.join(ws_dir, "questions.json")
        if os.path.isfile(questions_file):
            with open(questions_file, "r", encoding="utf-8") as f:
                result["question_store"] = json.load(f)

        # Sprint durumu (F3)
        sprint_file = os.path.join(ws_dir, "sprint_state.json")
        if os.path.isfile(sprint_file):
            with open(sprint_file, "r", encoding="utf-8") as f:
                result["sprint_state"] = json.load(f)

        ver_file = os.path.join(ws_dir, "verification.json")
        if os.path.isfile(ver_file):
            with open(ver_file, "r", encoding="utf-8") as fh:
                result["verification"] = json.load(fh)

        # Koşu geçmişi ve müzakere oturumları
        for key, fname in (("runs", "runs.json"), ("deliberation", "deliberations.json")):
            p = os.path.join(ws_dir, fname)
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as fh:
                    result[key] = json.load(fh)

        # Settings
        settings_file = os.path.join(ws_dir, "settings.json")
        if os.path.isfile(settings_file):
            with open(settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
                result["stats"] = settings.get("stats")
                result["test_profiles"] = settings.get("test_profiles")
                result["playwright_reports"] = settings.get("playwright_reports")
                result["last_active"] = settings.get("last_active")
                result["model_config"] = settings.get("model_config")
                result["settings"] = settings.get("settings")

        return result
    except Exception:
        return None
