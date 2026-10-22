"""Ingilizce katalog: tasarım yenileme turu (sprint_flow.ensure_design_task, steps/tasks.py)."""
EN = {
    "Tasarım yenileme v{n}: tüm ekranlar ve ekran akışları (profesyonel HTML mockup)": "Design refresh v{n}: all screens and screen flows (professional HTML mockups)",
    "Yönetici isteği: mevcut tasarım yetersiz; tasarım sistemini yenile, uygulamadaki TÜM ekranlar için profesyonel mockup'ları üret ve ekranlar arası akışı çıkar.":
        "Manager request: the current design is not good enough; refresh the design system, produce professional mockups for ALL screens of the application and map the flow between screens.",
    "Yönetici notu:": "Manager note:",
    "Tasarım sistemi yenilendi (design-system.html)": "Design system refreshed (design-system.html)",
    "PRD ve uygulamadaki her ekran için mockup var (screens/*.html), boş/hata/yükleniyor/dolu durumlarıyla": "A mockup exists for every screen in the PRD and the application (screens/*.html), with empty/error/loading/filled states",
    "Ekran akış haritası hazır (flows.md ve flows.html): ekran kimlikleri, geçişler, kullanıcı yolculukları": "Screen flow map is ready (flows.md and flows.html): screen ids, transitions, user journeys",
    "Yönetici onayı alındı": "Manager approval received",
    "Yönetici tasarım yenilemesi istedi (tur {n}).": "The manager asked for a design refresh (round {n}).",
    "YÖNETİCİ NOTU (öncelikli):": "MANAGER NOTE (priority):",
    "Bu adım TASARIM YENİLEME turudur (kod değil): mevcut tasarım yönetici tarafından yetersiz bulundu; öncekini referans al ama daha profesyonel, tutarlı ve tam bir tasarım üret. `files` içinde tek dosyalık, dışa bağımlılıksız (JS yok, harici kaynak yok) HTML+CSS ver: (1) `<docs>/design/design-system.html` (yenilenmiş belirteçler ve bileşenler), (2) PRD'deki, API sözleşmesindeki ve mevcut istemci yönlendirmesindeki (`route`) HER ekran için `<docs>/design/screens/<kimlik>.html`: gerçekçi içerik; mobil ve masaüstü; boş, hata, yükleniyor ve dolu durumları ayrı bölümlerde; erişilebilir (kontrast, odak, 44 px hedef), (3) `<docs>/design/coverage.md`: backend uç grubu → ekran eşlemesi (bağlamdaki 'Backend uç noktaları' bölümüne göre; kapsanmayan uç kalmasın), (4) `<docs>/design/flows.md` ve `<docs>/design/flows.html`: ekran akış haritası — her kullanıcı yolculuğu (kayıt/giriş, keşif, katılım, check-in, organizatör, yönetici) için ekran kimlikleri ve aralarındaki geçişler, giriş/çıkış koşulları. `payload.design.screens[]` TÜM ekranları (id, title, route, file, state_files) ve `design.flows[]` akışları (id, title, steps: ekran kimlikleri sırası) bildirsin; `design.tokens` belirteçleri bildirsin. Onaylı teknoloji yığınına uy. Yönetici onaylamadan frontend bu tasarıma geçmez.":
        "This step is a DESIGN REFRESH round (not code): the manager found the current design insufficient; use the previous one as a reference but produce a more professional, consistent and complete design. In `files` give single-file, dependency-free (no JS, no external resources) HTML+CSS: (1) `<docs>/design/design-system.html` (refreshed tokens and components), (2) `<docs>/design/screens/<id>.html` for EVERY screen in the PRD, the API contract and the current client routing (`route`): realistic content; mobile and desktop; empty, error, loading and filled states in separate sections; accessible (contrast, focus, 44 px targets), (3) `<docs>/design/coverage.md`: backend endpoint group → screen mapping (from the 'Backend endpoints' section of the context; no endpoint left uncovered), (4) `<docs>/design/flows.md` and `<docs>/design/flows.html`: the screen flow map — for every user journey (sign-up/login, discovery, joining, check-in, organizer, admin) the screen ids and the transitions between them, entry/exit conditions. `payload.design.screens[]` must list ALL screens (id, title, route, file, state_files) and `design.flows[]` the flows (id, title, steps: ordered screen ids); `design.tokens` must list the tokens. Follow the approved technology stack. The frontend does not switch to this design before the manager approves.",
}

