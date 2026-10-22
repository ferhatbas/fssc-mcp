"""F1 / A14: üretim kodunda sabit `docs/` yolu kalmadığını denetler (yol `server/paths.py` yardımcısından gelir)."""

import re
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent / "server"

# Muaf dosyalar: yardımcının kendisi, göç (eski yolu bilmek zorunda), demo/örnek metin üreten modüller (faz raporunda belirtildi);
# layout.py / migrate_layout.py belge klasörünün varsayılan adını tanımlar ve eski adlarla (FS-docs, docs) eşleştirir (docs/klasor-duzeni.md)
EXEMPT = {"paths.py", "migrate_docs.py", "config.py", "telemetry.py", "layout.py", "migrate_layout.py", "project_files.py"}   # project_files: eski ve yeni belge klasörü adlarını tarar

PATTERN = re.compile(r"""(["'`])docs(/|\\)|["']docs["']|\bos\.path\.join\([^)]*["']docs["']""")


def test_no_hardcoded_docs_paths_in_server():
    offenders = []
    for path in SERVER.rglob("*.py"):
        if path.name in EXEMPT or "locales" in path.parts:      # locales: çeviri kataloğu metinleri (kod yolu değil)
            continue
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if PATTERN.search(line):
                offenders.append(f"{path.relative_to(SERVER.parent)}:{no}: {line.strip()[:120]}")
    assert not offenders, "Sabit docs/ yolu bulundu (server/paths.py kullanın):\n" + "\n".join(offenders)


def test_prompt_files_use_placeholder():
    prompts = SERVER.parent / "agents" / "prompts"
    bad = []
    for path in prompts.rglob("*.md"):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"(?<![\w{}/-])docs/", line):
                bad.append(f"{path.relative_to(SERVER.parent)}:{no}")
    assert not bad, "Prompt dosyalarında sabit docs/ yolu: " + ", ".join(bad)
