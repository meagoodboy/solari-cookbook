"""The sequential investigation loop.

Runs batches of trials against a frozen world, branch by branch, and
looks for a branch whose success rate beats the baseline by more than
chance would allow. Alpha is spent evenly across the planned looks.
Any branch that clears a look must also survive one confirmation batch
on fresh seeds before Crux will name it as the cause. Branches that
track the baseline get dropped for futility, and when single factors
run out of road the search escalates to pairs.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

from .models import (
    BranchState,
    Factor,
    Investigation,
    InvestigationConfig,
    TrialResult,
    Verdict,
)
from .stats import fisher_exact_greater, holm, look_alpha, trial_seed
from .world import Oracle, World

BASELINE_ID = "baseline"


def branch_id_for(neutralized: Iterable[str]) -> str:
    """Branch id from the set of neutralized factor ids.

    Empty means the baseline. Singles are "no-<id>", pairs join the two
    single ids with "+" in sorted order.
    """
    parts = sorted(neutralized)
    if not parts:
        return BASELINE_ID
    return "+".join(f"no-{fid}" for fid in parts)


def _assignment(
    factors: Sequence[Factor], neutralized: Iterable[str]
) -> dict[str, bool]:
    off = set(neutralized)
    return {f.id: f.id not in off for f in factors}


def _run_batch(
    inv: Investigation,
    world: World,
    oracle: Oracle,
    snapshot: str,
    factors: Sequence[Factor],
    jobs: Sequence[tuple[BranchState, str, int]],
) -> list[bool]:
    """Run a batch of trials and record them in job order.

    Each job is (branch, seed_key, index); the seed and assignment are
    fully determined before anything runs, so a world that executes the
    batch concurrently produces byte-identical investigations to one
    that walks it sequentially. A world advertises concurrency by
    offering run_trials(snapshot, [(assignment, seed), ...]) returning
    RawRuns in the same order; without it the batch just loops.
    """
    prepared = [
        (
            branch,
            trial_seed(inv.config.seed, seed_key, index),
            _assignment(factors, branch.neutralized),
        )
        for branch, seed_key, index in jobs
    ]
    runner = getattr(world, "run_trials", None)
    if runner is None:
        raws = [
            world.run_trial(snapshot, assignment, seed)
            for _, seed, assignment in prepared
        ]
    else:
        raws = list(
            runner(snapshot, [(assignment, seed) for _, seed, assignment in prepared])
        )
        if len(raws) != len(prepared):
            raise RuntimeError(
                f"world returned {len(raws)} results for {len(prepared)} jobs"
            )
    outcomes: list[bool] = []
    for (branch, seed, _), raw in zip(prepared, raws):
        passed, detail = oracle(raw.artifact)
        inv.trials.append(
            TrialResult(
                branch_id=branch.branch_id,
                seed=seed,
                passed=passed,
                detail=detail,
                artifact=raw.artifact,
                duration_ms=raw.duration_ms,
            )
        )
        branch.trials += 1
        branch.successes += int(passed)
        outcomes.append(passed)
    return outcomes


def _describe(factors: Sequence[Factor], ids: Iterable[str]) -> str:
    lookup = {f.id: f.description for f in factors}
    return " and ".join(lookup.get(fid, fid) for fid in ids)


def _confirmed_verdict(
    inv: Investigation,
    baseline: BranchState,
    branch: BranchState,
    conf_p: float,
    per_arm: int,
    conf_succ: int,
    base_succ: int,
    rounds: int,
) -> Verdict:
    names = _describe(inv.factors, branch.neutralized)
    summary = (
        f"Neutralizing {names} flipped the outcome. "
        f"The baseline passed {baseline.successes} of {baseline.trials} trials, "
        f"a rate of {baseline.rate:.0%}, while this branch passed "
        f"{branch.successes} of {branch.trials}, a rate of {branch.rate:.0%}; "
        f"those totals include the confirmation trials, and the search phase "
        f"alone tends to flatter the winner. "
        f"The fresh confirmation batch is the unbiased read: {conf_succ} of "
        f"{per_arm} passed on this branch against {base_succ} of {per_arm} at "
        f"baseline, with p = {conf_p:.4g} against an alpha of {inv.config.alpha}."
    )
    return Verdict(
        cause=branch.neutralized,
        confirmation_p=conf_p,
        baseline_rate=baseline.rate,
        cause_rate=branch.rate,
        alpha=inv.config.alpha,
        trials_total=len(inv.trials),
        rounds=rounds,
        summary=summary,
    )


def _exhausted_verdict(
    inv: Investigation,
    baseline: BranchState,
    rounds: int,
    starved_bid: str | None = None,
) -> Verdict:
    scored = [
        b
        for b in inv.branches.values()
        if b.branch_id != BASELINE_ID and b.p_value is not None
    ]
    if starved_bid is not None:
        starved = inv.branches[starved_bid]
        names = _describe(inv.factors, starved.neutralized)
        summary = (
            f"The branch neutralizing {names} cleared the screening bar with "
            f"p = {starved.p_value:.3g}, passing {starved.successes} of "
            f"{starved.trials} trials against a baseline of "
            f"{baseline.successes} of {baseline.trials}, but the trial budget "
            f"could not fund a confirmation batch, so no cause is named. "
            f"The search stopped after {rounds} rounds and {len(inv.trials)} "
            f"of {inv.config.max_trials} allowed trials."
        )
    elif scored:
        closest = min(scored, key=lambda b: (b.p_value, b.branch_id))
        names = _describe(inv.factors, closest.neutralized)
        summary = (
            f"No suspect met the significance bar. The closest branch neutralized "
            f"{names}, passing {closest.successes} of {closest.trials} trials "
            f"against a baseline of {baseline.successes} of {baseline.trials}, "
            f"with p = {closest.p_value:.3g}. The search stopped after {rounds} "
            f"rounds and {len(inv.trials)} of {inv.config.max_trials} allowed trials."
        )
    else:
        summary = (
            f"No suspect met the significance bar, and no branch collected enough "
            f"trials to be scored. The baseline passed {baseline.successes} of "
            f"{baseline.trials} trials. The search stopped after {rounds} rounds "
            f"and {len(inv.trials)} of {inv.config.max_trials} allowed trials."
        )
    return Verdict(
        cause=None,
        confirmation_p=None,
        baseline_rate=baseline.rate,
        cause_rate=None,
        alpha=inv.config.alpha,
        trials_total=len(inv.trials),
        rounds=rounds,
        summary=summary,
    )


def _allocate(
    arms: Sequence[BranchState], remaining: int, per_branch: int
) -> dict[str, int]:
    """Plan this round's trial counts, baseline first when budget is short."""
    desired = per_branch * len(arms)
    if remaining >= desired:
        return {b.branch_id: per_branch for b in arms}
    share, extra = divmod(remaining, len(arms))
    return {
        b.branch_id: share + (1 if i < extra else 0) for i, b in enumerate(arms)
    }


