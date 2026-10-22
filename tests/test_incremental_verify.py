"""Artımlı doğrulama: görev adımlarında yalnızca değişen dosyaların testleri koşar; tam paket belirli aralıklarla ve faz adımlarında."""
import os

import pytest

from server import pipeline as P
from server import verify as V
from server.runs import PipelineRun, StepRecord

CMDS = {"lint": "cd apps/backend && npx tsc --noEmit", "build": "cd apps/backend && npm run build --silent", "test": "cd apps/backend && npm test --silent"}


def _project(tmp_path):
    b = tmp_path / "apps" / "backend" / "src"
    for rel in ("auth/ac-01.spec.ts", "auth/auth.service.ts", "auth/login.spec.ts", "events/events.controller.ts", "events/events.spec.ts", "swagger/swagger.setup.ts",
                "swagger/swagger-docs.spec.ts", "app.spec.ts", "main.ts", "integration/edge.spec.ts", "smoke/smoke.spec.ts"):
        f = b / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    return str(tmp_path)


def test_scoped_test_command_picks_only_needed_specs(tmp_path):
    pd = _project(tmp_path)
    out = V.scoped_test_command(CMDS["test"], ["apps/backend/src/swagger/swagger.setup.ts", "apps/backend/src/swagger/swagger-docs.spec.ts", "apps/backend/src/main.ts",
                                               "apps/backend/src/events/events.controller.ts", "apps/backend/package.json"], pd)
    assert out == ("cd apps/backend && npm test --silent -- --runTestsByPath src/app.spec.ts src/events/events.spec.ts src/swagger/swagger-docs.spec.ts")
    # merkez dosyalar (main.ts, controller) tüm paketi çekmez: integration/smoke/auth spec'leri seçilmedi
    assert V.select_specs(V._all_specs(os.path.join(pd, "apps", "backend")), ["src/auth/auth.service.ts"]) == ["src/auth/ac-01.spec.ts", "src/auth/login.spec.ts"]
    assert V.scoped_test_command("pytest -q", ["a.py"], pd) is None                              # jest değilse tam koşu
    assert V.scoped_test_command(CMDS["test"], ["apps/backend/src/yeni/orphan.ts"], pd) is None  # eşleşen spec yok: tam paket
    two = "cd apps/backend && npm test --silent && cd ../.. && cd apps/web && npm test --silent"
    out2 = V.scoped_test_command(two, ["apps/backend/src/auth/ac-01.spec.ts"], pd)
    assert "--runTestsByPath src/auth/ac-01.spec.ts" in out2 and 'cd apps/web && node -e "process.exit(0)"' in out2   # değişmeyen uygulama atlanır


def test_only_test_files():
    assert V.only_test_files(["apps/backend/src/a.spec.ts", "apps/backend/test_x.py"])
    assert not V.only_test_files(["apps/backend/src/a.spec.ts", "apps/backend/src/a.ts"]) and not V.only_test_files([])


async def _run(monkeypatch, files, test_exit=0, test_out="", changed_only=True, tmp_path=None):
    _project(tmp_path)
    seen = []

    async def fake(cmd, cwd, timeout_s, env=None):
        seen.append(cmd)
        if "--runTestsByPath" in cmd:
            return {"cmd": cmd, "exit_code": test_exit, "duration_ms": 1, "output": test_out, "timed_out": False}
        return {"cmd": cmd, "exit_code": 0, "duration_ms": 1, "output": "", "timed_out": False}
    monkeypatch.setattr(V, "run_command", fake)
    res = await V.run_verification(str(tmp_path), CMDS, files_written=files, do_install=False, isolation="host", changed_only=changed_only)
    return res, seen


async def test_yalnizca_test_eklenince_build_atlanir_ve_test_daralir(monkeypatch, tmp_path):
    res, seen = await _run(monkeypatch, ["apps/backend/src/auth/ac-01.spec.ts"], tmp_path=tmp_path)
    assert res["status"] == "PASSED" and res["scope"] == "incremental"
    assert not any("npm run build" in c for c in seen) and any("--runTestsByPath src/auth/ac-01.spec.ts" in c for c in seen)
    assert [r["name"] for r in res["results"] if r["name"] in ("lint", "build", "test")] == ["lint", "test"]


async def test_kaynak_degisince_build_kosar(monkeypatch, tmp_path):
    res, seen = await _run(monkeypatch, ["apps/backend/src/auth/auth.service.ts"], tmp_path=tmp_path)
    assert any("npm run build" in c for c in seen) and res["scope"] == "incremental"


