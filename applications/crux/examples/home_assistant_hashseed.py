"""Investigate a real flaky test in home-assistant/core with Crux.

The target is tests/test_bootstrap.py::test_setup_frontend_before_recorder
at commit de252d4b0db0570c69159fd576d6ae750004476f. At that commit the
relative setup order of two stage-0 components falls back to Python set
iteration order, so the test fails on roughly a third of hash seeds. The
bug was introduced by PR 176137 and fixed the same day by PR 176508;
pinning the checkout keeps the reproduction honest and permanent.

This script does not ship Home Assistant. Point it at your own checkout
and the venv you installed its test requirements into:

  python examples/home_assistant_hashseed.py \
      --repo-dir /path/to/ha-core --python /path/to/venv/bin/python

Five suspects go in. Only one is guilty, and the script does not tell
Crux which: hash randomization varies per trial through PYTHONHASHSEED
while the neutral branch pins it, and the other four are plausible
red herrings an engineer might blame (timezone, locale, bytecode
caching, the allocator).

Add --compare to also run the naive gap read (5 trials per arm, blame
the biggest gap) on the same world, for a head-to-head.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from crux.backends.command import CommandWorld, FactorSpec, command_oracle
from crux.models import Factor, InvestigationConfig
from crux.report import write_bundle
from crux.search import investigate
from crux.stats import trial_seed

TEST_NODE = "tests/test_bootstrap.py::test_setup_frontend_before_recorder"
PINNED_COMMIT = "de252d4b0db0570c69159fd576d6ae750004476f"

FACTORS = (
    Factor("hash_randomization", "per-process string hash randomization"),
    Factor("timezone", "host timezone applied through TZ"),
    Factor("locale", "UTF-8 host locale"),
    Factor("bytecode_cache", "pyc bytecode caching enabled"),
    Factor("malloc_allocator", "default pymalloc allocator"),
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
            "bytecode_cache",
            active={},
            neutral={"PYTHONDONTWRITEBYTECODE": "1"},
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
    parser.add_argument("--repo-dir", required=True, help="ha-core checkout")
    parser.add_argument("--python", required=True, help="venv python with HA test deps")
    parser.add_argument("--out", default="proof/realworld", help="bundle directory")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--compare", action="store_true", help="also run the naive gap read")
    args = parser.parse_args(argv)

    repo_dir = Path(args.repo_dir).expanduser().resolve()
    if not (repo_dir / "tests" / "test_bootstrap.py").exists():
        print(f"{repo_dir} does not look like a home-assistant/core checkout")
        return 2

    cmd = [args.python, "-m", "pytest", TEST_NODE, "-q", "-p", "no:cacheprovider"]
    world = CommandWorld(
        cmd=cmd, cwd=str(repo_dir), specs=build_specs(), timeout_s=120.0
    )
    config = InvestigationConfig(seed=args.seed)
    print(f"Investigating {TEST_NODE}")
    print(f"Checkout expected at commit {PINNED_COMMIT}")
    print(f"Budget: {config.max_trials} trials, each a fresh pytest process")
    started = time.monotonic()
    investigation = investigate(
        world, command_oracle, FACTORS, config,
        scenario_name="home-assistant-hashseed",
    )
    elapsed = time.monotonic() - started
    print(f"\n{investigation.verdict.summary}")
    print(f"Elapsed: {elapsed:.0f}s over {investigation.verdict.trials_total} trials")
    out_dir = Path(args.out)
    write_bundle(investigation, out_dir)
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
