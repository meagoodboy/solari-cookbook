"""Investigate a real flaky test in facebookresearch/ParlAI with Crux.

The target is tests/test_multiworld.py::TestMultiworld::test_stochastic
at commit fb5c92741243756516fa50073d34e94ba0b6981e. ParlAI is Meta AI's
dialogue research framework, around 10,600 stars and archived upstream,
so the pinned checkout will stay reproducible forever. The test appears
as row parlai_82 in the FLEX flaky-test dataset (FSE 2021).

The mechanism: parlai.core.worlds.MultiWorld picks which task to run
next episode by calling the global, unseeded python `random` module
(multitask_weights stochastic). The test then asserts that the observed
task ratio lands inside bounds that sit within about 0.7 standard
deviations of the sampling distribution, so a single attempt fails
roughly half the time on pure OS entropy. Upstream hides this behind a
testing_utils.retry(ntries=10) decorator. The retry masks the symptom
and leaves the cause in place.

This script does not ship ParlAI. Point it at your own checkout and a
venv with its test requirements installed:

  python examples/parlai_unseeded_rng.py \
      --repo-dir /path/to/ParlAI --python /path/to/venv/bin/python

A twelve-line driver runs the unwrapped test body exactly once (the
retry decorator uses functools.wraps, so the original body is reachable
as __wrapped__). If the checkout does not already contain the driver,
this script writes it there first; its full source lives below in
DRIVER_SOURCE. The driver reads CRUX_SEED: unset leaves the process
random module auto-seeded from OS entropy, which is the condition CI
actually runs under, while a set value calls random.seed first.

Five suspects go in and the script does not tell Crux which one is
guilty. The unseeded RNG varies per trial through CRUX_SEED={seed32},
which stands in for per-process OS entropy while staying replayable,
and its neutral branch pins CRUX_SEED=0, a value verified to pass.
The other four are plausible red herrings an engineer might blame:
string hash randomization, timezone, locale, and the allocator.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from crux.backends.command import CommandWorld, FactorSpec, command_oracle
from crux.models import Factor, InvestigationConfig
from crux.report import write_bundle
from crux.search import investigate

TEST_NODE = "tests/test_multiworld.py::TestMultiworld::test_stochastic"
PINNED_COMMIT = "fb5c92741243756516fa50073d34e94ba0b6981e"

# Verbatim source of the one-attempt driver. Upstream-test-invoking glue
# only: it imports the real test module and calls the real test body.
DRIVER_SOURCE = '''\
# Single attempt of ParlAI's TestMultiworld.test_stochastic, using only upstream
# test code. The upstream test wraps the body in testing_utils.retry(ntries=10),
# which masks the flakiness; functools.wraps exposes the original body as
# __wrapped__. Set CRUX_SEED to pin Python's global `random` RNG (the suspected
# factor: parlai.core.worlds.MultiWorld samples tasks via random.choices).
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tests.test_multiworld as m
seed = os.environ.get("CRUX_SEED")
if seed is not None:
    random.seed(int(seed))
t = m.TestMultiworld("test_stochastic")
t.test_stochastic.__wrapped__(t)
print("PASS")
'''

FACTORS = (
    Factor("unseeded_global_rng", "global random module left on OS entropy"),
    Factor("hash_randomization", "per-process string hash randomization"),
    Factor("timezone", "host timezone applied through TZ"),
    Factor("locale", "UTF-8 host locale"),
    Factor("malloc_allocator", "default pymalloc allocator"),
)


def build_specs() -> list[FactorSpec]:
    return [
        FactorSpec(
            "unseeded_global_rng",
            active={"CRUX_SEED": "{seed32}"},
            neutral={"CRUX_SEED": "0"},
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


def ensure_driver(repo_dir: Path, driver: str) -> Path:
    """Write the driver into the checkout when it is not already there."""
    path = repo_dir / driver
    if not path.exists():
        path.write_text(DRIVER_SOURCE, encoding="utf-8")
        print(f"Wrote driver to {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-dir", required=True, help="ParlAI checkout")
    parser.add_argument(
        "--python", required=True, help="venv python with ParlAI test deps"
    )
    parser.add_argument(
        "--driver",
        default="run_single_attempt.py",
        help="one-attempt driver, written into the checkout when missing",
    )
    parser.add_argument("--out", default="proof/realworld-parlai")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    repo_dir = Path(args.repo_dir).expanduser().resolve()
    if not (repo_dir / "tests" / "test_multiworld.py").exists():
        print(f"{repo_dir} does not look like a ParlAI checkout")
        return 2
    ensure_driver(repo_dir, args.driver)

    cmd = [args.python, args.driver]
    world = CommandWorld(
        cmd=cmd, cwd=str(repo_dir), specs=build_specs(), timeout_s=120.0
    )
    config = InvestigationConfig(seed=args.seed)
    print(f"Investigating {TEST_NODE}")
    print(f"Checkout expected at commit {PINNED_COMMIT}")
    print(f"Budget: {config.max_trials} trials, one driver process each")
    started = time.monotonic()
    investigation = investigate(
        world, command_oracle, FACTORS, config,
        scenario_name="parlai-unseeded-rng",
    )
    elapsed = time.monotonic() - started
    print(f"\n{investigation.verdict.summary}")
    print(f"Elapsed: {elapsed:.0f}s over {investigation.verdict.trials_total} trials")
    out_dir = Path(args.out)
    write_bundle(investigation, out_dir)
    print(f"Bundle written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
