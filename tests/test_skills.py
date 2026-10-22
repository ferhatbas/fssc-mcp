"""Skill kütüphanesi ve isteğe bağlı çekirdek ajanlar: katalog geçerli, rol başına skill seçimi, istem bölümü, ayar doğrulama, ajanlar kaldırılabilir/geri yüklenir."""
import json

from server import skills as SKL
from server.agent_registry import match_by_capability, routing_roles


def test_katalog_gecerli_ve_varsayilanlar_rol_basina_sinirli():
    cat = SKL.catalog()
    ids = [s["id"] for s in cat["skills"]]
    assert len(ids) == len(set(ids)) >= 30 and all(s["category"] and s["title"] and s["summary"] for s in cat["skills"])
    roles = {r for s in cat["skills"] for r in s["default_roles"]}
    assert {"BACKEND_DEV", "FRONTEND_DEV", "DESIGNER", "QA", "DEVOPS", "ARCHITECT", "DOCUMENTOR", "SECURITY_REVIEWER", "MOBILE_DESIGNER", "SEO_OPTIMIZER", "CODE_REVIEWER"} <= roles
    for r in roles:
        assert len([s for s in cat["skills"] if r in s["default_roles"]]) <= SKL.MAX_PER_ROLE + 1


async def test_rol_icin_varsayilan_ve_kullanici_secimi(hub):
    assert "frontend-design" in SKL.skills_for_role(hub, "DESIGNER")
    assert "security-best-practices" in SKL.skills_for_role(hub, "SECURITY_REVIEWER")
    await hub.update_settings({"agent_skills": {"roles": {"DESIGNER": ["clean-code", "yok-boyle-skill"]}, "max_chars": 99999999}})
    assert SKL.skills_for_role(hub, "DESIGNER") == ["clean-code"]                     # bilinmeyen kimlik süzülür
    assert hub.get_settings()["agent_skills"]["max_chars"] == 20000                   # bütçe sınırlanır
    await hub.update_settings({"agent_skills": {"enabled": False}})
    assert SKL.prompt_section(hub, "DESIGNER") == ""


async def test_istem_bolumu_onbellekteki_skilli_ozetler_oncelik_notu_koyar(hub, tmp_path, monkeypatch):
    monkeypatch.setenv("FSSC_SKILLS_CACHE", str(tmp_path))
    monkeypatch.setattr(SKL, "prefetch", lambda ids: None)                              # test ağa çıkmaz
    (tmp_path / "frontend-design.md").write_text("---\nname: frontend-design\n---\n# Başlık\n" + "içerik satırı\n" * 600, encoding="utf-8")
    text = SKL.prompt_section(hub, "DESIGNER")
    assert "## Ek yetenekler" in text and "ÖNCELİKLİDİR" in text and "frontend-design" in text and "name: frontend-design" not in text
    assert len(text) < 4500 and "kısaltıldı" in text
    assert SKL.prompt_section(hub, "QA") == ""                                          # önbellekte yoksa eklenmez (adım bekletilmez)


async def test_varsayilan_istege_bagli_ajanlar_gelir_kaldirilir_geri_yuklenir(hub):
    for aid in ("MOBILE_DESIGNER", "SECURITY_REVIEWER", "SEO_OPTIMIZER", "CODE_REVIEWER"):
        assert hub.agents[aid]["active"] and hub.agents[aid]["default_optional"]
    assert await hub.delete_agent("SEO_OPTIMIZER") is True and "SEO_OPTIMIZER" not in hub.agents
    hub._ensure_optional_agents()
    assert "SEO_OPTIMIZER" not in hub.agents                                            # kaldırılan geri gelmez
    assert await hub.restore_default_agents() == ["SEO_OPTIMIZER"] and "SEO_OPTIMIZER" in hub.agents


async def test_odak_sozcugu_rolsuz_gorevi_uzmana_yonlendirir_genel_gorevi_kapmaz(hub):
    roles = routing_roles(hub)
    assert match_by_capability(roles, "SECURITY_TEST", "OWASP zafiyet taraması yap") == "SECURITY_REVIEWER"
    assert match_by_capability(roles, "IMPROVEMENT", "SEO için meta etiketleri ve sitemap ekle") == "SEO_OPTIMIZER"
    assert match_by_capability(roles, "DESIGN", "mobil tasarım sistemi hazırla") == "MOBILE_DESIGNER"
    assert match_by_capability(roles, "REFACTOR", "kod incelemesi sonrası teknik borç") == "CODE_REVIEWER"
    assert match_by_capability(roles, "FEATURE", "Etkinlik oluşturma ekranı") is None
