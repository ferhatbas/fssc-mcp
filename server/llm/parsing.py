"""
LLM / MCP istemcisinden gelen adım çıktısını toleranslı biçimde ayrıştırır.

Beklenen zarf (A2A):
{
  "trace_id": "...", "from_agent": "PM", "to_agent": "ARCHITECT",
  "intent": "TASK_DISPATCH", "status": "SUCCESS",
  "payload": {
     "summary": "...", "files": [{"path": "{docs_root}/PRD.md", "content": "..."}],
     "friendly_dialogue": "...", "thinking": "...", "what_doing": "...", "what_next": "..."
  },
  "metadata": {"tokens_used": 0, "current_file": "{docs_root}/PRD.md"}
}
Model bazen JSON'u ```json çiti içinde, bazen düz metin arasında verir; hepsi denenir.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from ..i18n import translate as tx, N_

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n(.*?)\n\s*```", re.S)


class StepOutputError(ValueError):
    def __init__(self, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.errors = errors or [message]


def _balanced_json_object(text: str) -> Optional[str]:
    """Metindeki ilk dengeli `{...}` bloğunu döner (string içi süslü parantezleri atlar)."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        start = text.find("{", start + 1)
    return None


def extract_json_block(text: str) -> Tuple[Dict[str, Any], str]:
    """
    Sırasıyla dener: (1) son ```json çiti, (2) ilk dengeli JSON nesnesi, (3) tüm metin.
    (nesne, ham_json_metni) döner; hiçbiri geçerli değilse StepOutputError fırlatır.
    """
    if text is None:
        raise StepOutputError(tx("Boş çıktı."))
    if isinstance(text, dict):
        return text, json.dumps(text, ensure_ascii=False)
    candidates: List[str] = []
    fences = _FENCE_RE.findall(text)
    if fences:
        candidates.append(fences[-1])
    balanced = _balanced_json_object(text)
    if balanced:
        candidates.append(balanced)
    candidates.append(text.strip())

    last_error = tx("JSON bulunamadı")
    for raw in candidates:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = tx("JSON ayrıştırma hatası: {msg} (satır {line})", msg=e.msg, line=e.lineno)
            continue
        if isinstance(obj, dict):
            return obj, raw
        last_error = tx("JSON kökü bir nesne değil")
    raise StepOutputError(last_error)


def normalize_a2a(
    obj: Dict[str, Any],
    *,
    default_from: str,
    default_to: Optional[str],
    default_intent: str,
    trace_id: str,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Zarfı bilinen alanlara indirger; eksikleri varsayılanlarla doldurur.
    Geri dönüş: (normalize_zarf, uyarılar). Kritik eksikler StepOutputError fırlatır.
    """
    warnings: List[str] = []
    payload = obj.get("payload")
    if payload is None:
        # Zarf yerine doğrudan payload gönderilmiş olabilir
        if any(k in obj for k in ("summary", "files", "user_stories", "endpoints")):
            payload = {k: v for k, v in obj.items() if k not in ("trace_id", "from_agent", "to_agent", "intent", "status", "metadata")}
            warnings.append(tx("Zarf eksik: kök nesne payload olarak kabul edildi."))
        else:
            payload = {}
            warnings.append(tx("payload alanı yok; boş kabul edildi."))
    if not isinstance(payload, dict):
        raise StepOutputError(tx("payload bir nesne olmalı."), [tx("payload bir nesne olmalı")])

    files = payload.get("files") or []
    if not isinstance(files, list):
        raise StepOutputError(tx("payload.files bir liste olmalı."), [tx("payload.files bir liste olmalı")])
    clean_files: List[Dict[str, str]] = []
    for idx, f in enumerate(files):
        if not isinstance(f, dict) or not f.get("path") or f.get("content") is None:
            raise StepOutputError(
                tx("payload.files[{idx}] için 'path' ve 'content' zorunlu.", idx=idx),
                [tx("payload.files[{idx}]: path/content eksik", idx=idx)]
            )
        clean_files.append({
            "path": str(f["path"]).strip().replace("\\", "/"),
            "content": f["content"] if isinstance(f["content"], str) else json.dumps(f["content"], ensure_ascii=False, indent=2),
        })
    payload["files"] = clean_files

    from_agent = str(obj.get("from_agent") or default_from).upper().strip()
    to_agent = str(obj.get("to_agent") or default_to or "PM").upper().strip()
    intent = str(obj.get("intent") or obj.get("action") or default_intent).upper().strip()
    status = str(obj.get("status") or "SUCCESS").upper().strip()
    if status not in ("SUCCESS", "FAILED", "IN_PROGRESS", "BLOCKED", "PENDING"):
        warnings.append(tx("Bilinmeyen status '{status}', SUCCESS kabul edildi.", status=status))
        status = "SUCCESS"

    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    tokens_used = metadata.get("tokens_used", payload.get("tokens_used", 0))
    try:
        tokens_used = int(tokens_used or 0)
    except (TypeError, ValueError):
        tokens_used = 0

    if not payload.get("summary") and isinstance(obj.get("summary"), str) and obj["summary"].strip():
        payload["summary"] = obj["summary"].strip()          # §10.8: `summary` zarfın kökünde de gelebilir
    if not payload.get("handoff") and isinstance(obj.get("handoff"), list):
        payload["handoff"] = obj["handoff"]                  # §10.8: devir notları zarfın kökünde de gelebilir
    if not payload.get("summary"):
        payload["summary"] = tx("{agent} adımı tamamlandı ({intent}).", agent=from_agent, intent=intent)
        warnings.append(tx("payload.summary eksik; varsayılan üretildi."))

    return {
        "trace_id": obj.get("trace_id") or trace_id,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "intent": intent,
        "status": status,
        "payload": payload,
        "metadata": {
            "tokens_used": tokens_used,
            "current_file": metadata.get("current_file") or (clean_files[0]["path"] if clean_files else None),
        },
    }, warnings
