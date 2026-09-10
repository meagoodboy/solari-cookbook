"""Investigate a COLUMNS-sensitive test failure in Textualize/rich with Crux.

This is a previously unreported finding, observed 2026-09-11 at rich HEAD
(9d8f9a372cc5916fd4781fec207ced7ddac2f08f). Exporting COLUMNS in the
shell makes seven test nodes fail every time, because ConsoleDimensions
resolution in rich/console.py reads COLUMNS and LINES from the
environment before it reaches the mocked terminal-size fallback the
tests patch, and the tests never scrub those variables. The two fastest
of the seven are used here: hand runs at this commit fail 6/6 with
COLUMNS=200 LINES=50 exported and pass 6/6 without.

This script does not ship rich. Point it at a checkout with a venv that
has pytest and the repo's test requirements installed:

  python examples/rich_columns_env.py \
      --repo-dir /path/to/rich --python /path/to/venv/bin/python

Four suspects go in and the script does not tell Crux which one is
guilty. The twist this case adds: the guilty factor is a constant (the
same COLUMNS value every trial), while one decoy varies per trial
(PYTHONHASHSEED through {seed32}). An engineer staring at flaky-looking
CI would reach for the thing that changes between runs; Crux has to
release the mover and convict the constant. Timezone and locale round
out the lineup.

Because the active branch of the guilty factor adds COLUMNS and LINES
on top of the inherited environment, the parent shell must not export
either one already; there is no way to unset an inherited variable per
trial, so the script refuses to run if it finds them.

Add --compare to also run the naive gap read (5 trials per arm, blame
the biggest gap) on the same world, for a head-to-head.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from crux.backends.command import CommandWorld, FactorSpec, command_oracle
from crux.models import Factor, InvestigationConfig
from crux.report import write_bundle
from crux.search import investigate
from crux.stats import trial_seed

TEST_NODES = (
    "tests/test_console.py::test_size_can_fall_back_to_std_descriptors",
    "tests/test_ansi.py::test_decode_example",
)
PINNED_COMMIT = "9d8f9a372cc5916fd4781fec207ced7ddac2f08f"

FACTORS = (
    Factor("columns_exported", "COLUMNS and LINES exported in the shell"),
    Factor("hash_randomization", "per-process string hash randomization"),
    Factor("timezone", "host timezone applied through TZ"),
    Factor("locale", "UTF-8 host locale"),
)


def build_specs() -> list[FactorSpec]:
    return [
        FactorSpec(
            "columns_exported",
            active={"COLUMNS": "200", "LINES": "50"},
            neutral={},
        ),
        FactorSpec(
            "hash_randomization",
            active={"PYTHONHASHSEED": "{seed32}"},
            neutral={"PYTHONHASHSEED": "1"},
        ),
        FactorSpec(
            "timezone",
            active={"TZ": "Asia/Kolkata"},
            neutral={"TZ": "UTC"},
        ),
        FactorSpec(
            "locale",
            active={"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
            neutral={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        ),
    ]


def run_naive_gap(world: CommandWorld, master_seed: int) -> dict:
    """The eyeball baseline: 5 trials per arm, blame the biggest gap."""
    arms: dict[str, dict[str, bool]] = {
        "baseline": {f.id: True for f in FACTORS}
    }
    for factor in FACTORS:
        assignment = {f.id: True for f in FACTORS}
        assignment[factor.id] = False
        arms[f"no-{factor.id}"] = assignment
    rates: dict[str, float] = {}
    for arm, assignment in arms.items():
        passes = 0
        for index in range(5):
            seed = trial_seed(master_seed, f"naive:{arm}", index)
            raw = world.run_trial(world.snapshot(), assignment, seed)
            passed, _ = command_oracle(raw.artifact)
            passes += int(passed)
        rates[arm] = passes / 5
    gaps = {
        arm: rate - rates["baseline"]
        for arm, rate in rates.items()
        if arm != "baseline"
    }
    best_arm = max(sorted(gaps), key=lambda arm: gaps[arm])
    conviction = best_arm if gaps[best_arm] > 0 else None
    return {"rates": rates, "gaps": gaps, "conviction": conviction}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-dir", required=True, help="rich checkout")
    parser.add_argument(
        "--python", required=True, help="venv python with rich test deps"
    )
    parser.add_argument(
        "--out", default="proof/realworld-rich-columns", help="bundle directory"
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--compare", action="store_true", help="also run the naive gap read"
    )
    args = parser.parse_args(argv)

    for name in ("COLUMNS", "LINES"):
        if name in os.environ:
            print(
                f"{name} is exported in this shell. The neutral branch of "
                "columns_exported works by inheriting an environment without "
                "it; an inherited variable cannot be unset per trial. "
                f"Unset {name} and rerun."
            )
            return 2

    repo_dir = Path(args.repo_dir).expanduser().resolve()
    if not (repo_dir / "tests" / "test_console.py").exists():
        print(f"{repo_dir} does not look like a rich checkout")
        return 2

    cmd = [args.python, "-m", "pytest", *TEST_NODES, "-q", "-p", "no:cacheprovider"]
    world = CommandWorld(
        cmd=cmd, cwd=str(repo_dir), specs=build_specs(), timeout_s=120.0
    )
    config = InvestigationConfig(seed=args.seed)
    print("Investigating rich console-size tests under an exported COLUMNS")
    print(f"Checkout expected at commit {PINNED_COMMIT}")
    print(f"Budget: {config.max_trials} trials, each a fresh pytest process")
    started = time.monotonic()
    investigation = investigate(
        world, command_oracle, FACTORS, config,
        scenario_name="rich-columns-env",
    )
    elapsed = time.monotonic() - started
    print(f"\n{investigation.verdict.summary}")
    print(f"Elapsed: {elapsed:.0f}s over {investigation.verdict.trials_total} trials")
    out_dir = Path(args.out)
    write_bundle(investigation, out_dir, world_spec=world.to_spec())
    print(f"Bundle written to {out_dir}")

    if args.compare:
        print("\nNaive gap read on the same world (5 trials per arm):")
        naive = run_naive_gap(world, args.seed)
        for arm, rate in sorted(naive["rates"].items()):
            print(f"  {arm}: {rate:.0%} pass")
        print(f"  naive conviction: {naive['conviction']}")
        (out_dir / "naive.json").write_text(
            json.dumps(naive, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
