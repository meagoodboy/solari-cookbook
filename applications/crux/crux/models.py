"""Data types shared across Crux.

Plain data only: no I/O, no randomness, no statistics. The investigation
loop in search.py owns the logic and the backends own the side effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Factor:
    """One suspect the investigation can neutralize.

    A factor names a condition that was present in the observed failing
    run. The baseline keeps every factor active; a branch turns some off
    and reruns from the same snapshot.
    """

    id: str
    description: str


@dataclass(frozen=True)
class RawRun:
    """What a backend returns for a single trial, before scoring."""

    artifact: dict[str, Any]
    transcript: tuple[str, ...]
    duration_ms: int


@dataclass(frozen=True)
class TrialResult:
    branch_id: str
    seed: int
    passed: bool
    detail: str
    artifact: dict[str, Any]
    duration_ms: int


@dataclass
class BranchState:
    """Running tally for one branch. neutralized is () for the baseline."""

    branch_id: str
    neutralized: tuple[str, ...]
    trials: int = 0
    successes: int = 0
    p_value: float | None = None
    dropped_for_futility: bool = False
    confirmation_failed: bool = False

    @property
    def rate(self) -> float:
        return self.successes / self.trials if self.trials else 0.0


@dataclass(frozen=True)
class Verdict:
    cause: tuple[str, ...] | None
    confirmation_p: float | None
    baseline_rate: float
    cause_rate: float | None
    alpha: float
    trials_total: int
    rounds: int
    summary: str


@dataclass(frozen=True)
class InvestigationConfig:
    alpha: float = 0.05
    max_trials: int = 240
    max_rounds: int = 6
    round_trials_per_branch: int = 8
    confirm_trials: int = 24
    futility_min_trials: int = 16
    pairwise_top_k: int = 3
    seed: int = 7


@dataclass
class Investigation:
    investigation_id: str
    scenario: str
    factors: tuple[Factor, ...]
    config: InvestigationConfig
    branches: dict[str, BranchState] = field(default_factory=dict)
    trials: list[TrialResult] = field(default_factory=list)
    round_log: list[dict[str, Any]] = field(default_factory=list)
    verdict: Verdict | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "investigation_id": self.investigation_id,
            "scenario": self.scenario,
            "factors": [asdict(f) for f in self.factors],
            "config": asdict(self.config),
            "branches": {
                key: {
                    **asdict(state),
                    "neutralized": list(state.neutralized),
                    "rate": state.rate,
                }
                for key, state in self.branches.items()
            },
            "round_log": self.round_log,
            "verdict": asdict(self.verdict) if self.verdict else None,
            "trials": [asdict(t) for t in self.trials],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Investigation":
        branches = {}
        for key, raw in data["branches"].items():
            branches[key] = BranchState(
                branch_id=raw["branch_id"],
                neutralized=tuple(raw["neutralized"]),
                trials=raw["trials"],
                successes=raw["successes"],
                p_value=raw.get("p_value"),
                dropped_for_futility=raw.get("dropped_for_futility", False),
                confirmation_failed=raw.get("confirmation_failed", False),
            )
        verdict = None
        raw_verdict = data.get("verdict")
        if raw_verdict is not None:
            # A missing or null verdict means the run recorded no verdict.
            # Anything else present must be a real verdict object; an empty
            # or mistyped value marks a damaged bundle, not an undecided run.
            if not isinstance(raw_verdict, dict) or not raw_verdict:
                raise ValueError(
                    "verdict is present but is not a verdict object; "
                    "the bundle looks damaged"
                )
            raw = dict(raw_verdict)
            raw["cause"] = tuple(raw["cause"]) if raw["cause"] is not None else None
            verdict = Verdict(**raw)
        return cls(
            investigation_id=data["investigation_id"],
            scenario=data.get("scenario", ""),
            factors=tuple(Factor(**f) for f in data["factors"]),
            config=InvestigationConfig(**data["config"]),
            branches=branches,
            trials=[TrialResult(**t) for t in data.get("trials", [])],
            round_log=data.get("round_log", []),
            verdict=verdict,
        )
