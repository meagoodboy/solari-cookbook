"""Investigate an open PyTorch flake (pytorch/pytorch #196512) with Crux.

The target is a distilled unit test, test_knapsack_hashseed.py, built
from pytorch/pytorch issue 196512, filed 2026-09-09 and still OPEN and
unfixed at HEAD when this case was verified (2026-09-11, torch 2.14.0).
KnapsackEvaluator.evaluate_knapsack_output(account_for_backward_pass=True)
returns different peak_memory values across processes for identical
inputs. The cause sits in torch/_functorch/_activation_checkpointing/
graph_info_provider.py: line 184 collects the recomputable node names
into a Python set, and line 196 feeds that set to
candidate_graph.add_nodes_from. Node insertion order in the networkx
graph therefore follows string-hash order, which shifts the
topological-sort tie-breaking, the simulated backward schedule, and the
reported peak memory. The distilled unit exercises the identical public
API the issue names, nothing else.

This script does not ship PyTorch. Point it at a directory holding
test_knapsack_hashseed.py and a venv with torch 2.14.0, networkx and
pytest installed:

  python examples/pytorch_knapsack_hashseed.py \
      --repo-dir /path/to/workdir --python /path/to/venv/bin/python

Five suspects go in and the script never tells Crux which one is
guilty. Hash randomization varies per trial through PYTHONHASHSEED
while the neutral branch pins it to 1. The other four are decoys an
engineer might blame first: timezone, locale, bytecode caching, and
the allocator.

Hand-verified rates before wiring up Crux (12 varied hash seeds, then
8 pinned runs per pin, about 0.7s per run): varied seeds pass 4/12,
PYTHONHASHSEED=1 passes 8/8, PYTHONHASHSEED=0 fails 8/8.

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

TEST_FILE = "test_knapsack_hashseed.py"
ISSUE = "pytorch/pytorch#196512"
PINNED_TORCH = "2.14.0"

# Factors whose active state is the parent environment untouched. A
# CommandWorld cannot unset an inherited variable, so if the parent
# exports one of these the active and neutral branches stop differing
# and the lineup is broken. We refuse to run in that case.
MUST_NOT_BE_EXPORTED = ("PYTHONMALLOC", "PYTHONDONTWRITEBYTECODE")

FACTORS = (
    Factor("hash_randomization", "per-process string hash randomization"),
    Factor("timezone", "host timezone applied through TZ"),
    Factor("locale", "UTF-8 host locale"),
    Factor("malloc_allocator", "default pymalloc allocator"),
    Factor("bytecode_cache", "pyc bytecode caching enabled"),
)


def build_specs() -> list[FactorSpec]:
    return [
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
        FactorSpec(
            "bytecode_cache",
            active={},
            neutral={"PYTHONDONTWRITEBYTECODE": "1"},
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
    parser.add_argument(
        "--repo-dir", required=True,
        help="directory holding test_knapsack_hashseed.py",
    )
    parser.add_argument(
        "--python", required=True,
        help="venv python with torch 2.14.0, networkx and pytest",
    )
    parser.add_argument(
        "--out", default="proof/realworld-pytorch", help="bundle directory"
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--compare", action="store_true", help="also run the naive gap read"
    )
    args = parser.parse_args(argv)

    for name in MUST_NOT_BE_EXPORTED:
        if name in os.environ:
            print(
                f"{name} is exported in this shell. Two factors treat the "
                "absence of that variable as their active state, and a "
                "child environment cannot unset an inherited variable, so "
                "the lineup would be broken. Unset it and rerun."
            )
            return 2

    repo_dir = Path(args.repo_dir).expanduser().resolve()
    if not (repo_dir / TEST_FILE).exists():
        print(f"{repo_dir} does not contain {TEST_FILE}")
        return 2

    cmd = [
        args.python, "-m", "pytest", TEST_FILE, "-q",
        "-p", "no:cacheprovider",
    ]
    world = CommandWorld(
        cmd=cmd, cwd=str(repo_dir), specs=build_specs(), timeout_s=120.0
    )
    config = InvestigationConfig(seed=args.seed)
    print(f"Investigating {TEST_FILE}, distilled from {ISSUE}")
    print(f"Expected stack: torch {PINNED_TORCH}, bug open at HEAD")
    print(f"Budget: {config.max_trials} trials, each a fresh pytest process")
    started = time.monotonic()
    investigation = investigate(
        world, command_oracle, FACTORS, config,
        scenario_name="pytorch-knapsack-hashseed",
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
