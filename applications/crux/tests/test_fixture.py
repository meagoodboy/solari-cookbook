"""Calibration and mechanism tests for the invoice fixture.

The rate checks run 2000 trials per arm with seeds derived from the
default config seed, so every number here is reproducible. All arms
share the per-index seed stream. That pairs the draws across arms and
keeps each measured delta close to the true effect size.
"""

from __future__ import annotations

import hashlib
import random
from functools import lru_cache
from typing import Any

from crux.backends.local import ConjunctionWorld, LocalWorld, NoEffectWorld
from crux.fixture import (
    FACTORS,
    LARGE_INVOICE_P,
    generate_invoice,
    oracle,
    render_page,
    run_agent,
)

CONFIG_SEED = 7
TRIALS = 2000

FACTOR_IDS = tuple(f.id for f in FACTORS)
NOISE_IDS = ("cookie_banner", "model_temperature", "network_latency", "context_trim")

WEAK_LARGE_INVOICE_P = 0.10

_WORLDS = {
    "local": LocalWorld,
    "noeffect": NoEffectWorld,
    "conjunction": ConjunctionWorld,
    "weak": lambda: LocalWorld(large_invoice_p=WEAK_LARGE_INVOICE_P),
}


def _seed(index: int) -> int:
    digest = hashlib.sha256(f"{CONFIG_SEED}:calibration:{index}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _assignment(neutralized: tuple[str, ...] = ()) -> dict[str, bool]:
    return {factor_id: factor_id not in neutralized for factor_id in FACTOR_IDS}


@lru_cache(maxsize=None)
def _failure_rate(
    world_name: str, neutralized: tuple[str, ...] = (), trials: int = TRIALS
) -> float:
    world = _WORLDS[world_name]()
    assignment = _assignment(neutralized)
    failures = 0
    for index in range(trials):
        run = world.run_trial(world.snapshot(), assignment, _seed(index))
        passed, _ = oracle(run.artifact)
        if not passed:
            failures += 1
    world.close()
    return failures / trials


def test_factor_ids_match_the_contract() -> None:
    assert FACTOR_IDS == (
        "two_column_layout",
        "cookie_banner",
        "model_temperature",
        "network_latency",
        "context_trim",
    )


def test_baseline_failure_rate_in_band() -> None:
    assert 0.26 <= _failure_rate("local") <= 0.38


def test_neutralizing_the_layout_nearly_fixes_it() -> None:
    assert _failure_rate("local", ("two_column_layout",)) <= 0.07


def test_noise_factors_barely_move_the_rate() -> None:
    baseline = _failure_rate("local")
    for factor_id in NOISE_IDS:
        moved = _failure_rate("local", (factor_id,))
        assert abs(moved - baseline) < 0.04, factor_id


def _large_invoice() -> dict[str, Any]:
    line_items = [
        {"description": f"part #{index:02d}", "amount_cents": 1_000 + index}
        for index in range(12)
    ]
    return {
        "vendor": "Acme Supply Co",
        "po_number": "PO-123456",
        "line_items": line_items,
        "expected_total": sum(item["amount_cents"] for item in line_items),
    }


# Only the layout factor active, so no noise event can fire and the
# extraction path is the sole thing under test.
_QUIET = {
    "two_column_layout": True,
    "cookie_banner": False,
    "model_temperature": False,
    "network_latency": False,
    "context_trim": False,
}


def test_two_column_bug_is_real_agent_code() -> None:
    page = render_page(_large_invoice(), _QUIET)
    assert len(page["columns"]) == 2
    artifact = run_agent(page, _QUIET, random.Random(0))
    first_column_sum = sum(item["amount_cents"] for item in page["columns"][0])
    assert artifact["total_entered"] == first_column_sum
    assert artifact["total_entered"] != artifact["expected_total"]
    passed, detail = oracle(artifact)
    assert not passed
    assert "total mismatch" in detail


def test_neutralized_layout_renders_one_column_and_passes() -> None:
    assignment = dict(_QUIET, two_column_layout=False)
    page = render_page(_large_invoice(), assignment)
    assert len(page["columns"]) == 1
    artifact = run_agent(page, assignment, random.Random(0))
    assert artifact["total_entered"] == artifact["expected_total"]
    assert oracle(artifact)[0]


def test_ten_items_or_fewer_never_split() -> None:
    invoice = _large_invoice()
    invoice["line_items"] = invoice["line_items"][:10]
    invoice["expected_total"] = sum(
        item["amount_cents"] for item in invoice["line_items"]
    )
    page = render_page(invoice, _QUIET)
    assert len(page["columns"]) == 1
    artifact = run_agent(page, _QUIET, random.Random(0))
    assert oracle(artifact)[0]


def test_large_invoice_probability_matches_the_constant() -> None:
    rng = random.Random(CONFIG_SEED)
    large = sum(
        1 for _ in range(TRIALS) if len(generate_invoice(rng)["line_items"]) > 10
    )
    assert abs(large / TRIALS - LARGE_INVOICE_P) <= 0.05


def test_large_invoice_prevalence_hook() -> None:
    rng = random.Random(CONFIG_SEED)
    large = sum(
        1
        for _ in range(TRIALS)
        if len(generate_invoice(rng, WEAK_LARGE_INVOICE_P)["line_items"]) > 10
    )
    assert abs(large / TRIALS - WEAK_LARGE_INVOICE_P) <= 0.03


def test_default_prevalence_matches_explicit_default() -> None:
    plain = LocalWorld()
    explicit = LocalWorld(large_invoice_p=LARGE_INVOICE_P)
    assignment = _assignment()
    for index in range(50):
        seed = _seed(index)
        assert plain.run_trial(plain.snapshot(), assignment, seed) == (
            explicit.run_trial(explicit.snapshot(), assignment, seed)
        )


def test_weak_world_failure_rates() -> None:
    baseline = _failure_rate("weak")
    assert baseline < 0.20
    assert _failure_rate("weak", ("two_column_layout",)) <= 0.07


def test_oracle_rules() -> None:
    good = {
        "po_entered": "PO-000001",
        "total_entered": 500,
        "expected_po": "PO-000001",
        "expected_total": 500,
        "timed_out": False,
        "steps": [],
    }
    assert oracle(good) == (True, "po and total both correct")
    assert not oracle(dict(good, timed_out=True))[0]
    assert not oracle(dict(good, po_entered="PO-000002"))[0]
    assert not oracle(dict(good, po_entered=""))[0]
    assert not oracle(dict(good, total_entered=501))[0]
    assert not oracle(dict(good, total_entered=None))[0]


def test_local_world_is_deterministic() -> None:
    world = LocalWorld()
    assignment = _assignment()
    first = world.run_trial(world.snapshot(), assignment, 12345)
    second = world.run_trial(world.snapshot(), assignment, 12345)
    assert first == second
    assert first.transcript == tuple(first.artifact["steps"])


def test_no_effect_world_ignores_the_assignment() -> None:
    world = NoEffectWorld()
    all_on = world.run_trial(world.snapshot(), _assignment(), 99)
    all_off = world.run_trial(world.snapshot(), _assignment(FACTOR_IDS), 99)
    assert all_on == all_off


def test_no_effect_world_failure_rate_near_thirty_percent() -> None:
    assert 0.26 <= _failure_rate("noeffect") <= 0.34


def test_conjunction_world_needs_both_factors_neutralized() -> None:
    baseline = _failure_rate("conjunction", (), 1000)
    banner_only = _failure_rate("conjunction", ("cookie_banner",), 1000)
    latency_only = _failure_rate("conjunction", ("network_latency",), 1000)
    both = _failure_rate(
        "conjunction", ("cookie_banner", "network_latency"), 1000
    )
    assert 0.54 <= baseline <= 0.66
    assert abs(banner_only - baseline) < 0.06
    assert abs(latency_only - baseline) < 0.06
    assert both <= 0.06
