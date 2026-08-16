from __future__ import annotations

import json
import re
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_parser

from project_service.secretscan import SecretFinding, scan_text

MAX_FILES = 20000
MAX_TREE_ENTRIES = 2000
MAX_CONTENT_BYTES = 1_000_000
BINARY_PROBE_BYTES = 8192

IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "bower_components",
        "vendor",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".tox",
        ".next",
        ".nuxt",
        ".turbo",
        "dist",
        "build",
        "out",
        "target",
        "coverage",
        ".gradle",
        ".terraform",
    }
)

EXTENSION_LANGUAGE = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "bash",
    ".bash": "bash",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".rst": "markdown",
    ".txt": "text",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".svg": "image",
    ".bmp": "image",
    ".ico": "image",
    ".pdf": "document",
    ".zip": "archive",
    ".tar": "archive",
    ".gz": "archive",
}

PARSEABLE_LANGUAGES = frozenset(
    {
        "python",
        "javascript",
        "typescript",
        "tsx",
        "go",
        "rust",
        "java",
        "c",
        "cpp",
        "csharp",
        "ruby",
        "php",
        "bash",
    }
)

SHEBANG_LANGUAGE = (
    ("python", "python"),
    ("node", "javascript"),
    ("bash", "bash"),
    ("sh", "bash"),
    ("ruby", "ruby"),
)

CONVENTIONAL_ENTRY_POINTS = frozenset(
    {
        "main.py",
        "__main__.py",
        "manage.py",
        "app.py",
        "wsgi.py",
        "asgi.py",
        "index.js",
        "index.ts",
        "main.js",
        "main.ts",
        "server.js",
        "server.ts",
        "main.go",
        "main.rs",
        "Program.cs",
    }
)

REQUIREMENT_SPLIT = re.compile(r"[\s\[<>=!~;#]")
GO_REQUIRE_LINE = re.compile(r"^\s*([\w.\-/]+)\s+v\S+")


@dataclass(frozen=True)
class LanguageCount:
    language: str
    files: int
    size_bytes: int
    parsed: int


@dataclass(frozen=True)
class DependencyManifest:
    path: str
    ecosystem: str
    dependencies: list[str]


@dataclass(frozen=True)
class ScanResult:
    total_files: int
    total_size_bytes: int
    file_tree: list[str]
    languages: list[LanguageCount]
    dependency_manifests: list[DependencyManifest]
    entry_points: list[str]
    secret_findings: list[SecretFinding]
    skipped_directories: list[str]
    truncated: bool


@lru_cache(maxsize=32)
def parser_for(language: str) -> Parser | None:
    try:
        return get_parser(language)
    except (LookupError, ValueError):
        return None


def is_binary(payload: bytes) -> bool:
    return b"\x00" in payload[:BINARY_PROBE_BYTES]


def shebang_language(text: str) -> str | None:
    first = text.split("\n", 1)[0]

    if not first.startswith("#!"):
        return None

    for token, language in SHEBANG_LANGUAGE:
        if token in first:
            return language

    return None


def classify(relative: str, text: str | None) -> str:
    suffix = Path(relative).suffix.lower()
    declared = EXTENSION_LANGUAGE.get(suffix)

    if text is not None:
        detected = shebang_language(text)

        if detected is not None and (declared is None or declared == "text"):
            return detected

    return declared or "other"


def declares_python_main(root: Node) -> bool:
    return any(
        child.type == "if_statement" and b"__name__" in (child.text or b"")
        for child in root.children
    )


def declares_named_function(root: Node, node_type: str, name: bytes) -> bool:
    for child in root.children:
        if child.type != node_type:
            continue

        identifier = child.child_by_field_name("name")

        if identifier is not None and identifier.text == name:
            return True

    return False


def is_entry_point(language: str, relative: str, root: Node | None) -> bool:
    if Path(relative).name in CONVENTIONAL_ENTRY_POINTS:
        return True

    if root is None:
        return False

    if language == "python":
        return declares_python_main(root)

    if language == "go":
        return declares_named_function(root, "function_declaration", b"main")

    if language == "rust":
        return declares_named_function(root, "function_item", b"main")

    return False


def parse_names(payload: dict[str, Any], *keys: str) -> list[str]:
    names: list[str] = []

    for key in keys:
        section = payload.get(key)

        if isinstance(section, dict):
            names.extend(str(name) for name in section)

    return names


