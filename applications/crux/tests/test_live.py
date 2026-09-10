"""Tests for the Solari backend helpers and the live entry point.

The pure helpers (source builders, result-item parser, gating in
live.main) run offline with fake objects. Anything that would touch the
network is skipped unless SOLARI_API_KEY is set.
"""

import io
import json
import os
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

import pytest

from crux import live
from crux.backends import solari

HAVE_KEY = bool(os.environ.get("SOLARI_API_KEY"))
LIVE_OPTED_IN = os.environ.get("CRUX_LIVE_TESTS") == "1"
# Both gates on purpose: a key sitting in the shell must not be enough
# for pytest to start creating billable sandboxes. Set CRUX_LIVE_TESTS=1
# to opt in explicitly.
needs_key = pytest.mark.skipif(
    not (HAVE_KEY and LIVE_OPTED_IN),
    reason="needs SOLARI_API_KEY and CRUX_LIVE_TESTS=1",
)

FAKE_FIXTURE = """\
def generate_invoice(rng):
    return {"po_number": str(rng.randint(1000, 9999))}


def render_page(invoice, assignment):
    layout = "two" if assignment.get("two_column_layout") else "one"
    return {"invoice": invoice, "layout": layout}


def run_agent(page, assignment, rng):
    return {
        "po_entered": page["invoice"]["po_number"],
        "layout_seen": page["layout"],
        "steps": ["open", "read", "type"],
        "noise": rng.random(),
    }


def oracle(artifact):
    return (True, "ok")
"""


def _item(kind, text):
    return SimpleNamespace(type=kind, text=text)


def _run_trial_source(assignment, seed, path):
    code = solari.build_trial_source(assignment, seed, path=str(path))
    out = io.StringIO()
    with redirect_stdout(out):
        exec(compile(code, "<trial>", "exec"), {})
    return json.loads(out.getvalue().strip().splitlines()[-1])


def test_importing_solari_backend_needs_no_sdk():
    # The module is already imported at the top of this file without the
    # extra being required; the lazy import is what makes that work.
    assert hasattr(solari, "SolariWorld")
    assert hasattr(solari, "parse_artifact")


def test_build_setup_source_writes_file_and_passes_sanity_check(tmp_path):
    target = tmp_path / "crux_fixture.py"
    code = solari.build_setup_source(FAKE_FIXTURE, path=str(target))
    out = io.StringIO()
    with redirect_stdout(out):
        exec(compile(code, "<setup>", "exec"), {})
    assert target.read_text(encoding="utf-8") == FAKE_FIXTURE
    assert "fixture-ready" in out.getvalue()


def test_build_setup_source_rejects_incomplete_fixture(tmp_path):
    broken = FAKE_FIXTURE.replace("def oracle", "def not_oracle")
    code = solari.build_setup_source(broken, path=str(tmp_path / "f.py"))
    with pytest.raises(RuntimeError, match="oracle"):
        exec(compile(code, "<setup>", "exec"), {})


def test_build_trial_source_runs_one_deterministic_trial(tmp_path):
    target = tmp_path / "crux_fixture.py"
    target.write_text(FAKE_FIXTURE, encoding="utf-8")
    assignment = {"two_column_layout": True, "cookie_banner": False}

    first = _run_trial_source(assignment, 12345, target)
    again = _run_trial_source(assignment, 12345, target)
    other_seed = _run_trial_source(assignment, 54321, target)
    other_assignment = _run_trial_source(
        {"two_column_layout": False, "cookie_banner": False}, 12345, target
    )

    assert first == again
    assert first["layout_seen"] == "two"
    assert first["steps"] == ["open", "read", "type"]
    assert other_seed["noise"] != first["noise"]
    assert other_assignment["layout_seen"] == "one"


def test_build_trial_source_rejects_non_int_seed():
    with pytest.raises(TypeError):
        solari.build_trial_source({}, "7")


def test_parse_artifact_reads_stdout_item():
    artifact = {"po_entered": "123", "steps": ["a"]}
    items = [
        _item("stderr", "some warning\n"),
        _item("stdout", json.dumps(artifact) + "\n"),
    ]
    assert solari.parse_artifact(items) == artifact


def test_parse_artifact_reads_result_item_and_prefers_last_json():
    early = {"po_entered": "old"}
    late = {"po_entered": "new", "total_entered": 42.0}
    items = [
        _item("stdout", json.dumps(early) + "\n"),
        _item("result", "noise line\n" + json.dumps(late)),
    ]
    assert solari.parse_artifact(items) == late


def test_parse_artifact_accepts_mapping_items():
    artifact = {"timed_out": False}
    items = [{"type": "stdout", "text": json.dumps(artifact)}]
    assert solari.parse_artifact(items) == artifact


