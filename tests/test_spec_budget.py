"""Adım bağlamına giren şartname bütçelidir: yüzlerce KB'lık şartname her adıma tam girmez, görevle ilgili bölümler seçilir."""
from server.steps.base import spec_excerpt

SPEC = "# Giriş\n" + "genel bilgi. " * 100 + "\n" + "".join(
    f"## Bölüm {i}\n" + ("alakasız metin " * 300 if i != 7 else "check-in akışı çevrimdışı kampüs bodrum katı QR doğrulama " * 120) + "\n" for i in range(40))


def test_small_spec_is_returned_whole():
    assert spec_excerpt("kısa şartname", "x", 16000) == "kısa şartname"


def test_large_spec_is_budgeted_picks_relevant_section_and_lists_omitted_headings():
    out = spec_excerpt(SPEC, "Check-in ve çevrimdışı QR doğrulama", 12000)
    assert len(SPEC) > 100_000 and len(out) < 16_000
    assert "check-in akışı" in out and "## Bölüm 7" in out                    # ilgili bölüm girdi
    assert "diğer bölümleri (başlıklar)" in out and "## Bölüm 3" in out        # girmeyenler başlık olarak listelendi (sessiz kesme yok)


def test_large_openapi_is_summarized_with_all_endpoints_instead_of_cut_in_the_middle():
    import json
    from server.steps.base import openapi_digest
    doc = {"openapi": "3.0.3", "info": {"title": "T", "version": "1"},
           "paths": {f"/api/r{i}": {"get": {"summary": f"liste {i}", "description": "d" * 400}, "post": {"summary": f"ekle {i}", "security": [{"b": []}]}} for i in range(60)},
           "components": {"schemas": {"Event": {}, "User": {}}}}
    out = openapi_digest(json.dumps(doc))
    assert "GET /api/r59 — liste 59" in out and "POST /api/r0" in out and "[yetki]" in out and "Event" in out    # son uç noktalar da var
    assert len(out) < 7000 < len(json.dumps(doc))
    assert openapi_digest("{bozuk") == ""


def test_run_summary_is_compact_for_long_runs_but_keeps_failures_and_recent_steps():
    from server.runs import PipelineRun, StepRecord
    from server.steps.base import StepContext
    steps = [StepRecord(order=i, issue_id=f"JIRA-{i}", role="BACKEND_DEV", kind="task", title="x", status="FAILED" if i == 40 else "DONE",
                        summary="s" * 300, commit="abc" if i % 2 else None) for i in range(1, 201)]
    run = PipelineRun(project_id="p", steps=steps)
    ctx = StepContext.__new__(StepContext)
    ctx.run = run
    out = ctx.run_summary_md()
    assert len(out) < 6000 and "200 adım bitti, 1 başarısız" in out
    assert "| #40 |" in out and "| #200 |" in out and "| #100 |" not in out          # başarısız adım ve son adımlar var, ortadaki başarılılar satır olmaz
    assert "Önceki 185 adım" in out and "task/BACKEND_DEV ×185" in out
