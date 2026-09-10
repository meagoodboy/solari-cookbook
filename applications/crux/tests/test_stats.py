"""Tests for crux.stats.

The Fisher literals below were hand-derived from the hypergeometric tail
(integer binomials, one division) and cross-checked against
scipy.stats.fisher_exact(alternative="greater"). scipy itself is not a
dependency of this suite.

The two Monte Carlo suites at the bottom exercise the whole engine and
only run once crux.search and crux.backends.local exist; importorskip
keeps this file green while sibling modules are still being written.
"""

import pytest

from crux.stats import (
    fisher_exact_greater,
    holm,
    look_alpha,
    trial_seed,
    wilson_ci,
)


class TestFisherExactGreater:
    def test_strong_effect(self):
        # 2x2 table (succ, fail):  branch 8, 2 / baseline 2, 8
        # N=20, K=10, draws=10. Tail P(X>=8) = (45*45 + 10*10 + 1*1) / C(20,10)
        # = 2126 / 184756 = 1063/92378.
        assert fisher_exact_greater(8, 10, 2, 10) == pytest.approx(
            0.011507068782610578, abs=1e-9
        )

    def test_perfect_separation(self):
        # branch 5, 0 / baseline 0, 5. P(X>=5) = C(5,5)*C(5,0)/C(10,5) = 1/252.
        assert fisher_exact_greater(5, 5, 0, 5) == pytest.approx(
            0.003968253968253968, abs=1e-9
        )

    def test_wrong_direction_is_large(self):
        # branch 3, 7 / baseline 7, 3. The branch is worse, so the one-sided
        # p is near 1: P(X>=3) = 1 - 2126/184756 = 91315/92378.
        assert fisher_exact_greater(3, 10, 7, 10) == pytest.approx(
            0.9884929312173895, abs=1e-9
        )

    def test_unbalanced_margins(self):
        # branch 4, 8 / baseline 1, 7. N=20, K=5, draws=12.
        # P(X>=4) = (5*6435 + 1*6435) / C(20,12) = 38610/125970 = 99/323.
        assert fisher_exact_greater(4, 12, 1, 8) == pytest.approx(
            0.3065015479876161, abs=1e-9
        )

    def test_equal_rates(self):
        # branch 2, 6 / baseline 2, 6. Same rate on both sides, p well
        # above any alpha: 93/130.
        assert fisher_exact_greater(2, 8, 2, 8) == pytest.approx(
            0.7153846153846154, abs=1e-9
        )

    def test_zero_trials_both_sides(self):
        assert fisher_exact_greater(0, 0, 0, 0) == 1.0

    def test_zero_trials_one_side(self):
        assert fisher_exact_greater(0, 0, 3, 10) == 1.0
        assert fisher_exact_greater(3, 10, 0, 0) == 1.0

    def test_all_successes(self):
        # Constant success column carries no evidence.
        assert fisher_exact_greater(10, 10, 10, 10) == 1.0

    def test_all_failures(self):
        assert fisher_exact_greater(0, 10, 0, 10) == 1.0

    def test_invalid_counts_raise(self):
        with pytest.raises(ValueError):
            fisher_exact_greater(5, 3, 0, 10)
        with pytest.raises(ValueError):
            fisher_exact_greater(-1, 3, 0, 10)


class TestHolm:
    def test_all_rejected_when_each_clears_its_step(self):
        # m=3: thresholds 0.05/3, 0.05/2, 0.05/1 in sorted order.
        result = holm({"a": 0.001, "b": 0.02, "c": 0.04}, alpha=0.05)
        assert result == {"a": True, "b": True, "c": True}

    def test_step_down_stops_at_first_failure(self):
        # b at rank 2 needs p <= 0.025 and misses. c would clear 0.05 on
        # its own but the walk has already stopped.
        result = holm({"a": 0.001, "b": 0.03, "c": 0.04}, alpha=0.05)
        assert result == {"a": True, "b": False, "c": False}

    def test_none_rejected(self):
        result = holm({"a": 0.2, "b": 0.5}, alpha=0.05)
        assert result == {"a": False, "b": False}

    def test_single_hypothesis_uses_full_alpha(self):
        assert holm({"only": 0.049}, alpha=0.05) == {"only": True}
        assert holm({"only": 0.051}, alpha=0.05) == {"only": False}

    def test_empty_input(self):
        assert holm({}, alpha=0.05) == {}

    def test_tie_break_is_deterministic(self):
        # Equal p-values sort by id, so dict insertion order cannot
        # change the outcome.
        forward = holm({"x": 0.02, "y": 0.02}, alpha=0.05)
        backward = holm({"y": 0.02, "x": 0.02}, alpha=0.05)
        assert forward == backward