def test_parse_artifact_raises_when_no_json_present():
    with pytest.raises(ValueError):
        solari.parse_artifact([_item("stdout", "hello world")])
    with pytest.raises(ValueError):
        solari.parse_artifact([_item("stderr", json.dumps({"x": 1}))])
    with pytest.raises(ValueError):
        solari.parse_artifact([])
    with pytest.raises(ValueError):
        solari.parse_artifact(None)


def test_fixture_source_embeds_the_real_module():
    pytest.importorskip("crux.fixture")
    source = solari.fixture_source()
    for name in ("generate_invoice", "render_page", "run_agent", "oracle"):
        assert f"def {name}" in source


def test_fixture_source_execs_standalone_like_the_sandbox_does():
    # The kernel execs the file with no package context, which is exactly
    # how a stray relative import or misplaced future import breaks. A grep
    # for def names missed that once; running the source is the real check.
    pytest.importorskip("crux.fixture")
    namespace = {}
    exec(compile(solari.fixture_source(), "<sandbox>", "exec"), namespace)
    for name in ("generate_invoice", "render_page", "run_agent", "oracle", "FACTORS"):
        assert name in namespace
    import random

    invoice = namespace["generate_invoice"](random.Random(7))
    assignment = {f.id: True for f in namespace["FACTORS"]}
    page = namespace["render_page"](invoice, assignment)
    artifact = namespace["run_agent"](page, assignment, random.Random(7))
    passed, detail = namespace["oracle"](artifact)
    assert isinstance(passed, bool) and isinstance(detail, str)


def test_live_factors_picks_the_two_suspects():
    pytest.importorskip("crux.fixture")
    factors = live.live_factors()
    assert tuple(f.id for f in factors) == live.LIVE_FACTOR_IDS


def test_live_config_and_clone_plan_numbers():
    config = live.build_live_config()
    assert config.max_rounds == 2
    assert config.round_trials_per_branch == 6
    assert config.confirm_trials == 16
    round_clones, confirm_clones = live.clone_plan(config)
    assert round_clones == 36
    assert confirm_clones == 32
    assert config.max_trials == round_clones + confirm_clones


def test_live_config_is_mathematically_decidable():
    # The point of this config is that a real effect CAN convict. The best
    # possible one-sided Fisher p for an n-versus-n round is 1/C(2n, n);
    # it must clear the Holm-corrected look bar, and the confirmation batch
    # must clear full alpha, or the live run is theater.
    import math

    config = live.build_live_config()
    n = config.round_trials_per_branch
    best_round_p = 1 / math.comb(2 * n, n)
    look_bar = (config.alpha / config.max_rounds) / len(live.LIVE_FACTOR_IDS)
    assert best_round_p < look_bar
    c = config.confirm_trials
    best_confirm_p = 1 / math.comb(2 * c, c)
    assert best_confirm_p < config.alpha


def test_main_exits_2_with_one_line_when_key_missing(monkeypatch, capsys):
    monkeypatch.delenv("SOLARI_API_KEY", raising=False)
    rc = live.main(["--yes"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "SOLARI_API_KEY" in captured.err
    assert len(captured.err.strip().splitlines()) == 1


def test_main_prints_plan_and_refuses_without_yes(monkeypatch, capsys):
    monkeypatch.setenv("SOLARI_API_KEY", "fake-key-for-gate-test")
    already_loaded = "solari_sandbox" in sys.modules
    rc = live.main([])
    out = capsys.readouterr().out
    round_clones, confirm_clones = live.clone_plan(live.build_live_config())
    assert rc == 1
    assert str(round_clones) in out
    assert str(confirm_clones) in out
    assert str(round_clones + confirm_clones) in out
    assert "charges" in out.lower()
    assert "--yes" in out
    if not already_loaded:
        # Refusing early means the SDK was never touched.
        assert "solari_sandbox" not in sys.modules


def test_run_trial_before_snapshot_is_an_error():
    world = solari.SolariWorld(api_key="fake-key-never-used")
    try:
        with pytest.raises(solari.SolariWorldError, match="snapshot"):
            world.run_trial("snap-x", {}, 1)
    finally:
        world.close()
    with pytest.raises(solari.SolariWorldError, match="closed"):
        world.snapshot()


def test_world_requires_an_api_key():
    with pytest.raises(solari.SolariWorldError):
        solari.SolariWorld(api_key="")


@needs_key
def test_solari_world_single_trial_roundtrip():
    pytest.importorskip("solari_sandbox")
    fixture = pytest.importorskip("crux.fixture")
    world = solari.SolariWorld(api_key=os.environ["SOLARI_API_KEY"])
    try:
        snap = world.snapshot()
        assert snap
        assert world.snapshot() == snap
        assignment = {factor.id: True for factor in fixture.FACTORS}
        run = world.run_trial(snap, assignment, seed=987654321)
        assert isinstance(run.artifact, dict)
        assert "po_entered" in run.artifact
        assert isinstance(run.transcript, tuple)
        assert run.duration_ms >= 0
    finally:
        world.close()
