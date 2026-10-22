"""
Alt süreç yardımcıları.

Windows'ta konsolu olmayan bir süreç (bağımsız başlatılan sunucu, pythonw ...) bir konsol uygulaması (git, cmd, npm, docker ...) açtığında Windows
her biri için YENİ bir konsol penceresi açar; varsayılan terminal Windows Terminal ise o da açılıp kapanır ("birçok cmd ekranı açılıp kapanıyor",
saha: pano her yoklamada `git rev-parse` pencere açıyordu). `CREATE_NO_WINDOW` alt süreci pencere açmadan koşturur ve onun alt süreçleri de
aynı gizli konsolu devralır. Sunucudan açılan her alt süreç `**hidden()` ile başlatılır; `tests/test_no_console_windows.py` bunu denetler.
"""

from __future__ import annotations

import sys
from typing import Any, Dict

IS_WINDOWS = sys.platform.startswith("win")

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def hidden(**extra: Any) -> Dict[str, Any]:
    """`subprocess.run/Popen` ve `asyncio.create_subprocess_*` için anahtar sözcükler: Windows'ta pencere açmaz, diğer sistemlerde yalnızca `extra`.
    `extra["creationflags"]` verilirse `CREATE_NO_WINDOW` ile birleştirilir."""
    if not IS_WINDOWS:
        return dict(extra)
    flags = int(extra.pop("creationflags", 0) or 0) | CREATE_NO_WINDOW
    return {**extra, "creationflags": flags}
