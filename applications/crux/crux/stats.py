"""Statistical machinery for Crux investigations.

Everything here is exact or closed-form and uses only the stdlib. The
search loop calls into this module; nothing here touches a World or an
oracle, which keeps the numbers easy to test in isolation.
"""

from __future__ import annotations

import hashlib
from math import comb, sqrt


def trial_seed(config_seed: int, branch_id: str, index: int) -> int:
    """Derive the deterministic seed for one trial.

    First 8 bytes of sha256 over "config_seed:branch_id:index". The same
    triple always maps to the same seed, on any machine, so a saved
    investigation can be replayed bit for bit.
    """
    digest = hashlib.sha256(f"{config_seed}:{branch_id}:{index}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def fisher_exact_greater(
    branch_succ: int, branch_n: int, base_succ: int, base_n: int
) -> float:
    """One-sided Fisher exact p-value for "branch rate > baseline rate".

    Conditions on both margins of the 2x2 table and sums the upper
    hypergeometric tail with math.comb, so the result is exact up to one
    float division. With N total trials, K total successes, and branch_n
    draws, the p-value is P(X >= branch_succ) for X hypergeometric.

    Degenerate margins carry no evidence in either direction, so an empty
    row (zero trials on a side) or a constant column (all trials succeed,
    or none do) returns 1.0 instead of raising.
    """
    for value in (branch_succ, branch_n, base_succ, base_n):
        if value < 0:
            raise ValueError("counts must be non-negative")
    if branch_succ > branch_n or base_succ > base_n:
        raise ValueError("successes cannot exceed trials")

    total_n = branch_n + base_n
    total_succ = branch_succ + base_succ
    if branch_n == 0 or base_n == 0:
        return 1.0
    if total_succ == 0 or total_succ == total_n:
        return 1.0

    # Tail sum in exact integers, one correctly rounded division at the end.
    numerator = 0
    for k in range(branch_succ, min(total_succ, branch_n) + 1):
        numerator += comb(total_succ, k) * comb(total_n - total_succ, branch_n - k)
    return numerator / comb(total_n, branch_n)


def holm(pvals: dict[str, float], alpha: float) -> dict[str, bool]:
    """Holm step-down correction. Returns id -> rejected (significant).

    Sort p-values ascending and compare the i-th smallest against
    alpha / (m - i). The first failure stops the walk: everything at or
    beyond it is not rejected, even a later p that would clear its own
    threshold. Ties break by id so the outcome never depends on dict order.
    """
    if not pvals:
        return {}
    ordered = sorted(pvals.items(), key=lambda item: (item[1], item[0]))
    m = len(ordered)
    decisions: dict[str, bool] = {}
    failed = False
    for i, (key, p) in enumerate(ordered):
        if not failed and p <= alpha / (m - i):
            decisions[key] = True
        else:
            failed = True
            decisions[key] = False
    return decisions


def wilson_ci(succ: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Behaves sensibly at the edges: succ=0 gives a lower bound of exactly
    0, succ=n an upper bound of exactly 1, and n=0 returns the vacuous
    interval (0.0, 1.0). Bounds are clamped into [0, 1] against float
    round-off.
    """
    if n == 0:
        return (0.0, 1.0)
    if succ < 0 or succ > n:
        raise ValueError("successes must lie in [0, n]")
    phat = succ / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2 * n)) / denom
    half = z * sqrt(phat * (1.0 - phat) / n + z2 / (4 * n * n)) / denom
    low = max(0.0, center - half)
    high = min(1.0, center + half)
    return (low, high)


def look_alpha(alpha: float, max_rounds: int) -> float:
    """Per-look alpha under plain Bonferroni spending across rounds."""
    if max_rounds < 1:
        raise ValueError("max_rounds must be at least 1")
    return alpha / max_rounds
