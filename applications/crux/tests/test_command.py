"""Tests for the command backend.

Every trial here runs sys.executable -c with a tiny inline script, so
the suite needs nothing beyond the interpreter it is already running
under. The scripts stand in for a real flaky test suite: one fails on
odd seeds while its factor is active, one always passes, one sleeps
past the timeout, and one reports which env vars it can see.
"""

from __future__ import annotations

import os
import sys

from crux.backends.command import CommandWorld, FactorSpec, command_oracle

CWD = os.getcwd()

PARITY_SCRIPT = (
    "import os, sys; sys.exit(int(os.environ.get('CRUX_CHAOS', '0')) % 2)"
)
PARITY_SPEC = FactorSpec(
    factor_id="chaos",
    active={"CRUX_CHAOS": "{seed}"},
    neutral={"CRUX_CHAOS": "0"},
)


def _parity_world(timeout_s: float = 30.0) -> CommandWorld:
    return CommandWorld(
        cmd=[sys.executable, "-c", PARITY_SCRIPT],
        cwd=CWD,
        specs=[PARITY_SPEC],
        timeout_s=timeout_s,
    )


def test_seed_parity_flake() -> None:
    world = _parity_world()
    active = {"chaos": True}

    even = world.run_trial(world.snapshot(), active, seed=4)
    assert even.artifact["exit_code"] == 0
    assert command_oracle(even.artifact) == (True, "exit 0")

    odd = world.run_trial(world.snapshot(), active, seed=7)
    assert odd.artifact["exit_code"] == 1
    passed, detail = command_oracle(odd.artifact)
    assert not passed
    assert detail == "exit 1"

    # Neutralizing the factor pins the env var to 0, so the odd seed
    # that just failed now passes.
    calmed = world.run_trial(world.snapshot(), {"chaos": False}, seed=7)
    assert calmed.artifact["exit_code"] == 0
    assert command_oracle(calmed.artifact)[0]


def test_seed_substitution_and_artifact_shape() -> None:
    world = _parity_world()
    run = world.run_trial(world.snapshot(), {"chaos": True}, seed=41)

    assert run.artifact["seed"] == 41
    assert run.artifact["env_overrides"] == {"CRUX_CHAOS": "41"}
    assert run.artifact["timed_out"] is False
    assert isinstance(run.artifact["output_tail"], str)
    assert run.duration_ms >= 0

    # One transcript line per override, then the exit line.
    assert run.transcript == ("env CRUX_CHAOS=41", "exit 1")


def test_clean_pass() -> None:
    world = CommandWorld(
        cmd=[sys.executable, "-c", "print('all good')"],
        cwd=CWD,
        specs=[],
    )
    assert world.snapshot() == CWD
    run = world.run_trial(world.snapshot(), {}, seed=1)

    assert run.artifact["exit_code"] == 0
    assert run.artifact["timed_out"] is False
    assert run.artifact["env_overrides"] == {}
    assert "all good" in run.artifact["output_tail"]
    assert run.transcript == ("exit 0",)
    assert command_oracle(run.artifact) == (True, "exit 0")
    assert world.close() is None


