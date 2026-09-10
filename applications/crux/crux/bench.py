"""Operating-characteristics study for the Crux procedure.

Runs the full sequential investigation and two simpler baselines over
many seeded scenario instances, then tallies how often each method names
the true cause, convicts an innocent factor, or declines to convict.
The point is to put numbers on the claim that the procedure is both
safer than eyeballing a handful of trials and cheaper than one big
fixed-budget test.

Everything is deterministic. Instance seeds derive from the master seed
through the same trial_seed scheme the investigation itself uses, and
the two baseline methods draw their own trial seeds under distinct
namespace tags so no method reuses another's randomness.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .backends.local import ConjunctionWorld, LocalWorld, NoEffectWorld
from .fixture import FACTORS, oracle
from .models import InvestigationConfig
from .search import BASELINE_ID, branch_id_for, investigate
from .stats import fisher_exact_greater, holm, trial_seed
from .world import World

DEFAULT_SEEDS = 200
DEFAULT_MASTER_SEED = 7
DEFAULT_OUT = "bench"

WEAK_LARGE_INVOICE_P = 0.10
NAIVE_TRIALS_PER_BRANCH = 5
# The fairness claim is that fixed-budget gets exactly the trial budget
# crux gets, so the number is derived from the config rather than typed
# twice. With five factors this is 240 trials, 40 per arm.
FIXED_TOTAL_TRIALS = InvestigationConfig().max_trials

METHODS = ("crux", "naive-gap", "fixed-budget")


def _families() -> tuple[tuple[str, Callable[[], World], tuple[str, ...] | None], ...]:
    """Family name, world factory, and ground-truth cause for each scenario."""
    return (
        ("layout-cause", LocalWorld, ("two_column_layout",)),
        ("no-cause", NoEffectWorld, None),
        ("conjunction-cause", ConjunctionWorld, ConjunctionWorld.PAIR),
        (
            "weak-cause",
            lambda: LocalWorld(large_invoice_p=WEAK_LARGE_INVOICE_P),
            ("two_column_layout",),
        ),
    )


FAMILY_NAMES = tuple(name for name, _, _ in _families())


def _outcome(
    conviction: tuple[str, ...] | None, truth: tuple[str, ...] | None
) -> str:
    """Score one conviction against the ground truth.

    Correct means the convicted factor set equals the truth exactly.
    Declining to convict is scored as none, which is the right answer
    when the truth is None. Everything else is wrong, including a
    single-factor conviction against a conjunction truth.
    """
    if conviction is None:
        return "none"
    if truth is not None and set(conviction) == set(truth):
        return "correct"
    return "wrong"


def _assignment(neutralized: tuple[str, ...]) -> dict[str, bool]:
    off = set(neutralized)
    return {f.id: f.id not in off for f in FACTORS}


def _run_crux(
    world: World, instance_seed: int, family_name: str
) -> dict[str, Any]:
    config = InvestigationConfig(seed=instance_seed)
    inv = investigate(world, oracle, FACTORS, config, scenario_name=family_name)
    verdict = inv.verdict
    confirmations = sum(len(e.get("confirmations", ())) for e in inv.round_log)
    return {
        "conviction": list(verdict.cause) if verdict.cause is not None else None,
        "trials": verdict.trials_total,
        "rounds": verdict.rounds,
        "confirmations": confirmations,
    }


def _tally_arms(
    world: World, instance_seed: int, tag: str, per_branch: int
) -> tuple[dict[str, tuple[str, ...]], dict[str, int]]:
    """Run per_branch trials on baseline plus every single-factor branch.

    Trial seeds come from trial_seed(instance_seed, "<tag>:<branch>", j),
    so each method's draws live in their own namespace and never collide
    with the investigation's.
    """
    snapshot = world.snapshot()
    arms: dict[str, tuple[str, ...]] = {BASELINE_ID: ()}
    for factor in FACTORS:
        arms[branch_id_for((factor.id,))] = (factor.id,)
    successes: dict[str, int] = {}
    for bid, neutralized in arms.items():
        assignment = _assignment(neutralized)
        succ = 0
        for j in range(per_branch):
            seed = trial_seed(instance_seed, f"{tag}:{bid}", j)
            raw = world.run_trial(snapshot, assignment, seed)
            succ += int(oracle(raw.artifact)[0])
        successes[bid] = succ
    return arms, successes


def _run_naive_gap(world: World, instance_seed: int) -> dict[str, Any]:
    """The eyeball baseline: five trials per arm, convict the biggest gap.

    Convicts the branch with the largest positive success gap over the
    baseline, ties broken by branch id. Declines only when every gap is
    zero or negative.
    """
    arms, successes = _tally_arms(
        world, instance_seed, "naive", NAIVE_TRIALS_PER_BRANCH
    )
    base = successes[BASELINE_ID]
    best_bid = None
    best_gap = 0
    for bid in sorted(arms):
        if bid == BASELINE_ID:
            continue
        gap = successes[bid] - base
        if gap > best_gap:
            best_gap = gap
            best_bid = bid
    conviction = list(arms[best_bid]) if best_bid is not None else None
    return {
        "conviction": conviction,
        "trials": NAIVE_TRIALS_PER_BRANCH * len(arms),
    }


def _run_fixed_budget(world: World, instance_seed: int) -> dict[str, Any]:
    """One look at the full budget: 40 trials per arm, Fisher plus Holm.

    No early stop and no confirmation batch. Convicts the smallest
    significant p at the full alpha, ties broken by branch id.
    """
    alpha = InvestigationConfig().alpha
    per_branch, remainder = divmod(FIXED_TOTAL_TRIALS, len(FACTORS) + 1)
    if remainder:
        raise ValueError(
            f"fixed budget {FIXED_TOTAL_TRIALS} does not split evenly "
            f"across {len(FACTORS) + 1} arms; {remainder} trials would be "
            f"dropped silently"
        )
    arms, successes = _tally_arms(world, instance_seed, "fixed", per_branch)
    base = successes[BASELINE_ID]
    pvals = {
        bid: fisher_exact_greater(successes[bid], per_branch, base, per_branch)
        for bid in arms
        if bid != BASELINE_ID
    }
    decisions = holm(pvals, alpha)
    significant = sorted(
        (bid for bid, ok in decisions.items() if ok),
        key=lambda bid: (pvals[bid], bid),
    )
    conviction = list(arms[significant[0]]) if significant else None
    return {
        "conviction": conviction,
        "trials": per_branch * len(arms),
    }


def run_family(
    family_name: str, seeds: int, master_seed: int = DEFAULT_MASTER_SEED
) -> list[dict[str, Any]]:
    """Run every method on `seeds` instances of one family."""
    matches = [f for f in _families() if f[0] == family_name]
    if not matches:
        raise ValueError(f"unknown family {family_name!r}")
    _, factory, truth = matches[0]
    records: list[dict[str, Any]] = []
    for i in range(seeds):
        instance_seed = trial_seed(master_seed, family_name, i)
        world = factory()
        try:
            methods = {
                "crux": _run_crux(world, instance_seed, family_name),
                "naive-gap": _run_naive_gap(world, instance_seed),
                "fixed-budget": _run_fixed_budget(world, instance_seed),
            }
        finally:
            world.close()
        for result in methods.values():
            conviction = result["conviction"]
            result["outcome"] = _outcome(
                tuple(conviction) if conviction is not None else None, truth
            )
        records.append(
            {
                "family": family_name,
                "index": i,
                "instance_seed": instance_seed,
                "truth": list(truth) if truth is not None else None,
                "methods": methods,
            }
        )
    return records


def aggregate(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate per-instance records into per (family, method) metrics."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        for method, result in record["methods"].items():
            grouped[(record["family"], method)].append(result)
    out: dict[str, dict[str, Any]] = {}
    for (family, method), rows in grouped.items():
        n = len(rows)
        counts = Counter(row["outcome"] for row in rows)
        trials = [row["trials"] for row in rows]
        entry: dict[str, Any] = {
            "instances": n,
            "correct_pct": round(100.0 * counts["correct"] / n, 1),
            "wrong_pct": round(100.0 * counts["wrong"] / n, 1),
            "none_pct": round(100.0 * counts["none"] / n, 1),
            "mean_trials": round(statistics.fmean(trials), 1),
            "median_trials": statistics.median(trials),
        }
        if method == "crux":
            entry["mean_rounds"] = round(
                statistics.fmean(row["rounds"] for row in rows), 2
            )
            entry["mean_confirmations"] = round(
                statistics.fmean(row["confirmations"] for row in rows), 2
            )
        out.setdefault(family, {})[method] = entry
    return out


def run_bench(
    seeds: int = DEFAULT_SEEDS,
    master_seed: int = DEFAULT_MASTER_SEED,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run every family and return records, aggregates and metadata."""
    records: list[dict[str, Any]] = []
    for name, _, _ in _families():
        if progress is not None:
            progress(f"running {name} ({seeds} seeds)")
        records.extend(run_family(name, seeds, master_seed))
    metadata = {
        "master_seed": master_seed,
        "seeds_per_family": seeds,
        "families": {
            name: {"truth": list(truth) if truth is not None else None}
            for name, _, truth in _families()
        },
        "methods": list(METHODS),
        # The config's seed field is dropped: every crux run overrides it
        # with the record's instance_seed, so the default would only
        # mislead anyone replaying from this block.
        "config": {
            k: v for k, v in asdict(InvestigationConfig()).items() if k != "seed"
        },
        "naive_trials_per_branch": NAIVE_TRIALS_PER_BRANCH,
        "fixed_total_trials": FIXED_TOTAL_TRIALS,
        "weak_large_invoice_p": WEAK_LARGE_INVOICE_P,
    }
    return {
        "metadata": metadata,
        "aggregates": aggregate(records),
        "records": records,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _results_markdown(results: dict[str, Any]) -> str:
    meta = results["metadata"]
    aggregates = results["aggregates"]
    lines = [
        "# Crux operating characteristics",
        "",
        f"Master seed {meta['master_seed']}, {meta['seeds_per_family']} seeded "
        f"instances per family. Each instance runs three methods on the same "
        f"world construction: the full crux investigation, a naive gap read of "
        f"{meta['naive_trials_per_branch']} trials per arm, and a single "
        f"fixed-budget look of {meta['fixed_total_trials']} trials.",
        "",
        "## Scoring",
        "",
        "A conviction is correct only when it names the true factor set "
        "exactly. For the no-cause family the right outcome is no conviction "
        "at all, so any conviction there counts as wrong. For the conjunction "
        "family a single-factor conviction is wrong, with no partial credit. "
        "Note that the two baseline methods only ever test single-factor "
        "arms, so on the conjunction family their correct rate is zero by "
        "construction and the comparison there measures the crux pairwise "
        "escalation alone. "
        "A wrong conviction is worse than no conviction: wrong aims the fix "
        "at an innocent factor, while none just says keep looking.",
        "",
        "## Aggregate table",
        "",
        "| Family | Method | Correct % | Wrong % | None % | Mean trials | "
        "Median trials | Mean rounds | Mean confirmations |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for family in FAMILY_NAMES:
        for method in METHODS:
            entry = aggregates.get(family, {}).get(method)
            if entry is None:
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        family,
                        method,
                        _fmt(entry["correct_pct"]),
                        _fmt(entry["wrong_pct"]),
                        _fmt(entry["none_pct"]),
                        _fmt(entry["mean_trials"]),
                        _fmt(entry["median_trials"]),
                        _fmt(entry.get("mean_rounds")),
                        _fmt(entry.get("mean_confirmations")),
                    ]
                )
                + " |"
            )
    lines += [
        "",
        "## Reading the table",
        "",
        "Rounds and confirmations apply to crux only; the naive method takes "
        "one implicit look and the fixed-budget method exactly one planned "
        "look. Trial counts for crux vary because the procedure stops early "
        "once a cause is confirmed or every suspect is retired. Rerunning "
        "with the same master seed reproduces every number here.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(results: dict[str, Any], out_dir: Path) -> Path:
    """Write results.json and RESULTS.md into out_dir and return it."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "RESULTS.md").write_text(_results_markdown(results), encoding="utf-8")
    return out_dir
