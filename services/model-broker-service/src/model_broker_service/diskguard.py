from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiskVerdict:
    allowed: bool
    budget_gb: float
    used_gb: float
    incoming_gb: float
    reason: str | None


class DiskBudgetExceededError(RuntimeError):
    def __init__(self, verdict: DiskVerdict) -> None:
        super().__init__(verdict.reason or "local model disk budget exceeded")
        self.verdict = verdict


def evaluate(
    budget_gb: float,
    installed_sizes_gb: list[float],
    incoming_gb: float | None,
) -> DiskVerdict:
    used_gb = round(sum(installed_sizes_gb), 2)

    if incoming_gb is None:
        return DiskVerdict(
            allowed=False,
            budget_gb=budget_gb,
            used_gb=used_gb,
            incoming_gb=0.0,
            reason="model size is unknown; refusing a pull that cannot be budgeted",
        )

    projected = round(used_gb + incoming_gb, 2)

    if projected > budget_gb:
        return DiskVerdict(
            allowed=False,
            budget_gb=budget_gb,
            used_gb=used_gb,
            incoming_gb=incoming_gb,
            reason=(
                f"pull would bring local models to {projected} GB, "
                f"exceeding the {budget_gb} GB budget"
            ),
        )

    return DiskVerdict(
        allowed=True,
        budget_gb=budget_gb,
        used_gb=used_gb,
        incoming_gb=incoming_gb,
        reason=None,
    )