def requirement_name(line: str) -> str | None:
    stripped = line.strip()

    if not stripped or stripped.startswith(("#", "-")):
        return None

    name = REQUIREMENT_SPLIT.split(stripped, maxsplit=1)[0].strip()
    return name or None


def parse_manifest(relative: str, text: str) -> DependencyManifest | None:
    name = Path(relative).name

    try:
        if name == "package.json":
            payload = json.loads(text)
            return DependencyManifest(
                path=relative,
                ecosystem="npm",
                dependencies=sorted(
                    set(parse_names(payload, "dependencies", "devDependencies", "peerDependencies"))
                ),
            )

        if name == "pyproject.toml":
            payload = tomllib.loads(text)
            project = payload.get("project", {})
            declared = project.get("dependencies", []) if isinstance(project, dict) else []
            names = {requirement_name(str(item)) for item in declared}
            return DependencyManifest(
                path=relative,
                ecosystem="python",
                dependencies=sorted(item for item in names if item),
            )

        if name in {"requirements.txt", "requirements-dev.txt"}:
            names = {requirement_name(line) for line in text.splitlines()}
            return DependencyManifest(
                path=relative,
                ecosystem="python",
                dependencies=sorted(item for item in names if item),
            )

        if name == "Cargo.toml":
            payload = tomllib.loads(text)
            return DependencyManifest(
                path=relative,
                ecosystem="cargo",
                dependencies=sorted(set(parse_names(payload, "dependencies", "dev-dependencies"))),
            )

        if name == "go.mod":
            matches = {
                match.group(1)
                for match in (GO_REQUIRE_LINE.match(line) for line in text.splitlines())
                if match is not None
            }
            return DependencyManifest(path=relative, ecosystem="go", dependencies=sorted(matches))
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, ValueError):
        return DependencyManifest(path=relative, ecosystem="unparsed", dependencies=[])

    return None


def walk(root: Path) -> tuple[list[Path], list[str], bool]:
    files: list[Path] = []
    skipped: set[str] = set()
    truncated = False

    for directory, subdirectories, filenames in root.walk():
        retained = []

        for name in sorted(subdirectories):
            if name in IGNORED_DIRECTORIES:
                skipped.add(str((directory / name).relative_to(root).as_posix()))
            else:
                retained.append(name)

        subdirectories[:] = retained

        for name in sorted(filenames):
            if len(files) >= MAX_FILES:
                truncated = True
                break

            files.append(directory / name)

    return files, sorted(skipped), truncated


def read_text(path: Path, size: int) -> str | None:
    if size > MAX_CONTENT_BYTES:
        return None

    try:
        payload = path.read_bytes()
    except OSError:
        return None

    if is_binary(payload):
        return None

    return payload.decode("utf-8", errors="replace")


def scan_directory(root: Path) -> ScanResult:
    files, skipped, truncated = walk(root)

    total_size = 0
    tree: list[str] = []
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    manifests: list[DependencyManifest] = []
    entry_points: list[str] = []
    findings: list[SecretFinding] = []

    for path in files:
        relative = path.relative_to(root).as_posix()

        try:
            size = path.stat().st_size
        except OSError:
            continue

        total_size += size
        tree.append(relative)

        text = read_text(path, size)
        language = classify(relative, text)

        counts[language][0] += 1
        counts[language][1] += size

        if text is None:
            continue

        findings.extend(scan_text(relative, text))

        manifest = parse_manifest(relative, text)

        if manifest is not None:
            manifests.append(manifest)

        node: Node | None = None

        if language in PARSEABLE_LANGUAGES:
            parser = parser_for(language)

            if parser is not None:
                node = parser.parse(text.encode("utf-8")).root_node

                if not node.has_error:
                    counts[language][2] += 1

        if is_entry_point(language, relative, node):
            entry_points.append(relative)

    languages = [
        LanguageCount(language=name, files=value[0], size_bytes=value[1], parsed=value[2])
        for name, value in sorted(counts.items(), key=lambda item: (-item[1][0], item[0]))
    ]

    return ScanResult(
        total_files=len(tree),
        total_size_bytes=total_size,
        file_tree=sorted(tree)[:MAX_TREE_ENTRIES],
        languages=languages,
        dependency_manifests=sorted(manifests, key=lambda item: item.path),
        entry_points=sorted(entry_points),
        secret_findings=findings,
        skipped_directories=skipped,
        truncated=truncated or len(tree) > MAX_TREE_ENTRIES,
    )