def _escalate(inv: Investigation) -> None:
    """Add pairwise branches over the most promising single factors.

    Surviving singles are preferred, ranked by smallest current p with
    ties broken by id. When fewer than pairwise_top_k survive, the pool
    is topped up from the dropped ones in the same order, so an all
    dropped field excludes none. A conjunction hides its members behind
    futile looking singles, which is why dropped factors stay reachable
    here. A single that merely failed its confirmation keeps its seat
    too, since a small p that did not replicate is exactly the kind of
    factor a pair might rescue.

    Known limit: a pure conjunction gives neither member any marginal
    signal, so ranking singles by p is ranking noise. The needed pair is
    only instantiated when both members happen to land in the top
    pairwise_top_k singles, which for k of 3 over 5 factors is roughly a
    3 in 10 chance per run. With more factors than pairwise_top_k, plan
    on several seeds, or raise pairwise_top_k, when a conjunction is on
    the table. The ranking rule itself is fixed by the contract.
    """
    singles = [b for b in inv.branches.values() if len(b.neutralized) == 1]
    def rank(b: BranchState) -> tuple[float, str]:
        return (b.p_value if b.p_value is not None else 1.0, b.branch_id)

    kept = sorted((b for b in singles if not b.dropped_for_futility), key=rank)
    dropped = sorted((b for b in singles if b.dropped_for_futility), key=rank)
    candidates = kept + dropped
    top = [b.neutralized[0] for b in candidates[: inv.config.pairwise_top_k]]
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            pair = tuple(sorted((top[i], top[j])))
            bid = branch_id_for(pair)
            if bid not in inv.branches:
                inv.branches[bid] = BranchState(branch_id=bid, neutralized=pair)


