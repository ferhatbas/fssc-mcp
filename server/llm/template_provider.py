"""
Çevrimdışı şablon sağlayıcısı: LLM yerine adım işleyicisinin hazır A2A zarfını döner.
Demo / test modunda ve MCP istemcisi üst üste geçersiz çıktı verdiğinde yedek olarak kullanılır.
"""

from __future__ import annotations

from typing import Any, Dict

from ..steps.base import StepContext, StepHandler


class TemplateProvider:
    name = "template"

    async def complete(self, ctx: StepContext, handler: StepHandler) -> Dict[str, Any]:
        return handler.template_output(ctx)


template_provider = TemplateProvider()
