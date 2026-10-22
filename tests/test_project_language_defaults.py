"""Proje dili değişince hub'ın başlangıçta ürettiği varsayılan nesneler (JIRA-1..10, varsayılan ajan açıklamaları, hazır test profilleri) yeni dile çevrilir.

Kurallar: `tr` çıktısı birebir aynı kalır; yalnızca hâlâ varsayılan metni taşıyan alanlar çevrilir (kullanıcı/ajan düzenlediği alan ezilmez); ajan kimlikleri değişmez.
"""
from server import i18n as I18N
from server.config import DEFAULT_AGENTS, OPTIONAL_AGENTS
from server.telemetry import create_default_jira_issues, create_default_test_profiles, retranslate_defaults


def _tr_issues():
    return create_default_jira_issues("tr")


def _en_issues():
    return create_default_jira_issues("en")


def test_default_issue_factory_follows_the_language():
    tr, en = _tr_issues(), _en_issues()
    assert tr["JIRA-1"]["title"] == "Müşteri Görüşmeleri & PRD Gereksinim Analizi"            # tr: Türkçe kaynak aynen
    assert en["JIRA-1"]["title"] != tr["JIRA-1"]["title"] and "Müşteri" not in en["JIRA-1"]["title"]
    for key, issue in en.items():
        assert issue["id"] == tr[key]["id"] and issue["assignee"] == tr[key]["assignee"] and issue["key"] == tr[key]["key"]      # kimlikler değişmez
        assert len(issue["acceptance_criteria"]) == len(tr[key]["acceptance_criteria"])
        assert not any(ch in issue["title"] + issue["description"] for ch in "ığüşöçİĞÜŞÖÇ"), key                               # İngilizce değerde Türkçe harf kalmaz
    with I18N.use_lang("en"):                                                                                                  # lang verilmezse aktif dil
        assert create_default_issues_title() == en["JIRA-1"]["title"]


def create_default_issues_title():
    return create_default_jira_issues()["JIRA-1"]["title"]


async def test_tr_default_is_unchanged_and_switching_to_en_translates_defaults(hub):
    try:
        assert hub.jira_issues["JIRA-1"]["title"] == "Müşteri Görüşmeleri & PRD Gereksinim Analizi"
        before_agents = {a: dict(v) for a, v in hub.agents.items()}
        await hub.update_settings({"project_language": "tr"})                                    # değişiklik yok: hiçbir şey çevrilmez / değişmez
        assert hub.jira_issues["JIRA-1"]["title"] == "Müşteri Görüşmeleri & PRD Gereksinim Analizi"
        assert {a: v["description"] for a, v in hub.agents.items()} == {a: v["description"] for a, v in before_agents.items()}

        await hub.update_settings({"project_language": "en"})
        en = _en_issues()
        assert hub.settings["project_language"] == "en"
        for key in ("JIRA-1", "JIRA-5", "JIRA-10"):
            assert hub.jira_issues[key]["title"] == en[key]["title"]
            assert hub.jira_issues[key]["description"] == en[key]["description"]
            assert hub.jira_issues[key]["acceptance_criteria"] == en[key]["acceptance_criteria"]
        assert hub.jira_issues["JIRA-1"]["title"] != _tr_issues()["JIRA-1"]["title"]
        # varsayılan ajanlar: kimlik/ad aynı, açıklama İngilizce
        assert set(hub.agents) >= {a["id"] for a in DEFAULT_AGENTS}
        for a in DEFAULT_AGENTS:
            assert hub.agents[a["id"]]["id"] == a["id"] and hub.agents[a["id"]]["name"] == a["name"]
            assert hub.agents[a["id"]]["description"] == I18N.translate(a["description"], "en")
            assert not any(ch in hub.agents[a["id"]]["description"] for ch in "ığüşöçİĞÜŞÖÇ"), a["id"]
        for a in OPTIONAL_AGENTS:
            if a["id"] in hub.agents:
                assert hub.agents[a["id"]]["description"] == I18N.translate(a["description"], "en")
        # hazır test profilleri
        admin = next(p for p in hub.test_profiles if p["id"] == "preset-admin")
        assert admin["name"] == create_default_test_profiles("en")[0]["name"] and admin["name"] != create_default_test_profiles("tr")[0]["name"]
    finally:
        await hub.update_settings({"project_language": "tr"})
    # geri tr: tamamen eski Türkçe metinler
    tr = _tr_issues()
    for key in ("JIRA-1", "JIRA-5", "JIRA-10"):
        assert hub.jira_issues[key]["title"] == tr[key]["title"]
        assert hub.jira_issues[key]["description"] == tr[key]["description"]
        assert hub.jira_issues[key]["acceptance_criteria"] == tr[key]["acceptance_criteria"]
    for a in DEFAULT_AGENTS:
        assert hub.agents[a["id"]]["description"] == a["description"]


