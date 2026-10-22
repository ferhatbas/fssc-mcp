"""English catalog: step handlers (server/steps/handlers.py) — prompts, output examples, template documents, live-feed sentences."""
EN = {
    # ---- thinking / titles (N_) ----
    "Müşteri Görüşmeleri & PRD Gereksinim Analizi": "Customer Interviews & PRD Requirements Analysis",
    "Müşteri toplantı notları ve şartname belgelerini detaylı tarıyorum. İş gereksinimlerini PRD ve kabul kriterlerine dönüştürüyorum.":
        "I am going through the customer meeting notes and specification documents in detail. I am turning the business requirements into a PRD and acceptance criteria.",
    "PRD ve kullanıcı hikayelerini hazırlıyor": "Preparing the PRD and user stories",
    "Sistem mimarına mimari tasarım için devredecek": "Will hand over to the system architect for the architecture design",
    "Sistem Mimarisi, API Sözleşmesi & Veri Modelleri": "System Architecture, API Contract & Data Models",
    "PRD dokümanını inceledim. Modüler mimariyi ve OpenAPI 3.0 şemasını planlıyorum.": "I have reviewed the PRD. I am planning the modular architecture and the OpenAPI 3.0 schema.",
    "OpenAPI sözleşmesi ve veri modellerini kurguluyor": "Designing the OpenAPI contract and data models",
    "Backend geliştiriciye API şemasını aktaracak": "Will pass the API schema to the backend developer",
    "Senior Backend: REST API & Servisler": "Senior Backend: REST API & Services",
    "OpenAPI sözleşmesine uygun FastAPI endpoint'leri ve JWT yetkilendirme mantığını kodluyorum.": "I am coding the FastAPI endpoints that follow the OpenAPI contract and the JWT authorization logic.",
    "Kimlik doğrulama ve API servislerini geliştiriyor": "Developing authentication and API services",
    "Frontend takımına entegrasyon için hazır hale getirecek": "Will make it ready for the frontend team to integrate",
    "Senior Frontend: Responsive UI & Formlar": "Senior Frontend: Responsive UI & Forms",
    "Backend API'larına bağlanacak modern React/Vite arayüz bileşenlerini oluşturuyorum.": "I am building the modern React/Vite UI components that connect to the backend APIs.",
    "Modern Tailwind/React dashboard UI'ını inşa ediyor": "Building the modern Tailwind/React dashboard UI",
    "Kod kalitesi ve test için QA'ya devredecek": "Will hand over to QA for code quality and testing",
    "Backend ve Frontend arasında Bearer başlığı, CORS ve veri modeli uyumunu karşılıklı doğruluyoruz.": "Backend and Frontend are cross-checking the Bearer header, CORS and data model compatibility.",
    "A2A kontrat senkronizasyonu yapıyor": "Synchronizing the A2A contract",
    "QA'ya birim testleri için devredecek": "Will hand over to QA for unit tests",
    "Lead QA: Birim ve Fonksiyonel Doğrulama": "Lead QA: Unit & Functional Verification",
    "Senior yazılımcıların kodlarını inceliyorum. Pytest ve birim test senaryolarını çalıştırıyorum.": "I am reviewing the senior developers' code. I am running pytest and the unit test scenarios.",
    "API birim testlerini ve hata kontrollerini koşturuyor": "Running API unit tests and error checks",
    "E2E canlı tarayıcı testlerine geçilecek": "Moving on to E2E live browser tests",
    "Playwright E2E: Canlı Tarayıcı Doğrulama": "Playwright E2E: Live Browser Verification",
    "Canlı web arayüzünde kullanıcı senaryolarını test etmek için Playwright tarayıcısını başlatıyorum.": "I am starting the Playwright browser to test user scenarios on the live web UI.",
    "Playwright ile headless tarayıcıda form ve butonları sınıyor": "Testing forms and buttons in a headless browser with Playwright",
    "Test raporunu DevOps'a aktaracak": "Will pass the test report to DevOps",
    "DevOps Dağıtım & Docker Yayını": "DevOps Deployment & Docker Release",
    "Testler başarıyla tamamlandı. Dockerfile ve CI/CD pipeline yapılandırmalarını hazırlıyorum.": "Tests completed successfully. I am preparing the Dockerfile and CI/CD pipeline configuration.",
    "Docker konteyner imajı ve dağıtım konfigürasyonlarını kuruyor": "Setting up the Docker container image and deployment configuration",
    "Prodüksiyon dağıtımı ve sürüme onay verecek": "Will approve the production deployment and the release",
    "Product Owner (PO) UAT & Nihai Müşteri Kabulü": "Product Owner (PO) UAT & Final Customer Acceptance",
    "Geliştirilen sistemin PRD ve kullanıcı kabul kriterlerine uygunluğunu UAT testleriyle denetliyorum.": "I am auditing the developed system against the PRD and the user acceptance criteria with UAT tests.",
    "Nihai kullanıcı deneyimini ve şartname uyumunu kontrol ediyor": "Checking the final user experience and specification compliance",
    "UAT onayı verilecek veya yeni iyileştirme açılacak": "UAT approval will be given or a new improvement will be opened",
    "Documentor & Reporter: Kullanım Kılavuzu & Yönetici Özeti": "Documentor & Reporter: User Manual & Executive Summary",
    "Son kullanıcı kullanım kılavuzunu (User Manual) ve yönetim durum özetini derliyorum.": "I am compiling the end-user manual (User Manual) and the management status summary.",
    "Kullanım kılavuzu ve yönetici raporunu oluşturuyor": "Producing the user manual and the executive report",
    "Proje teslim dokümantasyonu tamamlanıyor": "The project delivery documentation is being completed",

    # ---- payload_schema examples (N_) ----
    "rol": "role",
    "istek": "want",
    "fayda": "benefit",
    "ölçülebilir kabul kriteri": "measurable acceptance criterion",
    "kapsam dışı madde": "out-of-scope item",
    "Şartnamede açık kalan teknoloji/mimari seçimi (dil, çatı, veritabanı, istemci, barındırma, entegrasyon...)": "Technology/architecture choice left open in the specification (language, framework, database, client, hosting, integration...)",
    "seçenek A": "option A",
    "seçenek B": "option B",
    "gerekçe": "rationale",
    "ana hedef": "main goal",
    "kapsam": "scope",
    "hikâye başlığı": "story title",
    "(varsa) JIRA-n": "(if any) JIRA-n",
    "notlarda geçen teknoloji": "technology mentioned in the notes",
    "notlardan AYNEN alınmış kısa alıntı (notlarda yoksa kalemi ekleme; uydurma)": "short quote taken VERBATIM from the notes (if it is not in the notes, do not add the item; do not invent)",
    "PRD dokümanının tam Markdown içeriği": "full Markdown content of the PRD document",
    "seçilen mimari yaklaşımın adı": "name of the chosen architecture approach",
    "modül / servis listesi": "module / service list",
    "alan: tip": "field: type",
    "görev başlığı": "task title",
    "SCAFFOLD | FEATURE | TEST | E2E_SCENARIO | DEVOPS | DOCS | BUG | IMPROVEMENT | REFACTOR | TEST_DESIGN | SECURITY_TEST | PERF_SMOKE (sprint kipinde)":
        "SCAFFOLD | FEATURE | TEST | E2E_SCENARIO | DEVOPS | DOCS | BUG | IMPROVEMENT | REFACTOR | TEST_DESIGN | SECURITY_TEST | PERF_SMOKE (in sprint mode)",
    "(sprint kipinde) hikâye kimliği": "(in sprint mode) story id",
    "ne yapılacak": "what to do",
    "ölçülebilir kriter": "measurable criterion",
    "dokunulacak/dosya.py": "file/to/touch.py",
    "kütüphane adı": "library name",
    "ne için": "what for",
    "onaylı teknoloji (örn. FastAPI)": "approved technology (e.g. FastAPI)",
    "bağımlılık kurulum komutu": "dependency install command",
    "test komutu": "test command",
    "build komutu (opsiyonel)": "build command (optional)",
    "lint komutu (opsiyonel)": "lint command (optional)",
    "uygulamayı başlatan komut": "command that starts the application",
    "mimari özeti": "architecture summary",
    "bileşen adları": "component names",
    "açıklama": "description",
    "nasıl düzeltildi / düzeltilmeli": "how it was fixed / should be fixed",
    "uygulamayı başlatan komut (opsiyonel; mimarınkini düzeltmek için)": "command that starts the application (optional; to correct the architect's one)",
    "kanıt: hangi test/E2E senaryosu ya da neden ret": "evidence: which test/E2E scenario, or the reason for rejection",
    "eksik/iyileştirilecek özellik": "missing/to-be-improved feature",
    "ne yapılmalı": "what should be done",

    # ---- PM ----
    "## Sprint kipi: epik ve hikâye üretimi (zorunlu)": "## Sprint mode: epic and story generation (mandatory)",
    "- `epics[]`: notlardaki her ana hedef için bir epik (`id`, `title`, `description`).": "- `epics[]`: one epic for every main goal in the notes (`id`, `title`, `description`).",
    "- `stories[]`: her kullanıcı ihtiyacı için bir hikâye (`id`, `epic`, `title`, `as_a`, `i_want`, `so_that`, `acceptance_criteria` = ölçülebilir cümleler). Sunucu `AC-n` ve `JIRA-n` kimliklerini atar.":
        "- `stories[]`: one story for every user need (`id`, `epic`, `title`, `as_a`, `i_want`, `so_that`, `acceptance_criteria` = measurable sentences). The server assigns the `AC-n` and `JIRA-n` ids.",
    "- Daha önce girdi alındıysa YALNIZCA yeni ya da değişen hikâyeleri yaz. Değişen bir hikâye kapatılmış bir sprintteyse `supersedes: \"JIRA-n\"` (ya da `related_to`) ile referans ver; kapatılmış maddeyi yeniden yazma.":
        "- If input was already received earlier, write ONLY new or changed stories. If a changed story belongs to a closed sprint, reference it with `supersedes: \"JIRA-n\"` (or `related_to`); do not rewrite the closed item.",
    "\nMevcut hikâyeler:": "\nExisting stories:",
    "- {id} · {title} · sprint={sprint} · durum={status}": "- {id} · {title} · sprint={sprint} · status={status}",
    "\n\nNot: Bu klasörde zaten kod varsa PRD'yi 'mevcut sistemin geliştirilmesi' olarak yaz; var olan modülleri ve kısıtları dikkate al, sıfırdan kurulum önerme.":
        "\n\nNote: If this folder already contains code, write the PRD as 'enhancement of the existing system'; take the existing modules and constraints into account and do not propose a from-scratch setup.",
    "\n\n### Müşteri Görüşme Notları ve Şartname\n{spec}": "\n\n### Customer Meeting Notes and Specification\n{spec}",
    """# Product Requirement Document (PRD)
## 1. Talep Özeti
{prompt}{specs_info}

## 2. Kullanıcı Hikayeleri
- **US-01**: Kullanıcı olarak güvenli JWT token ile sisteme giriş yapabilmeliyim.
- **US-02**: Modern ve responsive arayüz üzerinden veri kayıtlarını listeleyip yönetebilmeliyim.
- **US-03**: Hata durumlarında anlaşılır JSON bildirimleri almalıyım.

## 3. Kabul Kriterleri (Acceptance Criteria)
- P95 API yanıt süresi < 120ms.
- Senior Backend ve Senior Frontend arasında tam API sözleşme uyumu.
- Playwright ile canlı tarayıcı E2E testlerinin %100 başarılı olması.
- Docker konteyner dağıtımına tam uyumluluk.
""": """# Product Requirement Document (PRD)
## 1. Request Summary
{prompt}{specs_info}

## 2. User Stories
- **US-01**: As a user, I must be able to sign in to the system with a secure JWT token.
- **US-02**: I must be able to list and manage data records through a modern, responsive UI.
- **US-03**: I must receive understandable JSON notifications when errors occur.

## 3. Acceptance Criteria
- P95 API response time < 120ms.
- Full API contract compatibility between Senior Backend and Senior Frontend.
- 100% success of the live browser E2E tests with Playwright.
- Full compatibility with Docker container deployment.
""",
    "Ürün": "Product",
    "Notlardaki hedeflerin toplamı": "Sum of the goals in the notes",
    "Ürün Yöneticisi (PM), müşteri notlarını ve gereksinimleri analiz ederek PRD dökümanını (<docs>/PRD.md) hazırladı. Kullanıcı hikayeleri ve kabul kriterleri tanımlandı.":
        "The Product Manager (PM) analyzed the customer notes and requirements and prepared the PRD document (<docs>/PRD.md). User stories and acceptance criteria were defined.",
    "Selam Mimar! Müşterimizin şartnamesini ve toplantı notlarını analiz ettim. Harika ve hızlı bir sistem istiyorlar. Hadi sağlam bir mimari kuralım!":
        "Hi Architect! I have analyzed our customer's specification and meeting notes. They want a great and fast system. Let's build a solid architecture!",
    "Kullanıcı": "User",
    "JWT ile giriş yapmak": "sign in with JWT",
    "Hesabıma güvenle erişebileyim": "I can access my account securely",
    "Kayıtları listeleyip yönetmek": "list and manage records",
    "Verilerimi tek panodan kontrol edeyim": "I can control my data from a single dashboard",
    "P95 API yanıt süresi < 120ms": "P95 API response time < 120ms",
    "E2E testleri %100 yeşil": "E2E tests 100% green",
    "Docker dağıtımı hazır": "Docker deployment ready",
    "OAuth2 sosyal giriş ilk sürümde yok": "No OAuth2 social login in the first release",

    # ---- ARCHITECT ----
    "## Müzakere kararı (seçilen mimari plan)": "## Deliberation decision (chosen architecture plan)",
    "- Plan: {plan}": "- Plan: {plan}",
    "- Özet: {summary}": "- Summary: {summary}",
    "- Yığın: {stack}": "- Stack: {stack}",
    "- Dikkat: {cons}": "- Caution: {cons}",
    "- Kabul edilen teknolojiler: {stack}": "- Agreed technologies: {stack}",
    "Mimariyi ve OpenAPI sözleşmesini bu plana sadık kalarak üret.": "Produce the architecture and the OpenAPI contract staying faithful to this plan.",
    "\n## Sprint kipi: görev kırılımı (zorunlu)\n- Aşağıdaki hikâyelerin her birini teslim edilebilir görevlere böl (şartnamenin TAMAMINI kapsayacak kadar görev üret, gereken sayıyı sen belirle; güvenlik tavanı {max_tasks}; kalan hikâyeler sonraki yapılandırma adımına kalır). Her görev: `id` (yalnızca bu çıktıdaki bağımlılıkları çözmek için), `title`, `role` (BACKEND_DEV | FRONTEND_DEV | DESIGNER | DEVOPS | QA | DOCUMENTOR; E2E_TESTER ve SCM görev alamaz), `work_type` (SCAFFOLD | FEATURE | DESIGN | TEST | E2E_SCENARIO | DEVOPS | DOCS | BUG | IMPROVEMENT | REFACTOR | TEST_DESIGN | SECURITY_TEST | PERF_SMOKE; TEST_DESIGN: QA'nın kabul kriterlerinden test case üretimi — sunucu da ekler), `story_ref` (aşağıdaki hikâye kimliği), `ac_refs`, `acceptance_criteria`, `depends_on`.\n- Bir görev tek teslimde bitecek büyüklükte olsun. Proje zaten kuruluysa SCAFFOLD görevi üretme.\n":
        "\n## Sprint mode: task breakdown (mandatory)\n- Split each of the stories below into deliverable tasks (produce enough tasks to cover the ENTIRE specification, you decide the number needed; safety cap {max_tasks}; remaining stories are left to the next configuration step). Each task: `id` (only to resolve dependencies within this output), `title`, `role` (BACKEND_DEV | FRONTEND_DEV | DESIGNER | DEVOPS | QA | DOCUMENTOR; E2E_TESTER and SCM cannot take tasks), `work_type` (SCAFFOLD | FEATURE | DESIGN | TEST | E2E_SCENARIO | DEVOPS | DOCS | BUG | IMPROVEMENT | REFACTOR | TEST_DESIGN | SECURITY_TEST | PERF_SMOKE; TEST_DESIGN: QA generating test cases from the acceptance criteria — the server adds it too), `story_ref` (the story id below), `ac_refs`, `acceptance_criteria`, `depends_on`.\n- A task must be small enough to finish in a single delivery. Do not produce a SCAFFOLD task if the project is already set up.\n",
    "\nKırılımı bekleyen hikâyeler:\n": "\nStories awaiting breakdown:\n",
    "- {id} · {title} · {refs}": "- {id} · {title} · {refs}",
    "\nKırılımı bekleyen hikâye yok; yalnızca mimari belgeleri güncelle.": "\nNo stories awaiting breakdown; only update the architecture documents.",
    "\n## Backlog ve doğrulama (zorunlu)\n- `backlog`: PRD'deki kullanıcı hikayelerinin TAMAMINI kapsayacak kadar (sayıyı ihtiyaca göre sen belirle; güvenlik tavanı {max_tasks}) bağımsız teslim edilebilir geliştirme görevine böl. Her görev tek bir ajana atanır (`role`: BACKEND_DEV | FRONTEND_DEV | DESIGNER | DEVOPS | QA), 1-3 saatlik iş büyüklüğünde olsun, ölçülebilir `acceptance_criteria` ve dokunulacak `files` listesi içersin; `depends_on` ile sırayı belirt. Adım 3 (backend iskeleti) ve adım 4 (frontend iskeleti) proje kurulumunu yapar; backlog görevleri bu iskeletin ÜZERİNE özellik ekler, iskelet işlerini tekrar listeleme. Arayüz içeren projede ilk iş tasarımdır: tasarım sistemi + ilk ekranlar için `role: DESIGNER`, `work_type: DESIGN` görevi ekle; frontend görevleri ona `depends_on` ile bağlansın.\n- `libraries`: onaylı teknoloji yığını İÇİNDE kullanacağın her kütüphane (`name`, `purpose`, `technology`). Burada olmayan ya da onaylı teknolojide geçmeyen bir bağımlılığı manifeste (requirements.txt, package.json, composer.json, Dockerfile, compose) EKLEYEN teslimler sunucuca reddedilir; yeni teknoloji gerekiyorsa ekleme, yöneticiye bırak.\n- `verification`: sunucunun her teslimden sonra proje kökünde koşacağı GERÇEK komutlar (seçilen teknolojiye uygun): `install`, `test`, `build` (gerekirse `lint`), uygulamayı başlatan `run` ve sağlık adresi `health_url` (örn. install: \"pip install -r requirements.txt\", test: \"python -m pytest -q\", run: \"uvicorn src.main:app --port 8000\", health_url: \"http://127.0.0.1:8000/health\"). Komutlar bu makinede çalışacak; var olmayan araç kullanma.":
        "\n## Backlog and verification (mandatory)\n- `backlog`: split the PRD user stories into independently deliverable development tasks, enough to cover ALL of them (you decide the number as needed; safety cap {max_tasks}). Each task is assigned to a single agent (`role`: BACKEND_DEV | FRONTEND_DEV | DESIGNER | DEVOPS | QA), should be 1-3 hours of work, and must include measurable `acceptance_criteria` and the list of `files` to touch; state the order with `depends_on`. Step 3 (backend skeleton) and step 4 (frontend skeleton) do the project setup; backlog tasks add features ON TOP of that skeleton, so do not list the skeleton work again. In a project with a UI, the first job is design: add a `role: DESIGNER`, `work_type: DESIGN` task for the design system + first screens; frontend tasks must depend on it via `depends_on`.\n- `libraries`: every library you will use WITHIN the approved technology stack (`name`, `purpose`, `technology`). Deliveries that ADD a dependency to a manifest (requirements.txt, package.json, composer.json, Dockerfile, compose) that is not listed here or is not part of the approved technology are rejected by the server; if a new technology is needed, do not add it, leave it to the manager.\n- `verification`: the REAL commands the server will run in the project root after every delivery (appropriate for the chosen technology): `install`, `test`, `build` (and `lint` if needed), `run` which starts the application, and the health address `health_url` (e.g. install: \"pip install -r requirements.txt\", test: \"python -m pytest -q\", run: \"uvicorn src.main:app --port 8000\", health_url: \"http://127.0.0.1:8000/health\"). The commands will run on this machine; do not use tools that do not exist.",
    "\n## Özel ajanlar (G6)\n": "\n## Custom agents (G6)\n",
    "\n- Görevin işi bir özel ajanın odağına giriyorsa görevi ona ata (`role` = ajan kimliği); aksi halde çekirdek rolleri kullan.":
        "\n- If a task falls within a custom agent's focus, assign it to that agent (`role` = agent id); otherwise use the core roles.",
    "JWT Token Giriş": "JWT Token Login",
    "Token Başarılı": "Token Successful",
    "Veri listesi": "Data list",
    "Yeni kayıt oluştur": "Create new record",
    "Sistem Mimarı (Architect), mikroservis mimarisini tasarladı ve OpenAPI 3.0 API sözleşmesini (<docs>/openapi_spec.json) yayınladı.":
        "The System Architect designed the microservice architecture and published the OpenAPI 3.0 API contract (<docs>/openapi_spec.json).",
    "Selam Backend! REST API kontratı ve Pydantic veri modelleri hazır. Endpoint'leri kodlamaya başlayabilirsin!":
        "Hi Backend! The REST API contract and Pydantic data models are ready. You can start coding the endpoints!",
    "Kayıt listesi filtreleme ve sayfalama": "Record list filtering and pagination",
    "GET /api/v1/items için kategori filtresi ve sayfalama parametreleri ekle; birim testleriyle birlikte.":
        "Add a category filter and pagination parameters for GET /api/v1/items, together with unit tests.",
    "?category= ile filtrelenir": "Filters with ?category=",
    "?page=&size= ile sayfalanır": "Paginates with ?page=&size=",
    "Testler yeşil": "Tests are green",
    "Arayüzde kayıt listesi ve filtre bileşeni": "Record list and filter component in the UI",
    "Giriş sonrası kayıtları listeleyen, kategoriye göre filtreleyen bileşen ve API istemci fonksiyonu.":
        "A component that lists records after sign-in and filters them by category, plus the API client function.",
    "Liste API'den yüklenir": "The list loads from the API",
    "Filtre değişince liste yenilenir": "The list refreshes when the filter changes",
    "API çatısı": "API framework",
    "ASGI sunucusu": "ASGI server",
    "Girdi doğrulama": "Input validation",
    "Birim testleri": "Unit tests",

    # ---- BACKEND ----
    "## Bu adımın kapsamı: BACKEND İSKELETİ\nÇalışan, test edilebilir bir uygulama iskeleti kur: bağımlılık manifesti, giriş noktası, sağlık ucu (/health), kimlik doğrulama temeli, veri katmanı kurulumu ve en az bir birim testi. Backlog görevleri daha sonra bu iskelete özellik ekleyecek; tüm özellikleri burada yazmaya çalışma. Sunucu teslimden sonra kurulum/test komutlarını koşacak.":
        "## Scope of this step: BACKEND SKELETON\nSet up a working, testable application skeleton: dependency manifest, entry point, health endpoint (/health), authentication foundation, data layer setup and at least one unit test. Backlog tasks will add features to this skeleton later; do not try to write all the features here. The server will run the install/test commands after delivery.",
    "Kimlik Doğrulama ve JWT Token Modülü (demo — üretimde gerçek JWT kütüphanesi ve gizli anahtar yönetimi kullanın)":
        "Authentication and JWT Token Module (demo — in production use a real JWT library and proper secret management)",
    "FastAPI Backend Uygulaması - Senior Backend Developer": "FastAPI Backend Application - Senior Backend Developer",
    "Kullanıcı adı ve şifre zorunludur.": "Username and password are required.",
    "Kıdemli Backend Geliştiricisi, FastAPI REST servislerini, JWT token imzalama ve doğrulama modüllerini (src/auth.py, src/main.py) geliştirdi.":
        "The Senior Backend Developer built the FastAPI REST services and the JWT token signing and verification modules (src/auth.py, src/main.py).",
    "Selam Frontend! Giriş ve veri yönetim API'larını tamamladım, port 8080'de yayında. Arayüze bağlayabilirsin!":
        "Hi Frontend! I have finished the sign-in and data management APIs; they are live on port 8080. You can connect the UI!",
    "Şablon motoru yer tutucu testi (sıkı DoD): iskelet dosyaları var.": "Template engine placeholder test (strict DoD): the skeleton files exist.",

    # ---- FRONTEND ----
    "## Bu adımın kapsamı: İSTEMCİ İSKELETİ\nSeçilen istemci teknolojisiyle kurulabilir bir uygulama iskeleti kur: paket manifesti (örn. package.json ve build betiği), giriş ekranı/akışı, API istemci katmanı, yönlendirme temeli. Backlog görevleri ekranları bu iskelete ekleyecek. Backend'in gerçek uç noktalarını (OpenAPI) kullan; uydurma uç nokta yazma.":
        "## Scope of this step: CLIENT SKELETON\nSet up an installable application skeleton with the chosen client technology: package manifest (e.g. package.json and build script), sign-in screen/flow, API client layer, routing foundation. Backlog tasks will add the screens to this skeleton. Use the backend's real endpoints (OpenAPI); do not invent endpoints.",
    "Senior Frontend Developer - API Client Modülü": "Senior Frontend Developer - API Client Module",
    "Giriş başarısız. Bilgilerinizi kontrol edin.": "Sign-in failed. Please check your credentials.",
    "Kullanıcı Adı": "Username",
    "Şifre": "Password",
    "Giriş Yap": "Sign In",
    "Hoşgeldiniz, oturum aktif.": "Welcome, your session is active.",
    "Kıdemli Frontend Geliştiricisi, modern React panosunu (frontend/src/App.tsx) ve API Client (frontend/src/api_client.ts) modülünü kodladı.":
        "The Senior Frontend Developer coded the modern React dashboard (frontend/src/App.tsx) and the API Client module (frontend/src/api_client.ts).",
    "Harika, API bağlantılarını ve veri akışını teyit ettim. Karşılıklı el sıkıştık!": "Great, I have confirmed the API connections and the data flow. We shook hands!",

    # ---- HANDSHAKE ----
    "Geliştiriciler Arası Eş İnceleme (Peer Review): Senior Backend ve Senior Frontend doğrudan A2A iletişimi kurarak CORS, Bearer token başlığı ve model senkronizasyonunu onayladı.":
        "Peer Review between developers: Senior Backend and Senior Frontend communicated directly over A2A and confirmed CORS, the Bearer token header and model synchronization.",
    "Backend servislerini ve middleware'i kodladık, kontrat hizalandı. QA, birim testler için hazır!": "We coded the backend services and the middleware; the contract is aligned. QA, it is ready for unit tests!",
    "Senior Frontend, /api/auth/login dönüşünde Bearer token header'ını 'Authorization: Bearer <token>' formatında gönderdiğinden emin ol.":
        "Senior Frontend, make sure you send the Bearer token header in the 'Authorization: Bearer <token>' format after /api/auth/login returns.",
    "Doğrulandı Senior Backend. Fetch interceptor'ı Bearer header'ını ekleyecek şekilde yapılandırıldı.": "Confirmed, Senior Backend. The fetch interceptor is configured to add the Bearer header.",

    # ---- QA ----
    "\n## Kod dosyası: {rel}\n```\n{content}\n```": "\n## Code file: {rel}\n```\n{content}\n```",
    "\n## Bu adımın kapsamı: ENTEGRASYON VE REGRESYON TESTLERİ\nKabul kriterlerini ve uç durumları kapsayan GERÇEK test dosyaları yaz (seçilen test aracıyla: pytest/jest/phpunit...). Sunucu teslimden sonra test komutunu gerçekten koşacak; testler kalırsa geliştiriciye düzeltme turu açılır. `verdict` yalnızca kodun kabul kriterlerine uygunluğunu yansıtsın; kanıtsız APPROVED verme.":
        "\n## Scope of this step: INTEGRATION AND REGRESSION TESTS\nWrite REAL test files that cover the acceptance criteria and edge cases (with the chosen test tool: pytest/jest/phpunit...). The server will actually run the test command after delivery; if tests fail, a fix round is opened for the developer. `verdict` must reflect only whether the code conforms to the acceptance criteria; do not give APPROVED without evidence.",
    "Otomatik Birim ve Entegrasyon Testleri - QA Lead": "Automated Unit and Integration Tests - QA Lead",
    """# QA Onay Raporu
- Tüm birim testler: 2/2 GEÇTİ
- API kontrat uyumu: %100 ONAYLANDI
- Ajanlar arası veri bütünlüğü: DOĞRULANDI
- Tespit edilen hata: BUG-QA-01 (LOW) — boş kullanıcı adı doğrulaması eklendi
""": """# QA Approval Report
- All unit tests: 2/2 PASSED
- API contract compatibility: 100% APPROVED
- Data integrity between agents: VERIFIED
- Detected bug: BUG-QA-01 (LOW) — empty username validation added
""",
    "QA Mühendisi (Lead QA), otomatik birim testlerini (tests/test_app.py) çalıştırdı, tespit edilen küçük hata için düzeltme doğrulaması yaptı ve QA Onay Raporunu yayınladı.":
        "The QA Engineer (Lead QA) ran the automated unit tests (tests/test_app.py), verified the fix for the minor bug found and published the QA Approval Report.",
    "Birim ve API testleri başarıyla onaylandı. Canlı tarayıcı testlerine geçebilirsin!": "Unit and API tests were approved successfully. You can move on to the live browser tests!",
    "Birim testlerini koşturdum, bir hata yakaladım. Hemen düzeltip tekrar iletebilir misin?": "I ran the unit tests and caught a bug. Could you fix it right away and resubmit?",
    "Düzeltildi.": "Fixed.",

    # ---- E2E ----
    "Playwright koşulmadı": "Playwright was not run",
    "Playwright E2E Tester, canlı Chromium tarayıcısı açtı, kullanıcı formlarını denedi ve kanıt ekran görüntüleri yakaladı.":
        "The Playwright E2E Tester opened a live Chromium browser, tried the user forms and captured evidence screenshots.",
    "Playwright E2E testi KOŞULAMADI ({status}): {error}": "The Playwright E2E test COULD NOT RUN ({status}): {error}",
    "bilinmeyen hata": "unknown error",
    "Canlı Chromium tarayıcısında uçtan uca senaryoları çalıştırdım, ekran görüntülerini kaydettim. Her şey kusursuz!":
        "I ran the end-to-end scenarios in a live Chromium browser and saved the screenshots. Everything is flawless!",
    "Tarayıcı testini koşamadım, ortamda Playwright/Chromium eksik görünüyor. DevOps, bir göz atar mısın?":
        "I could not run the browser test; Playwright/Chromium seems to be missing in the environment. DevOps, could you take a look?",

    # ---- DEVOPS ----
    "\n## Manifest: {rel}\n```\n{content}\n```": "\n## Manifest: {rel}\n```\n{content}\n```",
    "\n## Kayıtlı doğrulama/çalıştırma komutları\n```json\n": "\n## Registered verification/run commands\n```json\n",
    "Konteyner ve başlatma yapılandırmasını seçilen teknolojiye ve gerçek dosya adlarına göre yaz; README'de kurulum ve çalıştırma adımlarını ver.":
        "Write the container and startup configuration according to the chosen technology and the real file names; give the install and run steps in the README.",
    "# {name}\n\nBu proje **FS-SC Çoklu Ajan Şirket Sistemi** tarafından üretilmiştir.\n10 maddelik Jira pipeline'ı ile geliştirilmiştir.\n":
        "# {name}\n\nThis project was generated by the **FS-SC Multi-Agent Company System**.\nIt was developed with a 10-item Jira pipeline.\n",
    "DevOps Mühendisi, Dockerfile ve docker-compose.yml yapılandırmasını tamamlayıp sürümü üretime hazır hale getirdi.":
        "The DevOps Engineer completed the Dockerfile and docker-compose.yml configuration and made the release ready for production.",
    "Konteyner ve deployment yapılandırması tamamlandı! Sistemimiz canlıda aktif, müşteriye gururla sunabiliriz.":
        "The container and deployment configuration is complete! Our system is live; we can proudly present it to the customer.",

    # ---- PO ----
    "Sprint {n} kabulü (PO UAT)": "Sprint {n} acceptance (PO UAT)",
    "Sprint {n} kapsamındaki kabul kriterlerini sunucunun topladığı kanıtla (test ve E2E sonuçları) karşılaştırıp kriter bazında karar vereceğim.":
        "I will compare the acceptance criteria in scope of sprint {n} with the evidence the server collected (test and E2E results) and decide per criterion.",
    "Sprint {n} kabul kriterlerini kanıtlarıyla denetliyor": "Auditing the sprint {n} acceptance criteria against their evidence",
    "Kanıtlı kriterleri kabul edecek, kanıtsızları iyileştirme işi olarak geri çevirecek": "Will accept the criteria that have evidence and send back those without evidence as improvement work",
    "\n## Kriter bazında karar (sıkı DoD, zorunlu)\n`criteria[]` içinde bu sprintin her kabul kriteri için ayrı karar ver (ACCEPTED | REJECTED, gerekçeyle). Kanıtı olmayan kriteri kabul edemezsin; sunucu kanıtsız kabulü reddeder.\n":
        "\n## Decision per criterion (strict DoD, mandatory)\nIn `criteria[]`, give a separate decision (ACCEPTED | REJECTED, with a reason) for each acceptance criterion of this sprint. You cannot accept a criterion that has no evidence; the server rejects acceptance without evidence.\n",
    "kanıt var (test: {tests}; E2E: {e2e}; case: {cases})": "evidence present (test: {tests}; E2E: {e2e}; case: {cases})",
    "KANIT YOK": "NO EVIDENCE",
    "- (bu sprintte kapsanan kriter yok)": "- (no criteria covered in this sprint)",
    "\nTest izlenebilirlik matrisi: kapsama %{coverage} (hedef %{target}); case'siz kriter: {no_case}; başarısız: {failing}; regresyon kümesi: {gate}. Kararını bu matrise dayandır.":
        "\nTest traceability matrix: coverage {coverage}% (target {target}%); criteria without a case: {no_case}; failing: {failing}; regression set: {gate}. Base your decision on this matrix.",
    "geçti": "passed",
    "GEÇMEDİ": "DID NOT PASS",
    "\n## UAT kuralı\nPRD'deki her kullanıcı hikayesi ve kabul kriteri için 'karşılandı / kısmen / eksik' kararı ver. ":
        "\n## UAT rule\nFor every user story and acceptance criterion in the PRD, give a 'met / partially met / missing' decision. ",
    "`uat_status: REJECTED` verirsen `improvements[]` içindeki her madde bir geliştirme görevine dönüşür ve ekip QA + UAT turunu yeniden koşar (kalan iyileştirme turu: {remaining}). Yalnızca gerçekten eksik olan işleri yaz.":
        "If you give `uat_status: REJECTED`, every item in `improvements[]` becomes a development task and the team re-runs the QA + UAT round (remaining improvement rounds: {remaining}). Write only the work that is truly missing.",
    "İyileştirme turu hakkı kalmadı: eksikleri `improvements[]` ile belgele; karar bilgilendirici olacak.":
        "No improvement rounds left: document the gaps in `improvements[]`; the decision will be informational.",
    """# 🏆 Product Owner (PO) UAT Kabul Raporu
**Proje:** {name}
**Tarih:** {date}
**PO Değerlendirmesi:** KABUL EDİLDİ (UAT_APPROVED) - Puan: 98/100

### 1. Doğrulanan Kabul Kriterleri
- [x] Müşteri toplantı notları ve şartname hedefleri eksiksiz karşılandı.
- [x] OpenAPI 3.0 sözleşmesi ve veri modelleri standartlara uygun.
- [x] FastAPI REST servisleri ve JWT kimlik doğrulama test edildi.
- [x] Modern ve responsive React arayüzü form validasyonları çalışıyor.
- [x] Lead QA birim testleri ve Playwright canlı tarayıcı E2E akışı yeşil.
- [x] Docker ve konteyner dağıtım konfigürasyonu hazır.

### 2. Kullanıcı Deneyimi & İş Değeri Notları
- Arayüz akıcı, bildirimler Türkçe ve anlaşılır.
- UAT testi başarıyla onaylanmış olup son kullanıcı kılavuzları için Documentor ajanı görevlendirilmiştir.
""": """# 🏆 Product Owner (PO) UAT Acceptance Report
**Project:** {name}
**Date:** {date}
**PO Assessment:** ACCEPTED (UAT_APPROVED) - Score: 98/100

### 1. Verified Acceptance Criteria
- [x] The customer meeting notes and specification goals were fully met.
- [x] The OpenAPI 3.0 contract and data models comply with the standards.
- [x] FastAPI REST services and JWT authentication were tested.
- [x] The modern, responsive React UI form validations work.
- [x] Lead QA unit tests and the Playwright live browser E2E flow are green.
- [x] Docker and container deployment configuration is ready.

### 2. User Experience & Business Value Notes
- The UI is fluid; notifications are clear and understandable.
- The UAT test was approved successfully and the Documentor agent has been assigned the end-user manuals.
""",
    "kanıt: ": "evidence: ",
    "yok": "none",
    "Product Owner (PO), geliştirilen ürünü PRD ve müşteri kabul kriterlerine göre denetledi, UAT onayını (UAT_APPROVED) verdi.":
        "The Product Owner (PO) audited the developed product against the PRD and the customer acceptance criteria and gave the UAT approval (UAT_APPROVED).",
    "UAT Kabul Testi Başarılı! Ürün müşteri şartnamesini karşılıyor. Son kullanıcı kılavuzunu hazırlayabilirsin Documentor!":
        "UAT acceptance test passed! The product meets the customer specification. You can prepare the end-user manual, Documentor!",
    "UAT kabul kriterlerini onaylıyor": "Approving the UAT acceptance criteria",
    "Documentor'a kullanım kılavuzu üretimini devrediyor": "Handing the user manual production over to the Documentor",

    # ---- DOCS ----
    "Durum raporunda koşu özetindeki gerçek adımları, doğrulama sonuçlarını ve commit'leri kullan; CHANGELOG.md'yi bu koşunun teslimatlarıyla yaz.":
        "In the status report use the real steps, verification results and commits from the run summary; write CHANGELOG.md with the deliveries of this run.",
    """# 📖 {name} - Kullanım Kılavuzu (User Manual)
**Hazırlayan:** Documentor Ajanı
**Tarih:** {date}

## 1. Sisteme Giriş ve Genel Bakış
Bu kılavuz, sistemin kurulumu ve son kullanıcı adımlarını açıklar.

### 2. Kurulum ve Çalıştırma
```bash
pip install -r requirements.txt
uvicorn src.main:app --port 8080
```

### 3. API Kullanımı
- `GET /health` -> Sistem sağlık kontrolü
- `POST /api/auth/login` -> Kullanıcı kimlik doğrulama
- `GET /api/v1/items` -> Veri listeleme ve yönetim
""": """# 📖 {name} - User Manual
**Prepared by:** Documentor Agent
**Date:** {date}

## 1. Introduction and Overview
This guide explains the installation of the system and the end-user steps.

### 2. Installation and Running
```bash
pip install -r requirements.txt
uvicorn src.main:app --port 8080
```

### 3. API Usage
- `GET /health` -> System health check
- `POST /api/auth/login` -> User authentication
- `GET /api/v1/items` -> Data listing and management
""",
    """# 📊 Yönetici Durum Raporu (Executive Summary)
**Proje:** {name}
**Tarih:** {date}
**Genel Sağlık:** 🟢 MÜKEMMEL (ALL GREEN)

### Özet İstatistikler
- **Toplam Tamamlanan Görev:** {done} / {done}
- **QA & E2E Test Başarısı:** bkz. <docs>/QA_REPORT.md ve <reports>/e2e_summary.json
- **PO UAT Onayı:** bkz. <docs>/uat/acceptance_criteria.md
- **Harcanan Token:** Yaklaşık {tokens} token
""": """# 📊 Executive Status Report (Executive Summary)
**Project:** {name}
**Date:** {date}
**Overall Health:** 🟢 EXCELLENT (ALL GREEN)

### Summary Statistics
- **Total Completed Tasks:** {done} / {done}
- **QA & E2E Test Success:** see <docs>/QA_REPORT.md and <reports>/e2e_summary.json
- **PO UAT Approval:** see <docs>/uat/acceptance_criteria.md
- **Tokens Spent:** approximately {tokens} tokens
""",
    "Documentor Ajanı son kullanıcı kılavuzunu (user_guide.md), Reporter Ajanı ise yönetici durum özetini (status_report.md) oluşturdu.":
        "The Documentor agent produced the end-user manual (user_guide.md) and the Reporter agent produced the executive status summary (status_report.md).",
    "Kılavuz ve yönetici özeti hazır! Teslimat dokümantasyonu tamamlandı, tebrikler ekip.": "The manual and the executive summary are ready! The delivery documentation is complete, congratulations team.",
}
