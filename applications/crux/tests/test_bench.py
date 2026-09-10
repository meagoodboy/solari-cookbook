"""Structural and directional checks for the operating-characteristics study.

The structural tests run the whole bench at 12 seeds per family and
check shapes, determinism and the output files. The directional tests
run 40 seeds on the two families with the sharpest expected contrasts
and assert with generous margins, so they stay stable under any change
that keeps the procedure roughly calibrated.
"""

from __future__ import annotations

import json
from functools import lru_cache

import pytest

pytest.importorskip("crux.fixture")
pytest.importorskip("crux.backends.local")

from crux.bench import (
    FAMILY_NAMES,
    FIXED_TOTAL_TRIALS,
    METHODS,
    NAIVE_TRIALS_PER_BRANCH,
    run_bench,
    run_family,
    write_outputs,
)
from crux.stats import trial_seed

MASTER_SEED = 7
SMALL_SEEDS = 12
DIRECTIONAL_SEEDS = 40


@lru_cache(maxsize=None)
def _small_results():
    return run_bench(seeds=SMALL_SEEDS, master_seed=MASTER_SEED)


@lru_cache(maxsize=None)
def _directional(family: str):
    return run_family(family, seeds=DIRECTIONAL_SEEDS, master_seed=MASTER_SEED)


def _crux_outcomes(records):
    return [record["methods"]["crux"]["outcome"] for record in records]


def test_families_and_methods_are_complete() -> None:
    results = _small_results()
    assert set(FAMILY_NAMES) == {
        "layout-cause",
        "no-cause",
        "conjunction-cause",
        "weak-cause",
    }
    records = results["records"]
    assert len(records) == len(FAMILY_NAMES) * SMALL_SEEDS
    for record in records:
        assert record["family"] in FAMILY_NAMES
        assert set(record["methods"]) == set(METHODS)


def test_record_shapes_and_outcomes() -> None:
    for record in _small_results()["records"]:
        truth = record["truth"]
        assert record["instance_seed"] == trial_seed(
            MASTER_SEED, record["family"], record["index"]
        )
        for method, result in record["methods"].items():
            assert result["outcome"] in {"correct", "wrong", "none"}
            conviction = result["conviction"]
            if conviction is None:
                assert result["outcome"] == "none"
            elif truth is not None and set(conviction) == set(truth):
                assert result["outcome"] == "correct"
            else:
                assert result["outcome"] == "wrong"
            assert result["trials"] > 0
        crux = record["methods"]["crux"]
        assert crux["rounds"] >= 1
        assert crux["confirmations"] >= 0
        assert record["methods"]["naive-gap"]["trials"] == (
            NAIVE_TRIALS_PER_BRANCH * 6
        )
        assert record["methods"]["fixed-budget"]["trials"] == FIXED_TOTAL_TRIALS


def test_baseline_methods_never_convict_a_pair() -> None:
    for record in _small_results()["records"]:
        for method in ("naive-gap", "fixed-budget"):
            conviction = record["methods"][method]["conviction"]
            assert conviction is None or len(conviction) == 1


def test_aggregates_cover_every_cell_and_sum_to_100() -> None:
    aggregates = _small_results()["aggregates"]
    for family in FAMILY_NAMES:
        for method in METHODS:
            entry = aggregates[family][method]
            assert entry["instances"] == SMALL_SEEDS
            total = entry["correct_pct"] + entry["wrong_pct"] + entry["none_pct"]
            assert total == pytest.approx(100.0, abs=0.5)
            if method == "crux":
                assert "mean_rounds" in entry
                assert "mean_confirmations" in entry
            else:
                assert "mean_rounds" not in entry


def test_run_family_is_deterministic() -> None:
    fresh = run_family("layout-cause", seeds=2, master_seed=MASTER_SEED)
    cached = [
        record
        for record in _small_results()["records"]
        if record["family"] == "layout-cause"
    ][:2]
    assert fresh == cached


def test_outputs_round_trip(tmp_path) -> None:
    results = _small_results()
    out_dir = write_outputs(results, tmp_path / "bench")
    loaded = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert loaded == results
    assert loaded["metadata"]["master_seed"] == MASTER_SEED
    assert loaded["metadata"]["seeds_per_family"] == SMALL_SEEDS
    assert loaded["metadata"]["config"]["alpha"] == 0.05

    text = (out_dir / "RESULTS.md").read_text(encoding="utf-8")
    assert "\u2014" not in text
    assert "\u2013" not in text
    assert "## Scoring" in text
    for family in FAMILY_NAMES:
        assert family in text
    for method in METHODS:
        assert method in text


def test_naive_gap_convicts_wildly_on_no_cause() -> None:
    records = _directional("no-cause")
    wrong = sum(
        1
        for record in records
        if record["methods"]["naive-gap"]["outcome"] == "wrong"
    )
    assert wrong / len(records) >= 0.50


def test_crux_rarely_convicts_on_no_cause() -> None:
    outcomes = _crux_outcomes(_directional("no-cause"))
    wrong = sum(1 for outcome in outcomes if outcome == "wrong")
    assert wrong / len(outcomes) <= 0.10


def test_crux_finds_the_layout_cause() -> None:
    outcomes = _crux_outcomes(_directional("layout-cause"))
    correct = sum(1 for outcome in outcomes if outcome == "correct")
    assert correct / len(outcomes) >= 0.70


def test_crux_spends_fewer_trials_than_fixed_budget_on_layout() -> None:
    records = _directional("layout-cause")
    mean_trials = sum(
        record["methods"]["crux"]["trials"] for record in records
    ) / len(records)
    assert mean_trials < FIXED_TOTAL_TRIALS
