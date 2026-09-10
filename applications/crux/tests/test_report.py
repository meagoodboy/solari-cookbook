"""Bundle writing: JSON round trip, report.md content, CSV shape."""

import csv
import json

import pytest

pytest.importorskip("crux.stats", reason="report.py imports wilson_ci from crux.stats")

from crux.models import (
    BranchState,
    Factor,
    Investigation,
    InvestigationConfig,
    TrialResult,
    Verdict,
)
from crux.report import write_bundle


def _decided_investigation() -> Investigation:
    factors = (
        Factor("layout_bug", "renders the page in two columns"),
        Factor("noise_knob", "adds random typos"),
    )
    branches = {
        "baseline": BranchState("baseline", (), trials=48, successes=30),
        "no-layout_bug": BranchState(
            "no-layout_bug", ("layout_bug",), trials=40, successes=38, p_value=0.0004
        ),
        "no-noise_knob": BranchState(
            "no-noise_knob",
            ("noise_knob",),
            trials=16,
            successes=9,
            p_value=0.61,
            dropped_for_futility=True,
        ),
    }
    trials = [
        TrialResult(
            branch_id="baseline",
            seed=101,
            passed=False,
            detail="total mismatch",
            artifact={"total_entered": 10.0, "expected_total": 22.5},
            duration_ms=120,
        ),
        TrialResult(
            branch_id="no-layout_bug",
            seed=202,
            passed=True,
            detail="ok",
            artifact={"total_entered": 22.5, "expected_total": 22.5},
            duration_ms=140,
        ),
    ]
    round_log = [
        {
            "round": 1,
            "alpha_spent": 0.05 / 6,
            "allocations": {"baseline": 8, "no-layout_bug": 8, "no-noise_knob": 8},
            "p_values": {"no-layout_bug": 0.03, "no-noise_knob": 0.7},
        },
        {
            "round": 2,
            "alpha_spent": 0.05 / 6,
            "allocations": {"baseline": 8, "no-layout_bug": 8},
            "p_values": {"no-layout_bug": 0.0004},
        },
    ]
    verdict = Verdict(
        cause=("layout_bug",),
        confirmation_p=0.0012,
        baseline_rate=30 / 48,
        cause_rate=38 / 40,
        alpha=0.05,
        trials_total=104,
        rounds=2,
        summary=(
            "Neutralizing layout_bug lifted the success rate from 30 of 48 at "
            "baseline to 38 of 40. A fresh confirmation batch agreed with "
            "p 0.0012. The two column layout is the cause."
        ),
    )
    return Investigation(
        investigation_id="demo-seed7",
        scenario="demo",
        factors=factors,
        config=InvestigationConfig(),
        branches=branches,
        trials=trials,
        round_log=round_log,
        verdict=verdict,
    )


def _undecided_investigation() -> Investigation:
    inv = _decided_investigation()
    inv.verdict = Verdict(
        cause=None,
        confirmation_p=None,
        baseline_rate=30 / 48,
        cause_rate=None,
        alpha=0.05,
        trials_total=240,
        rounds=6,
        summary=(
            "No suspect met the significance bar within budget. The closest "
            "branch was no-layout_bug at p 0.02 after correction."
        ),
    )
    return inv


def test_bundle_round_trip(tmp_path):
    inv = _decided_investigation()
    out = write_bundle(inv, tmp_path / "bundle")
    assert out == tmp_path / "bundle"

    data = json.loads((out / "investigation.json").read_text(encoding="utf-8"))
    loaded = Investigation.from_dict(data)

    assert set(loaded.branches) == set(inv.branches)
    for key, original in inv.branches.items():
        restored = loaded.branches[key]
        assert restored.trials == original.trials
        assert restored.successes == original.successes
        assert restored.p_value == original.p_value
        assert restored.neutralized == original.neutralized
        assert restored.dropped_for_futility == original.dropped_for_futility
    assert loaded.verdict is not None
    assert loaded.verdict.cause == ("layout_bug",)
    assert loaded.verdict.confirmation_p == pytest.approx(0.0012)
    assert len(loaded.trials) == len(inv.trials)


def test_report_md_names_cause_and_confirmation_p(tmp_path):
    inv = _decided_investigation()
    out = write_bundle(inv, tmp_path / "bundle")
    text = (out / "report.md").read_text(encoding="utf-8")

    assert "layout_bug" in text
    assert "0.0012" in text
    assert "crux verify" in text
    assert "\u2014" not in text  # em dash, written as an escape on purpose
    assert "\u2013" not in text  # en dash, same reason


def test_csv_has_one_row_per_branch(tmp_path):
    inv = _decided_investigation()
    out = write_bundle(inv, tmp_path / "bundle")
    with (out / "branches.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    assert len(rows) == len(inv.branches) + 1
    header = rows[0]
    assert "branch_id" in header
    assert "wilson_low" in header
    assert "wilson_high" in header
    body_ids = {row[0] for row in rows[1:]}
    assert body_ids == set(inv.branches)
    assert rows[1][0] == "baseline"


def test_undecided_bundle_still_renders(tmp_path):
    inv = _undecided_investigation()
    out = write_bundle(inv, tmp_path / "bundle")
    text = (out / "report.md").read_text(encoding="utf-8")

    assert "none met the significance bar" in text
    data = json.loads((out / "investigation.json").read_text(encoding="utf-8"))
    loaded = Investigation.from_dict(data)
    assert loaded.verdict is not None
    assert loaded.verdict.cause is None


def test_missing_verdict_bundle_still_renders(tmp_path):
    inv = _decided_investigation()
    inv.verdict = None
    out = write_bundle(inv, tmp_path / "bundle")
    text = (out / "report.md").read_text(encoding="utf-8")

    assert "No verdict was recorded" in text
    data = json.loads((out / "investigation.json").read_text(encoding="utf-8"))
    assert data["verdict"] is None
