"""İngilizce katalog: adım temel sınıfları, görev/akış işleyicileri, ekran sözleşmesi, canlı görünüm (display) ve belge eşitleme metinleri."""
EN = {
    'Yanıtını YALNIZCA tek bir ```json bloğu olarak ver; blok dışında hiçbir metin yazma.\nZarf (A2A):\n{\n  "trace_id": "<verilen trace_id>",\n  "from_agent": "<AJAN_ID>",\n  "to_agent": "<SONRAKİ_AJAN_ID>",\n  "intent": "<AKSİYON>",\n  "status": "SUCCESS" | "FAILED",\n  "payload": {\n    "summary": "1-3 cümlelik, teknik olmayan Türkçe özet",\n    "friendly_dialogue": "Sonraki ajana samimi, insansı bir el sıkışma cümlesi",\n    "thinking": "Bu adımda ne yapacağının (amaç ve yaklaşım) 1-2 cümlelik kısa plan notu",\n    "what_doing": "Şu an ne yapıyor (kısa)",\n    "what_next": "Sonraki ajanın ne yapması bekleniyor (kısa)",\n    "files": [ { "path": "proje köküne göreli yol", "content": "dosyanın TAM içeriği" } ],\n    ... (rol için istenen ek alanlar aşağıda)\n  },\n  "metadata": { "tokens_used": <tahmini toplam token>, "current_file": "<ana dosya yolu>" }\n}\nKurallar: `files[].path` yalnızca proje kökü altında göreli olmalı (\'..\' yasak; `.git/` ve `.fs-workspace/` altına yazılamaz). Dosyaları KENDİN yazma; içeriği `files` içinde ver, sunucu diske yazar.':
        'Reply ONLY with a single ```json block; write no text outside the block.\nEnvelope (A2A):\n{\n  "trace_id": "<given trace_id>",\n  "from_agent": "<AGENT_ID>",\n  "to_agent": "<NEXT_AGENT_ID>",\n  "intent": "<ACTION>",\n  "status": "SUCCESS" | "FAILED",\n  "payload": {\n    "summary": "1-3 sentence, non-technical English summary",\n    "friendly_dialogue": "A warm, human handshake sentence to the next agent",\n    "thinking": "A short plan note (goal and approach) of 1-2 sentences for what you will do in this step",\n    "what_doing": "What you are doing right now (short)",\n    "what_next": "What the next agent is expected to do (short)",\n    "files": [ { "path": "path relative to the project root", "content": "FULL content of the file" } ],\n    ... (additional fields requested for the role are below)\n  },\n  "metadata": { "tokens_used": <estimated total tokens>, "current_file": "<main file path>" }\n}\nRules: `files[].path` must be relative and stay under the project root (\'..\' is forbidden; nothing may be written under `.git/` or `.fs-workspace/`). Do NOT write the files yourself; give the content in `files` and the server writes it to disk.',
    '…(şartname {n:,} karakter; aşağıda bu görevle en ilgili bölümler)…':
        '...(spec is {n:,} characters; the sections most relevant to this task follow)...',
    '[Tam metin projede ve panoda; gerekirse görev açıklamasındaki kriterlere ve ilgili artefaktlara dayan.]':
        '[Full text is in the project and on the dashboard; if needed, rely on the criteria in the task description and the related artifacts.]',
    'Görevi analiz ediyorum.':
        'Analyzing the task.',
    'Görev üzerinde çalışıyor':
        'Working on the task',
    'Sonraki adıma devredecek':
        'Will hand over to the next step',
    'OpenAPI özeti: {title} v{version} (tam sözleşme proje klasöründeki dosyadadır)':
        'OpenAPI summary: {title} v{version} (the full contract is in the file in the project folder)',
    '## Proje klasörü ({n} dosya) — var olan dosyaları dikkate al, üzerine yazacaksan TAM içerik ver':
        '## Project folder ({n} files) — take existing files into account; if you overwrite one, give its FULL content',
    '## Koşu özeti (bu ana kadar: {done} adım bitti, {failed} başarısız/reddedildi)':
        '## Run summary (so far: {done} steps finished, {failed} failed/rejected)',
    '| Adım | Ajan | Tür | Durum | Doğrulama | Commit | Özet |':
        '| Step | Agent | Kind | Status | Verification | Commit | Summary |',
    '# Görev: {title} (Jira {issue}, adım #{n})':
        '# Task: {title} (Jira {issue}, step #{n})',
    'Proje: {name}  |  Hedef klasör: {dir}':
        'Project: {name}  |  Target folder: {dir}',
    'Talep / özellik: {prompt}':
        'Request / feature: {prompt}',
    '[Şartnamenin diğer bölümleri (başlıklar): {titles}]':
        '[Other sections of the spec (headings): {titles}]',
    'payload içinde ayrıca şu alanları doldur:':
        'Also fill in the following fields inside payload:',
    'Şemalar: ':
        'Schemas: ',
    '\n... (kısaltıldı)':
        '\n... (truncated)',
    '; {commits} commit. Başarısız/reddedilenler ve son {tail} adım aşağıda.':
        '; {commits} commits. Failed/rejected steps and the last {tail} steps are below.',
    'Not: `files` listesindeki yollar örnektir; kullanıcının teknoloji kararlarına uygun dosya adları ve dizin yapısı kullan (ör. PHP seçildiyse src/*.php ve composer.json, Node seçildiyse src/*.ts ve package.json).':
        "Note: the paths in the `files` list are examples; use file names and a directory layout that match the user's technology decisions (e.g. src/*.php and composer.json if PHP was chosen, src/*.ts and package.json if Node was chosen).",
    'Gerekli belge teslimde yok: {want} (payload.files içinde tam içeriğiyle ver).':
        'Required document missing from the delivery: {want} (provide it with its full content in payload.files).',
    '{agent} adımı tamamlandı.':
        '{agent} step completed.',
    ' [yetki]':
        ' [auth]',
    '... (liste {n} girdide kesildi)':
        '... (list truncated at {n} entries)',
    '### {rel} (özet)':
        '### {rel} (summary)',
    ' (düzeltme {n})':
        ' (fix {n})',
    'Önceki {n} adım (#{first}–#{last}): ':
        'Previous {n} steps (#{first}–#{last}): ',
    '## Görev açıklaması':
        '## Task description',
    '## Müşteri toplantı notları ve şartname':
        '## Customer meeting notes and specification',
    '## Önceki artefakt: {rel}':
        '## Previous artifact: {rel}',
    'Bu adım için: from_agent="{agent}", to_agent="{to}", intent="{intent}".':
        'For this step: from_agent="{agent}", to_agent="{to}", intent="{intent}".',
    '## Kabul kriterleri':
        '## Acceptance criteria',
    '{want} boş: dosyanın tam içeriğini ver.':
        '{want} is empty: give the full content of the file.',
    '{want} çok kısa (en az {n} karakter beklenir).':
        '{want} is too short (at least {n} characters expected).',
    '{want} geçerli JSON değil.':
        '{want} is not valid JSON.',
    'Sunucu tarafı kod, veri modelleri, servisler, birim testleri.':
        'Server-side code, data models, services, unit tests.',
    "Arayüz bileşenleri, API istemcisi, form/doğrulama, bileşen testleri. Onaylı tasarım sistemine ve mockup'lara uyar.":
        'UI components, API client, forms/validation, component tests. Follows the approved design system and mockups.',
    "Tasarım sistemi (renk/tipografi/boşluk/bileşen) ve ekran mockup'ları: kodsuz, tek dosyalık HTML+CSS; yönetici onayına sunulur.":
        'Design system (color/typography/spacing/components) and screen mockups: no code, single-file HTML+CSS; submitted for manager approval.',
    'Yapılandırma, konteyner, CI, betikler, ortam değişkenleri.':
        'Configuration, containers, CI, scripts, environment variables.',
    'Test senaryoları ve otomasyon kodu; hata bulursan bugs[] ile bildir.':
        'Test scenarios and automation code; report any bugs you find in bugs[].',
    'Tasarım dokümanı ve sözleşmeler.':
        'Design document and contracts.',
    'Dokümantasyon.':
        'Documentation.',
    "'{title}' üzerinde çalışıyor":
        "Working on '{title}'",
    'Sunucu doğrulaması (test/build) koşacak, ardından SCM commit atılacak':
        'The server will run verification (test/build), then an SCM commit will be made',
    'QA için kısa not (nasıl test edilir, bilinen sınırlar)':
        'short note for QA (how to test, known limits)',
    '(yalnızca düzeltme turunda) hatanın kök nedeni':
        '(fix round only) root cause of the defect',
    'Proje: {name}  |  Hedef klasör: {dir}  |  Rolün: {agent} — {hint}':
        'Project: {name}  |  Target folder: {dir}  |  Your role: {agent} — {hint}',
    'düzeltme turu {n}':
        'fix round {n}',
    'backlog görevi':
        'backlog task',
    'Görev {n}':
        'Task {n}',
    "'{title}' için başarısız doğrulama çıktısını inceliyor, kök nedeni düzeltiyorum.":
        "Reviewing the failed verification output for '{title}' and fixing the root cause.",
    "'{title}' görevinin kabul kriterlerini ve mevcut kodu inceliyor, dosya planını çıkarıyorum.":
        "Reviewing the acceptance criteria and existing code of '{title}' and drafting the file plan.",
    'eklenen/güncellenen test dosyaları':
        'added/updated test files',
    "tasarım kararları ve frontend'e notlar":
        'design decisions and notes for the frontend',
    "CLAUDE DESIGN KAYNAĞI: {url} — Artifact aracın varsa `action: read` ile bu tuvali oku (`project/canvas.json` ve `project/*.dc.html`); ekranları statik HTML+CSS'e çevirip `files` ile `<docs>/design/` altına teslim et (`.dc.html` ham biçimi değil, tek başına açılan HTML). Tuvali güncellediysen `design.source_url` ile aynı bağlantıyı bildir. Artifact aracın yoksa bu kaynağı kullanamazsın: tasarımı kendin üret ve teslimde bunu `notes` içinde belirt.":
        'CLAUDE DESIGN SOURCE: {url} — if you have the Artifact tool, read this canvas with `action: read` (`project/canvas.json` and `project/*.dc.html`); convert the screens to static HTML+CSS and deliver them under `<docs>/design/` via `files` (not the raw `.dc.html` format, but standalone HTML that opens by itself). If you updated the canvas, report the same link in `design.source_url`. If you do not have the Artifact tool you cannot use this source: produce the design yourself and say so in `notes` in your delivery.',
    "CLAUDE DESIGN (isteğe bağlı): Artifact aracın varsa tasarımı Claude Design'da (Artifact `quickstart` intent=design) üretebilirsin; ürettiğin tuvalin bağlantısını `design.source_url` ile bildir, ekranları statik HTML+CSS olarak `<docs>/design/` altına da teslim et. Aracın yoksa tasarımı doğrudan HTML olarak üret.":
        'CLAUDE DESIGN (optional): if you have the Artifact tool you may produce the design in Claude Design (Artifact `quickstart` intent=design); report the link of the canvas you produced in `design.source_url` and also deliver the screens as static HTML+CSS under `<docs>/design/`. If you do not have the tool, produce the design directly as HTML.',
    'Kural: Yalnızca sorunu çözen dosyaları ver; verdiğin her dosyanın TAM içeriğini ver. Testleri zayıflatma, silme; kök nedeni düzelt.':
        'Rule: give only the files that fix the problem; give the FULL content of every file you give. Do not weaken or delete tests; fix the root cause.',
    '## Teslim kuralları\n- Kodu çalışır ve test edilebilir yaz; görevle ilgili birim/bileşen testlerini de `files` içinde ver (testsiz teslim kabul edilmez).\n- Mevcut bir dosyayı değiştiriyorsan dosyanın TAMAMINI ver (diff/parça değil).\n- Bağımlılık eklediysen manifesti (requirements.txt / package.json / composer.json) de güncelle.\n- Sunucu teslimden sonra sözdizimi, build ve test komutlarını koşacak; başarısız olursa düzeltme turu açılır.':
        '## Delivery rules\n- Write code that runs and can be tested; also give the unit/component tests for the task in `files` (a delivery without tests is not accepted).\n- If you change an existing file, give the WHOLE file (not a diff/fragment).\n- If you added a dependency, also update the manifest (requirements.txt / package.json / composer.json).\n- The server will run syntax, build and test commands after the delivery; if they fail a fix round is opened.',
    'Bu adım TASARIM adımıdır (kod değil). `files` içinde tek dosyalık, dışa bağımlılıksız (JS yok, harici kaynak yok) HTML+CSS ver: `<docs>/design/design-system.html` (renk/tipografi/boşluk/yarıçap belirteçleri CSS değişkeni olarak, bileşen örnekleri: düğme, form alanı, kart, tablo, gezinme) ve her ilk ekran için `<docs>/design/screens/<kimlik>.html` (gerçekçi içerikli, mobil+masaüstü duyarlı). `payload.design.screens[]` ile ekranları (id, title, route, file) ve `design.tokens` ile belirteçleri bildir. Onaylı teknoloji yığınına uy (istemci: web/mobil). Yalnızca tasarım sistemi + İLK ekranlar: tüm uygulamayı çizme. Yönetici onaylamadan frontend başlamaz.':
        'This step is a DESIGN step (not code). In `files` give single-file, dependency-free (no JS, no external resources) HTML+CSS: `<docs>/design/design-system.html` (color/typography/spacing/radius tokens as CSS variables, component samples: button, form field, card, table, navigation) and, for each first screen, `<docs>/design/screens/<id>.html` (realistic content, responsive for mobile+desktop). Report the screens (id, title, route, file) with `payload.design.screens[]` and the tokens with `design.tokens`. Follow the approved technology stack (client: web/mobile). Only the design system + the FIRST screens: do not draw the whole application. The frontend does not start until the manager approves.',
    'Bu adım YÖNETİCİ KARARINI GÖREVLERE BÖLER (task_key="{key}"). Kod yazma; `payload.backlog[]` üret: her eleman {{"id":"T-01","title":"...","role":"BACKEND_DEV|FRONTEND_DEV|DEVOPS|QA","work_type":"FEATURE|SCAFFOLD|DEVOPS|TEST","description":"...","acceptance_criteria":["..."],"depends_on":["T-01"],"files":["..."]}}. Arayüz/ekran içeren her iş FRONTEND_DEV\'e verilir (ekran sözleşmesi screens[] ile). En fazla 12 görev; gereksiz bölme yapma. `files` boş olabilir.':
        'This step BREAKS THE MANAGER DECISION INTO TASKS (task_key="{key}"). Do not write code; produce `payload.backlog[]`: each element {{"id":"T-01","title":"...","role":"BACKEND_DEV|FRONTEND_DEV|DEVOPS|QA","work_type":"FEATURE|SCAFFOLD|DEVOPS|TEST","description":"...","acceptance_criteria":["..."],"depends_on":["T-01"],"files":["..."]}}. Every piece of work involving a UI/screen goes to FRONTEND_DEV (with a screens[] contract). At most 12 tasks; do not split needlessly. `files` may be empty.',
    'Görev mevcut kodla ZATEN karşılanıyorsa dosya yeniden yazma: `files` boş bırakıp `payload.already_satisfied` = {"evidence":[{"criterion":"kabul kriteri metni","test":"commit\'li test dosyasının yolu"}]} ver (her kabul kriteri için bir kanıt testi; sunucu o testleri koşar).':
        'If the task is ALREADY satisfied by the existing code, do not rewrite files: leave `files` empty and give `payload.already_satisfied` = {"evidence":[{"criterion":"acceptance criterion text","test":"path of the committed test file"}]} (one evidence test per acceptance criterion; the server runs those tests).',
    'Bu görev şablon motoruyla işaretlendi; gerçek kod MCP istemcisi (Claude Desktop / Claude Code) tarafından üretilir.':
        'This task was marked by the template engine; the real code is produced by the MCP client (Claude Desktop / Claude Code).',
    "'{title}' teslim edildi; QA doğrulamaya başlayabilir.":
        "'{title}' has been delivered; QA can start verification.",
    'Şablon motoru yer tutucu testi (sıkı DoD) — görev {key}: {refs}.':
        'Template engine placeholder test (strict DoD) — task {key}: {refs}.',
    '[kanıtla kapanış: {n} test dosyası]':
        '[closed with evidence: {n} test files]',
    'Görev teslimi en az bir dosya içermeli (payload.files boş); görev mevcut kodla zaten karşılanıyorsa `payload.already_satisfied` ile kanıt göster.':
        'The task delivery must contain at least one file (payload.files is empty); if the task is already satisfied by the existing code, show evidence with `payload.already_satisfied`.',
    'göreli/dosya/yolu':
        'relative/file/path',
    'dosyanın TAM içeriği (parça değil)':
        'FULL content of the file (not a fragment)',
    '# Görev: {title} ({issue} · {key}, adım #{n}':
        '# Task: {title} ({issue} · {key}, step #{n}',
    'Bu adım için task_key="{key}"; `files` boş olamaz.':
        'For this step task_key="{key}"; `files` must not be empty.',
    'QA, kabul kriterlerinden {n} test case tasarladı (şablon motoru).':
        'QA designed {n} test cases from the acceptance criteria (template engine).',
    "Test case'leri hazır; QA adımında otomasyonlarıyla koşacak.":
        'The test cases are ready; QA will run them with their automation in the QA step.',
    "'{title}' görevi şablon motoruyla tamamlandı (yer tutucu çıktı).":
        "Task '{title}' was completed by the template engine (placeholder output).",
    "'{title}' için düzeltme turu {n} şablon motoruyla işaretlendi.":
        "Fix round {n} for '{title}' was marked by the template engine.",
    'payload.files boş olamaz':
        'payload.files must not be empty',
    'tasarım sistemi sayfası (TAM içerik)':
        'design system page (FULL content)',
    '<docs>/design/screens/<ekran-kimliği>.html':
        '<docs>/design/screens/<screen-id>.html',
    "ekran mockup'ı (TAM içerik)":
        'screen mockup (FULL content)',
    'case başlığı':
        'case title',
    'ön koşul':
        'precondition',
    'beklenen sonuç':
        'expected result',
    'test verisi':
        'test data',
    'MANUAL | AUTOMATED:<test adı ya da senaryo kimliği>':
        'MANUAL | AUTOMATED:<test name or scenario id>',
    "Bu belirteçleri ve bileşen görünümlerini koddaki stillere aynen aktar; mockup'ta olmayan ekranı tasarım sistemine uyarak kur. Mockup'lardan sapma gerekiyorsa teslimde `questions` alanına yaz.":
        'Carry these tokens and component looks over into the code styles exactly; build screens that are not in the mockups following the design system. If you must deviate from the mockups, write it in the `questions` field of your delivery.',
    'Claude Design kaynağı: {url}':
        'Claude Design source: {url}',
    ', düzeltme turu {n}':
        ', fix round {n}',
    '## Bağımlı olduğu görevler (tamamlandı): ':
        '## Tasks it depends on (completed): ',
    'Doğrulama başarısız oldu; ayrıntı yok.':
        'Verification failed; no details.',
    '## Mimari artefakt: {rel}':
        '## Architecture artifact: {rel}',
    '## Mevcut dosya: {rel}':
        '## Existing file: {rel}',
    '- Tür: {kind}':
        '- Kind: {kind}',
    'adım 1':
        'step 1',
    'adım 2':
        'step 2',
    '## Kabul kriterleri (hepsi karşılanmalı)':
        '## Acceptance criteria (all must be met)',
    '(metin kayıtlı değil: görevin kabul kriterlerinden ve hikâyeden çıkar, soru sorma)':
        "(text not recorded: derive it from the task's acceptance criteria and the story, do not ask questions)",
    '## Bu görevin bağlı olduğu kabul kriteri kimlikleri (metinleriyle)':
        '## Acceptance criteria IDs this task is linked to (with their texts)',
    '## Başarısız doğrulama (bunu düzelt)':
        '## Failed verification (fix this)',
    '## Müşteri şartnamesi (kısa referans)':
        '## Customer specification (short reference)',
    'kabul kriteri yok':
        'no acceptance criteria',
    '- Ajan: {agent}':
        '- Agent: {agent}',
    "Tasarım sistemi: `{sys_rel}` (renk/tipografi/boşluk belirteçleri ve bileşen örnekleri). Ekran mockup'ları (`{shots}/`): ":
        'Design system: `{sys_rel}` (color/typography/spacing tokens and component samples). Screen mockups (`{shots}/`): ',
    '- Görev: {key} ({issue})':
        '- Task: {key} ({issue})',
    '## Onaylı tasarım (uymak ZORUNLU)':
        '## Approved design (MUST follow)',
    'Sprint planı ve taahhüdü':
        'Sprint plan and commitment',
    'Sprint kapanışı (review-retro)':
        'Sprint closing (review-retro)',
    'Görev kırılımı (devam)':
        'Task breakdown (continued)',
    'Kickoff toplantısı':
        'Kickoff meeting',
    'Sprint planlama toplantısı':
        'Sprint planning meeting',
    'Değerlendirme ve retrospektif toplantısı':
        'Review and retrospective meeting',
    'Mimari gözden geçirme toplantısı':
        'Architecture review meeting',
    'Acil girdi toplantısı':
        'Urgent input meeting',
    'Sprint {n}: kod ve mimari gözden geçirme':
        'Sprint {n}: code and architecture review',
    'Yeniden kapsamlama: {title}':
        'Rescoping: {title}',
    'Düzeltme limitine takılan işi inceliyor, böler ya da yaklaşımı değiştirir hâle getiriyorum.':
        'Reviewing the work that hit the fix limit, splitting it or changing the approach.',
    'Taşınan işi yeniden kapsamlıyor':
        'Rescoping the carried-over work',
    'Sprint planı yeni tanımı taahhüt edecek':
        'The sprint plan will commit to the new definition',
    '# Yeniden kapsamlama: {title} ({issue}, {key})':
        '# Rescoping: {title} ({issue}, {key})',
    'Taşınma nedeni: {reason} · kaç kez taşındı: {count}':
        'Carry-over reason: {reason} · times carried over: {count}',
    'Bu iş aynı tanımla yeniden taahhüt EDİLEMEZ: işi böl ya da yaklaşımı değiştir. `rescoped[0].title` veya `description` mevcut olandan farklı olmalı.':
        'This work CANNOT be re-committed with the same definition: split it or change the approach. `rescoped[0].title` or `description` must differ from the current one.',
    ' (yeniden kapsamlandı)':
        ' (rescoped)',
    '1-2 cümlelik sonuç':
        '1-2 sentence outcome',
    'sprint hedefi':
        'sprint goal',
    '{title} gündemini kuruyor, girdileri topluyorum.':
        '{title}: setting up the agenda and gathering the inputs.',
    '{title} yürütüyor':
        'Running {title}',
    'Sunucu tutanağı ve kararları kaydedecek':
        'The server will record the minutes and decisions',
    '{title} tamamlandı; kararlar ve sorular kaydedildi.':
        '{title} completed; decisions and questions recorded.',
    '{title} tamamlandı.':
        '{title} completed.',
    'Son etiketten bu yana oluşan farkı sözleşme ve mimariyle karşılaştırıyorum.':
        'Comparing the changes since the last tag against the contract and architecture.',
    'Kod ve mimari uygunluğu gözden geçiriyor':
        'Reviewing code and architecture conformance',
    'Bulgular iş maddesi olacak; PO kabul kararını kanıtla verecek':
        'Findings will become work items; the PO will decide on acceptance based on evidence',
    'Bağımsız değerlendirme: kararını geliştiricinin beyanına değil aşağıdaki sunucu kanıtına dayandır (§6.6).':
        "Independent evaluation: base your decision on the server evidence below, not on the developer's claim (§6.6).",
    'Bulgu yoksa `findings` boş olabilir; uydurma bulgu yazma. Kabul veremezsin, kabul kriterini değiştiremezsin.':
        '`findings` may be empty if there are none; do not invent findings. You cannot accept, and you cannot change acceptance criteria.',
    'Sprint planlandı.':
        'Sprint planned.',
    'Sprint kapatıldı.':
        'Sprint closed.',
    'yeni, daraltılmış başlık':
        'new, narrowed title',
    'değişen yaklaşım / kapsam':
        'changed approach / scope',
    'gerekçe ve yeni yaklaşım (ve varsa düzeltilmiş dosyalar)':
        'rationale and new approach (and corrected files if any)',
    '- Neden: {reason}':
        '- Reason: {reason}',
    "'{title}' işi daraltılarak yeniden kapsamlandı.":
        "'{title}' was rescoped by narrowing it.",
    'İşi daha küçük ve doğrulanabilir bir kapsama çektim; sprint planı yeniden taahhüt edebilir.':
        'I narrowed the work to a smaller, verifiable scope; the sprint plan can re-commit it.',
    '`rescoped[]` boş olamaz.':
        '`rescoped[]` must not be empty.',
    'Aynı tanımla yeniden taahhüt edilemez: başlık/açıklamayı değiştir ya da işi böl (`split`).':
        'Cannot be re-committed with the same definition: change the title/description or split the work (`split`).',
    '(varsa) mimari belge güncellemesi':
        '(if any) architecture document update',
    'Kalan hikâyeler görevlere bölündü.':
        'The remaining stories were broken into tasks.',
    'Kalan hikâyelerin görev kırılımını da çıkardım.':
        'I also produced the task breakdown of the remaining stories.',
    'Henüz kırılımı olmayan hikâyeleri görevlere bölüyorum.':
        'Breaking down the stories that have no breakdown yet into tasks.',
    'Görev kırılımına devam ediyor':
        'Continuing the task breakdown',
    'Sprint planı görevleri seçecek':
        'The sprint plan will select the tasks',
    'konu':
        'topic',
    'kısa, somut konuşma turu':
        'short, concrete conversation turn',
    'alınan karar':
        'decision made',
    'soru':
        'question',
    'öneri gerekçesi':
        'rationale for the recommendation',
    'Toplantı':
        'Meeting',
    '# {title} (sprint {n})':
        '# {title} (sprint {n})',
    'Moderatör: SCRUM_MASTER. Her rol kendi görev tanımı içinde konuşur; başkasının işini üstlenmez.':
        "Moderator: SCRUM_MASTER. Each role speaks within its own job description and does not take over anyone else's work.",
    'Önceki rolün devir notları ve ajanların sorumlulukları sistem promptundadır. Uydurma: notlarda olmayan gereksinimi ya da ölçülmemiş metriği yazma.':
        'The handoff notes of the previous role and the responsibilities of the agents are in the system prompt. Do not make things up: do not write requirements that are not in the notes or metrics that were not measured.',
    'Sprint {n}: hata yanıtları tek tip bir JSON şemasında mı döndürülsün?':
        'Sprint {n}: should error responses be returned in a single uniform JSON schema?',
    'İstemci tarafında hata gösterimini sadeleştirir; sonradan değiştirmek ucuzdur.':
        'It simplifies error display on the client; changing it later is cheap.',
    'bulgu başlığı':
        'finding title',
    'ne, nerede, neden önemli':
        'what, where, why it matters',
    'gözden geçirme notu (isteğe bağlı)':
        'review note (optional)',
    'Sprint {n} kod ve mimari gözden geçirmesi tamamlandı; uygunsuzluk bulunmadı.':
        'Sprint {n} code and architecture review completed; no non-conformance found.',
    'Fark sözleşmeye ve mimariye uygun; PO kabul kararına geçebilir.':
        'The changes conform to the contract and architecture; the PO can move on to the acceptance decision.',
    '`findings` bir liste olmalı.':
        '`findings` must be a list.',
    '## Mevcut tanım':
        '## Current definition',
    'rescoped[] boş':
        'rescoped[] is empty',
    'rescoped[0] mevcut tanımla aynı':
        'rescoped[0] is the same as the current definition',
    'neden':
        'reason',
    '## Girdiler':
        '## Inputs',
    '## Taahhüt adayları (kapasite {cap}: {basis})':
        '## Commitment candidates (capacity {cap}: {basis})',
    '- {id} · {wt} · {title} · {assignee} · {prio} · bağımlılık: {deps} · AC: {ac}':
        '- {id} · {wt} · {title} · {assignee} · {prio} · dependencies: {deps} · AC: {ac}',
    'Kurallar: `commitment.items` yalnızca yukarıdaki adaylardan seçilir ve kapasiteyi aşamaz; yeniden kapsamlanmamış taşınan iş taahhüt edilemez. Belirsiz bir tasarım/kapsam konusunu soru olarak aç: her sorunun kategorisi, seçenekleri, ÖNERİLEN cevabı ve gerekçesi zorunludur (önerisiz soru reddedilir). Teknoloji ya da dış etkili iş gerekiyorsa TECHNOLOGY / EXTERNAL_ACTION sorusu aç; bunlar engelleyicidir ve ancak yönetici cevaplar.':
        'Rules: `commitment.items` is chosen only from the candidates above and cannot exceed the capacity; carried-over work that has not been rescoped cannot be committed. Raise an unclear design/scope topic as a question: every question must have a category, options, a RECOMMENDED answer and a rationale (a question without a recommendation is rejected). If technology or externally-impacting work is needed, raise a TECHNOLOGY / EXTERNAL_ACTION question; these are blocking and only the manager can answer them.',
    '{n} hikâye var; kullanıcıya dönük akışları öne alalım.':
        "There are {n} stories; let's prioritize the user-facing flows.",
    'Kırılım':
        'Breakdown',
    'Kapasite':
        'Capacity',
    'Kapasite {cap} görev ({basis}); {n} iş taahhüt önerisi.':
        'Capacity is {cap} tasks ({basis}); {n} work items proposed for commitment.',
    'Hata yanıt şeması (sprint {n})':
        'Error response schema (sprint {n})',
    'Hata gövdesinin biçimi notlarda belirtilmemiş.':
        'The format of the error body is not specified in the notes.',
    'findings liste değil':
        'findings is not a list',
    'gerekiyorsa ayrı görev':
        'separate task if needed',
    '- Yeni başlık: {title}':
        '- New title: {title}',
    'seçenek':
        'option',
    ' · NETLEŞTİRİLMELİ (yönetici isteği, kapsam belirsiz: gerekiyorsa soru aç)':
        ' · NEEDS GROOMING (manager request, scope unclear: raise a question if needed)',
    '## Acil yönetici girdisi':
        '## Urgent manager input',
    '- (metin yok)':
        '- (no text)',
    '## Sprint taahhüdü (başlamamış işler yer değiştirebilir)':
        '## Sprint commitment (work that has not started can be swapped)',
    'Kurallar: `commitment.out_of_scope` yalnızca BAŞLAMAMIŞ taahhüt işlerini kapsam dışına alabilir (nedeniyle); `commitment.items` boşalan sayı kadar backlog adayı ekleyebilir (kapasite aşılmaz). Acil girdi yeni bir gereksinimse SCOPE/DESIGN sorusu aç; teknoloji gerekiyorsa TECHNOLOGY sorusu (engelleyici). Başlamış işi değiştirme.':
        'Rules: `commitment.out_of_scope` may only take work that has NOT STARTED out of scope (with a reason); `commitment.items` may add as many backlog candidates as slots freed (capacity is not exceeded). If the urgent input is a new requirement, raise a SCOPE/DESIGN question; if technology is needed, raise a TECHNOLOGY question (blocking). Do not change work that has already started.',
    'Taşınan {ids} yeniden kapsamlandı; ilk sıraya alınmalı.':
        'The carried-over {ids} were rescoped; they should go first.',
    'Görevler tek teslimde bitecek büyüklükte; bağımlılık sırası korunuyor.':
        'The tasks are small enough to finish in a single delivery; dependency order is preserved.',
    'Tek tip hata şeması':
        'Uniform error schema',
    'Uç başına serbest':
        'Free-form per endpoint',
    'Sprint {n} hedefi ve taahhüdü belirlendi.':
        'The sprint {n} goal and commitment were set.',
    '## Mimari: {rel}':
        '## Architecture: {rel}',
    '## Fark ({base}..HEAD)':
        '## Changes ({base}..HEAD)',
    '## Yama (sözleşme ve mimariyle karşılaştır; bulguları dosya ve satırla yaz)':
        '## Patch (compare with the contract and architecture; write findings with file and line)',
    '## Mevcut kabul kriterleri':
        '## Current acceptance criteria',
    '## Son başarısızlık izleri':
        '## Recent failure traces',
    'Yeniden kapsamlama: yaklaşım sadeleştirildi, doğrulama adımları ayrıştırıldı.':
        'Rescoping: the approach was simplified and the verification steps were separated.',
    '## Backlog adayları (yer değiştirme için)':
        '## Backlog candidates (for swapping)',
    'Taşınacak işler: ':
        'Work to carry over: ',
    'Retro yalnızca bu metriklere dayanır. Her aksiyon tipi PROCESS | PROMPT | BACKLOG olmalıdır; korkuluk ve bütçe ayarlarını değiştiren aksiyon yazma.':
        'The retro is based only on these metrics. Every action type must be PROCESS | PROMPT | BACKLOG; do not write actions that change guardrail or budget settings.',
    'İstemci hata işleme tek yerde':
        'Client error handling in one place',
    'Şema sürümleme ek iş':
        'Schema versioning is extra work',
    'Sprint {n} hedefi: {goal}':
        'Sprint {n} goal: {goal}',
    '{ids} düzeltme limitine takıldı':
        '{ids} hit the fix limit',
    'Her API ucu için en az bir test yaz ve testi kabul kriteri kimliğiyle (AC-n) etiketle.':
        'Write at least one test for every API endpoint and tag the test with the acceptance criterion ID (AC-n).',
    'sprint ölçümünde test kapsamını artırmak':
        'to increase test coverage as measured in the sprint',
    'Test verisi üreteci ekle':
        'Add a test data generator',
    'testlerde tekrarlayan veri kurulumu':
        'repetitive data setup in tests',
    'Sprint {n}: {done}/{committed} iş tamamlandı.':
        'Sprint {n}: {done}/{committed} work items completed.',
    'Acil girdi değerlendirildi.':
        'The urgent input was evaluated.',
    '## Doğrulama kanıtı':
        '## Verification evidence',
    '- Önceki başlık: {title}':
        '- Previous title: {title}',
    'Metrikler':
        'Metrics',
    'Taahhüt {committed}, tamamlanan {done}, ilk seferde geçen {first_pass}, düzeltme turu {fix_rounds}.':
        'Committed {committed}, completed {done}, passed first time {first_pass}, fix rounds {fix_rounds}.',
    'UAT reddi {rej}; E2E sonucu {e2e}.':
        'UAT rejections {rej}; E2E result {e2e}.',
    'Taşıma':
        'Carry-over',
    'Sprint {n} kapatılır; taşınan {c} iş sonraki planlamaya girer.':
        'Sprint {n} is closed; {c} carried-over work items enter the next planning.',
    '{id} {reason} nedeniyle taşındı':
        '{id} was carried over because of {reason}',
    'Girdi':
        'Input',
    'Girdi sonraki planlamaya alınacak; taahhüt değişmiyor.':
        'The input will be taken into the next planning; the commitment does not change.',
    'Acil girdi sonraki planlamaya alındı.':
        'The urgent input was taken into the next planning.',
    '# Yeniden kapsamlama: {issue}':
        '# Rescoping: {issue}',
    'BAŞLADI':
        'STARTED',
    'başlamadı':
        'not started',
    '## Sunucu metrikleri (rakamları değiştirme)':
        '## Server metrics (do not change the numbers)',
    'Taşınan: {items}; yeniden kapsamlanacak.':
        'Carried over: {items}; will be rescoped.',
    'Taşınan iş yok.':
        'No carried-over work.',
    '{done}/{committed} iş tamamlandı':
        '{done}/{committed} work items completed',
    "'{title}' görevi için teknik gereksinimleri ve dosya yapısını analiz ediyorum.":
        "Analyzing the technical requirements and file structure for task '{title}'.",
    'Test ve doğrulama aşamasına geçilecek':
        'Will move on to testing and verification',
    'Bu görev şablon motoruyla işaretlendi; gerçek içerik MCP istemcisi (Claude Desktop) tarafından üretilmelidir.':
        'This task was marked by the template engine; the real content must be produced by the MCP client (Claude Desktop).',
    "'{title}' görevini bitirdim, QA inceleyebilir.":
        "I finished '{title}'; QA can review it.",
    '\n**Ekran sözleşmesi (ekran/sayfa/bileşen eklediysen ZORUNLU):** `payload.screens[]` ile Tester\'a bu ekranda neler yapılabileceğini bildir; sunucu bunu Playwright senaryosuna çevirir ve ekran görüntüsü alır. Biçim: `{"id":"login","title":"Giriş","route":"/login","ready_selector":"#login-form","ac_refs":["AC-13"],"actions":[{"name":"gecerli-giris","steps":[{"fill":["#email","a@b.com"]},{"click":"#submit"},{"expect_text":"Hoş geldin"}]}]}`. Adımlar: goto, click, fill [seçici,değer], expect_text, expect_selector, expect_url_contains. Seçiciler kodundaki gerçek id/data-testid olsun; ekranın görünür durumlarını (boş, hata, dolu) ayrı eylem olarak yaz. Ekran yoksa `screens: []`.':
        '\n**Screen contract (REQUIRED if you added a screen/page/component):** report to the Tester what can be done on this screen with `payload.screens[]`; the server turns it into a Playwright scenario and takes a screenshot. Format: `{"id":"login","title":"Login","route":"/login","ready_selector":"#login-form","ac_refs":["AC-13"],"actions":[{"name":"valid-login","steps":[{"fill":["#email","a@b.com"]},{"click":"#submit"},{"expect_text":"Welcome"}]}]}`. Steps: goto, click, fill [selector,value], expect_text, expect_selector, expect_url_contains. Selectors must be the real id/data-testid in your code; write the visible states of the screen (empty, error, filled) as separate actions. If there is no screen, `screens: []`.',
    '. Senaryolar e2e/screens/ altında; E2E adımı her ekranı Playwright ile açıp ekran görüntüsü alır.':
        '. Scenarios are under e2e/screens/; the E2E step opens every screen with Playwright and takes a screenshot.',
    'yalnızca açılış':
        'opening only',
    'Test edilecek ekranlar: ':
        'Screens to test: ',
    'Ekran: {title}':
        'Screen: {title}',
    'Harcama: sprint {used:.0f} dk / {max_min} dk · {tok} / {max_tok} token':
        'Spend: sprint {used:.0f} min / {max_min} min · {tok} / {max_tok} tokens',
    'adım {a}/{b}':
        'step {a}/{b}',
    '{v:.1f} milyon':
        '{v:.1f} million',
    'sprint {n}':
        'sprint {n}',
    'Sprint {n} · ':
        'Sprint {n} · ',
    '  Giden mesaj — {frm} → {to}: {msg}':
        '  Outgoing message — {frm} → {to}: {msg}',
    '🗣 Toplantı {id} · {type} · sprint {n}':
        '🗣 Meeting {id} · {type} · sprint {n}',
    '{v} bin':
        '{v}k',
    '  Gelen mesaj — {frm} → {to}: {msg}':
        '  Incoming message — {frm} → {to}: {msg}',
    '✔ {agent} teslim etti':
        '✔ {agent} delivered',
    '  Doğrulama: {body}':
        '  Verification: {body}',
    '  Commit: {commit}':
        '  Commit: {commit}',
    '  Toplantı kaydı: {id}':
        '  Meeting record: {id}',
    '  Sıradaki: adım {n} · {role} · {label}':
        '  Next: step {n} · {role} · {label}',
    '⏸ Durdu: {reason}':
        '⏸ Stopped: {reason}',
    '  Yönetici: {todo}':
        '  Manager: {todo}',
    '⏸ Sprint BLOCKED: {reason} — {detail}':
        '⏸ Sprint BLOCKED: {reason} — {detail}',
    'Runner: son görülme {seen} · ':
        'Runner: last seen {seen} · ',
    ' (toplantı)':
        ' (meeting)',
    ' (yeniden kapsamlama)':
        ' (rescoping)',
    ' (görev kırılımı)':
        ' (task breakdown)',
    ': {n} dosya':
        ': {n} files',
    '  Karar {id}: {body}':
        '  Decision {id}: {body}',
    '  ❓ Soru {id} ({cat}{blocking}): {body} — öneri {rec}':
        '  ❓ Question {id} ({cat}{blocking}): {body} — recommendation {rec}',
    'FS-SC · proje {project} · durum {status}':
        'FS-SC · project {project} · status {status}',
    ' · koşu {run} {status}':
        ' · run {run} {status}',
    ' · etkin koşu yok':
        ' · no active run',
    '❓ Açık soru: {n} (engelleyici: {b}) — ':
        '❓ Open questions: {n} (blocking: {b}) — ',
    'güncel':
        'up to date',
    'istemci bekleniyor':
        'waiting for the client',
    ' · sprint {n} {status}':
        ' · sprint {n} {status}',
    'hiç':
        'never',
    'Son etkinlik:':
        'Recent activity:',
    '- Yok.':
        '- None.',
    ', engelleyici':
        ', blocking',
    '## Güncel karar durumu (FS-SC otomatik)':
        '## Current decision status (FS-SC automatic)',
    'Bu bölüm sunucu tarafından güncel kayıtlardan üretilir. Belgenin yazıldığı andaki "Onaysız konular" listesiyle çelişirse **bu bölüm geçerlidir**.':
        'This section is generated by the server from the current records. If it conflicts with the "Unapproved topics" list as of when the document was written, **this section prevails**.',
    '### Onaylı teknoloji yığını':
        '### Approved technology stack',
    '### Hâlâ bekleyen kararlar':
        '### Decisions still pending',
    '- Henüz onaylı teknoloji kalemi yok.':
        '- There is no approved technology item yet.',
    '### ADR ile karara bağlananlar':
        '### Decided with an ADR',
    '- Açık yönetici sorusu yok (belgede "onaysız" geçen diğer konular yalnızca ajan notudur).':
        '- There is no open manager question (other topics described as "unapproved" in the document are only agent notes).',
    '### Henüz oluşturulmamış yollar ("Çözüm yapısı" bölümünde geçenlerden)':
        '### Paths not created yet (among those mentioned in the "Solution structure" section)',
    ', ADR {adr}':
        ', ADR {adr}',
    # doc_sync: ajanın yazdığı bölüm başlığı eşleştirmesi (variants) için; tx() çağrısı değil
    "Çözüm yapısı": "Solution structure",
}
