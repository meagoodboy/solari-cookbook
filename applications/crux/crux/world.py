"""How Crux talks to a world it can freeze and fork."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from .models import RawRun

Oracle = Callable[[dict[str, Any]], tuple[bool, str]]
"""Scores a trial artifact: returns (passed, one-line detail)."""


class World(Protocol):
    """A backend that can freeze state once and rerun trials from it.

    Implementations decide what a snapshot ref means. run_trial must be
    deterministic for a given (snapshot, assignment, seed) wherever the
    backend can honour that; the local backend always can.
    """

    def snapshot(self) -> str: ...

    def run_trial(
        self, snapshot: str, assignment: dict[str, bool], seed: int
    ) -> RawRun: ...

    def close(self) -> None: ...
