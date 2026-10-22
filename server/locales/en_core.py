"""İngilizce katalog: çekirdek (pipeline sistem istemi ekleri)."""
EN = {
    "Bu ajana özel ek yönerge": "Additional instructions for this agent",
    "\n\n---\n## Çıktı Kuralı (FS-SC Pipeline)\nBu adımın sonucunu yalnızca istenen JSON zarfı olarak ver. Dosyaları kendin yazma; içeriklerini `payload.files` içinde ver, sunucu proje klasörüne yazar. Blok dışında açıklama yazma.":
        "\n\n---\n## Output rule (FS-SC pipeline)\nReturn the result of this step only as the requested JSON envelope. Do not write files yourself; put their contents in `payload.files` and the server writes them to the project folder. Do not write any explanation outside the block.",
}