def investigate(
    world: World,
    oracle: Oracle,
    factors: Sequence[Factor],
    config: InvestigationConfig,
    scenario_name: str = "",
) -> Investigation:
    """Run the full sequential procedure and return a decided Investigation.

    The verdict either names a confirmed cause or states honestly that no
    suspect met the bar within the trial and round budget. Every trial
    seed derives from config.seed, the branch id, and a per-branch index,
    so a run replays exactly from its investigation id.
    """
    factors = tuple(factors)
    inv = Investigation(
        investigation_id=f"{scenario_name or 'investigation'}-seed{config.seed}",
        scenario=scenario_name,
        factors=factors,
        config=config,
    )
    baseline = BranchState(branch_id=BASELINE_ID, neutralized=())
    inv.branches[BASELINE_ID] = baseline
    for f in factors:
        bid = branch_id_for((f.id,))
        inv.branches[bid] = BranchState(branch_id=bid, neutralized=(f.id,))

    snapshot = world.snapshot()
    next_index: dict[str, int] = {}
    spent = look_alpha(config.alpha, config.max_rounds)
    escalate_after = math.ceil(config.max_rounds * 0.6)
    escalated = False
    rounds_done = 0
    starved_bid: str | None = None

    def round_jobs(branch: BranchState, count: int) -> list[tuple[BranchState, str, int]]:
        jobs = []
        for _ in range(count):
            idx = next_index.get(branch.branch_id, 0)
            next_index[branch.branch_id] = idx + 1
            jobs.append((branch, branch.branch_id, idx))
        return jobs

    for r in range(1, config.max_rounds + 1):
        live = [
            b
            for b in inv.branches.values()
            if b.branch_id != BASELINE_ID
            and not b.dropped_for_futility
            and not b.confirmation_failed
        ]
        remaining = config.max_trials - len(inv.trials)
        if remaining <= 0:
            break
        arms = [baseline] + sorted(live, key=lambda b: b.branch_id)
        allocations = _allocate(arms, remaining, config.round_trials_per_branch)
        if all(n == 0 for n in allocations.values()):
            break
        rounds_done = r

        jobs: list[tuple[BranchState, str, int]] = []
        for branch in arms:
            jobs.extend(round_jobs(branch, allocations[branch.branch_id]))
        _run_batch(inv, world, oracle, snapshot, factors, jobs)

        p_values: dict[str, float] = {}
        for branch in live:
            if branch.trials == 0:
                continue
            p = fisher_exact_greater(
                branch.successes, branch.trials, baseline.successes, baseline.trials
            )
            branch.p_value = p
            p_values[branch.branch_id] = p
        decisions = holm(p_values, spent) if p_values else {}
        entry: dict = {
            "round": r,
            "alpha_spent": spent,
            "allocations": allocations,
            "p_values": dict(p_values),
        }
        inv.round_log.append(entry)

        for branch in live:
            if (
                branch.trials >= config.futility_min_trials
                and branch.rate <= baseline.rate
            ):
                branch.dropped_for_futility = True

        significant = sorted(
            (bid for bid, ok in decisions.items() if ok),
            key=lambda bid: (
                len(inv.branches[bid].neutralized),
                p_values[bid],
                bid,
            ),
        )
        for bid in significant:
            branch = inv.branches[bid]
            if branch.dropped_for_futility or branch.confirmation_failed:
                continue
            budget = config.max_trials - len(inv.trials)
            per_arm = min(config.confirm_trials, budget // 2)
            if per_arm <= 0:
                starved_bid = bid
                break
            # Feasibility gate: a starved batch can be too small to reach
            # alpha even on a perfect split (per_arm of 1 bottoms out at
            # p = 0.5). Running it would burn budget and retire the branch
            # on a test it could never pass, so skip instead and leave the
            # branch eligible. Larger power margins would be nicer still,
            # but the alpha bound is the line the procedure must not cross.
            best_possible = fisher_exact_greater(per_arm, per_arm, 0, per_arm)
            if best_possible > config.alpha:
                starved_bid = bid
                break
            namespace = f"confirm:{bid}"
            confirm_jobs = [
                (branch, namespace, i) for i in range(per_arm)
            ] + [
                (baseline, namespace, per_arm + i) for i in range(per_arm)
            ]
            outcomes = _run_batch(
                inv, world, oracle, snapshot, factors, confirm_jobs
            )
            conf_succ = sum(outcomes[:per_arm])
            base_succ = sum(outcomes[per_arm:])
            conf_p = fisher_exact_greater(conf_succ, per_arm, base_succ, per_arm)
            passed = conf_p <= config.alpha
            entry.setdefault("confirmations", []).append(
                {
                    "branch": bid,
                    "trials_per_arm": per_arm,
                    "branch_successes": conf_succ,
                    "baseline_successes": base_succ,
                    "p": conf_p,
                    "passed": passed,
                }
            )
            if passed:
                inv.verdict = _confirmed_verdict(
                    inv,
                    baseline,
                    branch,
                    conf_p,
                    per_arm,
                    conf_succ,
                    base_succ,
                    rounds_done,
                )
                return inv
            branch.confirmation_failed = True

        if not escalated:
            singles = [b for b in inv.branches.values() if len(b.neutralized) == 1]
            singles_out = singles and all(
                b.dropped_for_futility or b.confirmation_failed for b in singles
            )
            if singles_out or r >= escalate_after:
                escalated = True
                _escalate(inv)

    inv.verdict = _exhausted_verdict(inv, baseline, rounds_done, starved_bid)
    return inv
