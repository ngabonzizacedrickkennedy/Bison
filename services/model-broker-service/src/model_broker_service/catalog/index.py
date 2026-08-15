from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from model_broker_service.catalog.sources import CatalogRecord, CatalogSource

INDEX_SCHEMA_VERSION = 1


class CatalogIndex:
    def __init__(self, sources: list[CatalogSource], path: Path) -> None:
        self._sources = sources
        self._path = path
        self._records: list[CatalogRecord] = []
        self._indexed_at: datetime | None = None
        self._lock = asyncio.Lock()

    @property
    def indexed_at(self) -> datetime | None:
        return self._indexed_at

    @property
    def size(self) -> int:
        return len(self._records)

    def search(self, query: str, limit: int) -> list[CatalogRecord]:
        needle = query.strip().lower()

        if not needle:
            return self._records[:limit]

        scored = [
            (self._score(record, needle), record)
            for record in self._records
            if self._score(record, needle) > 0
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1].model_id))

        return [record for _, record in scored[:limit]]

    def get(self, model_id: str) -> CatalogRecord | None:
        return next((record for record in self._records if record.model_id == model_id), None)

    async def load(self) -> bool:
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        if not isinstance(raw, dict) or raw.get("schema_version") != INDEX_SCHEMA_VERSION:
            return False

        entries = raw.get("records")

        if not isinstance(entries, list):
            return False

        async with self._lock:
            self._records = [self._revive(entry) for entry in entries if isinstance(entry, dict)]
            self._indexed_at = self._parse_timestamp(raw.get("indexed_at"))

        return True

    async def refresh(self) -> int:
        gathered = await asyncio.gather(
            *(source.fetch() for source in self._sources), return_exceptions=True
        )

        merged: dict[str, CatalogRecord] = {}

        for result in gathered:
            if isinstance(result, BaseException):
                continue

            for record in result:
                merged.setdefault(record.model_id, record)

        if not merged:
            return self.size

        async with self._lock:
            self._records = sorted(merged.values(), key=lambda record: record.model_id)
            self._indexed_at = datetime.now(UTC)

        self._persist()

        return self.size

    def _persist(self) -> None:
        payload = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "indexed_at": (self._indexed_at or datetime.now(UTC)).isoformat(),
            "records": [asdict(record) for record in self._records],
        }

        temporary = self._path.with_suffix(f".{INDEX_SCHEMA_VERSION}.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self._path)

    @staticmethod
    def _score(record: CatalogRecord, needle: str) -> int:
        model_id = record.model_id.lower()

        if model_id == needle:
            return 100

        if model_id.startswith(needle):
            return 80

        if needle in model_id:
            return 60

        if any(needle in tag for tag in record.capability_tags):
            return 30

        if needle in record.provider.lower():
            return 10

        return 0

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None

        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _revive(entry: dict[str, Any]) -> CatalogRecord:
        tags = entry.get("capability_tags")
        locality = entry.get("locality")

        return CatalogRecord(
            model_id=str(entry.get("model_id", "")),
            provider=str(entry.get("provider", "")),
            locality="local" if locality == "local" else "remote",
            size_gb=entry.get("size_gb") if isinstance(entry.get("size_gb"), int | float) else None,
            capability_tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
            context_window=entry.get("context_window")
            if isinstance(entry.get("context_window"), int)
            else None,
        )
