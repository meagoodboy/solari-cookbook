"""Run a shell command as a World.

CommandWorld points Crux at a real repository: a flaky test suite, a
build that only breaks sometimes, anything you can phrase as a command
whose behaviour shifts with environment variables. Each factor maps to
two sets of env overrides, one applied while the factor is active and
one applied when a branch neutralizes it. Override values may embed
"{seed}", which is replaced with the per-trial seed, so an active
randomness factor varies from trial to trial yet replays exactly.

There is no shell involved. The command is executed directly with
subprocess.run, a timeout counts as a plain failure rather than an
exception, and nothing written into the child environment ever touches
the parent process.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..models import RawRun

OUTPUT_TAIL_CHARS = 2000


@dataclass(frozen=True)
class FactorSpec:
    """Env overrides for one factor, in both switch positions.

    active is applied when the assignment keeps the factor on, neutral
    when a branch turns it off. Values may contain "{seed}"; the world
    substitutes the per-trial seed before running the command. Use
    "{seed32}" instead where the consumer only accepts 32-bit values,
    the way PYTHONHASHSEED does; it substitutes seed modulo 2**32.
    """

    factor_id: str
    active: Mapping[str, str]
    neutral: Mapping[str, str]


def resolve_overrides(
    specs: Sequence[FactorSpec], assignment: Mapping[str, bool], seed: int
) -> dict[str, str]:
    """Turn an assignment into concrete env overrides for one trial.

    Shared by every backend that expresses factors as environment
    changes, so the local subprocess world and the Solari clone world
    resolve a branch identically.
    """
    overrides: dict[str, str] = {}
    for spec in specs:
        mapping = (
            spec.active if assignment.get(spec.factor_id, True) else spec.neutral
        )
        for key, value in mapping.items():
            resolved = value.replace("{seed32}", str(seed % 2**32))
            overrides[key] = resolved.replace("{seed}", str(seed))
    return overrides


class CommandWorld:
    """World over one command run per trial.

    The snapshot ref is the working directory: the command is expected
    to leave the checkout as it found it, and replays rely on that plus
    the seed. The base environment is a copy of os.environ unless
    env_base is given, in which case only env_base plus the factor
    overrides reach the child.
    """

    def __init__(
        self,
        cmd: Sequence[str],
        cwd: str,
        specs: Sequence[FactorSpec],
        timeout_s: float = 120.0,
        env_base: Mapping[str, str] | None = None,
        concurrency: int = 1,
    ) -> None:
        self._cmd = tuple(cmd)
        self._cwd = cwd
        self._specs = tuple(specs)
        self._timeout_s = timeout_s
        self._env_base = None if env_base is None else dict(env_base)
        self._concurrency = max(1, int(concurrency))

    def snapshot(self) -> str:
        return self._cwd

    def run_trials(
        self, snapshot: str, jobs: Sequence[tuple[dict[str, bool], int]]
    ) -> list[RawRun]:
        """Run a batch of trials, up to `concurrency` processes at once.

        Order of results always matches job order; seeds fully determine
        each trial, so the parallel path changes wall-clock time only.
        """
        if self._concurrency <= 1 or len(jobs) <= 1:
            return [
                self.run_trial(snapshot, assignment, seed)
                for assignment, seed in jobs
            ]
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            return list(
                pool.map(
                    lambda job: self.run_trial(snapshot, job[0], job[1]), jobs
                )
            )

    def run_trial(
        self, snapshot: str, assignment: dict[str, bool], seed: int
    ) -> RawRun:
        overrides = resolve_overrides(self._specs, assignment, seed)

        env = dict(os.environ) if self._env_base is None else dict(self._env_base)
        env.update(overrides)

        start = time.monotonic()
        timed_out = False
        try:
            completed = subprocess.run(
                list(self._cmd),
                cwd=self._cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
            exit_code = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = _as_text(exc.stdout)
            stderr = _as_text(exc.stderr)
        duration_ms = int((time.monotonic() - start) * 1000)

        merged = stdout + stderr
        artifact: dict[str, Any] = {
            "exit_code": exit_code,
            "timed_out": timed_out,
            "seed": seed,
            "env_overrides": dict(overrides),
            "output_tail": merged[-OUTPUT_TAIL_CHARS:],
        }
        if timed_out:
            exit_line = f"timed out after {self._timeout_s}s"
        else:
            exit_line = f"exit {exit_code}"
        transcript = tuple(
            f"env {key}={value}" for key, value in overrides.items()
        ) + (exit_line,)
        return RawRun(
            artifact=artifact,
            transcript=transcript,
            duration_ms=duration_ms,
        )

    def close(self) -> None:
        return None


def command_oracle(artifact: dict[str, Any]) -> tuple[bool, str]:
    """Pass iff the command exited 0 and did not time out."""
    if artifact["timed_out"]:
        return False, "timed out"
    exit_code = artifact["exit_code"]
    if exit_code == 0:
        return True, "exit 0"
    return False, f"exit {exit_code}"


def _as_text(captured: str | bytes | None) -> str:
    """Normalize output captured by TimeoutExpired, which may be bytes."""
    if captured is None:
        return ""
    if isinstance(captured, bytes):
        return captured.decode("utf-8", errors="replace")
    return captured
