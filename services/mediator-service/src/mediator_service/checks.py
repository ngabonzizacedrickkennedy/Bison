from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Final

SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-f0-9]{64}$")

MIN_PORT: Final[int] = 1
MAX_PORT: Final[int] = 65535
MIN_STATUS: Final[int] = 100
MAX_STATUS: Final[int] = 599

DECLARABLE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "file_exists",
        "file_hash",
        "port_open",
        "http_status",
        "sql_result",
        "window_title",
        "text_on_screen",
    }
)

REFUSED_TYPES: Final[dict[str, str]] = {
    "process_exit": (
        "a process_exit criterion names a step_id, and no step exists when the tree is built; "
        "state the observable result instead, with file_exists, port_open or http_status"
    )
}


class CheckSpecError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class FileExists:
    path: str
    TYPE: ClassVar[str] = "file_exists"


@dataclass(frozen=True)
class FileHash:
    path: str
    expected_sha256: str
    TYPE: ClassVar[str] = "file_hash"


@dataclass(frozen=True)
class PortOpen:
    host: str
    port: int
    TYPE: ClassVar[str] = "port_open"


@dataclass(frozen=True)
class HttpStatus:
    url: str
    expected_status: int
    timeout_ms: int
    TYPE: ClassVar[str] = "http_status"


@dataclass(frozen=True)
class SqlResult:
    connection_ref: str
    query: str
    expect: str
    TYPE: ClassVar[str] = "sql_result"


@dataclass(frozen=True)
class WindowTitle:
    pattern: str
    TYPE: ClassVar[str] = "window_title"


@dataclass(frozen=True)
class TextOnScreen:
    text: str
    region: Region | None
    TYPE: ClassVar[str] = "text_on_screen"


CheckSpec = FileExists | FileHash | PortOpen | HttpStatus | SqlResult | WindowTitle | TextOnScreen


def payload(spec: CheckSpec) -> dict[str, Any]:
    return {"type": spec.TYPE, **asdict(spec)}


def text(source: dict[str, Any], key: str, label: str) -> str:
    value = source.get(key)

    if not isinstance(value, str) or not value.strip():
        raise CheckSpecError(f"{label}.{key} must be a non-empty string")

    return value.strip()


def integer(source: dict[str, Any], key: str, label: str) -> int:
    value = source.get(key)

    if isinstance(value, bool) or not isinstance(value, int):
        raise CheckSpecError(f"{label}.{key} must be a whole number")

    return value


def bounded(source: dict[str, Any], key: str, label: str, low: int, high: int) -> int:
    value = integer(source, key, label)

    if value < low or value > high:
        raise CheckSpecError(f"{label}.{key} must be between {low} and {high}")

    return value


def positive(source: dict[str, Any], key: str, label: str) -> int:
    value = integer(source, key, label)

    if value <= 0:
        raise CheckSpecError(f"{label}.{key} must be greater than zero")

    return value


def non_negative(source: dict[str, Any], key: str, label: str) -> int:
    value = integer(source, key, label)

    if value < 0:
        raise CheckSpecError(f"{label}.{key} must not be negative")

    return value


def digest(source: dict[str, Any], key: str, label: str) -> str:
    value = text(source, key, label).lower()

    if not SHA256_PATTERN.match(value):
        raise CheckSpecError(
            f"{label}.{key} must be a 64-character hexadecimal SHA-256, "
            "not a placeholder or a description"
        )

    return value


def parse_region(entry: Any, label: str) -> Region | None:
    if entry is None:
        return None

    if not isinstance(entry, dict):
        raise CheckSpecError(f"{label}.region must be an object or null")

    return Region(
        x=non_negative(entry, "x", f"{label}.region"),
        y=non_negative(entry, "y", f"{label}.region"),
        width=positive(entry, "width", f"{label}.region"),
        height=positive(entry, "height", f"{label}.region"),
    )


def discriminator(entry: dict[str, Any], label: str) -> str:
    value = entry.get("type")

    if not isinstance(value, str) or not value:
        raise CheckSpecError(f"{label}.type must name one of {', '.join(sorted(DECLARABLE_TYPES))}")

    refusal = REFUSED_TYPES.get(value)

    if refusal is not None:
        raise CheckSpecError(f"{label}.type is {value}, which cannot be used here: {refusal}")

    if value not in DECLARABLE_TYPES:
        raise CheckSpecError(
            f"{label}.type is {value}, which is not a check BISON can run; "
            f"use one of {', '.join(sorted(DECLARABLE_TYPES))}"
        )

    return value


def parse(entry: Any, label: str) -> CheckSpec:
    if not isinstance(entry, dict):
        raise CheckSpecError(f"{label} must be an object")

    kind = discriminator(entry, label)

    if kind == "file_exists":
        return FileExists(path=text(entry, "path", label))

    if kind == "file_hash":
        return FileHash(
            path=text(entry, "path", label),
            expected_sha256=digest(entry, "expected_sha256", label),
        )

    if kind == "port_open":
        return PortOpen(
            host=text(entry, "host", label),
            port=bounded(entry, "port", label, MIN_PORT, MAX_PORT),
        )

    if kind == "http_status":
        return HttpStatus(
            url=text(entry, "url", label),
            expected_status=bounded(entry, "expected_status", label, MIN_STATUS, MAX_STATUS),
            timeout_ms=positive(entry, "timeout_ms", label),
        )

    if kind == "sql_result":
        return SqlResult(
            connection_ref=text(entry, "connection_ref", label),
            query=text(entry, "query", label),
            expect=text(entry, "expect", label),
        )

    if kind == "window_title":
        return WindowTitle(pattern=text(entry, "pattern", label))

    return TextOnScreen(
        text=text(entry, "text", label),
        region=parse_region(entry.get("region"), label),
    )
