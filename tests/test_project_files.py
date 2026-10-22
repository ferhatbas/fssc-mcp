"""Dökümanlara, test dosyalarına ve commit ayrıntısına salt-okunur erişim; test dosyalarında sözel senaryo listesi."""
import os
import subprocess

import pytest

from server import project_files as PF

SPEC = """/**
 * AC-7: Üç hatalı OTP denemesinden sonra hesap 24 saat kilitlenir.
 */
import { OtpService } from './otp.service';

describe('OTP kilidi', () => {
  describe('hatalı denemeler', () => {
    it('üçüncü hatalı denemede hesabı 24 saat kilitler', () => { /* AC-7 */ });
    it("kilitliyken doğru kod bile 423 döner", () => {});
  });
  test(`kilit süresi dolunca yeniden denenebilir`, () => {});
});
"""
PYTEST = '''import pytest


class TestKayit:
    def test_18_yas_alti_reddedilir(self):
        """18 yaş altı kayıt reddedilir ve gerekçe döner (AC-1)"""
        pass

    def test_parola_en_az_8_karakter(self):
        pass
'''


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def project(hub, tmp_project):
    root = tmp_project
    os.makedirs(os.path.join(root, "docs", "adr"))
    os.makedirs(os.path.join(root, "apps", "backend", "src", "auth"))
    os.makedirs(os.path.join(root, "node_modules", "x"))
    open(os.path.join(root, "docs", "PRD.md"), "w", encoding="utf-8").write("# PRD\nİçerik")
    open(os.path.join(root, "docs", "adr", "0001-x.md"), "w", encoding="utf-8").write("# ADR 1")
    open(os.path.join(root, "apps", "backend", "src", "auth", "ac-07-otp.spec.ts"), "w", encoding="utf-8").write(SPEC)
    open(os.path.join(root, "apps", "backend", "test_kayit.py"), "w", encoding="utf-8").write(PYTEST)
    open(os.path.join(root, ".env"), "w").write("SECRET=1")
    open(os.path.join(root, "node_modules", "x", "a.spec.ts"), "w").write("it('x', () => {})")
    _git(root, "init", "-q")
    _git(root, "add", "."); _git(root, "commit", "-q", "-m", "feat(JIRA-72): AC-7 için test senaryosu\n\nOTP kilidi senaryoları eklendi.")
    hub.projects[hub.active_project_id]["path"] = root
    return root


def test_js_senaryolari_ic_ice_describe_ile(project):
    doc = PF.read_document(__import__("types").SimpleNamespace(projects={"p": {"path": project}}, active_project_id="p", default_project_path=project), "apps/backend/src/auth/ac-07-otp.spec.ts")
    sc = [(s["suite"], s["name"]) for s in doc["scenarios"]]
    assert sc == [("OTP kilidi › hatalı denemeler", "üçüncü hatalı denemede hesabı 24 saat kilitler"),
                  ("OTP kilidi › hatalı denemeler", "kilitliyken doğru kod bile 423 döner"),
                  ("OTP kilidi", "kilit süresi dolunca yeniden denenebilir")]
    assert doc["is_test"] and doc["ac_refs"] == ["AC-7"] and "OTP denemesinden sonra" in doc["summary"]


def test_python_senaryolari_docstring_ve_insanlastirma():
    sc = PF.extract_scenarios(PYTEST, "test_kayit.py")
    assert [(s["suite"], s["name"]) for s in sc] == [("Kayit", "18 yaş altı kayıt reddedilir ve gerekçe döner (AC-1)"), ("Kayit", "Parola en az 8 karakter")]
    assert PF.extract_scenarios("func TestLoginFails(t *testing.T) {}", "a_test.go")[0]["name"] == "Login Fails"


