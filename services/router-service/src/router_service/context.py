from __future__ import annotations

from dataclasses import dataclass, field

MAX_STATEMENT_CHARS = 500
MAX_DESCRIPTION_CHARS = 4000
MAX_NOTE_CHARS = 500
MAX_HISTORY_ENTRIES = 12
MAX_CONTEXT_CHARS = 24000

HISTORY_STEPS = (MAX_HISTORY_ENTRIES, 6, 3, 0)


@dataclass(frozen=True)
class Criterion:
    criterion_id: str
    statement: str
    check_kind: str
    status: str


@dataclass(frozen=True)
class TaskFacts:
    title: str
    description: str
    kind: str
    state: str


@dataclass(frozen=True)
class BriefFacts:
    interpreted_goal: str
    project_type: str
    known_constraints: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HistoryEntry:
    title: str
    state: str
    note: str | None = None


@dataclass(frozen=True)
class RouterContext:
    task: TaskFacts
    criteria: list[Criterion]
    scope_root: str
    brief: BriefFacts | None = None
    history: list[HistoryEntry] = field(default_factory=list)


def clip(value: str, limit: int) -> str:
    text = value.strip()

    if len(text) <= limit:
        return text

    return f"{text[:limit].rstrip()} [...truncated]"


def bullets(values: list[str]) -> list[str]:
    return [f"- {clip(value, MAX_NOTE_CHARS)}" for value in values if value.strip()]


def render_criterion(criterion: Criterion) -> str:
    statement = clip(criterion.statement, MAX_STATEMENT_CHARS)

    return f"- {criterion.criterion_id} [{criterion.status}/{criterion.check_kind}] {statement}"


def render_history(entry: HistoryEntry) -> str:
    line = f"- {clip(entry.title, MAX_NOTE_CHARS)} [{entry.state}]"

    if entry.note:
        return f"{line} - {clip(entry.note, MAX_NOTE_CHARS)}"

    return line


def sections(context: RouterContext, history_entries: int) -> list[str]:
    task = context.task

    facts = [
        f"title: {clip(task.title, MAX_NOTE_CHARS)}",
        f"kind: {task.kind}",
        f"state: {task.state}",
    ]

    if task.description.strip():
        facts.append(f"description: {clip(task.description, MAX_DESCRIPTION_CHARS)}")

    blocks = ["\n".join(["TASK", *facts])]

    if context.criteria:
        rendered = [render_criterion(criterion) for criterion in context.criteria]
        blocks.append("\n".join(["ACCEPTANCE CRITERIA", *rendered]))
    else:
        blocks.append("ACCEPTANCE CRITERIA\nnone recorded for this task")

    blocks.append(f"WORKING DIRECTORY\n{context.scope_root}")

    if context.brief is not None:
        brief = context.brief
        lines = [
            f"type: {brief.project_type}",
            f"goal: {clip(brief.interpreted_goal, MAX_NOTE_CHARS)}",
        ]

        if brief.known_constraints:
            lines.extend(["constraints:", *bullets(brief.known_constraints)])

        if brief.out_of_scope:
            lines.extend(["out of scope:", *bullets(brief.out_of_scope)])

        if brief.assumptions:
            lines.extend(["assumptions:", *bullets(brief.assumptions)])

        blocks.append("\n".join(["PROJECT", *lines]))

    if context.history and history_entries > 0:
        shown = context.history[:history_entries]
        rendered = [render_history(entry) for entry in shown]
        heading = f"RECENT TASKS ({len(shown)} of {len(context.history)})"
        blocks.append("\n".join([heading, *rendered]))

    return blocks


def render(context: RouterContext, budget: int = MAX_CONTEXT_CHARS) -> str:
    rendered = "\n\n".join(sections(context, HISTORY_STEPS[0]))

    for history_entries in HISTORY_STEPS[1:]:
        if len(rendered) <= budget:
            return rendered

        rendered = "\n\n".join(sections(context, history_entries))

    return rendered if len(rendered) <= budget else clip(rendered, budget)


def criterion_ids(context: RouterContext) -> list[str]:
    return [criterion.criterion_id for criterion in context.criteria]