class TestWilsonCi:
    def test_bounds_within_unit_interval(self):
        for succ, n in [(0, 1), (1, 1), (3, 8), (7, 8), (120, 240)]:
            low, high = wilson_ci(succ, n)
            assert 0.0 <= low <= high <= 1.0

    def test_interval_contains_point_estimate(self):
        low, high = wilson_ci(3, 10)
        assert low < 0.3 < high

    def test_zero_successes_lower_bound_is_zero(self):
        low, high = wilson_ci(0, 20)
        assert low == 0.0
        assert 0.0 < high < 1.0

    def test_all_successes_upper_bound_is_one(self):
        low, high = wilson_ci(20, 20)
        assert high == 1.0
        assert 0.0 < low < 1.0

    def test_zero_trials_is_vacuous(self):
        assert wilson_ci(0, 0) == (0.0, 1.0)

    def test_narrows_with_more_trials(self):
        low_small, high_small = wilson_ci(5, 10)
        low_big, high_big = wilson_ci(50, 100)
        assert (high_big - low_big) < (high_small - low_small)


class TestTrialSeed:
    def test_deterministic(self):
        assert trial_seed(7, "baseline", 0) == trial_seed(7, "baseline", 0)

    def test_varies_with_each_component(self):
        base = trial_seed(7, "baseline", 0)
        assert trial_seed(8, "baseline", 0) != base
        assert trial_seed(7, "no-cookie_banner", 0) != base
        assert trial_seed(7, "baseline", 1) != base

    def test_matches_sha256_definition(self):
        import hashlib

        digest = hashlib.sha256(b"7:baseline:0").digest()
        assert trial_seed(7, "baseline", 0) == int.from_bytes(digest[:8], "big")

    def test_fits_in_64_bits(self):
        for i in range(50):
            assert 0 <= trial_seed(7, "no-x", i) < 2**64


class TestLookAlpha:
    def test_divides_evenly(self):
        assert look_alpha(0.05, 6) == pytest.approx(0.05 / 6)

    def test_single_round_spends_everything(self):
        assert look_alpha(0.05, 1) == 0.05

    def test_zero_rounds_rejected(self):
        with pytest.raises(ValueError):
            look_alpha(0.05, 0)


def test_type_one_error_rate():
    """No-effect world: over 100 seeded runs, false causes must be rare.

    Every factor is inert, so any non-None verdict is a false positive.
    The whole procedure (sequential looks, Holm, confirmation batch) has
    to hold the family-wise error near alpha; 0.08 leaves slack for
    Monte Carlo noise at 100 runs.
    """
    search = pytest.importorskip("crux.search")
    local = pytest.importorskip("crux.backends.local")
    fixture = pytest.importorskip("crux.fixture")
    from crux.models import InvestigationConfig

    false_causes = 0
    for seed in range(100):
        world = local.NoEffectWorld()
        try:
            inv = search.investigate(
                world,
                fixture.oracle,
                fixture.FACTORS,
                InvestigationConfig(seed=seed),
                scenario_name="no-effect",
            )
        finally:
            world.close()
        assert inv.verdict is not None
        if inv.verdict.cause is not None:
            false_causes += 1
    assert false_causes / 100 <= 0.08


def test_power_on_default_scenario():
    """Demo world: the planted cause should be found in >= 90% of runs."""
    search = pytest.importorskip("crux.search")
    local = pytest.importorskip("crux.backends.local")
    fixture = pytest.importorskip("crux.fixture")
    from crux.models import InvestigationConfig

    found = 0
    for seed in range(60):
        world = local.LocalWorld()
        try:
            inv = search.investigate(
                world,
                fixture.oracle,
                fixture.FACTORS,
                InvestigationConfig(seed=seed),
                scenario_name="invoice_demo",
            )
        finally:
            world.close()
        assert inv.verdict is not None
        cause = inv.verdict.cause
        if cause is not None and "two_column_layout" in cause:
            found += 1
    assert found / 60 >= 0.9
