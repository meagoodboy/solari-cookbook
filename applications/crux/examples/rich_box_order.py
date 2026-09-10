"""Investigate an order-dependent test failure in Textualize/rich with Crux.

The target is a two-test pair at rich HEAD, commit
9d8f9a372cc5916fd4781fec207ced7ddac2f08f (checked 2026-09-11, no report
of it in the rich issue tracker at that date).
tests/test_table.py::test_placement_table_box_elements builds a Table
with the shared module-level singleton rich.box.ASCII, then rewrites
that singleton in place via table.box.__dict__.update at
tests/test_table.py line 315 and never restores it. Every test that
renders with box.ASCII afterwards sees letters where box-drawing
characters should be: tests/test_box.py::test_get_row expects
'|-+--+---|' and gets 'ijkjjkjjjl'. The repo's natural order runs
test_box.py before test_table.py, which is the only reason the suite
stays green. pytest-randomly puts the polluter first on roughly half
its seeds and the pair fails.

Hand-measured rates on the pinned checkout before wiring up Crux:
victim-first with the plugin disabled passed 5 of 5 collected items,
polluter-first failed deterministically, and randomly-seeds 1..12
failed 7 of 12 runs.

This script does not ship rich. Point it at a checkout with a venv
holding pytest and pytest-randomly:

  python examples/rich_box_order.py \
      --repo-dir /path/to/rich --python /path/to/venv/bin/python

Five suspects go in and the script does not tell Crux which one is
guilty. Test order varies per trial through a pytest-randomly seed
while the neutral branch disables the plugin, restoring the natural
victim-then-polluter order. The other four are decoys an engineer
might reasonably blame first: hash randomization, timezone, locale,
and the allocator.

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

# Victim listed first: pytest keeps command-line arg order, and the
# natural suite order (test_box.py before test_table.py) is what keeps
# this pair green when shuffling is off.
VICTIM_NODE = "tests/test_box.py::test_get_row"
POLLUTER_NODE = "tests/test_table.py::test_placement_table_box_elements"
PINNED_COMMIT = "9d8f9a372cc5916fd4781fec207ced7ddac2f08f"

FACTORS = (
    Factor("test_order_shuffle", "pytest-randomly shuffles test order per run"),
    Factor("hash_randomization", "per-process string hash randomization"),
    Factor("timezone", "host timezone applied through TZ"),
    Factor("locale", "UTF-8 host locale"),
    Factor("malloc_allocator", "default pymalloc allocator"),
)


def build_specs() -> list[FactorSpec]:
    return [
        FactorSpec(
            "test_order_shuffle",
            active={"PYTEST_ADDOPTS": "--randomly-seed={seed32}"},
            neutral={"PYTEST_ADDOPTS": "-p no:randomly"},
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
        FactorSpec(
            "malloc_allocator",
            active={},
            neutral={"PYTHONMALLOC": "malloc"},
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
        "--python", required=True,
        help="venv python with pytest and pytest-randomly",
    )
    parser.add_argument(
        "--out", default="proof/realworld-rich-order", help="bundle directory"
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--compare", action="store_true", help="also run the naive gap read"
    )
    args = parser.parse_args(argv)

    repo_dir = Path(args.repo_dir).expanduser().resolve()
    if not (repo_dir / "tests" / "test_table.py").exists():
        print(f"{repo_dir} does not look like a rich checkout")
        return 2

    # The malloc factor's active state is the absence of PYTHONMALLOC.
    # A child process cannot unset a variable it inherits, so the
    # parent must not export it or the active branch would be wrong.
    if "PYTHONMALLOC" in os.environ:
        print(
            "PYTHONMALLOC is set in this shell; the malloc_allocator "
            "factor's active state needs it absent. Unset it and rerun."
        )
        return 2

    cmd = [
        args.python, "-m", "pytest", VICTIM_NODE, POLLUTER_NODE,
        "-q", "-p", "no:cacheprovider",
    ]
    world = CommandWorld(
        cmd=cmd, cwd=str(repo_dir), specs=build_specs(), timeout_s=120.0
    )
    config = InvestigationConfig(seed=args.seed)
    print(f"Investigating {VICTIM_NODE} after {POLLUTER_NODE}")
    print(f"Checkout expected at commit {PINNED_COMMIT}")
    print(f"Budget: {config.max_trials} trials, each a fresh pytest process")
    started = time.monotonic()
    investigation = investigate(
        world, command_oracle, FACTORS, config,
        scenario_name="rich-box-order",
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
