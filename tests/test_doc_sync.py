"""ARCHITECTURE.md: ajanın yazdığı bayat "Onaysız konular"/olmayan yollar yanında, sunucunun ürettiği güncel karar durumu bölümü."""
import os

from server import doc_sync as DS
from server import sprint as SP
from server.paths import hub_docs_path

ARCH = """# EventPulse Mimari

## Çözüm yapısı
- `apps/backend/package.json`: NestJS uygulaması
- `apps/backend/src/<modül>/`: modüller
- `db/schema.sql`: PostgreSQL şeması
- `test/e2e/`: uçtan uca senaryolar
- `docs/`: PRD

## Onaysız konular (yönetici kararı bekliyor)
1. Docker: onaylı listede yok; Dockerfile üretilmez.
"""


def _arch(hub, tmp_project):
    rel = hub_docs_path(hub, "ARCHITECTURE.md", tmp_project)
    path = os.path.join(tmp_project, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(ARCH)
    os.makedirs(os.path.join(tmp_project, "apps", "backend"), exist_ok=True)
    open(os.path.join(tmp_project, "apps", "backend", "package.json"), "w").write("{}")
    os.makedirs(os.path.join(tmp_project, os.path.dirname(rel)), exist_ok=True)
    return path


def test_yol_denetimi_yer_tutucu_ve_desenleri_atlar():
    assert DS.structure_paths(ARCH) == ["apps/backend/package.json", "db/schema.sql", "test/e2e/", "docs/"]


async def test_guncel_karar_bolumu_yazilir_ve_tekrarsiz(hub, tmp_project):
    path = _arch(hub, tmp_project)
    SP.ensure_state(hub)["decisions"] = [{"id": "DEC-4", "text": "Dağıtım için Docker kullanılsın mı? → Evet", "adr": "docs/adr/0002-docker.md", "sprint": 1}]
    assert DS.sync_architecture(hub, tmp_project)
    text = open(path, encoding="utf-8").read()
    assert "Onaysız konular (yönetici kararı bekliyor)" in text                       # ajanın metni silinmez
    assert "Güncel karar durumu (FS-SC otomatik)" in text and "bu bölüm geçerlidir" in text
    assert "DEC-4" in text and "docs/adr/0002-docker.md" in text
    assert "- `db/schema.sql`" in text and "- `test/e2e/`" in text and "- `apps/backend/package.json`" not in text.split(DS.BEGIN)[1]
    assert "Açık yönetici sorusu yok" in text                                             # hub fixture'ında teknoloji kapısı onaylı
    assert DS.sync_architecture(hub, tmp_project) is None and open(path, encoding="utf-8").read().count(DS.BEGIN) == 1


async def test_belge_yoksa_dokunmaz(hub, tmp_project):
    assert DS.sync_architecture(hub, tmp_project) is None
