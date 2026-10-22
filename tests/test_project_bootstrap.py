import json

from server import project_bootstrap as PB
from server.scm import merge_gitignore


def test_bootstrap_yeni_klasor(tmp_path):
    res = PB.bootstrap_project(str(tmp_path), "demo")
    assert set(res["changed"]) == {".mcp.json", ".agents/mcp_config.json", "CLAUDE.md", "GEMINI.md", ".gitignore"}
    cfg = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    srv = cfg["mcpServers"]["fssc-visual-observer"]
    assert srv["cwd"] == PB.REPO_ROOT and srv["args"][-2:] == ["--mode", "stdio"]
    md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert PB.BEGIN in md and PB.END in md and 'project_id="demo"' in md
    assert ".mcp.json" in (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert json.loads((tmp_path / ".agents" / "mcp_config.json").read_text(encoding="utf-8")) == cfg
    assert PB.BEGIN in (tmp_path / "GEMINI.md").read_text(encoding="utf-8")


def test_bootstrap_idempotent_ve_yol_guncelleme(tmp_path, monkeypatch):
    PB.bootstrap_project(str(tmp_path), "demo")
    assert PB.bootstrap_project(str(tmp_path), "demo")["changed"] == []
    # depo taşındı: bir sonraki bağlanışta .mcp.json yeni yolla yeniden yazılır
    monkeypatch.setattr(PB, "REPO_ROOT", str(tmp_path / "yeni-konum"))
    assert PB.bootstrap_project(str(tmp_path), "demo")["changed"] == [".mcp.json", ".agents/mcp_config.json"]
    assert "yeni-konum" in (tmp_path / ".mcp.json").read_text(encoding="utf-8")


def test_var_olan_claude_md_korunur(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# Benim kurallarım\nTürkçe yorum yaz.\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("node_modules/", encoding="utf-8")
    PB.bootstrap_project(str(tmp_path), "demo")
    PB.bootstrap_project(str(tmp_path), "yeni-ad")
    md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert md.startswith("# Benim kurallarım\nTürkçe yorum yaz.\n")
    assert md.count(PB.BEGIN) == 1 and 'project_id="yeni-ad"' in md and 'project_id="demo"' not in md
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines() == ["node_modules/", ".mcp.json", ".agents/mcp_config.json"]


def test_strip_block_ajan_baglami():
    md = "# X\nkural\n\n" + PB.claude_block("demo")
    out = PB.strip_block(md)
    assert "kural" in out and "start_pipeline_run" not in out and PB.BEGIN not in out


def test_scm_gitignore_mcp_json():
    assert ".mcp.json" in merge_gitignore("")


def test_projeyi_baglayinca_claude_dosyalari_yazilir(client, tmp_path):
    d = tmp_path / "yeni-proje"
    res = client.post("/api/projects/add", json={"path": str(d), "name": "Yeni"}).json()
    assert set(res["claude_files"]) == {".mcp.json", ".agents/mcp_config.json", "CLAUDE.md", "GEMINI.md", ".gitignore"}
    assert client.post("/api/projects/add", json={"path": str(d), "name": "Yeni"}).json()["claude_files"] == []


def test_blok_dongunun_kendiliginden_bitmemesini_soyler():
    from server.project_bootstrap import claude_block
    b = claude_block("p")
    assert "Durma:" in b and "get_next_step" in b and "devam edeyim mi" in b


def test_adim_talimati_ve_blok_kullaniciya_soru_sormayi_yasaklar():
    from server.engine.mcp_client import CLIENT_INSTRUCTIONS
    from server.project_bootstrap import claude_block
    assert "KULLANICIYA SORU SORMA" in CLIENT_INSTRUCTIONS and "devam edeyim mi" in CLIENT_INSTRUCTIONS and "`questions`" in CLIENT_INSTRUCTIONS
    assert "Soru sorma:" in claude_block("p")
