"""Koşu API'sinin hafif hata sınıfı (ağır modülleri yüklemeden içe aktarılabilsin diye ayrı dosyada)."""

from typing import Any, Dict


class RunsApiError(Exception):
    def __init__(self, message: str, status_code: int = 400, **extra: Any):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.extra = extra

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, **self.extra}