async def test_user_edited_fields_are_not_overwritten(hub):
    tr = _tr_issues()
    try:
        # kullanıcı JIRA-2 başlığını ve ilk kabul kriterini, bir ajanın açıklamasını, bir test profilinin adını düzenlemiş
        hub.jira_issues["JIRA-2"]["title"] = "Ödeme sistemi mimarisi"
        hub.jira_issues["JIRA-2"]["acceptance_criteria"][0] = "Ödeme sözleşmesi donduruldu"
        hub.agents["QA"]["description"] = "Mobil testler ve performans ölçümü"
        next(p for p in hub.test_profiles if p["id"] == "preset-user")["name"] = "Bizim müşteri"
        custom_id = "JIRA-99"
        hub.jira_issues[custom_id] = {**tr["JIRA-1"], "id": custom_id, "key": "DEV-99", "title": tr["JIRA-1"]["title"] + " (özel)"}

        await hub.update_settings({"project_language": "en"})
        en = _en_issues()
        assert hub.jira_issues["JIRA-2"]["title"] == "Ödeme sistemi mimarisi"                                   # düzenlenen alan ezilmedi
        assert hub.jira_issues["JIRA-2"]["acceptance_criteria"][0] == "Ödeme sözleşmesi donduruldu"
        assert hub.jira_issues["JIRA-2"]["acceptance_criteria"][1:] == en["JIRA-2"]["acceptance_criteria"][1:]   # dokunulmamış maddeler çevrildi
        assert hub.jira_issues["JIRA-2"]["description"] == en["JIRA-2"]["description"]                          # aynı maddenin dokunulmamış alanı çevrildi
        assert hub.agents["QA"]["description"] == "Mobil testler ve performans ölçümü"
        assert next(p for p in hub.test_profiles if p["id"] == "preset-user")["name"] == "Bizim müşteri"
        assert hub.jira_issues[custom_id]["title"].endswith("(özel)")                                           # özel madde olduğu gibi
        assert hub.agents["PM"]["description"] == I18N.translate(next(a for a in DEFAULT_AGENTS if a["id"] == "PM")["description"], "en")

        await hub.update_settings({"project_language": "tr"})
        assert hub.jira_issues["JIRA-2"]["title"] == "Ödeme sistemi mimarisi"
        assert hub.jira_issues["JIRA-2"]["acceptance_criteria"][1:] == tr["JIRA-2"]["acceptance_criteria"][1:]
        assert hub.agents["QA"]["description"] == "Mobil testler ve performans ölçümü"
        assert hub.agents["PM"]["description"] == next(a for a in DEFAULT_AGENTS if a["id"] == "PM")["description"]
    finally:
        await hub.update_settings({"project_language": "tr"})


async def test_retranslate_defaults_is_idempotent_and_reports_counts(hub):
    try:
        await hub.update_settings({"project_language": "en"})
        assert retranslate_defaults(hub, "en") == {"jira": 0, "agents": 0, "profiles": 0}                      # zaten İngilizce: değişen yok
        counts = retranslate_defaults(hub, "tr")
        assert counts["jira"] > 0 and counts["agents"] > 0 and counts["profiles"] > 0
        assert hub.jira_issues["JIRA-1"]["title"] == _tr_issues()["JIRA-1"]["title"]
    finally:
        await hub.update_settings({"project_language": "tr"})
