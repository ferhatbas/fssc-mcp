"""Claude Desktop'ın paketlediği Claude Code CLI'si PATH'te olmasa da bulunur (başsız otomatik runner için)."""
import os

from server import claude_bridge as CB


def _fake_desktop(tmp_path, versions):
    root = tmp_path / "Claude" / "claude-code"
    exe = "claude.exe" if os.name == "nt" else "claude"
    paths = {}
    for ver, h in versions:
        d = root / ver / h
        d.mkdir(parents=True)
        (d / exe).write_text("x")
        paths[ver] = str(d / exe)
    return paths


def test_en_yeni_surum_secilir(tmp_path, monkeypatch):
    paths = _fake_desktop(tmp_path, [("2.1.293", "aaa"), ("2.1.295", "bbb"), ("2.1.9", "ccc")])
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(CB.os.path, "expanduser", lambda p: str(tmp_path / "yok"))
    assert CB.desktop_bundled_cli() == paths["2.1.295"]                    # 2.1.9 < 2.1.293 < 2.1.295 (sayısal karşılaştırma)


def test_path_te_yoksa_paketlenmis_cli_kullanilir(tmp_path, monkeypatch):
    paths = _fake_desktop(tmp_path, [("2.1.295", "bbb")])
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(CB.os.path, "expanduser", lambda p: str(tmp_path / "yok"))
    monkeypatch.setattr(CB.shutil, "which", lambda *_a, **_k: None)
    assert CB._split_cli("claude") == [paths["2.1.295"]]
    assert CB._split_cli("claude --verbose")[0] == paths["2.1.295"] and CB._split_cli("claude --verbose")[1:] == ["--verbose"]
    assert CB._resolve_exe("baska-arac") is None                            # yalnızca varsayılan `claude` adı için


def test_path_te_varsa_o_kullanilir(tmp_path, monkeypatch):
    _fake_desktop(tmp_path, [("2.1.295", "bbb")])
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(CB.shutil, "which", lambda name, *_a, **_k: "C:/bin/claude.exe" if name == "claude" else None)
    assert CB._split_cli("claude") == ["claude"]


def test_masaustu_cli_yoksa_none(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "bos"))
    monkeypatch.setattr(CB.os.path, "expanduser", lambda p: str(tmp_path / "yok"))
    assert CB.desktop_bundled_cli() is None


def test_basisiz_oturum_ucretli_api_degiskenlerini_tasimaz():
    env = {"PATH": "x", "ANTHROPIC_API_KEY": "sk-test", "anthropic_auth_token": "t", "ANTHROPIC_BASE_URL": "https://proxy", "CLAUDE_CODE_USE_BEDROCK": "1",
           "AWS_BEARER_TOKEN_BEDROCK": "b", "CLAUDE_CODE_OAUTH_TOKEN": "abonelik-tokeni", "HOME": "h"}
    clean = CB.subscription_only_env(env)
    assert clean == {"PATH": "x", "CLAUDE_CODE_OAUTH_TOKEN": "abonelik-tokeni", "HOME": "h"}      # abonelik girişi (oauth) korunur, API/bulut yolları çıkar
