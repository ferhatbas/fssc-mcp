"""
FS-SC Çoklu Ajan ve Görsel Telemetri Başlatıcısı (Unified Runner).
Tek komutla hem MCP/WebSocket sunucusunu başlatır hem de tarayıcıyı açar.
"""

import os
import sys
import subprocess
import webbrowser
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def main():
    print("=" * 68)
    print("🌟 FS-SC ÇOKLU AJAN VE GÖRSEL MCP GÖZLEMLENEBİLİRLİK SİSTEMİ 🌟")
    print("=" * 68)
    print("1. Web Modu (API + Dashboard + WebSocket - Önerilen Geliştirme Modu)")
    print("2. Stdio Modu (Claude Desktop / Antigravity MCP Entegrasyonu)")
    print("3. Yalnızca Demo Simülasyonunu Koş (Server çalışıyorsa)")
    print("=" * 68)

    mode_choice = "1"
    if len(sys.argv) > 1:
        mode_choice = sys.argv[1]

    if mode_choice == "1":
        print("\n[*] Web Sunucusu Başlatılıyor (http://127.0.0.1:8099)...")
        print("[*] Dashboard: http://localhost:5173 (React Dev) veya http://127.0.0.1:8099")
        time.sleep(1)
        # Web sunucusunu başlat
        subprocess.run([sys.executable, "-m", "server.main", "--mode", "web"])
    elif mode_choice == "2":
        print("\n[*] Stdio MCP Modu Başlatılıyor...")
        subprocess.run([sys.executable, "-m", "server.main", "--mode", "stdio"])
    elif mode_choice == "3":
        print("\n[*] Demo senaryosu koşturuluyor...")
        subprocess.run([sys.executable, "scripts/orchestrator_demo.py"])

if __name__ == "__main__":
    main()
