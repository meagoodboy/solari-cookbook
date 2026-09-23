import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from crux.cli import main as crux_main
from crux.models import RawRun
from flake_conviction.convict import build_config, build_specs, build_stage, run
from flake_conviction.session import fixture_bytes

SUITE = fixture_bytes("ledger_suite.py")
DECOYS = ({"FIXTURE_TEST_ORDER": "987654321"}, {"TZ": "Asia/Kolkata"},
          {"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"})
CONFIG = build_config(11, 6, 10)
CENSUS = {"by_state": {"gone": 3}, "tagged_this_run": 0, "snapshots_total": 6}


def suite(cwd, *args, **env) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "ledger_suite.py", *args], cwd=cwd,
                          env={**os.environ, **env}, capture_output=True, text=True)


def record_expectation(cwd: Path) -> None:
    (cwd / "ledger_suite.py").write_bytes(SUITE)
    (cwd / "expected.txt").write_text(suite(cwd, "--record", PYTHONHASHSEED="0").stdout)


class StubWorld:
    """Fails exactly under hash randomization; artifacts carry what crux's Solari world records."""

    def __init__(self, lose_clones=False) -> None:
        self.closed, self.lose_clones = 0, lose_clones

    def snapshot(self) -> str:
        return "stub-0"

    def run_trial(self, snapshot, assignment, seed) -> RawRun:
        if self.lose_clones:
            raise RuntimeError("clone lost")
        code = 1 if assignment["hash_randomization"] else 0
        artifact = {"exit_code": code, "timed_out": False, "seed": seed, "env_overrides": {},
                    "attestation": {"ok": True, "level": "content", "digest": "56dcada0aadc" * 5},
                    "platform": {"clone": f"sbx-{seed % 10 ** 12:012d}", "ms": {"total": 23000}}}
        return RawRun(artifact=artifact, transcript=(f"exit {code}",), duration_ms=23000)

    def close(self) -> None:
        self.closed += 1

    def to_spec(self) -> dict:
        return {"kind": "stub"}

    def platform_report(self) -> dict:
        return {"counts": {"clones_created": 50, "clones_killed": 50, "reaped": 0, "filter_leaks": 0},
                "attestation": {"level": "content", "refusals": 0},
                "inventory": {"before": CENSUS, "after": CENSUS},
                "cleanup": {"clean": True, "snapshot_deleted": True}}


class FixtureTests(unittest.TestCase):
    def test_fixture_flakes_under_hash_randomization_and_passes_under_seed_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_expectation(Path(tmp))
            self.assertEqual(suite(tmp, PYTHONHASHSEED="0").returncode, 0)
            failed = sum(suite(tmp, PYTHONHASHSEED=str(s)).returncode != 0 for s in range(1, 13))
        self.assertGreaterEqual(failed, 6)

    def test_decoys_are_inert_with_the_seed_pinned(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_expectation(Path(tmp))
            for decoy in DECOYS:
                self.assertEqual(suite(tmp, PYTHONHASHSEED="0", **decoy).returncode, 0, decoy)

    def test_build_stage_is_static_and_carries_the_suite_through_env(self):
        stage = build_stage()
        self.assertEqual(stage.script.encode("utf-8"), fixture_bytes("build.sh"))
        self.assertNotIn("{", stage.script)
        self.assertEqual(stage.env["SUITE_SOURCE"].encode("utf-8"), SUITE)
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, **stage.env, "FIXTURE_DIR": f"{tmp}/fixture"}
            done = subprocess.run(["bash", "-c", stage.script], env=env, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stdout)
            self.assertTrue(Path(tmp, "fixture", "expected.txt").is_file())
        self.assertRegex(done.stdout, r"active arm: \d+ of 12")

    def test_neutral_side_of_hash_randomization_disables_it_outright(self):
        specs = {spec.factor_id: spec for spec in build_specs()}
        self.assertEqual(specs["hash_randomization"].neutral, {"PYTHONHASHSEED": "0"})
        self.assertIn("{seed32}", specs["hash_randomization"].active["PYTHONHASHSEED"])
        for factor_id in ("test_order", "timezone", "locale"):
            self.assertNotIn("PYTHONHASHSEED", {**specs[factor_id].active, **specs[factor_id].neutral})


class BundleTests(unittest.TestCase):
    def test_bundle_from_a_stub_world_passes_crux_verify_recorded(self):
        world = StubWorld()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, "bundle")
            self.assertEqual(run(world, out, CONFIG, lambda line: None), 0)
            for name in ("investigation.json", "world.json", "platform.json", "report.md"):
                self.assertTrue((out / name).is_file(), name)
            recorded = json.loads((out / "investigation.json").read_text("utf-8"))
            self.assertEqual(recorded["verdict"]["cause"], ["hash_randomization"])
            with redirect_stdout(io.StringIO()):
                self.assertEqual(crux_main(["verify", str(out), "--recorded"]), 0)
        self.assertEqual(world.closed, 1)

    def test_close_runs_when_investigate_raises(self):
        world = StubWorld(lose_clones=True)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RuntimeError):
            run(world, Path(tmp, "bundle"), CONFIG, lambda line: None)
        self.assertEqual(world.closed, 1)

    def test_summary_reads_attestation_and_cleanup_from_the_bundle(self):
        lines = []
        with tempfile.TemporaryDirectory() as tmp:
            run(StubWorld(), Path(tmp, "bundle"), CONFIG, lines.append)
        text = "\n".join(lines)
        self.assertIn("clones   50 trials in 50 clones, 50 attested at content level, "
                      "1 distinct world digest 56dcada0aadc, 0 refusals", text)
        self.assertIn("cleanup  created 50, killed 50, reaped 0, snapshot deleted, filter leaks 0, clean", text)
        self.assertIn("verdict  Neutralizing", text)
        self.assertNotIn("sbx_", text)


if __name__ == "__main__":
    unittest.main()
