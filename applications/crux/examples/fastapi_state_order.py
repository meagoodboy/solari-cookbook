"""Investigate an order-dependent test failure in fastapi/fastapi with Crux.

This is a previously unreported finding, observed 2026-09-11 at fastapi
HEAD (50113da16fec53b66b80d75e80a89296de4fa5a5, v0.141.1, 102k stars).
tests/test_dependency_contextmanager.py defines a module-level dict
`state` (lines 9-18) that the app's yield-dependencies mutate in place:
asyncgen_state (lines 38-41) sets state["/async"] to "asyncgen started"
and then to "asyncgen completed" after its yield. test_async_state
(line 216) opens by asserting the pristine value "asyncgen not started"
at line 217, so any earlier request through that dependency breaks it.
test_sync_async_state (line 313) is one such request: it GETs
/sync_async, which uses the same dependency. Run those two node ids in
reversed order on the pytest command line (pytest honors CLI order) and
line 217 fails every time with AssertionError: 'asyncgen completed' ==
'asyncgen not started'. Natural file order passes every time. Hand runs
at this commit: 8/8 fail reversed, 5/5 pass natural. Under a
pytest-randomly full-file shuffle the same leak produced 2 to 4
failures at every seed tried, since sibling tests share the pattern on
other state keys.

Searches of fastapi issues and PRs, open and closed, for
test_dependency_contextmanager, test_async_state, test_sync_async_state,
pytest-randomly, "test order", and "order-dependent" came back empty of
anything about ordering in fastapi's own suite. The library behavior is
correct; the shipped test file is what carries the defect.

This script does not ship fastapi. Point it at a shallow clone with a
venv holding the repo's tests dependency group:

  python examples/fastapi_state_order.py \
      --repo-dir /path/to/fastapi --python /path/to/venv/bin/python

Four suspects go in and the script does not tell Crux which one is
guilty. The guilty factor is a constant: the same reversed two-test
order every trial, injected through PYTEST_ADDOPTS while the neutral
branch injects the natural order. One decoy varies per trial
(PYTHONHASHSEED through {seed32}), which is the thing an engineer
watching flaky CI would blame first. Timezone and locale round out the
lineup as constant decoys.

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

TEST_FILE = "tests/test_dependency_contextmanager.py"
PINNED_COMMIT = "50113da16fec53b66b80d75e80a89296de4fa5a5"

REVERSED_ORDER = (
    f"{TEST_FILE}::test_sync_async_state {TEST_FILE}::test_async_state"
)
NATURAL_ORDER = (
    f"{TEST_FILE}::test_async_state {TEST_FILE}::test_sync_async_state"
)

FACTORS = (
    Factor("reversed_test_order", "the two test node ids run in reversed CLI order"),
    Factor("hash_randomization", "per-process string hash randomization"),
    Factor("timezone", "host timezone applied through TZ"),
    Factor("locale", "UTF-8 host locale"),
)


def build_specs() -> list[FactorSpec]:
    return [
        FactorSpec(
            "reversed_test_order",
            active={"PYTEST_ADDOPTS": REVERSED_ORDER},
            neutral={"PYTEST_ADDOPTS": NATURAL_ORDER},
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
    parser.add_argument("--repo-dir", required=True, help="fastapi checkout")
    parser.add_argument(
        "--python", required=True,
        help="venv python with the repo's tests dependency group",
    )
    parser.add_argument(
        "--out", default="proof/realworld-fastapi", help="bundle directory"
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--compare", action="store_true", help="also run the naive gap read"
    )
    args = parser.parse_args(argv)

    repo_dir = Path(args.repo_dir).expanduser().resolve()
    if not (repo_dir / TEST_FILE).exists():
        print(f"{repo_dir} does not look like a fastapi checkout")
        return 2

    # The two test node ids travel through PYTEST_ADDOPTS, which pytest
    # prepends to the command line, so the command itself names no tests.
    # codspeed and randomly are disabled up front: the repo installs
    # both, and either one would reorder or wrap the run behind Crux's
    # back. Both branches of the guilty factor set PYTEST_ADDOPTS, so an
    # inherited value never leaks through; nothing here needs a variable
    # to be absent from the parent environment.
    cmd = [
        args.python, "-m", "pytest", "-q",
        "-p", "no:codspeed", "-p", "no:randomly", "-p", "no:cacheprovider",
    ]
    world = CommandWorld(
        cmd=cmd, cwd=str(repo_dir), specs=build_specs(), timeout_s=120.0
    )
    config = InvestigationConfig(seed=args.seed)
    print(f"Investigating {TEST_FILE} shared-state order leak in fastapi")
    print(f"Checkout expected at commit {PINNED_COMMIT}")
    print(f"Budget: {config.max_trials} trials, each a fresh pytest process")
    started = time.monotonic()
    investigation = investigate(
        world, command_oracle, FACTORS, config,
        scenario_name="fastapi-state-order",
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
