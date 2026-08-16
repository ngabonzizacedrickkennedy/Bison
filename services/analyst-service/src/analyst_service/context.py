from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_TREE_ENTRIES = 120
MAX_DEPENDENCIES = 25
MAX_MARKDOWN_CHARS = 4000
MAX_NOTE_CHARS = 500
MAX_SECRET_SIGHTINGS = 20
MAX_CONTEXT_CHARS = 24000

TREE_STEPS = (MAX_TREE_ENTRIES, 60, 24, 8, 0)


@dataclass(frozen=True)
class LanguageTally:
    language: str
    files: int
    parsed: int


@dataclass(frozen=True)
class ManifestSummary:
    path: str
    ecosystem: str
    dependencies: list[str]


@dataclass(frozen=True)
class SecretSighting:
    path: str
    line: int
    kind: str


@dataclass(frozen=True)
class ScanSummary:
    total_files: int
    total_size_bytes: int
    file_tree: list[str]
    languages: list[LanguageTally]
    dependency_manifests: list[ManifestSummary]
    entry_points: list[str]
    secret_findings: list[SecretSighting]
    skipped_directories: list[str]
    truncated: bool


@dataclass(frozen=True)
class Material:
    material_id: str
    kind: str
    caption: str | None = None
    note: str | None = None
    url: str | None = None
    scan: ScanSummary | None = None


@dataclass(frozen=True)
class Conceive:
    revision_number: int
    blocks: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AnsweredQuestion:
    round: int
    text: str
    why_asked: str
    answer: str


@dataclass(frozen=True)
class PriorBrief:
    round: int
    summary: str
    interpreted_goal: str
    unresolved_fields: list[str]


@dataclass(frozen=True)
class ProjectFacts:
    name: str
    goal: str
    project_type: str
    description: str | None = None
    target_environment: str | None = None
    constraints: list[str] = field(default_factory=list)
    do_not_touch: list[str] = field(default_factory=list)
    sensitivity_flags: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    referenced_project_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AnalystContext:
    project: ProjectFacts
    conceive: Conceive
    materials: list[Material] = field(default_factory=list)
    answers: list[AnsweredQuestion] = field(default_factory=list)
    prior: PriorBrief | None = None


def clip(value: str, limit: int) -> str:
    text = value.strip()

    if len(text) <= limit:
        return text

    return f"{text[:limit].rstrip()} [...truncated]"


def human_bytes(total: int) -> str:
    units = ("B", "KB", "MB", "GB")
    size = float(total)

    for unit in units[:-1]:
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"

        size /= 1024

    return f"{size:.1f} {units[-1]}"


def bullets(values: list[str]) -> list[str]:
    return [f"- {clip(value, MAX_NOTE_CHARS)}" for value in values if value.strip()]


def suffixed(note: object) -> str:
    if not isinstance(note, str) or not note.strip():
        return ""

    return f" - {clip(note, MAX_NOTE_CHARS)}"


def render_block(block: dict[str, Any]) -> list[str]:
    kind = str(block.get("type", ""))

    if kind == "markdown":
        return [clip(str(block.get("text", "")), MAX_MARKDOWN_CHARS)]

    if kind == "image":
        caption = block.get("caption")
        label = clip(str(caption), MAX_NOTE_CHARS) if isinstance(caption, str) else "no caption"
        return [f"[image {block.get('material_id', '')}] {label}"]

    if kind == "link":
        return [f"[link] {block.get('url', '')}{suffixed(block.get('note'))}"]

    if kind == "project_ref":
        return [f"[project {block.get('project_id', '')}]{suffixed(block.get('note'))}"]

    if kind == "file_ref":
        reference = f"{block.get('material_id', '')}:{block.get('path', '')}"
        return [f"[file {reference}]{suffixed(block.get('note'))}"]

    return []


