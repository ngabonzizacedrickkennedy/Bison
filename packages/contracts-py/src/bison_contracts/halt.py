from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HaltReason = Literal["kill_switch", "step_failure", "project_switch", "user_stop"]

Boundary = Literal["immediate", "between_actions", "between_tasks"]

BOUNDARY_MEANING: dict[Boundary, str] = {
    "immediate": "the process tree is killed without waiting",
    "between_actions": "the action in flight completes, then nothing further starts",
    "between_tasks": "the task in flight completes, then nothing further starts",
}


class HaltSignal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    reason: HaltReason
    request_id: str | None = None
    project_id: str | None = None
    task_id: str | None = None
    issued_at: datetime


class HaltAcknowledgement(BaseModel):
    service: str
    boundary: Boundary
    boundary_meaning: str
    halted: bool
    signal_id: str
    reason: HaltReason
    accepted_at: datetime
    signals_received: int
    already_halted: bool


class HaltStatus(BaseModel):
    service: str
    boundary: Boundary
    boundary_meaning: str
    halted: bool
    signal: HaltSignal | None
    signals_received: int
    halted_at: datetime | None
    resumed_at: datetime | None
    resumed_by: str | None


class HaltedError(RuntimeError):
    def __init__(self, service: str, signal: HaltSignal) -> None:
        super().__init__(f"{service} is halted by {signal.reason} and accepts no new work")
        self.service = service
        self.signal = signal


class HaltState:
    def __init__(self, service: str, boundary: Boundary) -> None:
        self._service = service
        self._boundary = boundary
        self._signals: list[HaltSignal] = []
        self._halted = False
        self._halted_at: datetime | None = None
        self._resumed_at: datetime | None = None
        self._resumed_by: str | None = None

    @property
    def service(self) -> str:
        return self._service

    @property
    def boundary(self) -> Boundary:
        return self._boundary

    @property
    def halted(self) -> bool:
        return self._halted

    @property
    def signal(self) -> HaltSignal | None:
        return self._signals[-1] if self._signals else None

    def accept(self, signal: HaltSignal) -> HaltAcknowledgement:
        already = self._halted
        now = datetime.now(UTC)

        self._signals.append(signal)
        self._halted = True

        if not already:
            self._halted_at = now
            self._resumed_at = None
            self._resumed_by = None

        return HaltAcknowledgement(
            service=self._service,
            boundary=self._boundary,
            boundary_meaning=BOUNDARY_MEANING[self._boundary],
            halted=True,
            signal_id=signal.id,
            reason=signal.reason,
            accepted_at=now,
            signals_received=len(self._signals),
            already_halted=already,
        )

    def resume(self, actor: str) -> HaltStatus:
        self._halted = False
        self._resumed_at = datetime.now(UTC)
        self._resumed_by = actor

        return self.status()

    def guard(self) -> None:
        if self._halted:
            signal = self._signals[-1]
            raise HaltedError(self._service, signal)

    def status(self) -> HaltStatus:
        return HaltStatus(
            service=self._service,
            boundary=self._boundary,
            boundary_meaning=BOUNDARY_MEANING[self._boundary],
            halted=self._halted,
            signal=self.signal,
            signals_received=len(self._signals),
            halted_at=self._halted_at,
            resumed_at=self._resumed_at,
            resumed_by=self._resumed_by,
        )
