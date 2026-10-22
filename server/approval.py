"""
Token bazlı Onay Kapısı (ApprovalGate).

Human-in-the-loop adım onayı için tek global `asyncio.Event` yerine her bekleyen
adıma benzersiz bir token ve kendi `asyncio.Future`'ı verilir. Böylece:
- İki paralel koşu birbirinin onayını çalamaz.
- Bekleme süresi sınırlandırılabilir (timeout → None döner, karar verilmemiştir).
- MCP istemcisi kısa yoklamalarla (poll) aynı token'ı bekleyebilir; bekleme
  süresi dolsa da Future yerinde kalır ve bir sonraki yoklamada tekrar beklenebilir.
"""

import asyncio
import os
import uuid
from typing import Any, Dict, List, Optional

DEFAULT_STEP_APPROVAL_TIMEOUT_S = float(os.environ.get("STEP_APPROVAL_TIMEOUT_S", "1800"))


class ApprovalGate:
    def __init__(self) -> None:
        self._futures: Dict[str, "asyncio.Future[str]"] = {}
        self._infos: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Token yaşam döngüsü
    # ------------------------------------------------------------------
    @staticmethod
    def mint() -> str:
        """Yeni benzersiz onay token'ı üretir."""
        return uuid.uuid4().hex

    def register(self, token: str, info: Optional[Dict[str, Any]] = None) -> "asyncio.Future[str]":
        """Token için bekleyen bir Future kaydeder (idempotent)."""
        fut = self._futures.get(token)
        if fut is None or fut.done():
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            self._futures[token] = fut
        if info is not None:
            self._infos[token] = info
        return fut

    def is_pending(self, token: Optional[str]) -> bool:
        fut = self._futures.get(token or "")
        return fut is not None and not fut.done()

    def info(self, token: str) -> Optional[Dict[str, Any]]:
        return self._infos.get(token)

    @property
    def pending_tokens(self) -> List[str]:
        return [t for t, f in self._futures.items() if not f.done()]

    # ------------------------------------------------------------------
    # Bekleme ve çözümleme
    # ------------------------------------------------------------------
    async def wait(self, token: str, timeout: Optional[float] = None) -> Optional[str]:
        """
        Token çözülene kadar bekler ve kararı döner.
        Süre dolarsa None döner; Future yerinde kalır (yeniden beklenebilir).
        """
        fut = self.register(token)
        try:
            if timeout is None:
                return await asyncio.shield(fut)
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def peek(self, token: str) -> Optional[str]:
        """Bloklamadan: karar verildiyse kararı, verilmediyse None döner."""
        fut = self._futures.get(token)
        if fut is not None and fut.done() and not fut.cancelled():
            return fut.result()
        return None

    def resolve(self, token: Optional[str], decision: str) -> bool:
        """Token'ı verilen kararla çözer. Bekleyen yoksa False döner."""
        if not token:
            return False
        fut = self._futures.get(token)
        if fut is None or fut.done():
            return False
        fut.set_result(decision)
        return True

    def resolve_all(self, decision: str) -> int:
        """Bekleyen tüm token'ları aynı kararla çözer (örn. reset → CANCELLED)."""
        count = 0
        for token in list(self._futures.keys()):
            if self.resolve(token, decision):
                count += 1
        return count

    def cancel(self, token: str) -> None:
        """Token'ı bekleyen listesinden çıkarır (timeout sonrası temizlik)."""
        fut = self._futures.pop(token, None)
        self._infos.pop(token, None)
        if fut is not None and not fut.done():
            fut.cancel()

    def forget(self, token: str) -> None:
        """Çözülmüş token'ı hafızadan siler."""
        self._futures.pop(token, None)
        self._infos.pop(token, None)