EN.update({
    "Ekran: {title} ({route})": "Screen: {title} ({route})",
    "Onaylı tasarımdaki '{title}' ekranını ({mock}) uygulamada gerçekle: tasarım sistemine ve mockup'a birebir uy; boş, hata, yükleniyor ve dolu durumlarını da yap.":
        "Implement the '{title}' screen ({mock}) of the approved design in the application: follow the design system and the mockup exactly; also build the empty, error, loading and filled states.",
    "Akışlar: {flows}": "Flows: {flows}",
    "Ekran '{route}' adresinde açılır ve mockup'taki yerleşim, renk ve bileşenlerle eşleşir": "The screen opens at '{route}' and matches the layout, colors and components of the mockup",
    "Boş, hata, yükleniyor ve dolu durumları gösterilir": "Empty, error, loading and filled states are shown",
    "Ekran sözleşmesi (screens[]) bildirilir; çalışan uygulamada ekran görüntüsü alınabilir": "The screen contract (screens[]) is reported; a screenshot can be taken in the running application",
    "Tasarım ekranından otomatik açıldı ({id}).": "Opened automatically from the design screen ({id}).",
    "Web arayüzünü başlatıyorum: `{run}` — adres {url}": "Starting the web client: `{run}` — address {url}",
    "## Backend uç noktaları → gerekli ekranlar (sunucu taraması; {n} uç)": "## Backend endpoints → required screens (server scan; {n} endpoints)",
    "Her uç grubu için kullanıcının göreceği ekran(lar) tasarlanmalı: listeleme/detay/form/durum ekranları ve hata-boş durumları. Mevcut mockup'larla karşılaştır; eksik olanları üret.":
        "Design the screen(s) the user will see for every endpoint group: list/detail/form/state screens and their error/empty states. Compare with the existing mockups and produce the missing ones.",
    "Mevcut mockup'lar: ": "Existing mockups: ",
    "yok": "none",
    "İstemci ekran dosyaları: ": "Client screen files: ",
    "Teslimde `<docs>/design/coverage.md` yaz: her uç grubu → ekran kimliği/kimlikleri (ya da 'ekran gerekmez' + gerekçe); kapsanmayan uç kalmasın.":
        "In your delivery write `<docs>/design/coverage.md`: every endpoint group -> screen id(s) (or 'no screen needed' + reason); no endpoint may stay uncovered.",
    "Hiç ekran mockup'ı yok (`<docs>/design/screens/*.html`).": "There is no screen mockup at all (`<docs>/design/screens/*.html`).",
    "viewport meta yok": "no viewport meta",
    "mobil/masaüstü için duyarlılık yok (@media ya da esnek yerleşim: auto-fit, flex-wrap, clamp)": "not responsive (no @media or flexible layout: auto-fit, flex-wrap, clamp)",
    "JS içeriyor": "contains JS",
    "harici kaynak kullanıyor": "uses an external resource",
    "en az {n} durum bölümü yok (dolu + boş/hata/yükleniyor/alternatif)": "fewer than {n} state sections (filled + empty/error/loading/alternative)",
    "`{name}` yok": "`{name}` is missing",
    "coverage.md şu uçları kapsamıyor ({n}): {list}": "coverage.md does not cover these endpoints ({n}): {list}",
    "Bildirilen ekran dosyası yok: {file}": "Reported screen file is missing: {file}",
    "Tasarım teslimi eksik: ": "Design delivery is incomplete: ",
    "⚠ {reason}; düzeltme turu {n} açıldı.": "⚠ {reason}; fix round {n} opened.",
    "⚠ Tasarım teslimi eksik kaldı; düzeltme hakkı bitti: ": "⚠ The design delivery stayed incomplete; no fix rounds left: ",
    "Atlanacak adım bulunamadı (yok ya da zaten teslim edilmiş): #{order}": "No step to skip was found (missing or already delivered): #{order}",
    "Yönetici adımı atladı.": "The manager skipped the step.",
    "## Test yazımı geçici olarak KAPALI (yönetici kararı)": "## Test writing is temporarily OFF (manager decision)",
    "Bu görevde yeni test dosyası yazma ve test yazma görevi üstlenme; yalnızca görevin kendisini (kod/ekran/belge) teslim et. Mevcut testler sunucuda koşmaya devam eder; bozma.":
        "Do not write new test files in this task and do not take on test-writing work; deliver only the task itself (code/screen/document). Existing tests keep running on the server; do not break them.",
})
