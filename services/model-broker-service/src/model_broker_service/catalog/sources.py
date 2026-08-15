from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

import httpx


@dataclass(frozen=True, slots=True)
class CatalogRecord:
    model_id: str
    provider: str
    locality: Literal["local", "remote"]
    size_gb: float | None
    capability_tags: tuple[str, ...]
    context_window: int | None


class CatalogSource(ABC):
    name: str

    @abstractmethod
    async def fetch(self) -> list[CatalogRecord]: ...


OLLAMA_LIBRARY: tuple[tuple[str, float, int, tuple[str, ...]], ...] = (
    ("qwen2.5-coder:7b", 4.7, 32768, ("code", "structured", "fast")),
    ("qwen2.5-coder:14b", 9.0, 32768, ("code", "structured")),
    ("qwen2.5-coder:32b", 20.0, 32768, ("code", "structured", "reasoning")),
    ("qwen2.5:7b", 4.7, 32768, ("general", "structured", "fast")),
    ("qwen2.5:14b", 9.0, 32768, ("general", "structured")),
    ("llama3.1:8b", 4.9, 131072, ("general", "long-context", "fast")),
    ("llama3.1:70b", 40.0, 131072, ("general", "reasoning", "long-context")),
    ("llama3.2:3b", 2.0, 131072, ("general", "fast")),
    ("mistral:7b", 4.1, 32768, ("general", "fast")),
    ("mistral-nemo:12b", 7.1, 131072, ("general", "long-context")),
    ("gemma2:9b", 5.4, 8192, ("general",)),
    ("gemma2:27b", 16.0, 8192, ("general", "reasoning")),
    ("phi3.5:3.8b", 2.2, 131072, ("general", "fast", "long-context")),
    ("deepseek-coder-v2:16b", 8.9, 163840, ("code", "reasoning", "long-context")),
    ("codellama:13b", 7.4, 16384, ("code",)),
    ("nomic-embed-text", 0.3, 8192, ("embedding",)),
)


class OllamaLibrarySource(CatalogSource):
    name = "ollama"

    async def fetch(self) -> list[CatalogRecord]:
        return [
            CatalogRecord(
                model_id=model_id,
                provider="ollama",
                locality="local",
                size_gb=size_gb,
                capability_tags=tags,
                context_window=context_window,
            )
            for model_id, size_gb, context_window, tags in OLLAMA_LIBRARY
        ]


class OpenRouterSource(CatalogSource):
    name = "openrouter"

    def __init__(self, base_url: str, timeout_seconds: float, free_only: bool) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._free_only = free_only

    async def fetch(self) -> list[CatalogRecord]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get("/api/v1/models")
            response.raise_for_status()
            payload: Any = response.json()

        entries = payload.get("data") if isinstance(payload, dict) else None

        if not isinstance(entries, list):
            return []

        records = [
            self._describe(entry)
            for entry in entries
            if isinstance(entry, dict) and self._include(entry)
        ]

        return [record for record in records if record.model_id]

    def _include(self, entry: dict[str, Any]) -> bool:
        if not self._free_only:
            return True

        pricing = entry.get("pricing")

        if not isinstance(pricing, dict):
            return False

        return all(self._is_zero(pricing.get(key)) for key in ("prompt", "completion"))

    @staticmethod
    def _is_zero(value: Any) -> bool:
        try:
            return float(value) == 0.0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _describe(entry: dict[str, Any]) -> CatalogRecord:
        context_window = entry.get("context_length")
        architecture = entry.get("architecture")
        modality = architecture.get("modality") if isinstance(architecture, dict) else None

        tags = ["remote"]

        if isinstance(modality, str) and "image" in modality:
            tags.append("vision")

        if isinstance(context_window, int) and context_window >= 100000:
            tags.append("long-context")

        return CatalogRecord(
            model_id=str(entry.get("id", "")),
            provider="openrouter",
            locality="remote",
            size_gb=None,
            capability_tags=tuple(tags),
            context_window=context_window if isinstance(context_window, int) else None,
        )