def render_scan(scan: ScanSummary, tree_entries: int) -> list[str]:
    lines = [f"  {scan.total_files} files, {human_bytes(scan.total_size_bytes)}"]

    if scan.languages:
        tallied = [
            f"{tally.language} {tally.files} ({tally.parsed} parsed)" for tally in scan.languages
        ]
        lines.append(f"  languages: {', '.join(tallied)}")

    if scan.entry_points:
        lines.append(f"  entry points: {', '.join(scan.entry_points)}")

    for manifest in scan.dependency_manifests:
        shown = manifest.dependencies[:MAX_DEPENDENCIES]
        remaining = len(manifest.dependencies) - len(shown)
        listed = ", ".join(shown) if shown else "none declared"
        tail = f" (+{remaining} more)" if remaining > 0 else ""
        lines.append(f"  {manifest.path} [{manifest.ecosystem}]: {listed}{tail}")

    if scan.secret_findings:
        sighted = scan.secret_findings[:MAX_SECRET_SIGHTINGS]
        listed = ", ".join(f"{item.kind} at {item.path}:{item.line}" for item in sighted)
        lines.append(f"  secret-shaped strings: {len(scan.secret_findings)} flagged - {listed}")

    if scan.skipped_directories:
        lines.append(f"  pruned on ingest: {', '.join(scan.skipped_directories)}")

    if scan.truncated:
        lines.append("  the scan truncated this tree; it is not the whole listing")

    if tree_entries > 0 and scan.file_tree:
        shown = scan.file_tree[:tree_entries]
        lines.append(f"  tree ({len(shown)} of {scan.total_files}):")
        lines.extend(f"    {entry}" for entry in shown)

    return lines


def render_material(material: Material, tree_entries: int) -> list[str]:
    header = f"{material.kind} {material.material_id}"

    if material.url:
        header = f"{header} - {material.url}"

    lines = [header]

    if material.caption:
        lines.append(f"  caption: {clip(material.caption, MAX_NOTE_CHARS)}")

    if material.note:
        lines.append(f"  note: {clip(material.note, MAX_NOTE_CHARS)}")

    if material.scan is not None:
        lines.extend(render_scan(material.scan, tree_entries))

    return lines


def sections(context: AnalystContext, tree_entries: int) -> list[str]:
    project = context.project
    blocks: list[str] = []

    facts = [
        f"name: {project.name}",
        f"type: {project.project_type}",
        f"goal: {clip(project.goal, MAX_NOTE_CHARS)}",
    ]

    if project.target_environment:
        facts.append(f"environment: {clip(project.target_environment, MAX_NOTE_CHARS)}")

    if project.description:
        facts.append(f"description: {clip(project.description, MAX_MARKDOWN_CHARS)}")

    blocks.append("\n".join(["PROJECT", *facts]))

    if project.constraints:
        blocks.append("\n".join(["CONSTRAINTS", *bullets(project.constraints)]))

    if project.do_not_touch:
        blocks.append("\n".join(["DO NOT TOUCH", *bullets(project.do_not_touch)]))

    if project.sensitivity_flags:
        blocks.append("SENSITIVITY\n" + ", ".join(project.sensitivity_flags))

    if project.success_criteria:
        blocks.append("\n".join(["USER SUCCESS CRITERIA", *bullets(project.success_criteria)]))

    if project.referenced_project_ids:
        blocks.append("REFERENCED PROJECTS\n" + ", ".join(project.referenced_project_ids))

    conceive_lines: list[str] = []

    for block in context.conceive.blocks:
        conceive_lines.extend(render_block(block))

    heading = f"CONCEIVE (revision {context.conceive.revision_number})"
    blocks.append("\n".join([heading, *conceive_lines]) if conceive_lines else f"{heading}\nempty")

    if context.materials:
        material_lines: list[str] = []

        for material in context.materials:
            material_lines.extend(render_material(material, tree_entries))

        blocks.append("\n".join(["MATERIAL", *material_lines]))

    if context.answers:
        answer_lines: list[str] = []

        for answered in context.answers:
            answer_lines.append(f"round {answered.round}")
            answer_lines.append(f"  asked: {clip(answered.text, MAX_NOTE_CHARS)}")
            answer_lines.append(f"  why: {clip(answered.why_asked, MAX_NOTE_CHARS)}")
            answer_lines.append(f"  answered: {clip(answered.answer, MAX_MARKDOWN_CHARS)}")

        blocks.append("\n".join(["CLARIFICATION ANSWERS", *answer_lines]))

    if context.prior is not None:
        prior = context.prior
        prior_lines = [
            f"round: {prior.round}",
            f"summary: {clip(prior.summary, MAX_MARKDOWN_CHARS)}",
            f"interpreted goal: {clip(prior.interpreted_goal, 1000)}",
        ]

        if prior.unresolved_fields:
            prior_lines.append(f"still unresolved: {', '.join(prior.unresolved_fields)}")

        blocks.append("\n".join(["PREVIOUS BRIEF", *prior_lines]))

    return blocks


def render(context: AnalystContext, budget: int = MAX_CONTEXT_CHARS) -> str:
    rendered = "\n\n".join(sections(context, TREE_STEPS[0]))

    for tree_entries in TREE_STEPS[1:]:
        if len(rendered) <= budget:
            return rendered

        rendered = "\n\n".join(sections(context, tree_entries))

    return rendered if len(rendered) <= budget else clip(rendered, budget)
