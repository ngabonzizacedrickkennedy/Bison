from __future__ import annotations

from dataclasses import dataclass
from typing import Final

HALT_REASONS: Final[frozenset[str]] = frozenset(
    {"kill_switch", "step_failure", "project_switch", "user_stop"}
)

STEP_STATES: Final[frozenset[str]] = frozenset(
    {
        "pending",
        "awaiting_confirmation",
        "running",
        "succeeded",
        "failed",
        "aborted",
        "never_attempted",
    }
)

COMPLETED_STATE: Final[str] = "succeeded"
IN_FLIGHT_STATE: Final[str] = "running"
SETTLED_IN_FLIGHT_STATE: Final[str] = "aborted"
NEVER_ATTEMPTED_STATE: Final[str] = "never_attempted"

UNATTEMPTED_STATES: Final[frozenset[str]] = frozenset({"pending", "awaiting_confirmation"})
EXCLUDED_CRITERION_STATUSES: Final[frozenset[str]] = frozenset({"ignored"})

DESCRIPTION_EXCERPT: Final[int] = 120


class UnknownHaltReasonError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"unknown halt reason {reason}; expected one of {sorted(HALT_REASONS)}")
        self.reason = reason


class UnknownStepStateError(RuntimeError):
    def __init__(self, step_id: str, state: str) -> None:
        super().__init__(f"step {step_id} reported unknown state {state}")
        self.step_id = step_id
        self.state = state


class UnplannedStepError(RuntimeError):
    def __init__(self, missing: list[str]) -> None:
        super().__init__(f"outcomes reference steps not in this plan: {', '.join(missing)}")
        self.missing = missing


@dataclass(frozen=True)
class PlannedStep:
    step_id: str
    position: int
    description: str


@dataclass(frozen=True)
class RecordedOutcome:
    step_id: str
    state: str
    touched_paths: list[str]
    exit_code: int | None
    error_message: str | None
    started_at: str | None
    ended_at: str | None


@dataclass(frozen=True)
class CriterionState:
    id: str
    status: str


@dataclass(frozen=True)
class StepOutcome:
    step_id: str
    position: int
    description: str
    state: str
    touched_paths: list[str]
    exit_code: int | None
    error_message: str | None
    started_at: str | None
    ended_at: str | None


@dataclass(frozen=True)
class Reconciliation:
    request_id: str
    task_id: str
    halt_reason: str
    steps_total: int
    steps_completed: int
    steps_never_attempted: int
    step_outcomes: list[StepOutcome]
    criteria_verified_ids: list[str]
    criteria_unverified_ids: list[str]
    touched_paths: list[str]
    plain_summary: str


def assert_halt_reason(reason: str) -> None:
    if reason not in HALT_REASONS:
        raise UnknownHaltReasonError(reason)


def _settled_state(state: str) -> str:
    if state in UNATTEMPTED_STATES:
        return NEVER_ATTEMPTED_STATE

    if state == IN_FLIGHT_STATE:
        return SETTLED_IN_FLIGHT_STATE

    return state


def settle(steps: list[PlannedStep], outcomes: list[RecordedOutcome]) -> list[StepOutcome]:
    planned = {step.step_id: step for step in steps}
    missing = [o.step_id for o in outcomes if o.step_id not in planned]

    if missing:
        raise UnplannedStepError(list(dict.fromkeys(missing)))

    for outcome in outcomes:
        if outcome.state not in STEP_STATES:
            raise UnknownStepStateError(outcome.step_id, outcome.state)

    latest = {outcome.step_id: outcome for outcome in outcomes}
    settled: list[StepOutcome] = []

    for step in sorted(steps, key=lambda s: s.position):
        recorded = latest.get(step.step_id)

        if recorded is None:
            settled.append(
                StepOutcome(
                    step_id=step.step_id,
                    position=step.position,
                    description=step.description,
                    state=NEVER_ATTEMPTED_STATE,
                    touched_paths=[],
                    exit_code=None,
                    error_message=None,
                    started_at=None,
                    ended_at=None,
                )
            )
            continue

        settled.append(
            StepOutcome(
                step_id=step.step_id,
                position=step.position,
                description=step.description,
                state=_settled_state(recorded.state),
                touched_paths=list(recorded.touched_paths),
                exit_code=recorded.exit_code,
                error_message=recorded.error_message,
                started_at=recorded.started_at,
                ended_at=recorded.ended_at,
            )
        )

    return settled


def partition(criteria: list[CriterionState]) -> tuple[list[str], list[str]]:
    verified: list[str] = []
    unverified: list[str] = []

    for criterion in criteria:
        if criterion.status in EXCLUDED_CRITERION_STATUSES:
            continue

        if criterion.status == "verified":
            verified.append(criterion.id)
            continue

        unverified.append(criterion.id)

    return verified, unverified


def touched(outcomes: list[StepOutcome]) -> list[str]:
    seen: dict[str, None] = {}

    for outcome in outcomes:
        for path in outcome.touched_paths:
            seen.setdefault(path, None)

    return list(seen)


def _count(quantity: int, noun: str) -> str:
    return f"{quantity} {noun}" if quantity == 1 else f"{quantity} {noun}s"


def _percent(value: float) -> str:
    rounded = round(value, 1)

    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.1f}"


def _excerpt(text: str) -> str:
    if len(text) <= DESCRIPTION_EXCERPT:
        return text

    return text[: DESCRIPTION_EXCERPT - 3].rstrip() + "..."


def summarise(
    halt_reason: str,
    outcomes: list[StepOutcome],
    paths: list[str],
    percentage: float,
) -> str:
    total = len(outcomes)
    completed = sum(1 for o in outcomes if o.state == COMPLETED_STATE)
    aborted = sum(1 for o in outcomes if o.state == SETTLED_IN_FLIGHT_STATE)
    never = sum(1 for o in outcomes if o.state == NEVER_ATTEMPTED_STATE)
    failed = [o for o in outcomes if o.state == "failed"]

    sentences = [f"{completed} of {_count(total, 'step')} completed."]

    if failed:
        first = failed[0]
        sentences.append(f"Step {first.position + 1} failed: {_excerpt(first.description)}.")

    if aborted:
        sentences.append(f"{_count(aborted, 'step')} stopped in flight.")

    if never:
        sentences.append(f"{_count(never, 'step')} never attempted.")

    if paths:
        sentences.append(f"{_count(len(paths), 'file')} touched.")
    else:
        sentences.append("No files were touched.")

    sentences.append(f"Task is {_percent(percentage)}% verified.")
    sentences.append(f"Halted by {halt_reason.replace('_', ' ')}.")

    return " ".join(sentences)


def reconcile(
    request_id: str,
    task_id: str,
    halt_reason: str,
    steps: list[PlannedStep],
    outcomes: list[RecordedOutcome],
    criteria: list[CriterionState],
    percentage: float,
) -> Reconciliation:
    assert_halt_reason(halt_reason)

    settled = settle(steps, outcomes)
    verified, unverified = partition(criteria)
    paths = touched(settled)

    return Reconciliation(
        request_id=request_id,
        task_id=task_id,
        halt_reason=halt_reason,
        steps_total=len(settled),
        steps_completed=sum(1 for o in settled if o.state == COMPLETED_STATE),
        steps_never_attempted=sum(1 for o in settled if o.state == NEVER_ATTEMPTED_STATE),
        step_outcomes=settled,
        criteria_verified_ids=verified,
        criteria_unverified_ids=unverified,
        touched_paths=paths,
        plain_summary=summarise(halt_reason, settled, paths, percentage),
    )
