from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

MAX_LINE_LENGTH = 4096
MIN_ASSIGNED_ENTROPY = 3.0

PLACEHOLDER_VALUES = frozenset(
    {
        "changeme",
        "example",
        "none",
        "null",
        "placeholder",
        "redacted",
        "replaceme",
        "secret",
        "todo",
        "undefined",
        "yourkeyhere",
    }
)

TEMPLATE_MARKERS = ("${", "{{", "<%", "%(", "os.environ", "process.env")

LITERAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("stripe_key", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("bearer_style_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    (
        "json_web_token",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "connection_string_password",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:@/]+:[^\s:@/]{4,}@[^\s/]+"),
    ),
)

ASSIGNED_KEYWORDS = (
    r"api[_-]?key|secret[_-]?key|secret|password|passwd|pwd"
    r"|access[_-]?token|auth[_-]?token|token"
)

ASSIGNED_PATTERN = re.compile(
    r"(?i)\b(" + ASSIGNED_KEYWORDS + r")\b\s*[:=]\s*[\"']([^\"']{8,})[\"']"
)


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    kind: str
    preview: str


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0

    counts = Counter(value)
    length = len(value)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def mask(value: str) -> str:
    return f"{value[:4]}… ({len(value)} chars)"


def is_placeholder(value: str) -> bool:
    normalised = re.sub(r"[^a-z]", "", value.lower())

    if normalised in PLACEHOLDER_VALUES:
        return True

    if any(marker in value for marker in TEMPLATE_MARKERS):
        return True

    return len(set(value)) < 4


def scan_line(path: str, line_number: int, line: str) -> list[SecretFinding]:
    if len(line) > MAX_LINE_LENGTH:
        return []

    findings: list[SecretFinding] = []

    for kind, pattern in LITERAL_PATTERNS:
        match = pattern.search(line)

        if match is None:
            continue

        preview = kind if kind == "private_key_block" else mask(match.group(0))
        findings.append(SecretFinding(path=path, line=line_number, kind=kind, preview=preview))

    if findings:
        return findings

    assigned = ASSIGNED_PATTERN.search(line)

    if assigned is None:
        return findings

    value = assigned.group(2)

    if is_placeholder(value) or shannon_entropy(value) < MIN_ASSIGNED_ENTROPY:
        return findings

    keyword = assigned.group(1).lower().replace("-", "_")
    findings.append(
        SecretFinding(path=path, line=line_number, kind=f"assigned_{keyword}", preview=mask(value))
    )

    return findings


def scan_text(path: str, text: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []

    for index, line in enumerate(text.splitlines(), start=1):
        findings.extend(scan_line(path, index, line))

    return findings
