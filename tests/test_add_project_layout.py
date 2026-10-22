"""Yeni proje eklerken klasör düzeni sorulur: önerilen apps/devops/docs, isteğe bağlı düz; dolu klasörde apps dayatılmaz."""


def _add(client, path, **extra):
    res = client.post("/api/projects/add", json={"path": str(path), "name": path.name, **extra})
    assert res.status_code == 200
    return res.json()


def test_empty_folder_with_apps_choice_gets_apps_layout(client, tmp_path):
    d = tmp_path / "yeni-apps"
    data = _add(client, d, layout_mode="apps")
    assert data["layout"]["mode"] == "apps" and data["layout"]["apps_dir"] == "apps"
    assert data["layout_note"] == ""


def test_flat_choice_is_respected_for_empty_folder(client, tmp_path):
    data = _add(client, tmp_path / "yeni-duz", layout_mode="flat")
    assert data["layout"]["mode"] == "flat" and data["layout_note"] == ""


def test_apps_choice_is_not_forced_on_folder_with_product_files(client, tmp_path):
    d = tmp_path / "dolu"
    d.mkdir()
    (d / "package.json").write_text("{}", encoding="utf-8")
    data = _add(client, d, layout_mode="apps")
    assert data["layout"]["mode"] == "flat"                          # mevcut dosyalar taşınmadan apps dayatılmaz
    assert "göç" in data["layout_note"]


def test_without_choice_the_server_default_is_kept(client, tmp_path):
    empty = _add(client, tmp_path / "bos")
    assert empty["layout"]["mode"] == "apps"                         # boş klasör: önerilen düzen
    d = tmp_path / "eski"
    d.mkdir()
    (d / "src").mkdir()
    assert _add(client, d)["layout"]["mode"] == "flat"               # dolu klasör: düz
