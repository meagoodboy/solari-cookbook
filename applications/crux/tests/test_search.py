"""Tests for the sequential search procedure in crux.search."""

import random

import pytest

pytest.importorskip("crux.stats")
fixture = pytest.importorskip("crux.fixture")
local = pytest.importorskip("crux.backends.local")

from crux.models import Factor, InvestigationConfig, RawRun
from crux.search import branch_id_for, investigate

NOISE_IDS = {"cookie_banner", "model_temperature", "network_latency", "context_trim"}


def plain_oracle(artifact):
    return (artifact["ok"], "ok" if artifact["ok"] else "failed")


class BothOffWorld:
    """A constructed conjunction: trials pass reliably only when both
    cookie_banner and network_latency are neutralized. Either one alone
    changes nothing, so single branches look futile and only a pairwise
    branch can flip the outcome.
    """

    def snapshot(self):
        return "conj-0"

    def run_trial(self, snapshot, assignment, seed):
        rng = random.Random(seed)
        both_off = not assignment.get("cookie_banner", True) and not assignment.get(
            "network_latency", True
        )
        ok = rng.random() < (0.97 if both_off else 0.30)
        return RawRun(artifact={"ok": ok}, transcript=("trial",), duration_ms=3)

    def close(self):
        pass


CONJ_FACTORS = (
    Factor("cookie_banner", "the cookie consent banner"),
    Factor("network_latency", "injected network latency"),
    Factor("context_trim", "aggressive context trimming"),
)


def run_demo(seed: int = 7):
    world = local.LocalWorld()
    try:
        return investigate(
            world,
            fixture.oracle,
            fixture.FACTORS,
            InvestigationConfig(seed=seed),
            "demo",
        )
    finally:
        world.close()


def test_finds_two_column_layout_on_default_seed():
    inv = run_demo()
    v = inv.verdict
    assert v is not None
    assert v.cause == ("two_column_layout",)
    assert v.confirmation_p is not None
    assert v.confirmation_p <= inv.config.alpha
    assert v.trials_total == len(inv.trials)
    assert len(inv.trials) <= inv.config.max_trials
    assert inv.investigation_id == "demo-seed7"


def test_noise_factors_absent_from_cause():
    inv = run_demo()
    assert inv.verdict.cause is not None
    assert not (set(inv.verdict.cause) & NOISE_IDS)


def test_verdict_summary_names_the_cause_and_avoids_em_dashes():
    inv = run_demo()
    summary = inv.verdict.summary
    assert summary
    assert "\u2014" not in summary
    assert "\u2013" not in summary
    lookup = {f.id: f.description for f in fixture.FACTORS}
    assert lookup["two_column_layout"] in summary


def test_replay_is_deterministic_by_seed():
    first = run_demo()
    second = run_demo()
    assert first.investigation_id == second.investigation_id
    assert first.verdict.cause == second.verdict.cause
    assert [t.seed for t in first.trials] == [t.seed for t in second.trials]


def test_confirmation_seeds_are_fresh():
    inv = run_demo()
    seeds = [t.seed for t in inv.trials]
    assert len(seeds) == len(set(seeds))
    confirmations = [
        c for e in inv.round_log for c in e.get("confirmations", [])
    ]
    assert confirmations
    assert any(c["passed"] for c in confirmations)


def test_round_log_shape_and_alpha_spending():
    inv = run_demo()
    assert inv.round_log
    expected_alpha = inv.config.alpha / inv.config.max_rounds
    for entry in inv.round_log:
        assert set(entry) >= {"round", "alpha_spent", "allocations", "p_values"}
        assert entry["alpha_spent"] == pytest.approx(expected_alpha)
        assert "baseline" in entry["allocations"]


def test_conjunction_resolves_via_pairwise_branch():
    causes = []
    for seed in (7, 11, 13):
        inv = investigate(
            BothOffWorld(),
            plain_oracle,
            CONJ_FACTORS,
            InvestigationConfig(max_trials=400, seed=seed),
            "conjunction",
        )
        cause = inv.verdict.cause
        causes.append(cause)
        if cause is not None:
            assert cause == ("cookie_banner", "network_latency")
            pair_id = branch_id_for(cause)
            assert pair_id in inv.branches
            assert len(inv.branches[pair_id].neutralized) == 2
            assert any(
                pair_id in entry["allocations"] for entry in inv.round_log
            )
            break
    assert any(c is not None for c in causes), (
        "no seed resolved the conjunction: " + repr(causes)
    )


def test_no_effect_scenario_returns_none():
    world = local.NoEffectWorld()
    try:
        inv = investigate(
            world, fixture.oracle, fixture.FACTORS, InvestigationConfig(), "no-effect"
        )
    finally:
        world.close()
    v = inv.verdict
    assert v.cause is None
    assert v.confirmation_p is None
    assert v.cause_rate is None
    assert v.summary
    assert "\u2014" not in v.summary


def test_budget_is_never_exceeded_even_when_tiny():
    world = local.LocalWorld()
    try:
        inv = investigate(
            world,
            fixture.oracle,
            fixture.FACTORS,
            InvestigationConfig(max_trials=30),
            "tiny",
        )
    finally:
        world.close()
    assert len(inv.trials) <= 30
    assert inv.verdict is not None


def test_investigation_id_falls_back_to_investigation():
    world = local.NoEffectWorld()
    try:
        inv = investigate(
            world,
            fixture.oracle,
            fixture.FACTORS,
            InvestigationConfig(max_trials=8, max_rounds=1, round_trials_per_branch=1),
        )
    finally:
        world.close()
    assert inv.investigation_id == "investigation-seed7"
    assert inv.scenario == ""


class _ReversedBatchWorld:
    """Wraps a world and executes each batch in reversed order.

    Results are restored to job order before returning, the contract
    run_trials promises. If investigate() produced anything different
    through this wrapper, result order would be leaking into the
    statistics.
    """

    def __init__(self, inner):
        self._inner = inner

    def snapshot(self):
        return self._inner.snapshot()

    def run_trial(self, snapshot, assignment, seed):
        return self._inner.run_trial(snapshot, assignment, seed)

    def run_trials(self, snapshot, jobs):
        jobs = list(jobs)
        reversed_results = [
            self._inner.run_trial(snapshot, assignment, seed)
            for assignment, seed in reversed(jobs)
        ]
        return list(reversed(reversed_results))

    def close(self):
        self._inner.close()


def test_batch_execution_order_does_not_change_the_investigation():
    fixture = pytest.importorskip("crux.fixture")
    local = pytest.importorskip("crux.backends.local")
    config = InvestigationConfig(seed=7)
    plain = investigate(
        local.LocalWorld(), fixture.oracle, fixture.FACTORS, config, "demo"
    )
    batched = investigate(
        _ReversedBatchWorld(local.LocalWorld()),
        fixture.oracle, fixture.FACTORS, config, "demo",
    )
    assert plain.to_dict() == batched.to_dict()
