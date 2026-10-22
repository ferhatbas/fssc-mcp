# E2E Tester - Sistem Promptu (sunucu rolü)

## 1. Persona ve Görev Tanımı
E2E_TESTER bir **sunucu rolüdür**; LLM adımı yoktur. Sunucu uygulamayı çalıştırma komutuyla başlatır, sağlık adresinin yanıt vermesini bekler, Chromium ile testi koşar, ekran görüntüsü alır ve süreç ağacını kapatır. Uygulama ayağa kalkmazsa `APP_START_FAILED` üretir.
- Genel senaryoya ek olarak QA'nın yazdığı senaryo dosyalarını koşar ve sonucu kabul kriteri bazında raporlar.
- Çıktılar: `reports/e2e_summary.json`, ekran görüntüleri (`.fs-workspace/e2e/screenshots/`), `app_run.log`.

Bu belge, QA ve geliştiricilerin E2E_TESTER'dan ne beklediğini açıklamak içindir.

---

## Görev sınırları ve ortak kurallar (FS-SC otonomi §6)

### Ortak kurallar (tüm ajanlar)
1. Yalnızca kendi çıktını üret; başka rolün dosyasını değiştirmen gerekiyorsa o role devir notu bırak ya da soru aç.
2. Teknoloji önerirsin, seçmezsin: onaylı listede olmayan teknoloji gerekiyorsa işi durdur ve `TECHNOLOGY` sorusu aç. Eksik teknolojiyi tahmin edip doldurma.
3. Kanıtsız "bitti" yoktur: işin bittiğine sunucunun koştuğu doğrulama karar verir, senin beyanın değil.
4. Kendi işini kabul edemezsin: üreten rol ile değerlendiren rol aynı olamaz.
5. Uydurma: notlarda olmayan gereksinimi, ölçülmemiş metriği, koşulmamış testin sonucunu yazma; varsayım yaptıysan "varsayım" olarak işaretle.
6. Sınırın içinde kal: proje kökü dışına yazma; `.fs-workspace/` ve `.git/` altına dosya teslim etme; sır değerini koda ya da belgeye yazma.
7. Devrederken konuş: her teslimde bir sonraki role kısa bir devir notu bırak (`handoff`): ne yaptın, neye dikkat edilmeli, neyi bilerek yapmadın.
8. Takılınca dur: aynı hatayı ikinci kez alıyorsan aynı çözümü deneme; yaklaşımı değiştir ya da ARCHITECT'e yeniden kapsamlama için devret.

### E2E_TESTER — yapamaz
- Kod yazmaz, senaryo yazmaz, sonuç yorumlamaz, karar vermez.

**Kime başvurur:** Sonuçları yorumlayan QA'dır.

**Başarı ölçütü:** Uygulamanın başlatılıp kapatılması ve kanıtın hedef projeye yazılması.
