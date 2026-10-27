"""İngilizce karşılıklar: hub çekirdeği (telemetry, config, agent_registry, fs_workspace, hierarchy, jira_plus, project_bootstrap, project_files).

Anahtar = Türkçe kaynak metin (kodda `tx("...")` / `N_("...")`), değer = İngilizce. Kurallar: docs/i18n-sunucu-ceviri-kurallari.md.
"""
EN = {
    'Müşteri görüşme notlarını ve şartnamesini analiz et, iş gereksinimlerini ve kullanıcı kabul kriterlerini PRD dokümanına dök.':
        'Analyze the customer meeting notes and specification, and capture the business requirements and user acceptance criteria in the PRD document.',
    'Takım lideri / Architect değerlendirmesi: OpenAPI 3.0 şemaları, veri modelleri ve servis mimarisini tasarla.':
        'Tech lead / Architect review: design the OpenAPI 3.0 schemas, data models and service architecture.',
    'Senior Backend: Core Auth & REST Servisleri':
        'Senior Backend: Core Auth & REST Services',
    'Senior Backend Developer: Kimlik doğrulama, token yönetimi, veritabanı modelleri ve CRUD API uç noktalarını geliştir.':
        'Senior Backend Developer: build authentication, token management, database models and CRUD API endpoints.',
    'Senior Frontend: Responsive UI & API Client Entegrasyonu':
        'Senior Frontend: Responsive UI & API Client Integration',
    'Senior Frontend Developer: React / Tailwind / Vite kullanıcı arayüzü, state yönetimi ve API entegrasyonunu tamamla.':
        'Senior Frontend Developer: complete the React / Tailwind / Vite user interface, state management and API integration.',
    'Peer Review & Backend-Frontend API Handshake':
        'Peer Review & Backend-Frontend API Handshake',
    'Senior Backend ve Senior Frontend geliştiriciler arası doğrudan A2A iletişim: İstek/yanıt modelleri, CORS ve token senkronizasyonu.':
        'Direct A2A communication between the Senior Backend and Senior Frontend developers: request/response models, CORS and token synchronization.',
    'QA Kapsamlı Test & Bug Taraması':
        'QA Comprehensive Testing & Bug Sweep',
    "Lead QA Engineer: Birim testleri, regresyon testleri ve edge case taramaları koştur, bulunan bug'ları raporla ve doğrulama yap.":
        'Lead QA Engineer: run unit tests, regression tests and edge-case sweeps, report the bugs found and verify the fixes.',
    'Playwright E2E Otomasyonu (Tarayıcı Giriş & Akış Testi)':
        'Playwright E2E Automation (Browser Login & Flow Test)',
    'Playwright E2E Tester: Gerçek Chromium tarayıcısı açılır, uygulamaya login olunur, kritik akışlar test edilir ve ekran görüntüleri raporlanır.':
        'Playwright E2E Tester: open a real Chromium browser, log in to the application, test critical flows and report screenshots.',
    'DevOps Dağıtım & Docker/Health Kontrolü':
        'DevOps Deployment & Docker/Health Check',
    'DevOps & SRE: Dockerfile, Docker Compose yapılandırması, staging ortamı dağıtımı ve sağlık kontrolü (health check).':
        'DevOps & SRE: Dockerfile, Docker Compose configuration, staging deployment and health check.',
    'Product Owner: Geliştirilen ekranları, API yanıtlarını ve PRD gereksinimlerini kontrol et, UAT testini onayla ve eksiklikleri tespit et.':
        'Product Owner: review the delivered screens, API responses and PRD requirements, approve the UAT and identify gaps.',
    'Documentor Ajanı son kullanıcı kullanım kılavuzunu (docs/manuals/user_guide.md) üretir; Reporter Ajanı ise sprint özetini ve metriklerini yönetici raporuna (docs/reports/status_report.md) döker.':
        'The Documentor agent produces the end-user guide (docs/manuals/user_guide.md); the Reporter agent writes the sprint summary and metrics into the management report (docs/reports/status_report.md).',
    'Admin / Süper Yönetici':
        'Admin / Super Administrator',
    'Tüm modüllere tam yetkili yönetici erişimi ve kritik panel testi':
        'Full administrator access to all modules and critical panel testing',
    'Standart Müşteri / Son Kullanıcı':
        'Standard Customer / End User',
    'Temel kullanıcı kaydı, profil görüntüleme ve form akışları':
        'Basic user registration, profile viewing and form flows',
    'Mağaza & İçerik Editörü':
        'Store & Content Editor',
    'Katalog yönetimi, içerik güncelleme ve yayınlama yetkisi':
        'Catalog management, content updates and publishing rights',
    'Finans & Muhasebe Sorumlusu':
        'Finance & Accounting Officer',
    'Ödeme, fatura ve sipariş mutabakat ekranları testi':
        'Payment, invoice and order reconciliation screen tests',
    'Güvenlik Saldırısı / Hatalı Giriş (Negatif Test)':
        'Security Attack / Failed Login (Negative Test)',
    '401/403 yetkisiz erişim kontrolü ve form hata doğrulaması':
        '401/403 unauthorized access checks and form error validation',
    'Selam Takım! API kontratlarını, veri modellerini ve güvenliği planladım. Kodlamaya başlayabilirsiniz, kolay gelsin!':
        'Hi team! I have planned the API contracts, data models and security. You can start coding, good luck!',
    'Selam Frontend! Arayüz bileşen şemasını ve veri kontratını çıkardım. Sayfaları tasarlamaya başlayabilirsin!':
        'Hi Frontend! I have drafted the UI component schema and the data contract. You can start designing the pages!',
    'Selam QA Ekibi! İstenen özellikleri ve birim testlerini tamamladım. İncelemeniz ve test etmeniz için hazır!':
        'Hi QA team! I have finished the requested features and unit tests. Ready for your review and testing!',
    "Backend servislerini ve middleware'i kodladım. Birim testler için hazır, inceleyebilirsin!":
        'I have coded the backend services and middleware. Ready for unit tests, you can review it!',
    'Kullanıcı arayüzünü ve formları bitirdim. Sayfa çok akıcı ve şık oldu. Canlı tarayıcıda Playwright ile test edebilir misin?':
        'I have finished the user interface and the forms. The page feels smooth and polished. Can you test it with Playwright in a live browser?',
    'Birim testlerini koşturdum, birkaç küçük hata yakaladım. Hemen düzeltip tekrar iletebilir misin?':
        'I ran the unit tests and caught a few minor bugs. Could you fix them right away and resubmit?',
    'Test koşusu sırasında beklenmeyen bir hata oluştu, logları inceleyip düzeltebilir misin?':
        'An unexpected error occurred during the test run. Could you check the logs and fix it?',
    'Birim testleri ve güvenlik kontrolleri 0 hatayla geçti! Dağıtım ve canlıya çıkış için onay veriyorum.':
        'Unit tests and security checks passed with 0 failures! I approve it for deployment and go-live.',
    'Müşteri Keşif ve Gereksinim Projesi':
        'Customer Discovery & Requirements Project',
    'Kurumsal Müşteri':
        'Corporate Customer',
    'Müşteri görüşme notları ve yüklenen dosyalar incelendi':
        'Customer meeting notes and uploaded files were reviewed',
    'docs/PRD.md iş gereksinimleri oluşturuldu':
        'docs/PRD.md business requirements were created',
    'Kullanıcı kabul kriterleri (Acceptance Criteria) tanımlandı':
        'User acceptance criteria (Acceptance Criteria) were defined',
    'OpenAPI JSON ve Pydantic veri modelleri oluşturuldu':
        'OpenAPI JSON and Pydantic data models were created',
    'Frontend ve Backend geliştiriciler için API sözleşmesi donduruldu':
        'The API contract was frozen for Frontend and Backend developers',
    'Hata kodları ve HTTP durum standartları belirlendi':
        'Error codes and HTTP status standards were defined',
    'FastAPI REST servisleri ve auth middleware yazıldı':
        'FastAPI REST services and auth middleware were written',
    'JWT imzalama ve doğrulama mantığı entegre edildi':
        'JWT signing and verification logic was integrated',
    'İş mantığı exception handler ile korundu':
        'Business logic was protected with an exception handler',
    'Modern kullanıcı deneyimine sahip responsive bileşenler kodlandı':
        'Responsive components with a modern user experience were coded',
    'Giriş ve veri yönetim formları bağlandı':
        'Login and data management forms were wired up',
    'API istemcisi Backend sözleşmesiyle senkronize edildi':
        'The API client was synchronized with the Backend contract',
    'Geliştiriciler karşılıklı API kontratını doğruladı':
        'The developers mutually verified the API contract',
    'CORS ve token header geçişleri teyit edildi':
        'CORS and token header passing were confirmed',
    'Uçtan uca mock istekleriyle senkronizasyon sağlandı':
        'Synchronization was achieved with end-to-end mock requests',
    'Birim testler ve edge-case senaryoları çalıştırıldı':
        'Unit tests and edge-case scenarios were run',
    "Tespit edilen bug'lar Developer'a iletilip kapatıldı":
        'The detected bugs were forwarded to the Developer and closed',
    'Tüm fonksiyonel gereksinimler doğrulandı':
        'All functional requirements were verified',
    'Playwright Chromium tarayıcısı canlı uygulamayı açtı':
        'The Playwright Chromium browser opened the live application',
    'Kullanıcı giriş ve form etkileşimi simüle edildi':
        'User login and form interaction were simulated',
    'Rapor ve ekran görüntüleri sisteme kaydedildi':
        'The report and screenshots were saved to the system',
    'Dockerfile ve docker-compose konfigürasyonu üretildi':
        'Dockerfile and docker-compose configuration were produced',
    'Healthcheck endpoint doğrulandı':
        'The healthcheck endpoint was verified',
    "Team Lead ve PM'e release onayı iletildi":
        'The release approval was forwarded to the Team Lead and PM',
    'Kullanıcı kabul kriterleri PRD ile birebir doğrulandı':
        'User acceptance criteria were verified one-to-one against the PRD',
    'Kullanıcı deneyimi (UX/UI) denetlendi ve UAT onayı verildi':
        'The user experience (UX/UI) was reviewed and the UAT approval was given',
    'Eksik özellik veya iyileştirme açılmadıysa canlı sürüme onay verildi':
        'If no missing feature or improvement was raised, the go-live was approved',
    'docs/manuals/user_guide.md kullanım kılavuzu oluşturuldu':
        'docs/manuals/user_guide.md user guide was created',
    'README.md ve API referansları güncellendi':
        'README.md and API references were updated',
    'docs/reports/status_report.md yönetici durum özeti hazırlandı':
        'docs/reports/status_report.md management status summary was prepared',
    "{from_agent}: '{action}' adımını tamamladım, {to_agent} ile el sıkışıyoruz.":
        "{from_agent}: I completed the '{action}' step, shaking hands with {to_agent}.",
    'Müşteri Görüşme Notu':
        'Customer Meeting Note',
    'Müşteri':
        'Customer',
    'Müşteri Keşif & PRD: {title}':
        'Customer Discovery & PRD: {title}',
    'Müşteri: {client}\nTalep: {title}\nÖzet: {summary}...\nBelgeler: {docs}':
        'Customer: {client}\nRequest: {title}\nSummary: {summary}...\nDocuments: {docs}',
    'Sistem Mimarisi & API Kontratı ({title})':
        'System Architecture & API Contract ({title})',
    'Team Lead / Architect: {client} için mikroservis şemaları, OpenAPI 3.0 sözleşmesi ve veri modelleri.':
        'Team Lead / Architect: microservice schemas, OpenAPI 3.0 contract and data models for {client}.',
    'Senior Backend: REST API & Servisleri ({title})':
        'Senior Backend: REST API & Services ({title})',
    'Senior Backend Dev: {title} kapsamında JWT auth, CRUD operasyonları ve iş mantığını kodla.':
        'Senior Backend Dev: code the JWT auth, CRUD operations and business logic within the scope of {title}.',
    'Senior Frontend: Responsive UI & Formlar ({title})':
        'Senior Frontend: Responsive UI & Forms ({title})',
    'Senior Frontend Dev: {client} talebine uygun React / Tailwind kullanıcı deneyimi ve API istemcisi.':
        'Senior Frontend Dev: React / Tailwind user experience and API client matching the request of {client}.',
    'Geliştiriciler arası doğrudan A2A mutabakatı: {title} veri akışı, CORS ve Bearer token header senkronizasyonu.':
        'Direct A2A agreement between the developers: {title} data flow, CORS and Bearer token header synchronization.',
    'Lead QA: Birim ve Fonksiyonel Doğrulama ({title})':
        'Lead QA: Unit & Functional Verification ({title})',
    "Lead QA: {title} test senaryolarını çalıştır, edge case'leri doğrula ve QA raporunu yayınla.":
        'Lead QA: run the {title} test scenarios, verify the edge cases and publish the QA report.',
    'Playwright E2E: Canlı Tarayıcı Doğrulama ({title})':
        'Playwright E2E: Live Browser Verification ({title})',
    'Playwright E2E Tester: Canlı Chromium tarayıcısında {title} arayüzünü test et ve ekran görüntüleri yakala.':
        'Playwright E2E Tester: test the {title} interface in a live Chromium browser and capture screenshots.',
    'DevOps Dağıtım & Docker Yayını ({title})':
        'DevOps Deployment & Docker Release ({title})',
    'DevOps Mühendisi: {title} uygulamasını Dockerfile ve docker-compose ile üretime hazırla.':
        'DevOps Engineer: get the {title} application production-ready with a Dockerfile and docker-compose.',
    'Product Owner (PO) UAT & Kabul Onayı ({title})':
        'Product Owner (PO) UAT & Acceptance Approval ({title})',
    'Product Owner (PO): {title} teslimatını müşteri kabul kriterlerine göre denetle ve UAT onayı ver.':
        'Product Owner (PO): audit the {title} delivery against the customer acceptance criteria and give the UAT approval.',
    'Documentor & Reporter: Kullanım Kılavuzu & Yönetici Raporu ({title})':
        'Documentor & Reporter: User Guide & Management Report ({title})',
    'Documentor Ajanı son kullanıcı kullanım kılavuzunu üretir; Reporter Ajanı ise sprint özetini ve metriklerini yönetici raporuna döker.':
        'The Documentor agent produces the end-user guide; the Reporter agent writes the sprint summary and metrics into the management report.',
    'Özel Test Kullanıcısı':
        'Custom Test User',
    'Kullanıcı tanımlı test profili':
        'User-defined test profile',
    'Revize için geri bildirim (ne düzeltilsin?) yazın.':
        'Write feedback for the revision (what should be fixed?).',
    'Proje kuruluşunda notlardan çıkarılan ve yönetici tarafından cevaplanan teknoloji kalemleri ({n} kalem) tek kararla onaylandı.':
        'The technology items extracted from the notes at project setup and answered by the manager ({n} items) were approved in a single decision.',
    'Deneme bayrağı (FSSC_DRY_RUN=1) kapalı; teknoloji kapısı yalnızca yönetici onayıyla geçilir.':
        "The dry-run flag (FSSC_DRY_RUN=1) is off; the technology gate can only be passed with the manager's approval.",
    'Hedef proje bulunamadı: {pid}':
        'Target project not found: {pid}',
    'Kayıt dosyası bozuktu ({err}); son sağlam yedekten yüklendi ({bak}). Bozuk kopya: {corrupt}':
        'The registry file was corrupt ({err}); loaded from the last good backup ({bak}). Corrupt copy: {corrupt}',
    "Kapatılmış sprintin maddesi değiştirilemez; değişiklik yeni madde olarak ve 'related_to' ile eklenir: ":
        "An item of a closed sprint cannot be changed; the change is added as a new item linked with 'related_to': ",
    'Müşteri ({client}) şartname belgeleri ve isterleri analiz edildi':
        'The specification documents and requirements of the customer ({client}) were analyzed',
    'docs/PRD.md iş kuralları ve kullanıcı hikayeleri donduruldu':
        'docs/PRD.md business rules and user stories were frozen',
    'OpenAPI JSON spesifikasyonu donduruldu':
        'The OpenAPI JSON specification was frozen',
    '{title} için Pydantic ve veri modelleri çıkarıldı':
        'Pydantic and data models were derived for {title}',
    'Hata ve yetkilendirme sözleşmesi hazırlandı':
        'The error and authorization contract was prepared',
    'FastAPI servisleri ve middleware kodlandı':
        'FastAPI services and middleware were coded',
    'Veritabanı ve session mantığı entegre edildi':
        'Database and session logic were integrated',
    'Girdi doğrulama ve hata yakalayıcılar eklendi':
        'Input validation and error handlers were added',
    '{title} için modern responsive sayfalar kodlandı':
        'Modern responsive pages were coded for {title}',
    'Backend API istemcisi senkronize edildi':
        'The Backend API client was synchronized',
    'Giriş ve etkileşim formları bağlandı':
        'Login and interaction forms were wired up',
    'Geliştiriciler veri modellerini karşılıklı doğruladı':
        'The developers mutually verified the data models',
    'CORS ve token header geçişleri onaylandı':
        'CORS and token header passing were approved',
    'Uçtan uca mock testleriyle uyum sağlandı':
        'Alignment was achieved with end-to-end mock tests',
    'Birim testler 4/4 başarıyla geçti':
        'Unit tests passed 4/4',
    '{client} gereksinimlerine göre testler yapıldı':
        'Tests were performed according to the requirements of {client}',
    'docs/QA_REPORT.md onaylandı':
        'docs/QA_REPORT.md was approved',
    'Chromium tarayıcısında butonlar ve formlar denendi':
        'Buttons and forms were exercised in the Chromium browser',
    'Kanıt ekran görüntüleri .fs-workspace/e2e/screenshots altında toplandı':
        'Evidence screenshots were collected under .fs-workspace/e2e/screenshots',
    'Sayfa yüklenme ve DOM doğrulaması sağlandı':
        'Page load and DOM verification were completed',
    'Dockerfile ve docker-compose.yml hazırlandı':
        'Dockerfile and docker-compose.yml were prepared',
    'README.md proje dokümanı oluşturuldu':
        'The README.md project document was created',
    'Konteyner ortamı doğrulandı':
        'The container environment was verified',
    'Müşteri toplantı notları ve şartname maddeleri birebir doğrulandı':
        'The customer meeting notes and specification items were verified one-to-one',
    'Kullanıcı kabul testi (UAT) başarıyla geçti':
        'The user acceptance test (UAT) passed successfully',
    'Eksik özellikler varsa yeni geliştirme talebine dönüştürüldü':
        'Missing features, if any, were converted into a new development request',
    'docs/manuals/user_guide.md son kullanıcı kılavuzu tamamlandı':
        'docs/manuals/user_guide.md end-user guide was completed',
    'README.md ve mimari API referansları güncellendi':
        'README.md and the architecture API references were updated',
    'Teknoloji yığınının kuruluş onayı':
        'Technology stack setup approval',
    'Ek bağımlılık: {dep}':
        'Additional dependency: {dep}',
    'eklenmesine izin verildi':
        'its addition was allowed',
    "'{dep}' ({file}) onaylı teknolojilerde ve kütüphane kaydında yok. Eklenmesine izin verilsin mi?":
        "'{dep}' ({file}) is not in the approved technologies or the library registry. Allow it to be added?",
    'Reddet':
        'Reject',
    'Teknoloji ya da kütüphane seçimi yöneticiye aittir (§3.2).':
        'The choice of technology or library belongs to the manager (§3.2).',
    'Kayıt dosyası bozuk ({err}) ve sağlam yedek yok; boş başlatıldı. Bozuk kopya: {corrupt}':
        'The registry file is corrupt ({err}) and there is no good backup; started empty. Corrupt copy: {corrupt}',
    'Şartname':
        'Specification',
    'Teknoloji kararları TECH_REQUIREMENTS.md belgesinden geri kuruldu ({n} kalem).':
        'Technology decisions were restored from the TECH_REQUIREMENTS.md document ({n} items).',
    'Teknoloji değişikliği':
        'Technology change',
    'Onaylı bir teknoloji kalemi yönetici kararıyla değiştirildi ya da yeni notla yeniden onaylandı.':
        "An approved technology item was changed by the manager's decision or re-approved with a new note.",
    'Teknoloji değişikliği: ek bağımlılık':
        'Technology change: additional dependency',
    '{dep} ({file}) onaylı teknolojilerde yoktu; yönetici ekleme kararı verdi.':
        '{dep} ({file}) was not among the approved technologies; the manager decided to add it.',
    'Onaylandı (yönetici kararı {did})':
        'Approved (manager decision {did})',
    'Metin notları':
        'Text notes',
    'Onayla ve kütüphane olarak kaydet':
        'Approve and register as a library',
    'İş devam eder':
        'Work continues',
    'Yeni bağımlılık':
        'New dependency',
    'Yığın sade kalır':
        'The stack stays lean',
    'Ajan başka çözüm bulmak zorunda':
        'The agent has to find another solution',
    'Temel fonksiyonel isterler netleştirildi':
        'Basic functional requirements were clarified',
    "Madde '{status}' durumunda; yeni yükleme tanımını değiştirmedi ({title}).":
        "The item is in status '{status}'; the new upload did not change its definition ({title}).",
    'yönetici onaylı ek bağımlılık':
        'manager-approved additional dependency',
    'yönetici kararıyla onaylı ({did})':
        'approved by manager decision ({did})',
    'Yeni yükleme: {title}':
        'New upload: {title}',
    'Müşteri görüşmeleri, gereksinim analizi ve PRD dokümantasyonu':
        'Customer interviews, requirements analysis and PRD documentation',
    'Sistem mimarisi, OpenAPI 3.0 sözleşmeleri ve modül sınırları':
        'System architecture, OpenAPI 3.0 contracts and module boundaries',
    'FastAPI REST servisleri, JWT auth ve veritabanı iş mantığı':
        'FastAPI REST services, JWT auth and database business logic',
    'React responsive kullanıcı arayüzü, formlar ve API client entegrasyonu':
        'React responsive user interface, forms and API client integration',
    "Tasarım sistemi (renk, tipografi, bileşenler) ve ilk ekranların HTML mockup'ları; frontend onaylı tasarıma uyar":
        'Design system (colors, typography, components) and HTML mockups of the first screens; the frontend follows the approved design',
    'Birim testler, regresyon kontrolleri ve hata (bug) raporlama':
        'Unit tests, regression checks and bug reporting',
    'Gerçek Chromium tarayıcısı açarak canlı login, form doldurma ve UI ekran görüntüsü testi':
        'Opens a real Chromium browser for live login, form filling and UI screenshot testing',
    'Dockerfile, docker-compose, staging dağıtımı ve sağlık kontrolü':
        'Dockerfile, docker-compose, staging deployment and health check',
    'Ürün kabulü (UAT), iş değeri ve kullanıcı beklentisi doğrulaması':
        'Product acceptance (UAT), business value and user expectation validation',
    'Yönetici durum özetleri, token ve sprint metrikleri raporlaması':
        'Management status summaries, token and sprint metrics reporting',
    'Kullanıcı kılavuzları, kurulum rehberleri ve API referans dokümantasyonu':
        'User guides, installation guides and API reference documentation',
    'Git versiyonlama, branching stratejisi ve merge çakışma çözümü':
        'Git versioning, branching strategy and merge conflict resolution',
    'Sprint planı, kapasite, taahhüt, taşıma ve sprint kapanışı':
        'Sprint plan, capacity, commitment, carry-over and sprint closing',
    "Mobil (iOS/Android) tasarım sistemi ve ekran mockup'ları: dokunma hedefleri, gezinme kalıpları, küçük ekran düzeni":
        'Mobile (iOS/Android) design system and screen mockups: touch targets, navigation patterns, small-screen layout',
    'Güvenlik incelemesi ve testi: OWASP zafiyetleri, yetkilendirme, gizli bilgi, bağımlılık riskleri; bulguları hata olarak bildirir':
        'Security review and testing: OWASP vulnerabilities, authorization, secrets, dependency risks; reports findings as bugs',
    'Teknik SEO ve web performansı: meta etiketler, sitemap, yapılandırılmış veri, Core Web Vitals':
        'Technical SEO and web performance: meta tags, sitemap, structured data, Core Web Vitals',
    'Kod inceleme ve kalite: okunabilirlik, doğruluk, performans, teknik borç; küçük, gerekçeli iyileştirme görevleri açar':
        'Code review and quality: readability, correctness, performance, technical debt; opens small, well-reasoned improvement tasks',
    '- Özel ajanlar (bu projede görev alabilir; `role` alanına kimliğini yaz):':
        '- Custom agents (they can take tasks in this project; write their id in the `role` field):',
    'profile bir nesne olmalı (model, effort, max_tokens, tools_allow, language, budget).':
        'profile must be an object (model, effort, max_tokens, tools_allow, language, budget).',
    'Ajan tanımı bir nesne olmalı.':
        'The agent definition must be an object.',
    '; odak: {words}':
        '; focus: {words}',
    '  - `{aid}` ({name}{desc}); yetenekler: {caps}; temel rol: {base}{focus}':
        '  - `{aid}` ({name}{desc}); capabilities: {caps}; base role: {base}{focus}',
    'Ajan kimliği boş olamaz.':
        'The agent id cannot be empty.',
    'Havuzda böyle bir ajan yok.':
        'There is no such agent in the pool.',
    "'{aid}' bu projede zaten var.":
        "'{aid}' already exists in this project.",
    "Geçersiz ajan paketi (format '{fmt}' beklenir).":
        "Invalid agent package (format '{fmt}' expected).",
    'Paketteki ajanın kimliği ya da adı yok.':
        'The agent in the package has no id or name.',
    "'{aid}' çekirdek bir roldür; paketle değiştirilemez.":
        "'{aid}' is a core role; it cannot be replaced by a package.",
    'Geçersiz şablon anahtarı: {key}':
        'Invalid template key: {key}',
    'Şablonda uygulanabilir ajan yok: {key}':
        'The template has no applicable agent: {key}',
    "Geçersiz çaba düzeyi '{effort}': {values}.":
        "Invalid effort level '{effort}': {values}.",
    "Geçersiz dil '{lang}': {values}.":
        "Invalid language '{lang}': {values}.",
    '{key} 1 ile {hi} arasında olmalı.':
        '{key} must be between 1 and {hi}.',
    "Geçersiz temel rol '{role}': {values}.":
        "Invalid base role '{role}': {values}.",
    'Şablon bulunamadı: {key}':
        'Template not found: {key}',
    '{key} tamsayı olmalı.':
        '{key} must be an integer.',
    '## 🧠 Öğrenilen Dersler':
        '## 🧠 Lessons Learned',
    '# {role} - Şirket Standardı Sistem Promptu\n## Persona ve Sorumluluklar\nBu ajan {role} rolünde görev yapmaktadır.\n\n## Proje Kuralları ve Standartlar\n- Kod ve mimari kurallarına uygun geliştirme yapın.\n- Edge case ve hata durumlarını kontrol edin.\n':
        '# {role} - Company Standard System Prompt\n## Persona and Responsibilities\nThis agent works in the {role} role.\n\n## Project Rules and Standards\n- Develop in line with the code and architecture rules.\n- Check edge cases and error conditions.\n',
    "Geri Yükleme (Rollback): '{version}' versiyonuna dönüldü.":
        "Restore (Rollback): returned to version '{version}'.",
    '## 🧠 Öğrenilen Dersler ve Proje Tecrübeleri (Learnings & Memory)\\n- *Global standart yeniden eşitlendi.*':
        '## 🧠 Lessons Learned and Project Experience (Learnings & Memory)\\n- *Global standard re-synchronized.*',
    '## 🧠 Öğrenilen Dersler ve Proje Tecrübeleri (Learnings & Memory)':
        '## 🧠 Lessons Learned and Project Experience (Learnings & Memory)',
    '- *Ajan bu projede görev yaptıkça ve kurallar eklendikçe burada yeni tecrübeler birikir.*':
        '- *New experience accumulates here as the agent works on this project and rules are added.*',
    'Versiyon {version} güncellemesi':
        'Version {version} update',
    'Versiyon bulunamadı: {version}':
        'Version not found: {version}',
    'Versiyon snapshot dosyası bulunamadı: {path}':
        'Version snapshot file not found: {path}',
    'Global standart şablondan ({name}) yeniden kalıtıldı.':
        'Re-inherited from the global standard template ({name}).',
    'Terfi ettirilecek ajan içeriği boş.':
        'The agent content to be promoted is empty.',
    'Global standart şablondan ({name}) kalıtıldı.':
        'Inherited from the global standard template ({name}).',
    '🧠 Otonom Öğrenim: {title} tecrübesi hafızaya eklendi.':
        '🧠 Autonomous Learning: the experience from {title} was added to memory.',
    'Platform, altyapı ve belgeler':
        'Platform, infrastructure and documents',
    'İskelet, DevOps, belge, karar uygulama ve refactor işleri: belirli bir kullanıcı hikâyesine ait olmayan teknik zemin.':
        'Scaffold, DevOps, documents, decision implementation and refactor work: the technical groundwork that does not belong to a specific user story.',
    'Kalite, hata ve iyileştirmeler':
        'Quality, bugs and improvements',
    'QA/UAT/retro kaynaklı hata, iyileştirme ve test işleri.':
        'Bug, improvement and test work originating from QA/UAT/retro.',
    'eşleşen epik/hikâye bulunamadı':
        'no matching epic/story found',
    'ebeveyn: {old} → {parent_id} ({reason})':
        'parent: {old} → {parent_id} ({reason})',
    '(sistem epiği: {title})':
        '(system epic: {title})',
    'kabul kriteri {ids}':
        'acceptance criterion {ids}',
    'bağımlı olduğu iş {key}':
        'work it depends on {key}',
    'metinde anılan {key}':
        'mentioned in the text {key}',
    'başlık/açıklama benzerliği ({key})':
        'title/description similarity ({key})',
    'teknik zemin işi':
        'technical groundwork item',
    'kalite/hata/iyileştirme işi':
        'quality/bug/improvement item',
    'UAT kaynaklı hikâye':
        'story originating from UAT',
    'Sistem epiği: bir epiğe bağlanamayan işlerin ortak çatısı.':
        'System epic: the common umbrella for items that cannot be linked to an epic.',
    'Düzenlenemez alan: {field}':
        'Field cannot be edited: {field}',
    '{status}: durum geçişi kaydı yok (başlangıç durumu).':
        '{status}: no status transition recorded (initial status).',
    '{status}: yönetici {frm} → {to} taşıdı ({who}, {ts}).':
        '{status}: the manager moved it {frm} → {to} ({who}, {ts}).',
    'liste bekleniyor':
        'a list is expected',
    'Tahmin XS/S/M/L/XL ya da 0-1000 puan olmalı.':
        'Estimate must be XS/S/M/L/XL or 0-1000 points.',
    'Silinmiş madde düzenlenemez; önce geri alın.':
        'A deleted item cannot be edited; restore it first.',
    'Kapatılmış sprintin maddesi değiştirilemez; değişiklik yeni madde olarak (related_to) eklenir.':
        'An item of a closed sprint cannot be changed; the change is added as a new item (related_to).',
    'Başlamış iş silinemez (IN_PROGRESS/IN_REVIEW); önce adımın bitmesini ya da koşunun kapanmasını bekleyin.':
        'A started item cannot be deleted (IN_PROGRESS/IN_REVIEW); wait for the step to finish or the run to close first.',
    'yönetici geri aldı':
        'restored by the manager',
    'Bu maddede geri alınabilir bir sorumlu değişikliği kaydı yok.':
        'There is no revertible assignee change record on this item.',
    'Sorumlu son kayıttan sonra yeniden değişmiş ({assignee}); otomatik düzeltilmez.':
        'The assignee changed again after the last record ({assignee}); it is not corrected automatically.',
    'Yorum boş olamaz.':
        'The comment cannot be empty.',
    'Bağ tipi {values} olmalı.':
        'Link type must be one of {values}.',
    'Madde kendine bağlanamaz.':
        'An item cannot be linked to itself.',
    'Ek için path ya da url gerekli.':
        'A path or url is required for an attachment.',
    'Geçersiz yol.':
        'Invalid path.',
    'Durum {values} olmalı.':
        'Status must be one of {values}.',
    'Silinmiş madde taşınamaz; önce geri alın.':
        'A deleted item cannot be moved; restore it first.',
    'Kapatılmış sprintin maddesinin durumu değişmez.':
        'The status of an item of a closed sprint does not change.',
    'Yönetici panoda taşıdı: {old} → {status}':
        'The manager moved it on the board: {old} → {status}',
    'Yönetici {status} sütununda {pos}. sıraya taşıdı.':
        'The manager moved it to position {pos} in the {status} column.',
    'Yönetici işi {target} için sabitledi.':
        'The manager pinned the item to {target}.',
    'Toplu işlem {values} olmalı.':
        'Bulk action must be one of {values}.',
    'Beklenmeyen: {token}':
        'Unexpected: {token}',
    'Süzgeç adı gerekli.':
        'A filter name is required.',
    'Sprint hedefi yalnızca PLANNING durumunda düzenlenir.':
        'The sprint goal can only be edited in the PLANNING status.',
    'Hedef boş olamaz.':
        'The goal cannot be empty.',
    'Başlık boş olamaz.':
        'The title cannot be empty.',
    'Öncelik {values} olmalı.':
        'Priority must be one of {values}.',
    'Atanan boş olamaz.':
        'The assignee cannot be empty.',
    'Madde tipi {values} olmalı.':
        'Issue type must be one of {values}.',
    'Tahmin puanı 0-1000 arası olmalı.':
        'The estimate points must be between 0 and 1000.',
    'Madde kendi ebeveyni olamaz.':
        'An item cannot be its own parent.',
    'Ebeveyn bulunamadı: {v}':
        'Parent not found: {v}',
    'Ebeveyn döngüsü: hedef bu maddenin altındadır.':
        'Parent cycle: the target is under this item.',
    'Süren sprintin taahhüdündeki iş, koşuda başlamamış bir adım olarak bulunamadı; silinemez (kapsam değişikliği acil girdi ile yapılır).':
        'The item committed in the running sprint could not be found as a not-yet-started step in the run; it cannot be deleted (a scope change is made with an urgent input).',
    ' (yanlışlıkla yapılan değişiklik geri alındı)':
        ' (the mistaken change was reverted)',
    ' (DoD kanıtı olmadan DONE; yönetici sorumluluğunda)':
        " (DONE without DoD evidence; on the manager's responsibility)",
    "Yalnızca backlog'daki ve henüz bir sprinte alınmamış iş sprint/sıra değişikliğine açıktır.":
        'Only an item in the backlog and not yet taken into a sprint is open to sprint/order changes.',
    'Madde bu yönde taşınamaz (sıranın başında/sonunda ya da aday değil).':
        'The item cannot be moved in this direction (at the start/end of the order or not a candidate).',
    'order by için geçerli bir alan verin.':
        'Provide a valid field for order by.',
    'Sorgu beklenmedik şekilde bitti.':
        'The query ended unexpectedly.',
    'Koşul bekleniyor.':
        'A condition is expected.',
    'Bilinmeyen alan: {field} (alanlar: {fields})':
        'Unknown field: {field} (fields: {fields})',
    'Bilinmeyen operatör: {op}':
        'Unknown operator: {op}',
    'Adım #{order} ({kind}) {status}: {summary}':
        'Step #{order} ({kind}) {status}: {summary}',
    'Son tarih YYYY-AA-GG biçiminde olmalı.':
        'The due date must be in YYYY-MM-DD format.',
    'yönetici sildi':
        'deleted by the manager',
    'Yönetici backlog sırasında {move} taşıdı.':
        'The manager moved it {move} in the backlog order.',
    "')' bekleniyor.":
        "')' is expected.",
    "'not in' bekleniyor.":
        "'not in' is expected.",
    "'is empty' / 'is not empty' bekleniyor.":
        "'is empty' / 'is not empty' is expected.",
    "'(' bekleniyor.":
        "'(' is expected.",
    'planned_sprint pozitif tamsayı ya da null olmalı.':
        'planned_sprint must be a positive integer or null.',
    'Sprint {n} başlamış ya da kapanmış; yalnızca planlanacak sprintlere iş sabitlenir.':
        'Sprint {n} has started or closed; items can only be pinned to sprints that are still to be planned.',
    'bulunamadı':
        'not found',
    '{BEGIN}\n## FS-SC pipeline (otomatik bölüm — elle düzenleme, her proje bağlanışında yeniden yazılır)\nBu klasör FS-SC projesidir (`project_id`: `{project_id}`). Pipeline\'ı bu klasörden çalıştır; MCP sunucusu `fssc-visual-observer` (`.mcp.json`).\n"pipeline\'ı çalıştır" denince:\n1. `start_pipeline_run(project_id="{project_id}", steps=[...])` (boş `steps` = 1-10). `RESUMED`/`EXISTING` gelirse aynı işi yeniden başlatma.\n2. Döngü: `get_next_step(run_id)` → `STEP` ise `system_prompt` rolünü üstlen, `report_thinking` gönder, yalnızca `output_contract` JSON zarfını\n   `submit_step_result(run_id, order, result_json)` ile ver. `WAITING_APPROVAL` → `wait_for_approval`; `PAUSED` aynı; `RUN_COMPLETE`/`CANCELLED` → bitir.\n3. `REJECTED` → `validation_errors`\'a göre düzeltip aynı order ile tekrar gönder. `inserted_steps > 0` ise yeni görev maddeleri aç.\nKurallar: dosyaları kendin yazma (içeriği `payload.files[].content` içinde tam ver), komut koşma (doğrulamayı sunucu yapar), zarf dışında metin üretme,\n"Yönetici notları" öncelikli talimattır, kullanıcıya yalnızca adım geçişlerinde tek satır bildir.\n**Docker:** Dockerfile/compose/CI dosyaları yalnızca `devops/` altında olur (kökte ya da uygulama klasöründe değil); sunucu aksini reddeder.\n**Yeni kütüphane:** onaylı listede olmayan kütüphane gerekirse adımı durdurma, sohbette onay isteme; manifesti teslime koy, sunucu yöneticiye panodan soru (D-n) açar (sohbet onayı FS-SC\'ye işlemez).\n**Soru sorma:** sohbette "devam edeyim mi / sürdüreyim mi / onaylıyor musun" diye sorma; belirsizlikte makul varsayımla ilerle, varsayımı teslimdeki `summary`/`questions` alanına yaz.\n**Durma:** koşu `RUN_COMPLETE`/`CANCELLED`/`WAITING_APPROVAL`/`BLOCKED`/`SESSION_BOUNDARY` olana kadar döngüyü sürdür; `submit_step_result` `NEXT` dönünce hemen `get_next_step` çağır,\n"devam edeyim mi?" diye sorma, adım sayısı arttı ya da doğrulama çıktısı kesik geldi diye durma (bunlar durma nedeni değildir; sunucu kayıtlarını tutar).\nKoşu kopmasına karşı: oturumun başında `get_runner_schedule` çağır; zamanlanmış görev araçların varsa FS-SC için tek görevi `interval_minutes` aralığıyla kur/güncelle (ayrıntı FS-SC deposundaki CLAUDE.md, madde 8).\nDashboard: http://127.0.0.1:{SERVER_PORT}\n{END}\n':
        '{BEGIN}\n## FS-SC pipeline (automatic section - do not edit by hand, rewritten every time the project is connected)\nThis folder is an FS-SC project (`project_id`: `{project_id}`). Run the pipeline from this folder; the MCP server is `fssc-visual-observer` (`.mcp.json`).\nWhen told "run the pipeline":\n1. `start_pipeline_run(project_id="{project_id}", steps=[...])` (empty `steps` = 1-10). If `RESUMED`/`EXISTING` comes back, do not restart the same job.\n2. Loop: `get_next_step(run_id)` -> if `STEP`, take on the role in `system_prompt`, send `report_thinking`, and give only the `output_contract` JSON envelope\n   with `submit_step_result(run_id, order, result_json)`. `WAITING_APPROVAL` -> `wait_for_approval`; `PAUSED` the same; `RUN_COMPLETE`/`CANCELLED` -> finish.\n3. `REJECTED` -> fix according to `validation_errors` and resubmit with the same order. If `inserted_steps > 0`, open new task items.\nRules: do not write files yourself (give the content in full in `payload.files[].content`), do not run commands (the server does the verification), do not produce text outside the envelope,\nthe "Manager notes" are a priority instruction, report to the user only at step transitions, in a single line.\n**Docker:** Dockerfile/compose/CI files live only under `devops/` (not in the root or the application folder); the server rejects otherwise.\n**New library:** if a library outside the approved list is needed, do not stop the step and do not ask for approval in chat; put the manifest in the delivery, the server opens a question (D-n) to the manager on the dashboard (chat approval does not register in FS-SC).\n**Asking questions:** do not ask in chat "shall I continue / shall I proceed / do you approve"; when in doubt proceed with a reasonable assumption and write the assumption in the delivery\'s `summary`/`questions` field.\n**Stopping:** keep the loop going until the run is `RUN_COMPLETE`/`CANCELLED`/`WAITING_APPROVAL`/`BLOCKED`/`SESSION_BOUNDARY`; when `submit_step_result` returns `NEXT`, call `get_next_step` immediately,\ndo not ask "shall I continue?", and do not stop because the step count grew or the verification output arrived truncated (these are not reasons to stop; the server keeps the records).\nAgainst a dropped run: at the start of the session call `get_runner_schedule`; if you have scheduled-task tools, create/update the single FS-SC task with the `interval_minutes` interval (details in CLAUDE.md in the FS-SC repository, item 8).\nDashboard: http://127.0.0.1:{SERVER_PORT}\n{END}\n',
    'Belge':
        'Document',
    'Toplantı':
        'Meeting',
    'Test planı':
        'Test plan',
    'Rapor':
        'Report',
    'Bu klasör görüntülenemez.':
        'This folder cannot be viewed.',
    'Gizli bilgi içerebilecek dosya görüntülenmez.':
        'A file that may contain secrets is not displayed.',
    'Yol proje klasörünün dışında.':
        'The path is outside the project folder.',
    'Klasör bulunamadı.':
        'Folder not found.',
    'İkili dosya görüntülenemez.':
        'A binary file cannot be viewed.',
    'Geçersiz commit kimliği.':
        'Invalid commit id.',
    'Proje bir git deposu değil.':
        'The project is not a git repository.',
    'Klasör okunamadı.':
        'The folder could not be read.',
    'git hatası':
        'git error',
    '**Geçici dosyalar:** zarf/betik/ara JSON gibi geçici dosyaları (build_step_*.js, submit_*.js, step_*.json ...) proje köküne yazma; yalnızca `.fs-workspace/tmp/` altına yaz (git\'e girmez). Kökte kalanları sunucu oraya taşır.':
        '**Temporary files:** never write temporary files such as envelopes, scripts or intermediate JSON (build_step_*.js, submit_*.js, step_*.json ...) to the project root; write them only under `.fs-workspace/tmp/` (not in git). The server moves any left in the root there.',
    'Aynı işi tarif eden yeni görev açılmadı: {title}':
        'No new task opened for work already described: {title}',
    "Bu öğeler projede VAR: önce bunları oku ve kabul kriterlerini mevcut koda karşı doğrula. Hepsi karşılanıyorsa dosya yeniden yazma; `payload.already_satisfied` ile her kriter için commit'li bir test kanıtı göster. Yalnızca gerçek bir eksik varsa o dosyaları değiştir.":
        "These items EXIST in the project: read them first and check the acceptance criteria against the current code. If everything is met, do not rewrite files; show a committed test as evidence for each criterion via `payload.already_satisfied`. Change files only if something is genuinely missing.",
    '\n\n## Kodda zaten bulunanlar (sunucu taraması)\n':
        '\n\n## Already in the code (server scan)\n',
    "GEÇİCİ DOSYA: zarf, teslim betiği ya da ara JSON gibi geçici dosya gerekirse yalnızca `<proje>/.fs-workspace/tmp/` altına yaz; proje köküne asla (submit_*.js, step_*.json vb.). Sunucu köke bırakılanları oraya taşır ve git'e almaz.":
        "TEMPORARY FILES: if you need a temporary file such as an envelope, submit script or intermediate JSON, write it only under `<project>/.fs-workspace/tmp/`, never in the project root (submit_*.js, step_*.json, etc.). The server moves anything left in the root there and keeps it out of git.",
    "Ekran görevi arayüz kaynağını değiştirmedi: onaylı mockup'ı (`{mock}`) açıp çalışan ekranla karşılaştır; ekran bileşeni ve stil dosyalarını (.tsx/.css) mockup'a (düzen, renk, tipografi, boş/hata/yükleniyor/dolu durumlar) uyduracak şekilde güncelleyip teslim et. `already_satisfied` ya da yalnızca ekran sözleşmesi bu görevi kapatmaz.":
        "The screen task did not change any UI source: open the approved mockup (`{mock}`), compare it with the running screen, and deliver updated screen component and style files (.tsx/.css) that match it (layout, colors, typography, empty/error/loading/filled states). `already_satisfied` or a screen contract alone does not close this task.",
    'Ekran uyumu: {title}':
        'Screen fidelity: {title}',
    "{id} yalnızca ekran sözleşmesi yazıp mockup'ı uygulamadı; uyum görevi açıldı.":
        "{id} only wrote the screen contract and did not implement the mockup; a fidelity task was opened.",
    "Mockup dosyası yok: {path}":
        "Mockup file is missing: {path}",
    "{view}: uygulama başka sayfaya yönlendirdi ({url}); ekran görülemedi (oturum/rota gerekebilir)":
        "{view}: the app redirected to another page ({url}); the screen could not be seen (a session/route may be needed)",
    "{view}: mockup metinlerinin yalnızca %{pct}'i uygulamada var":
        "{view}: only {pct}% of the mockup texts appear in the app",
    "{view}: görsel benzerlik düşük (%{pct})":
        "{view}: visual similarity is low ({pct}%)",
    "{view}: ekran açılamadı ({err})":
        "{view}: the screen could not be opened ({err})",
    "Sunucunun ekran uyumu denetimi sonucu: {problems}":
        "Server screen fidelity check result: {problems}",
    "Ekran uyumu denetimi eşik altı kaldı: {problems}":
        "Screen fidelity check fell below the threshold: {problems}",
    "Açık hedef varken {n} yeni görev açılmadı: {titles}":
        "{n} new tasks were not opened while a goal is open: {titles}",
    "## Ürün tanımı (yönetici, bağlayıcı)":
        "## Product definition (manager, binding)",
    "Şartname ve notlardaki örnekler bu tanımı daraltmaz; çelişirse bu tanım geçerlidir.":
        "Examples in the specification and notes do not narrow this definition; if they conflict, this definition wins.",
    "\n## Saha Kuralları (sahadan öğrenildi)\n- Geçici dosya (zarf, betik, ara JSON) yalnızca `.fs-workspace/tmp/` altına; proje köküne asla.\n- Ekran/arayüz görevinde onaylı mockup'ı aç, çalışan ekranla karşılaştır ve arayüz kaynağını (.tsx/.css) mockup'a uyduracak şekilde değiştir; aynı dosyayı değiştirmeden yeniden vermek ya da yalnızca ekran sözleşmesi yazmak görevi kapatmaz.\n- Bir iş yapmadan/önermeden önce adı geçen sınıf, servis ve dosyaların projede zaten var olup olmadığına bak; var olanı yeniden açma, yeniden yazma.\n- Örnek metinleri (ürün adı, sektör, kullanıcı türü) kısıt sanma: yönetici örnek verdiyse onu genelle, örnekteki varsayımları zorunlu kılma.\n- Yöneticinin açık hedefi (Hedefler) dışında iş önerme ya da başlatma; belirsizse yönetici hedefini izle.\n":
        "\n## Field rules (learned in the field)\n- Temporary files (envelopes, scripts, intermediate JSON) go only under `.fs-workspace/tmp/`, never in the project root.\n- For a screen/UI task, open the approved mockup, compare it with the running screen and change the UI source (.tsx/.css) so it matches; resubmitting an unchanged file or writing only a screen contract does not close the task.\n- Before doing or proposing work, check whether the named classes, services and files already exist in the project; do not reopen or rewrite what exists.\n- Do not treat example text (product name, industry, user type) as a constraint: if the manager gave an example, generalize it and do not make the example's assumptions mandatory.\n- Do not propose or start work outside the manager's open goals (Goals); when unsure, follow the manager's goal.\n",
    'Ürün tanımı (statement) gerekli.':
        'A product definition (statement) is required.',
    '3) Kapsam dışı kalan, başlamamış işler sunucuca silindi ({n}); onları yeniden açma.':
        '3) Not-started items that fell out of scope were deleted by the server ({n}); do not reopen them.',
    'Kapsam düzeltmesi: ürün tanımı değişti ({terms})':
        'Scope correction: the product definition changed ({terms})',
    'İncelenecek mevcut işler ({n}):':
        'Existing items to review ({n}):',
    "Kapsam düzeltmesi: PRD'yi yeni ürün tanımına göre güncelle ve kısıtları kaldır":
        'Scope correction: update the PRD to the new product definition and remove the constraints',
    'PRD ve belgeler yeni ürün tanımına göre güncellenir':
        'The PRD and documents are updated to the new product definition',
    'Kalan kısıtları kaldıran/genelleştiren işler rol bazlı backlog olarak çıkar':
        'Work that removes or generalizes the remaining constraints is produced as a role-based backlog',
    'Silinen işler yeniden açılmaz':
        'Deleted items are not reopened',
    '2) Kodda, testte ve ekranda kalan bu kısıtları (kimlik/rozet/alan adı doğrulaması, kampüs sınırı vb.) kaldıran ya da genelleştiren işleri `backlog[]` olarak üret; genel hesap doğrulaması (e-posta/telefon) kalabilir. Her iş tek bir role verilsin, kabul kriteri ve `files` ipucu olsun.':
        '2) Produce, as `backlog[]`, the work that removes or generalizes the constraints left in code, tests and screens (identity/badge/domain verification, campus limits, etc.); generic account verification (email/phone) may stay. Give each item a single role, acceptance criteria and a `files` hint.',
    '1) PRD ve ilgili belgeleri (ürün gereksinimleri, hikâyeler, kabul kriterleri) yeni tanıma göre baştan yaz; bu kısıtları belgelerden çıkar, genel kullanıcı (herkes) için yaz. Teslimde güncellenen belge dosyalarını `files` içinde ver.':
        '1) Rewrite the PRD and related documents (requirements, stories, acceptance criteria) from scratch for the new definition; remove these constraints and write for general users (everyone). Deliver the updated document files in `files`.',
    'Şartnamedeki şu terimler yalnızca örnekti, zorunluluk değildir: {terms}.':
        'These terms in the specification were only examples, not requirements: {terms}.',
    'YÖNETİCİ KAPSAM DÜZELTMESİ. Ürün tanımı (bağlayıcı): {statement}':
        'MANAGER SCOPE CORRECTION. Product definition (binding): {statement}',
    'Karşılaştırma görüntüleri: .fs-workspace/e2e/screenshots/fidelity_{id}_desktop.png (sol mockup, sağ uygulama)':
        'Comparison images: .fs-workspace/e2e/screenshots/fidelity_{id}_desktop.png (left: mockup, right: app)',
    'verification.client_url tanımlı değil':
        'verification.client_url is not set',
    'ekran tasarımı bulunamadı':
        'screen design not found',
    'ekran oturum/rota gerektiriyor (yönlendirildi); doğrulanamadı':
        'the screen needs a session/route (redirected); it could not be verified',
    'istemci kapalı ve verification.client_run tanımlı değil':
        'the client is down and verification.client_run is not set',
    'istemci başlatılamadı: {err}':
        'the client could not be started: {err}',
    "{view}: mockup'ta olup uygulamada görünmeyen metinler: {words}":
        '{view}: texts in the mockup that are not visible in the app: {words}',
    'Ekran uyumu kabul kapısı geçilmedi: ':
        'Screen fidelity acceptance gate failed: ',
    '(ekran uyumu denetlenemedi: {note})':
        '(screen fidelity could not be checked: {note})',
    '✗ Ekran mockup ile uyuşmuyor; düzeltme hakkı bitti, görev bitmiş sayılmaz: ':
        '✗ The screen does not match the mockup; fix rounds are used up, the task is not counted as done: ',
    'payload.delete bir yol listesi olmalı.':
        'payload.delete must be a list of paths.',
    '[{n} dosya silindi]':
        '[{n} files deleted]',
    'En çok {n} dosya silinebilir.':
        'At most {n} files can be deleted.',
    'Silinemez yol: {rel}':
        'Path cannot be deleted: {rel}',
    'Yönetim dosyası silinemez: {rel}':
        'Management file cannot be deleted: {rel}',
    'Silinecek dosya yok (ya da klasör): {rel}':
        'File to delete does not exist (or is a folder): {rel}',
    'Proje kökü dışı yol: {rel}':
        'Path is outside the project root: {rel}',
    'Silinen dosyalar: ':
        'Deleted files: ',
    'Dosya SİLMEN gerekiyorsa `payload.delete` = ["proje köküne göreli yol", ...] ver (en çok 80 dosya; yalnızca var olan dosyalar, klasör ve korunan yollar silinemez); silme tek başına geçerli bir teslimdir.':
        'If you NEED TO DELETE files, give `payload.delete` = ["path relative to the project root", ...] (at most 80 files; only existing files, folders and protected paths cannot be deleted); a deletion alone is a valid delivery.',
}