def test_timeout_is_a_failure_not_an_exception() -> None:
    world = CommandWorld(
        cmd=[sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=CWD,
        specs=[],
        timeout_s=0.5,
    )
    run = world.run_trial(world.snapshot(), {}, seed=3)

    assert run.artifact["timed_out"] is True
    assert run.artifact["exit_code"] == -1
    passed, detail = command_oracle(run.artifact)
    assert not passed
    assert detail == "timed out"
    assert run.transcript[-1] == "timed out after 0.5s"


def test_overrides_do_not_leak_into_parent() -> None:
    marker = "CRUX_LEAK_PROBE"
    assert marker not in os.environ

    world = CommandWorld(
        cmd=[
            sys.executable,
            "-c",
            f"import os; print(os.environ.get('{marker}', 'unset'))",
        ],
        cwd=CWD,
        specs=[
            FactorSpec(
                factor_id="probe",
                active={marker: "planted"},
                neutral={},
            )
        ],
    )
    run = world.run_trial(world.snapshot(), {"probe": True}, seed=1)

    # The child saw the override; the parent never did.
    assert "planted" in run.artifact["output_tail"]
    assert marker not in os.environ


def test_env_base_replaces_inherited_environment() -> None:
    marker = "CRUX_BASE_PROBE"
    os.environ[marker] = "inherited"
    try:
        script = f"import os; print(os.environ.get('{marker}', 'unset'))"
        world = CommandWorld(
            cmd=[sys.executable, "-c", script],
            cwd=CWD,
            specs=[],
            env_base={"PATH": os.environ.get("PATH", "")},
        )
        run = world.run_trial(world.snapshot(), {}, seed=1)
        # With env_base given, os.environ is not copied in, so the
        # child cannot see the marker the parent holds.
        assert "unset" in run.artifact["output_tail"]
        assert run.artifact["exit_code"] == 0
    finally:
        del os.environ[marker]


def test_seed32_substitution_stays_in_hashseed_range():
    spec = FactorSpec(
        "hash", active={"PYTHONHASHSEED": "{seed32}"}, neutral={"PYTHONHASHSEED": "1"}
    )
    world = CommandWorld(
        cmd=[sys.executable, "-c", "import os; print(os.environ['PYTHONHASHSEED'])"],
        cwd=".",
        specs=[spec],
    )
    big_seed = 2**63 + 12345
    raw = world.run_trial(world.snapshot(), {"hash": True}, big_seed)
    value = int(raw.artifact["env_overrides"]["PYTHONHASHSEED"])
    assert 0 <= value < 2**32
    assert value == big_seed % 2**32
    assert raw.artifact["exit_code"] == 0


def test_resolve_overrides_is_shared_and_deterministic():
    from crux.backends.command import resolve_overrides

    specs = [
        FactorSpec("a", active={"X": "{seed}"}, neutral={"X": "0"}),
        FactorSpec("b", active={}, neutral={"Y": "off"}),
    ]
    active = resolve_overrides(specs, {"a": True, "b": True}, 42)
    assert active == {"X": "42"}
    neutral = resolve_overrides(specs, {"a": False, "b": False}, 42)
    assert neutral == {"X": "0", "Y": "off"}


def test_solari_command_trial_source_runs_and_prints_artifact(capsys):
    from crux.backends.solari_command import build_command_trial_source

    source = build_command_trial_source(
        cmd=[sys.executable, "-c", "import os; raise SystemExit(int(os.environ['RC']))"],
        cwd=".",
        overrides={"RC": "3"},
        seed=99,
        timeout_s=30.0,
    )
    namespace = {}
    exec(compile(source, "<clone>", "exec"), namespace)
    import json as jsonlib

    line = capsys.readouterr().out.strip().splitlines()[-1]
    artifact = jsonlib.loads(line)
    assert artifact["exit_code"] == 3
    assert artifact["timed_out"] is False
    assert artifact["seed"] == 99
    assert artifact["env_overrides"] == {"RC": "3"}


def test_solari_stage_source_raises_on_failure(capsys):
    from crux.backends.solari_command import build_stage_source

    good = build_stage_source("echo hello-stage")
    namespace = {}
    exec(compile(good, "<stage>", "exec"), namespace)
    out = capsys.readouterr().out
    assert "hello-stage" in out and "stage-ok" in out

    bad = build_stage_source("exit 7")
    try:
        exec(compile(bad, "<stage>", "exec"), {})
    except RuntimeError as exc:
        assert "rc=7" in str(exc)
    else:
        raise AssertionError("failing stage did not raise")


def test_world_spec_round_trip():
    world = CommandWorld(
        cmd=[sys.executable, "-c", "pass"], cwd="/tmp",
        specs=[FactorSpec("f", active={"A": "{seed32}"}, neutral={"A": "1"})],
        timeout_s=42.0, concurrency=3,
    )
    spec = world.to_spec()
    rebuilt = CommandWorld.from_spec(spec)
    assert rebuilt.to_spec() == spec
    assert spec["kind"] == "command" and spec["timeout_s"] == 42.0
