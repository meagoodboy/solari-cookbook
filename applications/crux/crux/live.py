"""A small real run on Solari sandboxes to prove the mechanics.

This is the paid path. It reruns a shrunken version of the invoice
investigation on real forked sandboxes: two suspect factors, up to two
rounds, a short confirmation batch. The scale is chosen as the smallest
run that can still reach a decision: six trials per branch per round
keeps the best achievable Fisher p well under the Holm-corrected bar,
so a real effect can actually convict here, and the bundle it writes is
the receipt.

Nothing here talks to the network until the API key is present and the
--yes flag is given. Cost is printed first, as an exact clone count.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .models import Factor, InvestigationConfig

LIVE_FACTOR_IDS: tuple[str, ...] = ("two_column_layout", "cookie_banner")
DEFAULT_OUT = Path("proof/live")


def build_live_config(seed: int = 7) -> InvestigationConfig:
    """The small live config: two rounds, six trials per branch.

    Sized to be decidable, not just to run. With six trials per branch a
    perfect 6-0 split against the baseline gives p = 1/C(12,6), about
    0.0011, comfortably under the Holm-corrected look bar of 0.0125.
    The earlier three-trial version could never convict: its best
    possible p was 0.05 against a bar of 0.025.
    """
    branches = 1 + len(LIVE_FACTOR_IDS)
    round_trials = 6
    # Confirmation is where a small live run actually dies. A first run
    # with 8 per arm saw the true effect at the look (p = 0.0069) and then
    # failed confirmation at p = 0.10 because the baseline happened to pass
    # 5 of 8. Sixteen per arm has roughly 90 percent power against the
    # baseline this fixture produces, so a real effect usually survives.
    confirm = 16
    return InvestigationConfig(
        alpha=0.05,
        max_trials=branches * round_trials * 2 + 2 * confirm,
        max_rounds=2,
        round_trials_per_branch=round_trials,
        confirm_trials=confirm,
        futility_min_trials=16,
        pairwise_top_k=3,
        seed=seed,
    )


def clone_plan(
    config: InvestigationConfig, n_factors: int = len(LIVE_FACTOR_IDS)
) -> tuple[int, int]:
    """Return (round clones, confirmation clones). One clone per trial."""
    branches = 1 + n_factors
    round_clones = branches * config.round_trials_per_branch * config.max_rounds
    confirm_clones = 2 * config.confirm_trials
    return round_clones, confirm_clones


def live_factors() -> tuple[Factor, ...]:
    """The two suspects for the live run, taken from the fixture."""
    from . import fixture

    by_id = {factor.id: factor for factor in fixture.FACTORS}
    missing = [fid for fid in LIVE_FACTOR_IDS if fid not in by_id]
    if missing:
        raise RuntimeError(
            "fixture is missing expected factors: " + ", ".join(missing)
        )
    return tuple(by_id[fid] for fid in LIVE_FACTOR_IDS)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="crux live",
        description=(
            "Rerun a shrunken invoice investigation on real Solari "
            "sandboxes. Creates billable sandboxes; requires --yes."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="accept the sandbox charges and actually run",
    )
    parser.add_argument(
        "--seed", type=int, default=7, help="investigation seed (default 7)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="bundle output directory (default proof/live/)",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("SOLARI_API_KEY", "").strip()
    if not api_key:
        print(
            "SOLARI_API_KEY is not set; export it and rerun, crux live "
            "cannot start without it.",
            file=sys.stderr,
        )
        return 2

    config = build_live_config(seed=args.seed)
    round_clones, confirm_clones = clone_plan(config)
    branches = 1 + len(LIVE_FACTOR_IDS)
    worst_case = round_clones + confirm_clones
    print(
        f"crux live will create 1 base sandbox and {round_clones} trial "
        f"clones ({branches} branches x {config.round_trials_per_branch} "
        f"trials x {config.max_rounds} rounds, if no round decides early)."
    )
    print(
        f"If a suspect reaches significance, one confirmation batch adds "
        f"{confirm_clones} more clones ({config.confirm_trials} on the "
        f"branch + {config.confirm_trials} on baseline)."
    )
    print(
        f"Worst case: {worst_case} clones, {worst_case + 1} sandboxes in "
        f"total. Normal Solari usage charges apply to every one."
    )
    if not args.yes:
        print("Nothing was created. Rerun with --yes to accept and start.")
        return 1

    from . import fixture
    from .backends.solari import SolariWorld
    from .report import write_bundle
    from .search import investigate

    factors = live_factors()
    world = SolariWorld(api_key=api_key)
    try:
        investigation = investigate(
            world, fixture.oracle, factors, config, scenario_name="live-solari"
        )
    finally:
        world.close()

    args.out.mkdir(parents=True, exist_ok=True)
    bundle = write_bundle(investigation, args.out)
    if investigation.verdict is None:
        print(
            "The live investigation ended without a verdict; that is an "
            "engine failure, not a null result. The partial bundle was "
            "still written.",
            file=sys.stderr,
        )
        print(f"Bundle written to {bundle}")
        return 1
    print(investigation.verdict.summary)
    print(f"Bundle written to {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
