"""Zero-config investigation of a flaky Python test command.

`crux flaky -- python -m pytest tests/test_x.py::test_y` is the whole
interface. It ships a built-in suspect lineup, the same five that
convicted the Home Assistant bootstrap bug: hash randomization,
timezone, locale, bytecode caching, and the allocator. No FactorSpec
writing, no scenario file.

The lineup is deliberately one-sided: every factor's active mapping is
empty except hash randomization, so the baseline runs the command in
the user's real environment (plus a per-trial PYTHONHASHSEED, which is
what the OS does anyway, made replayable). Only neutralizing a factor
changes anything.

Three phases:
1. Pin probe: find a fixed PYTHONHASHSEED the command passes with,
   three trials per candidate so one lucky pass cannot pick a bad pin.
2. Baseline probe: run the command a few times as-is. Never fails
   means nothing to investigate. Always fails with no passing pin
   means the command is plain broken, not flaky; both stop early
   instead of burning an investigation.
3. The investigation itself, through CommandWorld with the standard
   sequential procedure, bundle written like any other.

Probe trials use their own seed namespaces and are not counted inside
the investigation, so the reported statistics stay clean.
"""

from __future__ import annotations

import hashlib
import shlex
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass

from .backends.command import CommandWorld, FactorSpec, command_oracle
from .models import Factor, Investigation, InvestigationConfig
from .stats import trial_seed

HASH_PIN_CANDIDATES = ("1", "0", "2", "3", "4")
PIN_TRIALS = 3

FLAKY_FACTORS = (
    Factor("hash_randomization", "per-process string hash randomization"),
    Factor("timezone", "the host timezone"),
    Factor("locale", "the host locale"),
    Factor("bytecode_cache", "reuse of cached pyc bytecode"),
    Factor("malloc_allocator", "the default pymalloc allocator"),
)


@dataclass(frozen=True)
class ProbeReport:
    """What the two probe phases observed before the investigation."""

    hash_pin: str
    hash_pin_passed: bool
    baseline_failures: int
    baseline_runs: int

    @property
    def always_failed(self) -> bool:
        return self.baseline_runs > 0 and self.baseline_failures == self.baseline_runs


def build_flaky_specs(hash_pin: str) -> list[FactorSpec]:
    """The built-in lineup. Active mappings stay empty on purpose.

    An empty active mapping means the baseline is the user's own
    environment, untouched. Neutralizing pins the suspect: a fixed hash
    seed, UTC, the C locale, a fresh per-trial pyc cache prefix (which
    disables reuse of stale bytecode, not just writing new files), or
    the plain malloc allocator.
    """
    pyc_prefix = tempfile.gettempdir() + "/crux-pyc-{seed}"
    return [
        FactorSpec(
            "hash_randomization",
            active={"PYTHONHASHSEED": "{seed32}"},
            neutral={"PYTHONHASHSEED": hash_pin},
        ),
        FactorSpec("timezone", active={}, neutral={"TZ": "UTC"}),
        FactorSpec(
            "locale",
            active={},
            neutral={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        ),
        FactorSpec(
            "bytecode_cache",
            active={},
            neutral={"PYTHONPYCACHEPREFIX": pyc_prefix},
        ),
        FactorSpec(
            "malloc_allocator", active={}, neutral={"PYTHONMALLOC": "malloc"}
        ),
    ]


def parse_command(raw: Sequence[str]) -> list[str]:
    """Accept both `-- cmd arg arg` and one quoted string.

    Only the single leading separator is stripped, so a command that
    uses its own `--` (npm test -- --grep foo) survives intact. The
    quoted-string form is shlex-split; for an executable path with a
    space in it, use the `--` form, which is never re-split.
    """
    parts = list(raw)
    explicit = bool(parts) and parts[0] == "--"
    if explicit:
        parts = parts[1:]
    if not parts:
        raise ValueError("no command given")
    if not explicit and len(parts) == 1 and " " in parts[0]:
        return shlex.split(parts[0])
    return parts


def command_scenario_name(cmd: Sequence[str]) -> str:
    """A stable id fragment per command, so bundles do not clobber."""
    digest = hashlib.sha256(" ".join(cmd).encode()).hexdigest()[:8]
    return f"flaky-{digest}"


def choose_hash_pin(
    cmd: Sequence[str],
    cwd: str,
    timeout_s: float,
    master_seed: int,
    candidates: Sequence[str] = HASH_PIN_CANDIDATES,
    pin_trials: int = PIN_TRIALS,
) -> tuple[str, bool]:
    """Find a fixed hash seed the command passes with, repeatedly.

    A candidate must pass pin_trials times in a row; a single lucky
    pass under a still-stochastic seed would otherwise pin the neutral
    branch to a seed that actually fails, and a genuine hash flake
    would walk. When every candidate fails, the first is returned with
    passed=False and the caller decides what that means.
    """
    for cand_index, candidate in enumerate(candidates):
        pin_specs = [
            FactorSpec(
                "hash_randomization",
                active={"PYTHONHASHSEED": candidate},
                neutral={"PYTHONHASHSEED": candidate},
            )
        ]
        pin_world = CommandWorld(
            cmd=cmd, cwd=cwd, specs=pin_specs, timeout_s=timeout_s
        )
        assignment = {factor.id: True for factor in FLAKY_FACTORS}
        all_passed = True
        for trial_index in range(pin_trials):
            seed = trial_seed(
                master_seed, f"probe:hash-pin:{cand_index}", trial_index
            )
            raw = pin_world.run_trial(pin_world.snapshot(), assignment, seed)
            passed, _ = command_oracle(raw.artifact)
            if not passed:
                all_passed = False
                break
        if all_passed:
            return candidate, True
    return candidates[0], False


def probe_baseline(
    world: CommandWorld, master_seed: int, runs: int
) -> tuple[int, int]:
    """Run the command in the investigation's baseline world a few times."""
    assignment = {factor.id: True for factor in FLAKY_FACTORS}
    failures = 0
    for index in range(runs):
        seed = trial_seed(master_seed, "probe:baseline", index)
        raw = world.run_trial(world.snapshot(), assignment, seed)
        passed, _ = command_oracle(raw.artifact)
        failures += int(not passed)
    return failures, runs


def run_flaky(
    cmd: Sequence[str],
    cwd: str,
    config: InvestigationConfig,
    timeout_s: float = 120.0,
    probe_runs: int = 8,
    parallel: int = 1,
) -> tuple[Investigation | None, ProbeReport]:
    """Probe, then investigate.

    Returns (None, report) when there is nothing to investigate: the
    command never failed in the probe, or it failed every probe run
    with no passing hash pin either, which is a broken command rather
    than a flaky one. report.always_failed separates the two.
    """
    from .search import investigate

    pin, pin_passed = choose_hash_pin(cmd, cwd, timeout_s, config.seed)
    specs = build_flaky_specs(pin)
    world = CommandWorld(
        cmd=cmd, cwd=cwd, specs=specs, timeout_s=timeout_s, concurrency=parallel
    )
    failures, runs = probe_baseline(world, config.seed, probe_runs)
    report = ProbeReport(
        hash_pin=pin,
        hash_pin_passed=pin_passed,
        baseline_failures=failures,
        baseline_runs=runs,
    )
    if failures == 0:
        return None, report
    if report.always_failed and not pin_passed:
        return None, report

    investigation = investigate(
        world, command_oracle, FLAKY_FACTORS, config,
        scenario_name=command_scenario_name(cmd),
    )
    return investigation, report