async def test_ilgili_test_bulunamazsa_tam_pakete_duser(monkeypatch, tmp_path):
    res, seen = await _run(monkeypatch, ["apps/backend/src/auth/auth.service.ts"], test_exit=1, test_out="No tests found, exiting with code 1", tmp_path=tmp_path)
    assert res["scope"] == "full" and seen[-1] == CMDS["test"]            # testsiz teslim "geçti" sayılmaz: tam paket koşar


async def test_tam_kip_degismez(monkeypatch, tmp_path):
    res, seen = await _run(monkeypatch, ["apps/backend/src/a.spec.ts"], changed_only=False, tmp_path=tmp_path)
    assert res["scope"] == "full" and CMDS["test"] in seen and any("npm run build" in c for c in seen)


def _rec(order, kind="task", scope=None, status="PASSED"):
    r = StepRecord(order=order, issue_id=f"JIRA-{order}", role="QA", kind=kind)
    if scope is not None:
        r.verification = {"status": status, "scope": scope}
    return r


async def test_tam_paket_politikasi(hub):
    run = PipelineRun(project_id=hub.active_project_id)
    cur = _rec(20)
    run.steps = [cur]
    assert P.use_incremental_verify(hub, run, cur, ["a.spec.ts"]) is False          # ilk doğrulama: taban çizgisi tam
    run.steps = [_rec(10, scope="full"), cur]
    assert P.use_incremental_verify(hub, run, cur, ["a.spec.ts"]) is True
    run.steps = [_rec(10, scope="full")] + [_rec(11 + k, scope="incremental") for k in range(4)] + [cur]
    assert P.use_incremental_verify(hub, run, cur, ["a.spec.ts"]) is False         # 4 artımlıdan sonra 5. adım tam
    phase = _rec(6, kind="phase")
    run.steps = [_rec(10, scope="full"), phase]
    assert P.use_incremental_verify(hub, run, phase, ["a.spec.ts"]) is False       # faz adımı her zaman tam
    await hub.update_settings({"verify_scope": "full"})
    run.steps = [_rec(10, scope="full"), cur]
    assert P.use_incremental_verify(hub, run, cur, ["a.spec.ts"]) is False         # ayar 'full'


async def test_degismeyen_bagimlilik_icin_kurulum_tekrarlanmaz(tmp_path):
    from server import verify as V
    app = tmp_path / "apps" / "backend"
    (app / "node_modules").mkdir(parents=True)
    (app / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    cmd = "cd apps/backend && echo kuruldu"
    junit = str(tmp_path / "junit.xml")
    r1 = await V._run_commands(str(tmp_path), {"install": cmd}, True, None, False, junit, None, "t", [], "host")
    assert r1["ran_install"] is True and not r1["results"][0].get("cached")              # ilk kez gerçekten koşar
    r2 = await V._run_commands(str(tmp_path), {"install": cmd}, True, None, False, junit, None, "t", [], "host")
    assert r2["ran_install"] is False and r2["results"][0].get("cached") is True and r2["results"][0]["status"] == "PASSED"
    (app / "package.json").write_text('{"name":"x","dependencies":{"a":"1"}}', encoding="utf-8")      # bildirim değişti: yeniden kurulur
    r3 = await V._run_commands(str(tmp_path), {"install": cmd}, True, None, False, junit, None, "t", [], "host")
    assert r3["ran_install"] is True and not r3["results"][0].get("cached")


def test_node_modules_yoksa_imza_yok_kurulum_atlanmaz(tmp_path):
    from server import verify as V
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert V.install_signature(str(tmp_path), "npm install") is None


async def test_hafif_kipte_artimli_adimda_build_atlanir_planli_komutlar_gercegi_yansitir(tmp_path):
    from server import verify as V
    app = tmp_path / "apps" / "backend"
    (app / "node_modules").mkdir(parents=True)
    (app / "package.json").write_text("{}", encoding="utf-8")
    cmds = {"install": "cd apps/backend && echo i", "lint": "echo l", "build": "echo b", "test": "echo t"}
    plan = V.planned_commands(str(tmp_path), cmds, True, True, ["apps/backend/src/a.ts"], True)
    assert set(plan) == {"install", "lint", "test"}                                     # kurulum ilk kez: koşar; build hafif kipte yok
    junit = str(tmp_path / "j.xml")
    r = await V._run_commands(str(tmp_path), cmds, True, None, False, junit, None, "t", [], "host", ["apps/backend/src/a.ts"], True)
    assert [x["name"] for x in r["results"]] == ["install", "lint", "test"]
    plan2 = V.planned_commands(str(tmp_path), cmds, True, True, ["apps/backend/src/a.ts"], True)
    assert set(plan2) == {"lint", "test"}                                               # kurulum önbellekte: planda da görünmez
    full = V.planned_commands(str(tmp_path), cmds, True, False, ["apps/backend/src/a.ts"], True)
    assert "build" in full                                                              # tam doğrulamada build koşar
