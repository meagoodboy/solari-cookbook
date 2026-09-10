"""Tests for the zero-config flaky-command investigation."""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("crux.search")

from crux.flaky import (
    FLAKY_FACTORS,
    ProbeReport,
    build_flaky_specs,
    choose_hash_pin,
    command_scenario_name,
    parse_command,
    run_flaky,
)
from crux.models import InvestigationConfig

SMALL_CONFIG = InvestigationConfig(
    max_trials=160,
    max_rounds=4,
    round_trials_per_branch=6,
    confirm_trials=12,
    futility_min_trials=12,
    seed=7,
)


def _cmd(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_parse_command_forms():
    assert parse_command(["--", "python", "-m", "pytest"]) == ["python", "-m", "pytest"]
    assert parse_command(["python -m pytest tests/x.py"]) == [
        "python", "-m", "pytest", "tests/x.py",
    ]
    with pytest.raises(ValueError):
        parse_command(["--"])
    with pytest.raises(ValueError):
        parse_command([])


def test_parse_command_keeps_inner_separators_and_space_paths():
    # Only the leading -- is the crux separator; the command's own --
    # belongs to the command. And the -- form is never re-split, so an
    # executable path with a space survives.
    assert parse_command(["--", "npm", "test", "--", "--grep", "foo"]) == [
        "npm", "test", "--", "--grep", "foo",
    ]
    assert parse_command(["--", "/tmp/my app/run.sh"]) == ["/tmp/my app/run.sh"]


def test_scenario_name_differs_per_command():
    a = command_scenario_name(["python", "-m", "pytest", "tests/a.py"])
    b = command_scenario_name(["python", "-m", "pytest", "tests/b.py"])
    assert a != b
    assert a.startswith("flaky-")
    assert a == command_scenario_name(["python", "-m", "pytest", "tests/a.py"])


def test_choose_hash_pin_finds_the_passing_seed():
    code = "import os, sys; sys.exit(0 if os.environ.get('PYTHONHASHSEED') == '2' else 1)"
    pin, passed = choose_hash_pin(_cmd(code), ".", 30.0, 7, candidates=("1", "0", "2"))
    assert (pin, passed) == ("2", True)


def test_choose_hash_pin_rejects_a_lucky_single_pass(tmp_path):
    # Seed '1' passes exactly once (a state file flips it to failing),
    # seed '2' always passes. One-trial pinning would grab '1' and later
    # doom the neutral branch; the three-trial rule must reject it.
    marker = tmp_path / "seen-once"
    code = (
        "import os, pathlib, sys\n"
        f"marker = pathlib.Path({str(marker)!r})\n"
        "seed = os.environ.get('PYTHONHASHSEED')\n"
        "if seed == '2':\n"
        "    sys.exit(0)\n"
        "if seed == '1' and not marker.exists():\n"
        "    marker.write_text('used')\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n"
    )
    pin, passed = choose_hash_pin(
        _cmd(code), ".", 30.0, 7, candidates=("1", "0", "2")
    )
    assert (pin, passed) == ("2", True)


def test_choose_hash_pin_reports_when_nothing_passes():
    pin, passed = choose_hash_pin(
        _cmd("import sys; sys.exit(1)"), ".", 30.0, 7, candidates=("1", "0")
    )
    assert (pin, passed) == ("1", False)


def test_run_flaky_declines_when_nothing_fails():
    investigation, probe = run_flaky(
        _cmd("import sys; sys.exit(0)"), ".", SMALL_CONFIG, probe_runs=4
    )
    assert investigation is None
    assert isinstance(probe, ProbeReport)
    assert probe.baseline_failures == 0
    assert not probe.always_failed


def test_run_flaky_declines_a_plain_broken_command():
    investigation, probe = run_flaky(
        _cmd("import sys; sys.exit(1)"), ".", SMALL_CONFIG, probe_runs=4
    )
    assert investigation is None
    assert probe.always_failed
    assert not probe.hash_pin_passed


def test_run_flaky_convicts_hash_randomization_end_to_end():
    # A genuinely hash-dependent flake: whether hash('crux') lands on a
    # multiple of 3 depends only on the per-process hash seed, so the
    # baseline (seeded per trial) fails on a fraction of runs and the
    # pinned branch holds steady. The built-in lineup must convict
    # hash_randomization and nothing else.
    code = "import sys; sys.exit(1 if hash('crux') % 3 == 0 else 0)"
    investigation, probe = run_flaky(_cmd(code), ".", SMALL_CONFIG, probe_runs=8)
    assert probe.baseline_failures > 0
    assert investigation is not None
    assert investigation.verdict.cause == ("hash_randomization",)
    assert investigation.verdict.confirmation_p is not None
    assert investigation.verdict.confirmation_p < SMALL_CONFIG.alpha
    # Probe trials stay outside the investigation statistics.
    assert len(investigation.trials) == investigation.verdict.trials_total
    tallied = sum(b.trials for b in investigation.branches.values())
    assert tallied == investigation.verdict.trials_total


def test_specs_cover_every_factor_and_leave_the_world_alone():
    specs = build_flaky_specs("1")
    assert {spec.factor_id for spec in specs} == {f.id for f in FLAKY_FACTORS}
    for spec in specs:
        if spec.factor_id == "hash_randomization":
            assert spec.active == {"PYTHONHASHSEED": "{seed32}"}
        else:
            assert spec.active == {}
    by_id = {spec.factor_id: spec for spec in specs}
    assert "{seed}" in by_id["bytecode_cache"].neutral["PYTHONPYCACHEPREFIX"]


def test_parallel_investigation_matches_sequential():
    code = "import sys; sys.exit(1 if hash('crux') % 3 == 0 else 0)"
    sequential, _ = run_flaky(_cmd(code), ".", SMALL_CONFIG, probe_runs=8)
    parallel, _ = run_flaky(_cmd(code), ".", SMALL_CONFIG, probe_runs=8, parallel=4)
    assert sequential is not None and parallel is not None
    strip = lambda inv: [
        (t.branch_id, t.seed, t.passed) for t in inv.trials
    ]
    assert strip(sequential) == strip(parallel)
    assert sequential.verdict.cause == parallel.verdict.cause
    assert sequential.verdict.confirmation_p == parallel.verdict.confirmation_p


def test_flaky_bundle_replays_through_crux_verify(tmp_path):
    # The receipts table promises replay; this is the test that keeps
    # that promise true. A command bundle carries world.json, and crux
    # verify rebuilds the world from it and reaches the same cause.
    from crux.backends.command import CommandWorld
    from crux.cli import main as cli_main
    from crux.flaky import build_flaky_specs
    from crux.report import write_bundle

    code = "import sys; sys.exit(1 if hash('crux') % 3 == 0 else 0)"
    investigation, probe = run_flaky(_cmd(code), ".", SMALL_CONFIG, probe_runs=8)
    assert investigation is not None
    spec = CommandWorld(
        cmd=_cmd(code), cwd=".", specs=build_flaky_specs(probe.hash_pin),
        timeout_s=30.0,
    ).to_spec()
    bundle = tmp_path / "bundle"
    write_bundle(investigation, bundle, world_spec=spec)
    assert (bundle / "world.json").is_file()
    assert cli_main(["verify", str(bundle)]) == 0


def test_verify_refuses_unreplayable_bundle_with_exit_3(tmp_path):
    from crux.cli import main as cli_main
    from crux.report import write_bundle

    investigation, _ = run_flaky(
        _cmd("import sys; sys.exit(1 if hash('crux') % 3 == 0 else 0)"),
        ".", SMALL_CONFIG, probe_runs=8,
    )
    bundle = tmp_path / "no-world"
    write_bundle(investigation, bundle)
    assert cli_main(["verify", str(bundle)]) == 3
