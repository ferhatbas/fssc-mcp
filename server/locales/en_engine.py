"""İngilizce katalog: motor/sürücü katmanı (pipeline çekirdeği, MCP istemci motoru, koşu API'si, sürücü, runner, MCP etkinliği)."""
EN = {
    "Kurumsal Çok Katmanlı Servis ve Modern Arayüz Çözümü":
        "Enterprise Multi-Tier Service and Modern UI Solution",
    "Sır bulundu, hiçbir dosya yazılmadı: {file}:{line} {kind} ({preview}). Değeri ortam değişkeninden oku (os.environ / process.env); koda, belgeye ya da .env'e gerçek değer yazma.":
        "Secret found, no file was written: {file}:{line} {kind} ({preview}). Read the value from an environment variable (os.environ / process.env); never write real values into code, documents or .env.",
    "Teslimde sır (anahtar/parola) var; dosya yazılmadı: ":
        "The delivery contains a secret (key/password); no file was written: ",
    "Geçersiz dosya yolu: {path}":
        "Invalid file path: {path}",
    "Korunan yola yazım reddedildi: {rel}":
        "Write to protected path rejected: {rel}",
    "Korunan yol (.fs-workspace/.git yazılamaz): {rel}":
        "Protected path (.fs-workspace/.git cannot be written): {rel}",
    "Proje kökü dışına yazım reddedildi: {rel}":
        "Write outside the project root rejected: {rel}",
    "Kök dışı yol: {rel}":
        "Path outside the root: {rel}",
    "Adım #{n}":
        "Step #{n}",
    "Otonom ajan çalışmaya başladı: {label}":
        "Autonomous agent started working: {label}",
    "Selamlar! '{title}' görevi üzerinde çalışmaya başladım. {thinking}":
        "Hello! I started working on the task '{title}'. {thinking}",
    "\n\n## Önceki rollerden devir notları\n":
        "\n\n## Handoff notes from previous roles\n",
    "- {frm} (adım #{n}): {message}":
        "- {frm} (step #{n}): {message}",
    "Pipeline Tamamlandı":
        "Pipeline Completed",
    "Docker/compose dosyası devops/ dışında: ":
        "Docker/compose file outside devops/: ",
    "Teslim proje klasör düzenine uymuyor: ":
        "The delivery does not comply with the project folder layout: ",
    "Koşu zaten tamamlandı.":
        "The run is already completed.",
    "Kayıtsız bağımlılık: '{dep}' ({file}) onaylı teknolojilerde ve mimarın kütüphane kaydında yok. Kullanma ya da yöneticiden onay iste (TECHNOLOGY sorusu açıldı).":
        "Unregistered dependency: '{dep}' ({file}) is not in the approved technologies or the architect's library registry. Do not use it, or ask the manager for approval (a TECHNOLOGY question was opened).",
    "[{id} · {n} karar, {m} soru]":
        "[{id} · {n} decisions, {m} questions]",
    "✓ {n} test case: {ids}{more}.":
        "✓ {n} test cases: {ids}{more}.",
    "zaten karşılanıyor: yeni dosya yok, kanıt testleri koştu":
        "already satisfied: no new files, evidence tests ran",
    "Ajan görevi mevcut kodla karşılanmış saydı; kanıt testleri: ":
        "The agent considered the task satisfied by existing code; evidence tests: ",
    "⚠ Doğrulama başarısız ({step}); düzeltme turu {n} açıldı.":
        "⚠ Verification failed ({step}); fix round {n} opened.",
    "✗ Doğrulama {step} adımında kaldı; düzeltme hakkı bitti.":
        "✗ Verification stayed at the {step} step; the fix budget is exhausted.",
    "✓ Doğrulama geçti; {n} bekleyen düzeltme adımı kaldırıldı.":
        "✓ Verification passed; {n} pending fix step(s) removed.",
    "Doğrulama geçti; {n} bekleyen düzeltme adımı kaldırıldı.":
        "Verification passed; {n} pending fix step(s) removed.",
    "Sır taraması commit'i durdurdu: ":
        "The secret scan stopped the commit: ",
    "✗ Sıkı DoD: doğrulama kapalı/çalışmadı (auto_verify); iş bitmiş sayılamaz.":
        "✗ Strict DoD: verification is off/did not run (auto_verify); the work cannot count as done.",
    "Sıkı DoD ihlali: ":
        "Strict DoD violation: ",
    "⚠ {reason}; düzeltme turu {n} açıldı.":
        "⚠ {reason}; fix round {n} opened.",
    "✗ {reason}; düzeltme hakkı bitti.":
        "✗ {reason}; the fix budget is exhausted.",
    "Tamamlandı: {title}":
        "Completed: {title}",
    "Düzeltme bekliyor: {title}":
        "Waiting for fix: {title}",
    "UAT reddedildi: {title}":
        "UAT rejected: {title}",
    "Adım #{n} el kaldırdı ('not al ve devam et' modu): {summary}":
        "Step #{n} raised a hand ('take notes and continue' mode): {summary}",
    "Adım #{n} yönetici onayı bekliyor.":
        "Step #{n} is waiting for manager approval.",
    "Kullanıcı onayı bekleniyor.":
        "Waiting for user approval.",
    "Koşu tamamlandı.":
        "The run is completed.",
    "Sonraki adım: #{n}":
        "Next step: #{n}",
    "Jira Task #{n} - Canlı Tarayıcı Doğrulama ve Ekran Yakalama":
        "Jira Task #{n} - Live Browser Verification and Screen Capture",
    "auto_verify kapalı: uygulama sunucu tarafından başlatılamaz":
        "auto_verify is off: the application cannot be started by the server",
    "verification.run ve health_url tanımlı değil (mimar/DevOps teslimi ya da model penceresi 0c)":
        "verification.run and health_url are not defined (architect/DevOps delivery or model window 0c)",
    ". Projede bulunan olası çalıştırma komutları: {hints} (model penceresi 0c → Doğrulama: run + health_url)":
        ". Possible run commands found in the project: {hints} (model window 0c → Verification: run + health_url)",
    "E2E koşamadım: {why}. Hedef uygulama tanımlanmadan 'geçti' demem.":
        "I could not run E2E: {why}. I will not say 'passed' without a defined target application.",
    "Çalıştırma komutu ve sağlık adresi tanımlanmalı (verification.run / health_url); E2E hedefsiz koşmaz.":
        "The run command and health address must be defined (verification.run / health_url); E2E does not run without a target.",
    "Uygulamayı başlatıyorum: `{run}` — sağlık adresi {health}":
        "Starting the application: `{run}` — health address {health}",
    "Uygulama ayağa kalkmadı: {error}":
        "The application did not come up: {error}",
    "Uygulama başlatılamadı; DevOps çalıştırma komutunu ve sağlık ucunu kontrol etmeli.":
        "The application could not be started; DevOps should check the run command and the health endpoint.",
    "[i] {target} kökü 404 döndü, sağlık adresi sağlıklı: arayüz yok (API-only). Genel UI duman testi uygulanamaz.":
        "[i] The root of {target} returned 404 while the health address is healthy: there is no UI (API-only). The generic UI smoke test does not apply.",
    "Uygulamanın kökünde arayüz yok; API kanıtı QA testleridir. Arayüz varsa verification.app_url verin ya da QA e2e/scenarios yazsın.":
        "The application root has no UI; the API evidence is the QA tests. If there is a UI, provide verification.app_url or let QA write e2e/scenarios.",
    "Doğrulama koşuyor: #{n} {title}":
        "Running verification: #{n} {title}",
    "Doğrulama geçti: {summary}":
        "Verification passed: {summary}",
    "Koşacak test/build komutu bulunamadı; yalnızca sözdizimi denetlendi.":
        "No test/build command to run was found; only the syntax was checked.",
    "Doğrulama kaldı ({step}). Çıktıyı inceleyip düzeltir misin?":
        "Verification failed ({step}). Could you review the output and fix it?",
    "Test/build komutlarını koşturdu":
        "Ran the test/build commands",
    "Geçtiyse SCM commit, kaldıysa düzeltme turu":
        "If it passed an SCM commit, if it failed a fix round",
    "Aynı hata imzası ({sig}) art arda iki turda görüldü; kalan düzeltme turları harcanmadı, iş yeniden kapsamlanmak üzere taşınacak.":
        "The same error signature ({sig}) was seen in two consecutive rounds; the remaining fix rounds were not spent and the work will be carried over to be re-scoped.",
    "Sprint {n}: döngü kırıcı; sprint kapanışında FIX_LIMIT ile taşınacak.":
        "Sprint {n}: loop breaker; will be carried over with FIX_LIMIT at sprint close.",
    "{n} düzeltme turu sonrasında doğrulama hâlâ başarısız; görev FAILED olarak işaretlendi.":
        "Verification still fails after {n} fix rounds; the task was marked FAILED.",
    "Sprint {n}: düzeltme limiti doldu; sprint kapanışında FIX_LIMIT ile taşınacak.":
        "Sprint {n}: fix limit reached; will be carried over with FIX_LIMIT at sprint close.",
    "Düzeltme turu {n}/{max} → {role}: {summary}":
        "Fix round {n}/{max} → {role}: {summary}",
    "Testler/build kaldı ({step}). Düzeltme turu {n} senin, kök nedeni çöz lütfen.":
        "Tests/build failed ({step}). Fix round {n} is yours; please resolve the root cause.",
    "Düzeltme bekliyor: #{n} {title}":
        "Waiting for fix: #{n} {title}",
    "Commit durduruldu: sır bulgusu ({note}). Değeri ortam değişkenine taşıyıp tekrar gönder.":
        "Commit stopped: secret finding ({note}). Move the value to an environment variable and resubmit.",
    "Commit atıldı: {hash} · {message}":
        "Commit made: {hash} · {message}",
    " (yeni depo açıldı)":
        " (new repository created)",
    "Değişiklikleri sürümledi":
        "Versioned the changes",
    "Sonraki teslimi bekliyor":
        "Waiting for the next delivery",
    "{origin} tarafından oluşturuldu ({key})":
        "Created by {origin} ({key})",
    "QA notu / önerilen çözüm: {resolution}":
        "QA note / suggested fix: {resolution}",
    "Hata giderilir ve regresyon testi eklenir":
        "The defect is fixed and a regression test is added",
    "{n} hata maddesi açtım: ":
        "I opened {n} bug items: ",
    "Bulguları Jira'ya yazdı":
        "Wrote the findings to Jira",
    "Hatalar sprint planında öncelik alır":
        "Bugs take priority in sprint planning",
    "Geçerli çıktı alınamadı ({n} deneme); adım FAILED. Son hata: {error}":
        "No valid output was obtained ({n} attempts); step FAILED. Last error: {error}",
    "Adım #{n} için geçerli bir teslim üretilemedi; yer tutucu yazmadım, adımı FAILED bıraktım.":
        "Could not produce a valid delivery for step #{n}; I did not write a placeholder and left the step FAILED.",
    "{n} geliştirme görevi çıkardım":
        "I drafted {n} development tasks",
    ", koşuya eklendi; iskeletten sonra sırayla işlenecek.":
        ", added to the run; they will be processed in order after the skeleton.",
    " (Jira backlog'una yazıldı).":
        " (written to the Jira backlog).",
    "Backlog'u Jira'ya yazdı":
        "Wrote the backlog to Jira",
    "Geliştiriciler iskeleti kurup görevleri alacak":
        "Developers will set up the skeleton and pick up the tasks",
    "{n} görev: ":
        "{n} tasks: ",
    "{n} iyileştirme sonraki sprintin adayı olarak backlog'a yazıldı.":
        "{n} improvements were written to the backlog as candidates for the next sprint.",
    "PO {n} iyileştirme istedi ama iyileştirme turu hakkı doldu ({max}); liste Jira'ya yazıldı.":
        "PO requested {n} improvements but the improvement round budget is exhausted ({max}); the list was written to Jira.",
    "UAT'de {n} eksik buldum; iyileştirme turu {round} açıldı, ardından QA ve UAT yeniden koşacak.":
        "I found {n} gaps in UAT; improvement round {round} is open, then QA and UAT will run again.",
    "İyileştirme görevlerini açtı":
        "Opened the improvement tasks",
    "Geliştiriciler eksikleri tamamlayacak":
        "Developers will complete the gaps",
    "Tur {n}/{max}: ":
        "Round {n}/{max}: ",
    "Teknoloji ve mimari kararları":
        "Technology and architecture decisions",
    "Sistem (karar kapısı)":
        "System (decision gate)",
    "Adım #{n} başlamadan önce yönetici onayı gerekiyor: {items} teknoloji kalemi ({pending} onay bekliyor, {open} açık engelleyici soru). Dosya: {file}":
        "Manager approval is required before step #{n} can start: {items} technology items ({pending} awaiting approval, {open} open blocking questions). File: {file}",
    "Not boş olamaz.":
        "The note cannot be empty.",
    "Koşu sonlanmış ({status}); not eklenemez.":
        "The run has ended ({status}); a note cannot be added.",
    "Yönetici revize istedi":
        "Manager requested a revision",
    "Yönetici müdahale etti":
        "Manager intervened",
    "Not bir sonraki adımın bağlamına eklenecek":
        "The note will be added to the next step's context",
    "Aynı adım geri bildirimle yeniden üretilecek":
        "The same step will be regenerated with the feedback",
    "REVİZE İSTEĞİ":
        "REVISION REQUEST",
    "NOT":
        "NOTE",
    "\n\n## Yönetici notları (öncelikli — bunlara uy)\n":
        "\n\n## Manager notes (priority — follow them)\n",
    "Bu adımın önceki teslimi yönetici tarafından revize için geri çevrildi. Aşağıdaki geri bildirime göre adımı yeniden üret; değişen dosyaların TAMAMINI ver.\n":
        "The previous delivery of this step was sent back by the manager for revision. Regenerate the step according to the feedback below; provide the COMPLETE content of every changed file.\n",
    "\n\n**Cevap zorunlu ({ids}):** teslim zarfının `payload.manager_replies` listesine her NOT için ":
        "\n\n**Reply required ({ids}):** for each NOTE, add ",
    "`{\"note_id\": \"N-1\", \"answer\": \"...\"}` ekle. Not bir soruysa doğrudan ve somut cevapla (bilmiyorsan ya da yapamıyorsan bunu açıkça yaz; uydurma). Talimatsa nasıl uyguladığını ya da neden uygulamadığını bir-iki cümleyle yaz. Cevap yöneticiye panoda notun altında gösterilir.":
        "`{\"note_id\": \"N-1\", \"answer\": \"...\"}` to the `payload.manager_replies` list of the delivery envelope. If the note is a question, answer directly and concretely (if you do not know or cannot do it, say so explicitly; do not make things up). If it is an instruction, say in a sentence or two how you applied it or why you did not. The reply is shown to the manager under the note on the dashboard.",
    "Revize edilecek adım yok.":
        "There is no step to revise.",
    "Revize yalnızca MCP istemcisi (Claude) koşularında vardır; şablon motoru içeriği yeniden üretmez.":
        "Revision exists only in MCP client (Claude) runs; the template engine does not regenerate content.",
    "Revize yalnızca bir adım teslimi onay beklerken istenebilir.":
        "A revision can only be requested while a step delivery is awaiting approval.",
    "'{kind}' adımları için revize desteklenmiyor; bir not bırakın ya da soruları cevaplayın.":
        "Revision is not supported for '{kind}' steps; leave a note or answer the questions.",
    "Sunucu tarafı adımlar için revize yoktur (içeriği ajan üretmedi).":
        "There is no revision for server-side steps (the agent did not produce the content).",
    "Yönetici revize istedi (adım #{n})":
        "Manager requested a revision (step #{n})",
    "; {n} backlog görevi geri alındı":
        "; {n} backlog task(s) rolled back",
    "Adım #{n} yönetici tarafından onaylandı.":
        "Step #{n} was approved by the manager.",
    "Adım #{n} için kullanıcı onayı alınamadı ({decision}); koşu durduruldu.":
        "User approval for step #{n} could not be obtained ({decision}); the run was stopped.",
    "{as_a} olarak {i_want} — {so_that}":
        "{as_a}: {i_want} — {so_that}",
    "PM notlardan üretti":
        "Produced by PM from the notes",
    " ({id} yerini alır)":
        " (replaces {id})",
    "Notları değerlendirdim: {n} yeni epik/hikâye maddesi açıldı.":
        "I evaluated the notes: {n} new epic/story item(s) opened.",
    "Görev kırılımı (devam: {n} hikâye kaldı)":
        "Task breakdown (continued: {n} stories left)",
    "ARCHITECT bu hikâye için görev üretmedi.":
        "ARCHITECT did not produce tasks for this story.",
    "{n} görev çıkardım":
        "I drafted {n} tasks",
    "; {n} hikâye sonraki adıma kaldı.":
        "; {n} stories are left for the next step.",
    "; tüm hikâyeler görevlere bölündü.":
        "; all stories have been split into tasks.",
    "Yönetici kararından türeyen görev: geçerli adımdan sonra çalışır.":
        "Task derived from a manager decision: runs after the current step.",
    "Yönetici kararını {n} göreve böldüm; geçerli adımdan sonra sırayla çalışacak.":
        "I split the manager decision into {n} tasks; they will run in order after the current step.",
    "{id} notuna cevap verdi":
        "Answered note {id}",
    "Cevap panoda notun altında görünür":
        "The reply appears under the note on the dashboard",
    "{ids} notuna adım #{n} içinde cevap verilmedi.":
        "Note(s) {ids} were not answered within step #{n}.",
    "Devir notu bıraktı":
        "Left a handoff note",
    "{target} sonraki adımda notu okuyacak":
        "{target} will read the note in the next step",
    "`{key}` komutu izin listesinde değil: `{cmd}`. Çalıştırılmasına izin verilsin mi?":
        "The command `{key}` is not on the allowlist: `{cmd}`. Should it be allowed to run?",
    "İzin ver; '{prefix}' önekini izin listesine ekle":
        "Allow; add the '{prefix}' prefix to the allowlist",
    "Reddet; komut koşmasın":
        "Reject; do not run the command",
    "Komut yalıtımı izin listesiyle çalışır (§12 madde 1); liste dışı komut yönetici kararı gerektirir. ":
        "Command isolation works with the allowlist (§12 item 1); a command outside the list requires a manager decision. ",
    "{id}: izin listesi dışı komut ({key})":
        "{id}: command outside the allowlist ({key})",
    "Teslim reddedildi: sır bulgusu ({note}). Dosya yazılmadı; değeri ortam değişkenine taşıyıp aynı adımı tekrar gönder.":
        "Delivery rejected: secret finding ({note}). No file was written; move the value to an environment variable and resubmit the same step.",
    "sır bulgusu {n}. kez tekrarlandı":
        "secret finding repeated {n} times",
    "Önerilen parça: ":
        "Suggested part: ",
    "Bu adımda `system_prompt` içindeki rolü üstlen, `user_context`'i oku ve YALNIZCA `output_contract`'ta tanımlanan JSON zarfını üret. Ardından `submit_step_result(run_id, order, result_json)` çağır. Sonuç 'WAITING_APPROVAL' ise kullanıcı dashboard'dan onaylayana kadar `wait_for_approval(run_id)` ile (gerekirse tekrar tekrar) bekle; 'NEXT' ise `get_next_step(run_id)` ile devam et; 'RUN_COMPLETE' ise bitir. Adıma başlamadan önce ne yapacağını anlatan 1-2 cümlelik kısa plan notunu `report_thinking(run_id, agent_id, text)` ile gönder. Dosyaları kendin yazma. 'PAUSED' gelirse kullanıcı duraklatmıştır: `wait_for_approval(run_id)` ile bekle, 'RESUMED' gelince `get_next_step` çağır. Koşu dinamiktir: mimari adımından sonra sunucu backlog görevlerini (kind='task'), doğrulama (test/build) kalınca düzeltme adımlarını (kind='fix', aynı order) ve PO reddinde iyileştirme turunu koşuya ekler; `submit_step_result` yanıtındaki `verification` ve `inserted_steps` alanlarına bak, toplam adım sayısı (`total_steps`) artabilir. Görev listesi: bir görev/todo aracın varsa (Claude Code: TodoWrite) koşunun her adımı için `todo_title` ile birer madde tut (yeni eklenen adımlar için de madde aç); bu adımı in_progress, submit sonrası completed işaretle — kullanıcı ilerlemeyi soldaki iş listesinden izler. Yönetici müdahalesi: `user_context` sonundaki 'Yönetici notları' bölümü öncelikli talimattır, ona uy. `wait_for_approval` 'REVISE' dönerse yönetici revize istemiştir: aynı adımı `get_next_step` ile yeniden al ve geri bildirime göre yeniden üret. KULLANICIYA SORU SORMA: sohbette 'devam edeyim mi / sürdüreyim mi / onaylıyor musun / böyle mi yapayım' diye sorma ve onay bekleme; belirsizlikte en makul varsayımla ilerle, varsayımı ve açık noktayı teslimdeki `summary` / `questions` alanına yaz (yönetici soruyu panodan cevaplar). Bir iş zaten yapılmış görünüyorsa bile adımı yine teslim et (kısa bir özetle) ve `get_next_step` ile devam et. Yalnızca `RUN_COMPLETE`, `CANCELLED`, `BLOCKED`, `WAITING_APPROVAL`, `SESSION_BOUNDARY` ya da kullanıcı duraklatması döngüyü bitirir. KRİTER METNİ: bir kabul kriterinin (AC-n) metni bağlamda yoksa kullanıcıdan isteme ve kapsam dışı bırakmayı önermeden önce `get_acceptance_criteria(ac_ids)` aracıyla sunucudan al (sunucu hikâyelerden geri kurar); araç da yoksa `get_next_step(run_id)` ile adımı yeniden çek: bağlam güncellenmiş olabilir. YENİ KÜTÜPHANE/TEKNOLOJİ: onaylı listede olmayan bir kütüphane gerekiyorsa adımı kendin durdurma ve sohbette onay isteme; işi yap ve manifesti teslime koy: sunucu bağımlılığı denetler, gerekirse yöneticiye panodan teknoloji sorusu (D-n) açar ve onay gelene kadar bekletir (sohbetteki onay FS-SC'ye işlemez, yalnızca pano onayı geçerlidir).":
        "In this step take on the role in `system_prompt`, read `user_context` and produce ONLY the JSON envelope defined in `output_contract`. Then call `submit_step_result(run_id, order, result_json)`. If the result is 'WAITING_APPROVAL', wait with `wait_for_approval(run_id)` (repeatedly if needed) until the user approves on the dashboard; if 'NEXT', continue with `get_next_step(run_id)`; if 'RUN_COMPLETE', finish. Before starting the step, send a short 1-2 sentence plan note describing what you will do with `report_thinking(run_id, agent_id, text)`. Do not write the files yourself. If 'PAUSED' arrives, the user paused the run: wait with `wait_for_approval(run_id)` and call `get_next_step` when 'RESUMED' arrives. The run is dynamic: after the architecture step the server adds backlog tasks (kind='task'), fix steps when verification (test/build) fails (kind='fix', same order) and an improvement round when PO rejects; look at the `verification` and `inserted_steps` fields of the `submit_step_result` response, the total step count (`total_steps`) may grow. Task list: if you have a task/todo tool (Claude Code: TodoWrite), keep one item per run step with `todo_title` (open items for newly added steps too); mark this step in_progress and completed after submit — the user follows progress from the task list on the left. Manager intervention: the 'Manager notes' section at the end of `user_context` is a priority instruction, follow it. If `wait_for_approval` returns 'REVISE', the manager asked for a revision: get the same step again with `get_next_step` and regenerate it according to the feedback. DO NOT ASK THE USER QUESTIONS: do not ask in the chat things like 'shall I continue / shall I proceed / do you approve / shall I do it this way' and do not wait for approval; when in doubt proceed with the most reasonable assumption and write the assumption and the open point into the `summary` / `questions` field of the delivery (the manager answers the question from the dashboard). Even if a job seems to be already done, still deliver the step (with a short summary) and continue with `get_next_step`. Only `RUN_COMPLETE`, `CANCELLED`, `BLOCKED`, `WAITING_APPROVAL`, `SESSION_BOUNDARY` or a user pause ends the loop. CRITERION TEXT: if the text of an acceptance criterion (AC-n) is missing from the context, before asking the user or suggesting to leave it out of scope, fetch it from the server with the `get_acceptance_criteria(ac_ids)` tool (the server rebuilds it from the stories); if the tool is missing too, re-fetch the step with `get_next_step(run_id)`: the context may have been updated. NEW LIBRARY/TECHNOLOGY: if you need a library that is not on the approved list, do not stop the step yourself and do not ask for approval in the chat; do the work and put the manifest in the delivery: the server audits the dependency, opens a technology question (D-n) for the manager on the dashboard if needed and holds the step until approval arrives (approval given in the chat does not reach FS-SC, only the dashboard approval is valid).",
    "koşu tamamlandı":
        "run completed",
    "yönetici onayı/cevabı bekleniyor":
        "waiting for manager approval/answer",
    "koşu duraklatıldı":
        "run paused",
    "koşu iptal edildi":
        "run cancelled",
    "Sprint durdu ({reason}): {detail}. Yönetici çözene kadar iş yok; oturumu bitir.":
        "Sprint stopped ({reason}): {detail}. There is no work until the manager resolves it; end the session.",
    "dashboard'dan sınırı artırıp sprinti sürdürmek ya da kapatmak":
        "raise the limit on the dashboard and resume or close the sprint",
    "Oturum sınırı: bu oturumu bitir; sonraki zamanlanmış çalıştırma claim_work ile taze oturumda sürdürür.":
        "Session boundary: end this session; the next scheduled run continues in a fresh session with claim_work.",
    "oturum sınırı":
        "session boundary",
    "bağımsız değerlendirme / oturum adım sınırı":
        "independent evaluation / session step limit",
    "bir şey yapmana gerek yok; sonraki çalıştırma sürdürür":
        "nothing for you to do; the next run continues",
    "Koşu iptal edildi ({reason}).":
        "The run was cancelled ({reason}).",
    "kullanıcı":
        "user",
    "Adım kullanıcı onayı bekliyor. `wait_for_approval(run_id)` çağır.":
        "The step is waiting for user approval. Call `wait_for_approval(run_id)`.",
    "Sunucu adımı #{n} tamamlandı; kullanıcı onayı bekleniyor.":
        "Server step #{n} completed; waiting for user approval.",
    "Kullanıcının teknoloji kararları bekleniyor; `wait_for_approval(run_id)` ile bekle, APPROVED gelince `get_next_step` çağır.":
        "Waiting for the user's technology decisions; wait with `wait_for_approval(run_id)` and call `get_next_step` when APPROVED arrives.",
    "Adım {n}{suffix}: {agent} — {title}":
        "Step {n}{suffix}: {agent} — {title}",
    "Koşu zaten sonlandı.":
        "The run has already ended.",
    "Önce bekleyen onay çözülmeli (`wait_for_approval`).":
        "The pending approval must be resolved first (`wait_for_approval`).",
    "Beklenen adım #{n}, gönderilen #{got}.":
        "Expected step #{n}, submitted #{got}.",
    "Sıra uyuşmuyor: şu an #{n} bekleniyor.":
        "Order mismatch: step #{n} is expected now.",
    "{n} denemede geçerli JSON alınamadı; şablon çıktısı kullanıldı. Son hata: {error}":
        "No valid JSON was obtained in {n} attempts; the template output was used. Last error: {error}",
    "Adım #{n} FAILED: {a} denemede geçerli JSON alınamadı; yer tutucu üretilmedi.":
        "Step #{n} FAILED: no valid JSON was obtained in {a} attempts; no placeholder was produced.",
    "adım #{n} FAILED":
        "step #{n} FAILED",
    "geçerli çıktı alınamadı":
        "no valid output was obtained",
    "bir şey yapmana gerek yok; koşu sonraki adımla sürer, iş sprint kapanışında taşınır":
        "nothing for you to do; the run continues with the next step, the work is carried over at sprint close",
    "Çıktı doğrulanamadı; yalnızca tek bir ```json bloğu ile tekrar gönder.":
        "The output could not be validated; resubmit with only a single ```json block.",
    "Düzeltme adımı eklendi: aynı order ile get_next_step çağır.":
        "A fix step was added: call get_next_step with the same order.",
    "Adım FAILED: {summary}":
        "Step FAILED: {summary}",
    "Koşuya {n} yeni adım eklendi (toplam {total}).":
        "{n} new step(s) were added to the run (total {total}).",
    "Sprint durdu ({reason}); yönetici çözene kadar iş yok.":
        "Sprint stopped ({reason}); there is no work until the manager resolves it.",
    "Oturum sınırı ({reason}): bu oturumu bitir; sonraki çalıştırma taze oturumla sürdürür.":
        "Session boundary ({reason}): end this session; the next run continues with a fresh session.",
    "Koşu SÜRÜYOR (sıradaki adım #{n}): kullanıcıya sormadan ve durum özeti beklemeden hemen get_next_step çağır.":
        "The run CONTINUES (next step #{n}): call get_next_step right away without asking the user and without waiting for a status summary.",
    "bir şey yapmana gerek yok":
        "nothing for you to do",
    "sınırı artırıp sprinti sürdür ya da kapat":
        "raise the limit and resume or close the sprint",
    "Koşu kullanıcı tarafından duraklatıldı; `wait_for_approval(run_id)` ile devam edilmesini bekle, RESUMED gelince `get_next_step` çağır.":
        "The run was paused by the user; wait with `wait_for_approval(run_id)` for it to continue and call `get_next_step` when RESUMED arrives.",
    "Koşu sonlandı.":
        "The run has ended.",
    "Devam edildi; `get_next_step` ile sürdür.":
        "Resumed; continue with `get_next_step`.",
    "Onay henüz verilmedi; tekrar `wait_for_approval` çağır.":
        "Approval has not been given yet; call `wait_for_approval` again.",
    "Yönetici revize istedi: aynı adımı `get_next_step` ile yeniden al ve 'Yönetici notları' bölümündeki geri bildirime göre yeniden üret.":
        "The manager requested a revision: get the same step again with `get_next_step` and regenerate it according to the feedback in the 'Manager notes' section.",
    "Koşu iptal edildi.":
        "The run was cancelled.",
    "Onaylandı; koşu tamamlandı.":
        "Approved; the run is completed.",
    "Onay alınamadı; koşu durdu.":
        "Approval could not be obtained; the run stopped.",
    "Onaylandı; `get_next_step` ile devam et.":
        "Approved; continue with `get_next_step`.",
    "Koşu bulunamadı: {id}":
        "Run not found: {id}",
    "Proje bulunamadı: {id}":
        "Project not found: {id}",
    "Bu proje için zaten bekleyen/aktif bir koşu var; aynı koşu döndürüldü.":
        "There is already a pending/active run for this project; the same run was returned.",
    "Bilinmeyen motor: {engine}":
        "Unknown engine: {engine}",
    "Seçime uyan Jira maddesi bulunamadı.":
        "No Jira item matching the selection was found.",
    "Şablon motoru koşuyu başlattı.":
        "The template engine started the run.",
    "Koşu kuyruğa alındı; MCP istemcisi (Claude Desktop) `get_next_step` çağırınca başlar.":
        "The run was queued; it starts when the MCP client (Claude Desktop) calls `get_next_step`.",
    "UYARI: sprint kipi açık; sabit adım listesiyle başlatılan bu koşu sprint akışını (yükleme → plan → taahhüt) atlar.":
        "WARNING: sprint mode is on; this run started with a fixed step list skips the sprint flow (intake → plan → commitment).",
    "Bu proje için zaten bekleyen/aktif bir koşu var; yeni yükleme bekleyen değerlendirmeye eklendi.":
        "There is already a pending/active run for this project; the new upload was added to the pending evaluation.",
    "Şablon motoru sprint koşusunu başlattı.":
        "The template engine started the sprint run.",
    "Sprint koşusu kuyruğa alındı; MCP istemcisi `get_next_step` çağırınca başlar.":
        "The sprint run was queued; it starts when the MCP client calls `get_next_step`.",
    "Engelleyici soru (TECHNOLOGY/EXTERNAL_ACTION) MCP aracıyla cevaplanamaz; yönetici dashboard'dan cevaplar.":
        "A blocking question (TECHNOLOGY/EXTERNAL_ACTION) cannot be answered with an MCP tool; the manager answers it on the dashboard.",
    "Not kasaya eklendi (sprint kipi kapalı: iş otomatik başlamaz).":
        "The note was added to the vault (sprint mode is off: work does not start automatically).",
    "Not kasaya eklendi; süren sprintte acil girdi (adhoc) toplantısı açıldı: başlamamış işler yer değiştirebilir.":
        "The note was added to the vault; an urgent input (adhoc) meeting was opened in the running sprint: unstarted work may be swapped.",
    "Not kasaya eklendi; değerlendirme kuyruğa alındı.":
        "The note was added to the vault; the evaluation was queued.",
    " Backlog'a iş açıldı: {key} ({title}) → {mode}.":
        " A backlog item was opened: {key} ({title}) → {mode}.",
    "sıradaki planlama":
        "next planning",
    " Benzer açık iş zaten var: {key}.":
        " A similar open item already exists: {key}.",
    "Bu koşu şablon motoru tarafından yürütülüyor; adım çekilemez.":
        "This run is executed by the template engine; steps cannot be pulled.",
    "Bu koşu şablon motoru tarafından yürütülüyor.":
        "This run is executed by the template engine.",
    "doğrulama {v}":
        "verification {v}",
    "Şablon motoru koşusu.":
        "Template engine run.",
    "Müzakere oturumu bulunamadı: {id}":
        "Deliberation session not found: {id}",
    "Yönetici revize istedi: geri bildirimi oku, aynı oturumda `deliberation_turn` ile yeni turlar ekle ve `close_deliberation` ile yeniden öneri sun.":
        "The manager requested a revision: read the feedback, add new turns in the same session with `deliberation_turn` and submit a new proposal with `close_deliberation`.",
    "Müzakere henüz kapatılmadı.":
        "The deliberation has not been closed yet.",
    "Yönetici henüz karar vermedi (onay / revize); tekrar `wait_for_approval` çağır.":
        "The manager has not decided yet (approve / revise); call `wait_for_approval` again.",
    "Yönetici onayladı: {plan}. Adım 2'de bu planı kullan.":
        "The manager approved: {plan}. Use this plan in step 2.",
    "Koşu zaten sonlanmış: {status}":
        "The run has already ended: {status}",
    "Koşu {run} canlandırıldı (adım {done}/{total}); yeni koşu kurulmadı. Sunucu iş itmez: adımları bir Claude oturumu çekene kadar ilerlemez. ":
        "Run {run} was revived (step {done}/{total}); no new run was created. The server does not push work: steps do not advance until a Claude session pulls them. ",
    "Claude'a şunu yaz: \"{p} projesi için pipeline'ı çalıştır (kaldığı yerden: {r})\". Baştan başlamak için force_new=true.":
        "Tell Claude: \"Run the pipeline for project {p} (resume from: {r})\". Use force_new=true to start over.",
    "Baştan başlatma {run} koşusunun ilerlemesini ({done}/{total} adım) çöpe atar. Bu yalnızca panoda, proje adı yazılarak onaylanır; kaldığı yerden sürdürmek için force_new kullanmayın.":
        "Starting over would discard the progress of run {run} ({done}/{total} steps). This is confirmed only on the dashboard by typing the project name; do not use force_new to resume.",
    "Onay için proje adını aynen yazın.":
        "Type the project name exactly to confirm.",
    "Koşu zaten sonlanmış.":
        "The run has already ended.",
    "Her katılımcı için sırayla `deliberation_turn(session_id, agent_id, message, sentiment)` çağır (sentiment: PROPOSAL | CRITIQUE | AGREE | CONSENSUS). ARCHITECT turunda 2-3 alternatif mimari planı kısaca karşılaştır. Son PM turunda konsensüsü açıkla ve `close_deliberation(session_id, consensus_json)` çağır; consensus_json: {\"chosen_plan\": str, \"decision\": \"APPROVED_BY_CONSENSUS\", \"agreed_stack\": [..]}.":
        "For each participant, call `deliberation_turn(session_id, agent_id, message, sentiment)` in order (sentiment: PROPOSAL | CRITIQUE | AGREE | CONSENSUS). In the ARCHITECT turn, briefly compare 2-3 alternative architecture plans. In the last PM turn, explain the consensus and call `close_deliberation(session_id, consensus_json)`; consensus_json: {\"chosen_plan\": str, \"decision\": \"APPROVED_BY_CONSENSUS\", \"agreed_stack\": [..]}.",
    "Kararı rol bazlı görevlere böl ({ref}): {plan}":
        "Split the decision into role-based tasks ({ref}): {plan}",
    "Yönetici onaylı karar {ref}: {plan}.":
        "Manager-approved decision {ref}: {plan}.",
    " Yığın: {stack}.":
        " Stack: {stack}.",
    " Özet: {summary}":
        " Summary: {summary}",
    " Bu kararı uygulanabilir backlog görevlerine böl: her görev tek bir role (BACKEND_DEV, FRONTEND_DEV, DEVOPS, QA) ait, kabul kriterli ve bağımlılığı belirtilmiş olsun; arayüz gerektiren her iş FRONTEND_DEV'e verilsin. Yığına ve onaylı teknoloji kararlarına uy, yeni kütüphane önerme. Tutanak: müzakere belgeleri.":
        " Split this decision into actionable backlog tasks: each task belongs to a single role (BACKEND_DEV, FRONTEND_DEV, DEVOPS, QA), has acceptance criteria and states its dependencies; every job that needs a UI goes to FRONTEND_DEV. Follow the stack and the approved technology decisions, do not propose new libraries. Minutes: deliberation documents.",
    "Karar, rol bazlı backlog görevlerine bölünür (backend, frontend, devops, test)":
        "The decision is split into role-based backlog tasks (backend, frontend, devops, test)",
    "Her görevin rolü, kabul kriterleri ve bağımlılığı vardır":
        "Every task has a role, acceptance criteria and dependencies",
    "Görevler onaylı yığına uygundur":
        "Tasks conform to the approved stack",
    "Yalnızca yönetici onaylı karar bölünebilir.":
        "Only a manager-approved decision can be split.",
    "Görev açılamadı (sprint kipi kapalı ya da metin geçersiz).":
        "The task could not be opened (sprint mode is off or the text is invalid).",
    "Öneri yöneticiye sunuldu: nihai karar yöneticinindir. `wait_for_approval(run_id=<session_id>)` ile bekle; 'REVISE' gelirse geri bildirimle yeni turlar ekleyip yeniden kapat, 'APPROVED' gelirse onaylanan planla devam et.":
        "The proposal was presented to the manager: the final decision is the manager's. Wait with `wait_for_approval(run_id=<session_id>)`; if 'REVISE' arrives, add new turns with the feedback and close again, if 'APPROVED' arrives, continue with the approved plan.",
    "Pipeline beklenmedik bir hatayla durdu: {error}":
        "The pipeline stopped with an unexpected error: {error}",
    "Koşu kopunca ilerletecek zamanlanmış görev görünmüyor: get_runner_schedule çağır; zamanlanmış görev araçların varsa task_prompt metniyle `{task}` görevini {minutes} dk aralıkla (cron {cron}) kur.":
        "No scheduled task that would advance the run when it drops is visible: call get_runner_schedule; if you have scheduled-task tools, create the task `{task}` with the task_prompt text at an interval of {minutes} min (cron {cron}).",
    "Görev {used} token harcadı (sınır {limit}); sprint kapanışında TOKEN_LIMIT ile yeniden kapsamlanmak üzere taşınacak.":
        "The task spent {used} tokens (limit {limit}); it will be carried over at sprint close with TOKEN_LIMIT to be re-scoped.",
    "Sprint {n} durdu ({reason}): {detail}":
        "Sprint {n} stopped ({reason}): {detail}",
    "Bütçe uyarısı: {key} {used}/{limit} (%{pct}). İş sürüyor.":
        "Budget warning: {key} {used}/{limit} (%{pct}). Work continues.",
    "token {used}/{limit}":
        "tokens {used}/{limit}",
    "etkin süre {used}/{limit} dk":
        "active time {used}/{limit} min",
    "adım {used}/{limit}":
        "steps {used}/{limit}",
    "art arda başarısız adım {used}/{limit}":
        "consecutive failed steps {used}/{limit}",
    "art arda {n} adımda ilerleme yok (sınır {limit})":
        "no progress in {n} consecutive steps (limit {limit})",
    "Sprint {n} BLOCKED değil.":
        "Sprint {n} is not BLOCKED.",
    "Engelleyici soru açık: önce soruyu cevaplayın (POST /api/questions/{id}/answer).":
        "A blocking question is open: answer it first (POST /api/questions/{id}/answer).",
    "Sınır hâlâ aşılıyor: önce autonomy.budget değerini artırın.":
        "The limit is still exceeded: raise autonomy.budget first.",
    "Sprint {n} zaten {status}.":
        "Sprint {n} is already {status}.",
    "Sprint {n} yönetici tarafından kapatıldı.":
        "Sprint {n} was closed by the manager.",
    "`verification.test` tanımlı (yoksa doğrulama SKIPPED olur ve hiçbir şey denetlenmez)":
        "`verification.test` is defined (otherwise verification is SKIPPED and nothing is checked)",
    "Model penceresi 0c → Doğrulama komutları → Test (ya da mimar adım 2'de önerir)":
        "Model window 0c → Verification commands → Test (or the architect proposes it in step 2)",
    "Sürücü hazır: Claude Desktop runner görevi güncel (§9.3) ya da otomatik runner açık ve Claude Code CLI kurulu (G3)":
        "Driver ready: the Claude Desktop runner task is up to date (§9.3) or the automatic runner is on and the Claude Code CLI is installed (G3)",
    "Claude paneli → Başlat & Bağlan → Otomatik runner (CLI gerekir) ya da Desktop zamanlanmış görevi (scripts\\fssc.ps1 runner prompt)":
        "Claude panel → Start & Connect → Automatic runner (requires the CLI) or the Desktop scheduled task (scripts\\fssc.ps1 runner prompt)",
    "Komut yalıtımı açık: sandbox.mode=container, sandbox.command_policy=allowlist ve Docker kullanılabilir (§12 madde 1)":
        "Command isolation is on: sandbox.mode=container, sandbox.command_policy=allowlist and Docker is available (§12 item 1)",
    "Model penceresi 0d → kip = container, politika = izin listesi":
        "Model window 0d → mode = container, policy = allowlist",
    "Docker Desktop'ı başlat; ":
        "Start Docker Desktop; ",
    "Bütçeler tanımlı (§3.5)":
        "Budgets are defined (§3.5)",
    "POST /api/settings/autonomy {budget: {max_sprints, max_tokens_per_sprint, ...}} (hepsi > 0)":
        "POST /api/settings/autonomy {budget: {max_sprints, max_tokens_per_sprint, ...}} (all > 0)",
    "Hedef proje kendi git deposunda, başka bir deponun altında değil":
        "The target project is in its own git repository, not under another repository",
    "Proje klasöründe `git init` (SCM ajanı ilk commit'te kendisi açar); üst klasörlerde başka bir .git olmamalı":
        "Run `git init` in the project folder (the SCM agent opens it on the first commit); there must be no other .git in the parent folders",
    "Bilinmeyen seviye: {level}":
        "Unknown level: {level}",
    "L3 reddedildi; eksik ön koşullar: ":
        "L3 rejected; missing preconditions: ",
    "Ürün tamamlandı; yapılacak iş yok.":
        "The product is complete; there is nothing to do.",
    "Zamanlanmış görevi duraklatabilirsin; kasaya yeni not yüklenirse proje yeniden başlar.":
        "You can pause the scheduled task; the project restarts when a new note is uploaded to the vault.",
    "Proje bütçe sınırı nedeniyle duraklatıldı (özet rapor hazır).":
        "The project was paused because of the budget limit (summary report is ready).",
    "Yönetici sınırı artırıp projeyi sürdürene kadar zamanlanmış görevi duraklatabilirsin.":
        "You can pause the scheduled task until the manager raises the limit and resumes the project.",
    "Yönetici dashboard'dan çözmeli (soruyu cevaplamak, sınırı artırıp sprinti sürdürmek ya da sprinti kapatmak).":
        "The manager must resolve it on the dashboard (answer the question, raise the limit and resume the sprint, or close the sprint).",
    "Bekleyen iş yok.":
        "There is no pending work.",
    "Kasaya not yüklenince ya da yönetici sıradaki sprinti başlatınca iş oluşur.":
        "Work appears when a note is uploaded to the vault or the manager starts the next sprint.",
    "Etkin koşu ({id}) şablon motoruyla yürüyor; çekilemez.":
        "The active run ({id}) is executed by the template engine; it cannot be pulled.",
    "Koşu duraklatıldı ({reason}).":
        "The run was paused ({reason}).",
    "Dashboard'dan devam ettir.":
        "Resume it from the dashboard.",
    "Yönetici onayı/cevabı bekleniyor ({gate}).":
        "Waiting for manager approval/answer ({gate}).",
    "Dashboard'dan onayla ya da soruyu cevapla.":
        "Approve or answer the question on the dashboard.",
    "Bu proje için başka bir runner oturumu çalışıyor (kira geçerli).":
        "Another runner session is working for this project (the lease is valid).",
    "Koşu {id} üstlenildi; get_next_step ile sürdür.":
        "Run {id} was claimed; continue with get_next_step.",
    "# QA Standalone Test Raporu":
        "# QA Standalone Test Report",
    "- **Tarih**: {date}":
        "- **Date**: {date}",
    "- **Hedef URL**: {url}":
        "- **Target URL**: {url}",
    "- **Test Profili**: {user} (Rol: {role})":
        "- **Test profile**: {user} (Role: {role})",
    "- **Doğrulama paketi**: {status} — {summary}":
        "- **Verification suite**: {status} — {summary}",
    "| Adım | Komut | Durum | Çıkış kodu | Süre |":
        "| Step | Command | Status | Exit code | Duration |",
    "| {name} | `{cmd}` | {status} | {code} | {dur} sn |":
        "| {name} | `{cmd}` | {status} | {code} | {dur} s |",
    "| — | (doğrulama komutu tanımlı değil; model penceresi 0c'den girin) | SKIPPED | — | — |":
        "| — | (no verification command defined; enter it in model window 0c) | SKIPPED | — | — |",
    "## Başarısız adım: {step}":
        "## Failed step: {step}",
    "- **E2E Durumu**: Playwright Chromium testine devredildi (sonuç ayrı raporda, uydurulmaz)":
        "- **E2E status**: Delegated to the Playwright Chromium test (result in a separate report, not made up)",
    "Standart Kullanıcı":
        "Standard User",
    "Bağımsız QA ve Canlı Tarayıcı E2E Test Koşusu":
        "Standalone QA and Live Browser E2E Test Run",
    "Test Süiti Koşusu: {user} ({role})":
        "Test Suite Run: {user} ({role})",
    "Hedef: {url} | Senaryo: {scenario}":
        "Target: {url} | Scenario: {scenario}",
    "Lead QA doğrulama paketi geçti ({summary}). Gerçek tarayıcı testi başlatılıyor ({user}).":
        "The Lead QA verification suite passed ({summary}). Starting the real browser test ({user}).",
    "Lead QA doğrulama paketi {status}: {summary}. E2E yine koşar; madde DONE sayılmaz.":
        "The Lead QA verification suite {status}: {summary}. E2E still runs; the item does not count as DONE.",
    "Test Süiti Tamamlandı: {user}":
        "Test Suite Completed: {user}",
    "Test Süiti Başarısız: {user}":
        "Test Suite Failed: {user}",
    "QA doğrulama paketi ve E2E tarayıcı testi geçti. Rapor: {id}":
        "The QA verification suite and the E2E browser test passed. Report: {id}",
    "QA doğrulama: {qa} · E2E: {e2e}. Rapor: {id}":
        "QA verification: {qa} · E2E: {e2e}. Report: {id}",
    "FS-SC yazılım şirketi pipeline'ını çalıştır. Proje: {project} — Adımlar: {steps}.\n\nDöngü:\n0. Bir görev/todo aracın varsa (Claude Code: TodoWrite) koşunun adımları için birer madde aç (\"Adım N: AJAN — başlık\"); her adımı başlarken in_progress, submit sonrası completed yap.\n   Koşu dinamiktir: sunucu mimari adımından sonra backlog görevlerini, doğrulama kalınca düzeltme adımlarını ve PO reddinde iyileştirme turunu ekler —\n   `submit_step_result` yanıtındaki `inserted_steps`/`total_steps` artınca yeni maddeler aç.\n1. `start_pipeline_run(project_id=\"{project_id}\", steps=[{steps_list}])` çağır (boş liste = 1-10 tamamı). run_id'yi sakla.\n2. `get_next_step(run_id)` çağır (`progress`, `kind`, `todo_title` alanları görev listesi içindir).\n   - status == \"STEP\": `system_prompt` içindeki rolü üstlen, `user_context`'i oku; önce `report_thinking(run_id, agent_id, \"<ne yapacağını anlatan 1-2 cümlelik plan notu>\")` gönder;\n     sonra YALNIZCA `output_contract`'taki JSON zarfını üret ve `submit_step_result(run_id, order, result_json)` çağır.\n     kind == \"task\": mimarın backlog görevi — kabul kriterlerini karşılayan kodu ve testlerini yaz. kind == \"fix\": aynı görevin düzeltme turu —\n     `user_context`'teki başarısız test/build çıktısını kök nedeninden çöz, testleri zayıflatma.\n   - status == \"WAITING_APPROVAL\": kullanıcı dashboard'dan onaylayana kadar `wait_for_approval(run_id)` çağır (STILL_WAITING geldikçe tekrar).\n   - status == \"RUN_COMPLETE\" veya \"CANCELLED\": döngüyü bitir ve kısa bir özet ver.\n3. `submit_step_result` sonucu:\n   - \"REJECTED\": `validation_errors`'a göre JSON'u düzelt ve aynı order ile tekrar gönder.\n   - \"NEXT\": 2. adıma dön (`verification` alanı sunucunun test/build sonucudur; `fix_requested` true ise sıradaki adım aynı order'ın düzeltmesidir).\n     \"WAITING_APPROVAL\": onay bekle. \"RUN_COMPLETE\": bitir.\nKurallar: Dosyaları kendin yazma (içerikleri payload.files içinde TAM ver, parça değil); zarf dışında metin üretme; her adımda ajanın rolüne sadık kal;\nteknoloji kararlarına uy; kullanıcıya yalnızca adım geçişlerinde tek satırlık durum bildir (doğrulama sonucu ve commit varsa onu da söyle).":
        "Run the FS-SC software company pipeline. Project: {project} — Steps: {steps}.\n\nLoop:\n0. If you have a task/todo tool (Claude Code: TodoWrite), open one item per run step (\"Step N: AGENT — title\"); mark each step in_progress when it starts and completed after submit.\n   The run is dynamic: after the architecture step the server adds backlog tasks, fix steps when verification fails and an improvement round when PO rejects —\n   open new items when `inserted_steps`/`total_steps` in the `submit_step_result` response grow.\n1. Call `start_pipeline_run(project_id=\"{project_id}\", steps=[{steps_list}])` (empty list = all of 1-10). Keep the run_id.\n2. Call `get_next_step(run_id)` (the `progress`, `kind`, `todo_title` fields are for the task list).\n   - status == \"STEP\": take on the role in `system_prompt`, read `user_context`; first send `report_thinking(run_id, agent_id, \"<1-2 sentence plan note describing what you will do>\")`;\n     then produce ONLY the JSON envelope in `output_contract` and call `submit_step_result(run_id, order, result_json)`.\n     kind == \"task\": the architect's backlog task — write the code that meets the acceptance criteria and its tests. kind == \"fix\": the fix round of the same task —\n     resolve the failing test/build output in `user_context` at its root cause, do not weaken the tests.\n   - status == \"WAITING_APPROVAL\": call `wait_for_approval(run_id)` until the user approves on the dashboard (repeat while STILL_WAITING arrives).\n   - status == \"RUN_COMPLETE\" or \"CANCELLED\": end the loop and give a short summary.\n3. Result of `submit_step_result`:\n   - \"REJECTED\": fix the JSON according to `validation_errors` and resubmit with the same order.\n   - \"NEXT\": go back to step 2 (the `verification` field is the server's test/build result; if `fix_requested` is true the next step is the fix of the same order).\n     \"WAITING_APPROVAL\": wait for approval. \"RUN_COMPLETE\": finish.\nRules: Do not write the files yourself (give the contents FULLY in payload.files, not fragments); do not produce text outside the envelope; stay faithful to the agent's role in every step;\nfollow the technology decisions; report status to the user in a single line only at step transitions (also mention the verification result and the commit if any).",
    "(dashboard'daki aktif proje)":
        "(the active project on the dashboard)",
    "Etkin koşu yok":
        "No active run",
    "Claude'da 'pipeline'ı çalıştır' dersen ya da dashboard'dan koşu başlatırsan iş başlar.":
        "If you tell Claude 'run the pipeline' or start a run from the dashboard, work starts.",
    "Claude bekleniyor (koşu terk edilmiş görünüyor)":
        "Waiting for Claude (the run looks abandoned)",
    "Sunucu yeniden başladı ya da Claude uzun süredir çağrı yapmadı. Claude bir sonraki çağrısında koşu kaldığı yerden sürer.":
        "The server restarted or Claude has not made a call for a long time. On Claude's next call the run continues where it left off.",
    "Koşu {status}":
        "Run {status}",
    "Şablon motoru çalışıyor (Claude devrede değil)":
        "The template engine is running (Claude is not involved)",
    "Bu koşu sunucudaki şablon motoruyla yürüyor.":
        "This run is executed by the template engine on the server.",
    "Sıra sende: adım #{n} onayı bekliyor":
        "Your turn: step #{n} is awaiting approval",
    "Dashboard'da adımı incele; onayla ya da revize iste.":
        "Review the step on the dashboard; approve it or request a revision.",
    "Sıra sende: engelleyici soru bekliyor":
        "Your turn: a blocking question is waiting",
    "Sprint {n} durdu: {reason}. Sorular panelinden cevapla.":
        "Sprint {n} stopped: {reason}. Answer from the Questions panel.",
    "Sıra sende: Sprint {n} engelde":
        "Your turn: Sprint {n} is blocked",
    "{reason}. Cevaplanacak açık soru yok; engeli kaldırmak yönetici kararıdır.":
        "{reason}. There is no open question to answer; removing the block is a manager decision.",
    "Koşu duraklatıldı":
        "Run paused",
    "Devam ettirene kadar Claude'a yeni adım verilmez.":
        "No new step is given to Claude until you resume it.",
    "Claude bekleniyor":
        "Waiting for Claude",
    "Koşu kuyrukta; Claude get_next_step çağırınca başlar.":
        "The run is queued; it starts when Claude calls get_next_step.",
    "Sunucu adımı #{n} yürütülüyor":
        "Server step #{n} is running",
    "Claude üretiyor: {role} · adım #{n}":
        "Claude is producing: {role} · step #{n}",
    "Bekleniyor":
        "Waiting",
}