def test_liste_ve_guvenlik(hub, project):
    listing = PF.list_documents(hub)
    assert {d["path"] for d in listing["docs"]} == {"docs/PRD.md", "docs/adr/0001-x.md"}
    assert {t["path"] for t in listing["tests"]} == {"apps/backend/src/auth/ac-07-otp.spec.ts", "apps/backend/test_kayit.py"}   # node_modules hariç
    assert [d["category"] for d in listing["docs"] if "adr" in d["path"]] == ["ADR"]
    for bad in ("../etc/passwd", "/etc/passwd", ".env", "node_modules/x/a.spec.ts", ".git/config", "docs/../../x", "C:/Windows/win.ini"):
        with pytest.raises(PF.FileAccessError):
            PF.read_document(hub, bad)
    assert PF.read_document(hub, "docs/PRD.md")["content"].startswith("# PRD")
    with pytest.raises(PF.FileAccessError) as e:
        PF.read_document(hub, "docs/yok.md")
    assert e.value.status_code == 404


def test_commit_ayrintisi(hub, project):
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True).stdout.strip()
    c = PF.commit_detail(hub, sha[:7])
    assert c["short"] == sha[:7] and c["issue"] == "JIRA-72" and c["subject"].startswith("feat(JIRA-72)") and "OTP kilidi" in c["body"]
    assert {f["path"] for f in c["files"]} >= {"docs/PRD.md", "apps/backend/src/auth/ac-07-otp.spec.ts"} and c["added"] > 0
    assert "describe('OTP kilidi'" in c["patch"]
    for bad in ("", "xyz", "--help", "HEAD; rm -rf /"):
        with pytest.raises(PF.FileAccessError):
            PF.commit_detail(hub, bad)


def test_uclar_ve_kanit_zenginlestirme(client, hub, project):
    assert client.get("/api/project/docs").json()["docs"]
    r = client.get("/api/project/file", params={"path": "apps/backend/src/auth/ac-07-otp.spec.ts"}).json()
    assert len(r["scenarios"]) == 3
    assert client.get("/api/project/file", params={"path": "../x"}).status_code == 400
    assert client.get("/api/project/file", params={"path": ".env"}).status_code == 403
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True).stdout.strip()
    assert client.get(f"/api/project/commit/{sha}").json()["issue"] == "JIRA-72"
    assert client.get("/api/project/commit/zzzz").status_code == 400
    # kanıt: AC-7'yi anan test dosyası → sözel senaryolar kanıt satırına gelir
    from server import sprint as SP
    SP.ensure_state(hub)["acs"]["AC-7"] = {"text": "Üç hatalı denemeden sonra hesap 24 saat kilitlenir.", "story": None}


async def test_kanit_satirina_sozel_senaryolar_gelir(hub, project):
    from server import jira_plus as JP
    from server import sprint as SP
    SP.ensure_state(hub)["acs"]["AC-7"] = {"text": "Üç hatalı denemeden sonra hesap 24 saat kilitlenir.", "story": None}
    await hub.update_jira_issue("JIRA-72", {"order": 72, "title": "AC-7 için test", "issue_type": "STORY", "status": "DONE", "ac_refs": ["AC-7"]})
    ev = JP.evidence(hub, "JIRA-72")
    item = ev["ac_coverage"]["items"][0]
    assert item["ac"] == "AC-7" and "24 saat" in item["ac_text"]
    f = item["files"][0]
    assert f["path"].endswith("ac-07-otp.spec.ts") and len(f["scenarios"]) == 3 and "OTP denemesinden" in f["summary"]


def test_dosya_gezgini_tek_duzey_listeler(project, hub):
    top = PF.list_dir(hub, "")
    names = [e["name"] for e in top["entries"]]
    assert "apps" in names and "docs" in names
    assert "node_modules" not in names and ".git" not in names and ".env" not in names     # yasaklı klasör ve gizli dosya listelenmez
    assert top["entries"][0]["type"] == "dir"                                                # klasörler önce
    sub = PF.list_dir(hub, "apps/backend")
    assert {"src", "test_kayit.py"} <= {e["name"] for e in sub["entries"]}
    assert next(e for e in sub["entries"] if e["name"] == "test_kayit.py")["path"] == "apps/backend/test_kayit.py"
    with pytest.raises(PF.FileAccessError):
        PF.list_dir(hub, "../")
    with pytest.raises(PF.FileAccessError):
        PF.list_dir(hub, "node_modules/x")
