"""Investigate an order-dependent test failure in encode/uvicorn with Crux.

The target is tests/test_config.py in uvicorn 0.16.0. In its natural
order the file passes every time. Shuffle it and it fails on many seeds,
because tests share the module-level LOGGING_CONFIG dict in
uvicorn/config.py: any test that loads a Config with use_colors set
mutates that dict in place, and test_log_config_default then asserts on
the leftover value instead of the packaged default. The repo's own order
happens to hide the leak. pytest-randomly exposes it.

This script does not ship uvicorn. Point it at a checkout with a venv
holding pytest 6.2.5 and pytest-randomly 3.10.3:

  python examples/uvicorn_test_order.py \
      --repo-dir /path/to/uvicorn --python /path/to/venv/bin/python

Five suspects go in and the script does not tell Crux which one is
guilty. Test order varies per trial through a pytest-randomly seed while
the neutral branch disables the plugin, restoring the file's natural
order. The other four are decoys an engineer might reasonably blame
first: hash randomization, timezone, locale, and the allocator.

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

TEST_FILE = "tests/test_config.py"
PINNED_VERSION = "0.16.0"

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
    parser.add_argument("--repo-dir", required=True, help="uvicorn checkout")
    parser.add_argument(
        "--python", required=True,
        help="venv python with pytest and pytest-randomly",
    )
    parser.add_argument(
        "--out", default="proof/realworld-uvicorn", help="bundle directory"
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--compare", action="store_true", help="also run the naive gap read"
    )
    args = parser.parse_args(argv)

    repo_dir = Path(args.repo_dir).expanduser().resolve()
    if not (repo_dir / "tests" / "test_config.py").exists():
        print(f"{repo_dir} does not look like a uvicorn checkout")
        return 2

    cmd = [
        args.python, "-m", "pytest", TEST_FILE, "-q",
        "-p", "no:cacheprovider", "--basetemp", "/tmp/uvtmp",
    ]
    world = CommandWorld(
        cmd=cmd, cwd=str(repo_dir), specs=build_specs(), timeout_s=240.0
    )
    config = InvestigationConfig(seed=args.seed)
    print(f"Investigating {TEST_FILE} in uvicorn {PINNED_VERSION}")
    print(f"Budget: {config.max_trials} trials, each a fresh pytest process")
    started = time.monotonic()
    investigation = investigate(
        world, command_oracle, FACTORS, config,
        scenario_name="uvicorn-test-order",
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
