"""The Home Assistant investigation, run entirely on Solari sandboxes.

Same target, same five suspects, same engine as
examples/home_assistant_hashseed.py. The difference is where trials run:
setup builds one base sandbox in Solari's cloud (clones
home-assistant/core at the pinned commit, installs Python 3.14 and the
test requirements with uv, sanity-runs the test once with a pinned hash
seed), snapshots it, and then every trial forks a fresh clone from that
snapshot. Nothing about the repository under test lives on your machine.

This is the paid path: one long-lived base sandbox for setup plus one
clone per trial, all billed at normal Solari rates. The exact worst-case
clone count is printed first and nothing runs without --yes.

  export SOLARI_API_KEY=slr_live_...
  python examples/home_assistant_hashseed_solari.py --yes

Use --smoke to stop after the snapshot and three probe trials, which is
the cheap way to prove the setup works before committing to a full run.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from crux.backends.command import FactorSpec, command_oracle
from crux.backends.solari_command import SolariCommandWorld
from crux.models import Factor, InvestigationConfig
from crux.report import write_bundle
from crux.search import investigate
from crux.stats import trial_seed

TEST_NODE = "tests/test_bootstrap.py::test_setup_frontend_before_recorder"
PINNED_COMMIT = "de252d4b0db0570c69159fd576d6ae750004476f"
REPO_DIR = "/root/ha"
VENV_PYTHON = "/root/ha-venv/bin/python"

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
        FactorSpec("timezone", active={"TZ": "Asia/Kolkata"}, neutral={"TZ": "UTC"}),
        FactorSpec(
            "locale",
            active={"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
            neutral={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        ),
        FactorSpec(
            "bytecode_cache", active={}, neutral={"PYTHONDONTWRITEBYTECODE": "1"}
        ),
        FactorSpec("malloc_allocator", active={}, neutral={"PYTHONMALLOC": "malloc"}),
    ]


def build_setup_stages() -> list[str]:
    tooling = "\n".join(
        [
            "set -e",
            "export HOME=/root",
            "export DEBIAN_FRONTEND=noninteractive",
            "command -v git >/dev/null || (apt-get update -qq"
            " && apt-get install -y -qq git curl ca-certificates)",
            "command -v curl >/dev/null || (apt-get update -qq"
            " && apt-get install -y -qq curl ca-certificates)",
            "curl -LsSf https://astral.sh/uv/install.sh | sh",
            "mkdir -p /root/ha && cd /root/ha",
            "git init -q",
            "git remote add origin https://github.com/home-assistant/core.git",
            f"git fetch --depth 1 origin {PINNED_COMMIT}",
            "git checkout -q FETCH_HEAD",
            "git rev-parse HEAD",
        ]
    )
    interpreter = "\n".join(
        [
            "set -e",
            "export HOME=/root",
            "export PATH=/root/.local/bin:$PATH",
            "uv python install 3.14",
            "uv venv --python 3.14 /root/ha-venv",
            f"{VENV_PYTHON} --version",
        ]
    )
    dependencies = "\n".join(
        [
            "set -e",
            "export HOME=/root",
            "export PATH=/root/.local/bin:$PATH",
            "export VIRTUAL_ENV=/root/ha-venv",
            "cd /root/ha",
            "uv pip install -q -e . -r requirements_test.txt"
            " ifaddr==0.2.0 paho-mqtt==2.1.0",
        ]
    )
    sanity = "\n".join(
        [
            "set -e",
            "cd /root/ha",
            f"env PYTHONHASHSEED=1 {VENV_PYTHON} -m pytest"
            f" {TEST_NODE} -q -p no:cacheprovider",
        ]
    )
    return [tooling, interpreter, dependencies, sanity]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Investigate the Home Assistant hashseed bug on Solari"
    )
    parser.add_argument("--yes", action="store_true", help="accept sandbox charges")
    parser.add_argument("--smoke", action="store_true", help="setup plus 3 probe trials only")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default="proof/realworld-solari")
    parser.add_argument(
        "--parallel", type=int, default=1,
        help="clones to fork at once (default 1; try 3 on a starter account)",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("SOLARI_API_KEY", "")
    if not api_key:
        print("SOLARI_API_KEY is not set; export it and rerun.")
        return 2

    config = InvestigationConfig(seed=args.seed)
    worst = 3 if args.smoke else config.max_trials
    print(f"This run creates 1 base sandbox (multi-minute setup) plus up to "
          f"{worst} trial clones, each a fresh fork of the snapshot.")
    print("Normal Solari usage charges apply to every one.")
    if not args.yes:
        print("Refusing to run without --yes.")
        return 2

    world = SolariCommandWorld(
        api_key=api_key,
        setup_stages=build_setup_stages(),
        trial_cmd=[VENV_PYTHON, "-m", "pytest", TEST_NODE, "-q", "-p", "no:cacheprovider"],
        trial_cwd=REPO_DIR,
        specs=build_specs(),
        snapshot_name="crux-ha-hashseed",
        concurrency=args.parallel,
        progress=lambda line: print(f"  [world] {line}", flush=True),
    )
    if args.parallel > 1:
        print(f"Forking up to {args.parallel} clones at once.")
    try:
        started = time.monotonic()
        snapshot = world.snapshot()
        print(f"Snapshot ready after {time.monotonic() - started:.0f}s: {snapshot}")

        if args.smoke:
            probes = [
                ("baseline", {f.id: True for f in FACTORS}),
                ("baseline", {f.id: True for f in FACTORS}),
                ("no-hash_randomization",
                 {f.id: f.id != "hash_randomization" for f in FACTORS}),
            ]
            for index, (label, assignment) in enumerate(probes):
                seed = trial_seed(args.seed, f"smoke:{label}", index)
                raw = world.run_trial(snapshot, assignment, seed)
                passed, detail = command_oracle(raw.artifact)
                print(f"probe {label}: passed={passed} ({detail})"
                      f" in {raw.duration_ms} ms")
            print("Smoke finished; no investigation run.")
            return 0

        investigation = investigate(
            world, command_oracle, FACTORS, config,
            scenario_name="home-assistant-hashseed-solari",
        )
        elapsed = time.monotonic() - started
        print(f"\n{investigation.verdict.summary}")
        print(f"Elapsed: {elapsed:.0f}s over "
              f"{investigation.verdict.trials_total} sandbox clones")
        out_dir = Path(args.out)
        write_bundle(investigation, out_dir)
        print(f"Bundle written to {out_dir}")
        return 0
    finally:
        world.close()


if __name__ == "__main__":
    sys.exit(main())
