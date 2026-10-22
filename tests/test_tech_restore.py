"""Teknoloji kararları durum kaydı kaybolsa da onaylı TECH_REQUIREMENTS.md'den geri kurulur (yeniden sorulmaz)."""
import os

from server import tech_requirements as TR

DOC = """# Teknoloji gereksinimleri: demo

- **Durum:** ONAYLANDI · **İlk onay:** 2026-10-12, MANAGER
- **Kaynaklar:** Şartname

## 1. Teknolojiler
| # | Kategori | Karar | Notlardaki durum | Kaynak ve alıntı | Onay | ADR |
|---|---|---|---|---|---|---|
| TR-1 | Backend dili ve çatısı hangisi olsun? | Node.js/NestJS | ÇELİŞKİLİ → Q-1 | Şartname: "js/NestJS öneriyor | ışma zamanı modeli" | MANAGER, 2026-10-12 | 0001 |
| TR-2 | Veritabanı | PostgreSQL (+PostGIS) | ÇELİŞKİLİ → Q-2 | Şartname: "PostGIS" | MANAGER, 2026-10-12 | 0001 |
| TR-3 | Barındırma | Global düzeyde olacak ancak ilk Türkiye | EKSİK → Q-3 | Notlarda yok | MANAGER, 2026-10-12 | 0001 |
| TR-4 | Bekleyen | - | EKSİK → Q-4 | Notlarda yok | — | - |
"""


def test_onayli_belge_ayristirilir_alinti_hucresindeki_boru_isaretine_dayanir():
    got = TR.parse_approved_markdown(DOC)
    assert set(got) == {"TR-1", "TR-2", "TR-3"}                        # TR-4 onaysız: alınmaz
    assert got["TR-1"] == {"value": "Node.js/NestJS", "by": "MANAGER", "at": "2026-10-12", "adr": "0001"}
    assert got["TR-3"]["value"] == "Global düzeyde olacak ancak ilk Türkiye"


def test_onaysiz_belge_bos_doner():
    assert TR.parse_approved_markdown(DOC.replace("**Durum:** ONAYLANDI", "**Durum:** ONAY BEKLİYOR")) == {}
    assert TR.parse_approved_markdown("") == {}


async def test_hub_durum_kaybinda_kararlari_belgeden_geri_kurar(hub, tmp_project):
    from server.paths import hub_docs_path
    rel = hub_docs_path(hub, "TECH_REQUIREMENTS.md", tmp_project)
    os.makedirs(os.path.dirname(os.path.join(tmp_project, *rel.split("/"))), exist_ok=True)
    rows = "\n".join(f"| TR-{n} | etiket | Karar-{n} | ÇELİŞKİLİ → Q-{n} | Şartname | MANAGER, 2026-10-12 | 0001 |" for n in range(1, 8))
    with open(os.path.join(tmp_project, *rel.split("/")), "w", encoding="utf-8") as f:
        f.write("# T\n\n- **Durum:** ONAYLANDI · **İlk onay:** 2026-10-12, MANAGER\n\n## 1. Teknolojiler\n| # | K | K | N | K | O | A |\n|---|---|---|---|---|---|---|\n" + rows + "\n")
    hub.settings = {k: v for k, v in hub.settings.items() if k not in ("tech_requirements", "tech_decisions")}   # durum kaydı kaybolmuş
    req = await hub.ensure_tech_requirements(tmp_project)
    assert TR.is_approved(req) and [it["value"] for it in req["items"]] == [f"Karar-{n}" for n in range(1, 8)]
    assert not any(q.get("status") == "AÇIK" for q in req["questions"])        # engelleyici soru kalmadı
    assert hub.tech_requirements_approved()


async def test_bos_ama_bekleyen_kayit_da_belgeden_geri_kurulur(hub, tmp_project):
    """Saha durumu: durum kaydı yeniden kurulmuş (hiç onaylı kalem yok); belge hâlâ onaylı."""
    from server.paths import hub_docs_path
    rel = hub_docs_path(hub, "TECH_REQUIREMENTS.md", tmp_project)
    path = os.path.join(tmp_project, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = "\n".join(f"| TR-{n} | etiket | Karar-{n} | ÇELİŞKİLİ → Q-{n} | Şartname | MANAGER, 2026-10-12 | 0001 |" for n in range(1, 8))
    with open(path, "w", encoding="utf-8") as f:
        f.write("# T\n\n- **Durum:** ONAYLANDI · **İlk onay:** 2026-10-12, MANAGER\n\n## 1. Teknolojiler\n| # | K | K | N | K | O | A |\n|---|---|---|---|---|---|---|\n" + rows + "\n")
    pending = TR.build_requirements(hub.tech_questions(), "", "", tmp_project)           # hiç onaylı kalem yok
    hub.settings = {**hub.settings, "tech_requirements": pending}
    assert not TR.is_approved(hub.tech_requirements())
    req = await hub.ensure_tech_requirements(tmp_project)
    assert TR.is_approved(req) and req["items"][0]["value"] == "Karar-1" and hub.tech_requirements_approved()
