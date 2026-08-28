from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

MAX_GOAL_CHARS: Final[int] = 1000
MAX_SUMMARY_CHARS: Final[int] = 2000
MAX_NOTE_CHARS: Final[int] = 500
MAX_APPROACH_CHARS: Final[int] = 6000
MAX_LIST_ENTRIES: Final[int] = 10
MAX_CONTEXT_CHARS: Final[int] = 24000

LIST_STEPS: Final[tuple[int, ...]] = (MAX_LIST_ENTRIES, 5, 2, 0)

TRUNCATION_NOTE: Final[str] = "[...truncated]"


@dataclass(frozen=True)
class Capability:
    name: str
    backend: str | None
    strength: str


@dataclass(frozen=True)
class MachineFacts:
    os_version: str
    cpu_cores: int
    ram_gb: float
    free_disk_gb: float
    capabilities: list[Capability] = field(default_factory=list)


@dataclass(frozen=True)
class BriefFacts:
    interpreted_goal: str
    project_type: str
    summary: str = ""
    known_constraints: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    seeded_success_criteria: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MediatorContext:
    brief: BriefFacts
    machine: MachineFacts
    scope_root: str


def clip(value: str, limit: int) -> str:
    text = value.strip()

    if len(text) <= limit:
        return text

    return f"{text[:limit].rstrip()} {TRUNCATION_NOTE}"


def bullets(values: list[str], keep: int) -> list[str]:
    taken = [value for value in values if value.strip()][:keep]

    return [f"- {clip(value, MAX_NOTE_CHARS)}" for value in taken]


def section(heading: str, lines: list[str]) -> list[str]:
    if not lines:
        return []

    return [f"{heading}:", *lines, ""]


def render_capability(capability: Capability) -> str:
    backend = capability.backend if capability.backend else "none"

    return f"- {capability.name}: {backend} ({capability.strength})"


def render_machine(machine: MachineFacts) -> list[str]:
    lines = [
        f"- os: {machine.os_version}",
        f"- cpu cores: {machine.cpu_cores}",
        f"- ram: {machine.ram_gb:g} GB",
        f"- free disk: {machine.free_disk_gb:g} GB",
    ]
    lines.extend(render_capability(capability) for capability in machine.capabilities)

    return lines


def assemble(context: MediatorContext, keep: int, approach: str | None) -> str:
    brief = context.brief
    lines: list[str] = [
        "GOAL:",
        clip(brief.interpreted_goal, MAX_GOAL_CHARS),
        "",
        f"PROJECT TYPE: {brief.project_type}",
        f"PROJECT DIRECTORY: {context.scope_root}",
        "",
    ]

    if keep > 0 and brief.summary.strip():
        lines.extend(["SUMMARY:", clip(brief.summary, MAX_SUMMARY_CHARS), ""])

    lines.extend(section("MACHINE", render_machine(context.machine)))
    lines.extend(section("CONSTRAINTS", bullets(brief.known_constraints, keep)))
    lines.extend(section("ASSUMPTIONS", bullets(brief.assumptions, keep)))
    lines.extend(section("OUT OF SCOPE", bullets(brief.out_of_scope, keep)))
    lines.extend(
        section("SUCCESS CRITERIA THE USER ASKED FOR", bullets(brief.seeded_success_criteria, keep))
    )

    if approach is not None and approach.strip():
        lines.extend(["PROPOSED APPROACH:", clip(approach, MAX_APPROACH_CHARS), ""])

    return "\n".join(lines).strip()


def render(
    context: MediatorContext,
    budget_chars: int = MAX_CONTEXT_CHARS,
    approach: str | None = None,
) -> str:
    rendered = assemble(context, LIST_STEPS[0], approach)

    for keep in LIST_STEPS:
        rendered = assemble(context, keep, approach)

        if len(rendered) <= budget_chars:
            return rendered

    return clip(rendered, max(budget_chars - len(TRUNCATION_NOTE) - 1, 0))
