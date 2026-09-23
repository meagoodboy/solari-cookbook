"""One crux investigation of the planted fixture, in forked Solari clones. The
bundle it writes is what makes the number replayable: `crux verify --recorded`
re-derives the verdict with no key, `crux verify --yes` rebuilds the world."""

import json
from pathlib import Path

from crux.backends.command import FactorSpec, command_oracle
from crux.backends.solari import Stage
from crux.models import Factor, InvestigationConfig
from crux.report import write_bundle
from crux.search import investigate

from .session import HOLDING, WORLD_DIR, fixture_bytes

SCENARIO = "flake-conviction"
FACTORS = (
    Factor("hash_randomization", "per-process string hash randomization"),
    Factor("test_order", "randomized test execution order"),
    Factor("timezone", "host timezone applied through TZ"),
    Factor("locale", "UTF-8 host locale"),
)


def build_specs() -> list[FactorSpec]:
    """The neutral side of hash_randomization is PYTHONHASHSEED=0, which turns
    randomization off, rather than a seed that was seen to pass: a passing seed
    is a property of one interpreter build, and a neutral arm that silently
    stopped passing would read as a cleared suspect."""
    return [
        FactorSpec("hash_randomization", active={"PYTHONHASHSEED": "{seed32}"},
                   neutral={"PYTHONHASHSEED": "0"}),
        FactorSpec("test_order", active={"FIXTURE_TEST_ORDER": "{seed32}"},
                   neutral={"FIXTURE_TEST_ORDER": "0"}),
        FactorSpec("timezone", active={"TZ": "Asia/Kolkata"}, neutral={"TZ": "UTC"}),
        FactorSpec("locale", active={"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
                   neutral={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}),
    ]


def build_stage() -> Stage:
    """The script is the shipped file and the suite travels as an env value, so
    nothing is built as a string and world.json carries both verbatim."""
    return Stage(name="build", script=fixture_bytes("build.sh").decode("utf-8"),
                 env={"FIXTURE_DIR": WORLD_DIR,
                      "SUITE_SOURCE": fixture_bytes("ledger_suite.py").decode("utf-8")})


def build_config(seed: int, round_trials: int, confirm: int) -> InvestigationConfig:
    """Six per branch is the smallest round that can convict: a clean 6-0 split
    gives Fisher p = 1/C(12,6), about 0.0011, under the corrected bar."""
    return InvestigationConfig(
        alpha=0.05, max_trials=worst_case(round_trials, confirm), max_rounds=1,
        round_trials_per_branch=round_trials, confirm_trials=confirm,
        futility_min_trials=16, pairwise_top_k=3, seed=seed)


def worst_case(round_trials: int, confirm: int) -> int:
    return (1 + len(FACTORS)) * round_trials + 2 * confirm


def build_world(key: str, say):
    #  Imported here so --help and the key check never load crux's Solari layer.
    from crux.backends.solari_command import SolariCommandWorld

    return SolariCommandWorld(
        api_key=key, setup_stages=[build_stage()], trial_cmd=["python3", "ledger_suite.py"],
        trial_cwd=WORLD_DIR, specs=build_specs(), snapshot_name=SCENARIO,
        trial_timeout_s=120.0, concurrency=1, attest_level="content",
        progress=lambda line: say(f"[crux] {line}"))


def run(world, out_dir: Path, config: InvestigationConfig, say) -> int:
    try:
        world.snapshot()
        investigation = investigate(world, command_oracle, FACTORS, config,
                                    scenario_name=SCENARIO)
    finally:
        world.close()
    #  After close(), so the platform report carries the cleanup inventory.
    bundle = write_bundle(investigation, Path(out_dir), world_spec=world.to_spec(),
                          platform_report=world.platform_report())
    verdict = investigation.verdict
    say(f"verdict  {verdict.summary if verdict else 'none: no suspect met the bar'}")
    say(f"bundle   {bundle}   (crux verify {bundle} --recorded)")
    clean = summarize(bundle, say)
    if verdict is None:
        return 1
    return 0 if clean else 3


def summarize(bundle_dir: Path, say) -> bool:
    """Every number comes from the bundle, so a reader can recompute each one."""
    bundle = Path(bundle_dir)
    trials = json.loads((bundle / "investigation.json").read_text("utf-8"))["trials"]
    platform = json.loads((bundle / "platform.json").read_text("utf-8"))
    artifacts = [t["artifact"] for t in trials]
    clones = {a["platform"]["clone"] for a in artifacts}
    attested = sum(a["attestation"].get("ok") is True for a in artifacts)
    digests = sorted({a["attestation"]["digest"][:12] for a in artifacts
                      if a["attestation"].get("digest")})
    counts, cleanup, attest = platform["counts"], platform["cleanup"], platform["attestation"]
    say(f"clones   {len(trials)} trials in {len(clones)} clones, {attested} attested at "
        f"{attest['level']} level, {len(digests)} distinct world digest {' '.join(digests)}, "
        f"{attest['refusals']} refusals")
    say(f"cleanup  created {counts['clones_created']}, killed {counts['clones_killed']}, "
        f"reaped {counts['reaped']}, snapshot "
        f"{'deleted' if cleanup.get('snapshot_deleted') else 'not deleted'}, filter leaks "
        f"{counts['filter_leaks']}, {'clean' if cleanup.get('clean') else 'left something behind'}")
    say("   ".join(f"{phase:<8} " + census(platform["inventory"].get(phase) or {})
                   for phase in ("before", "after")))
    return bool(cleanup.get("clean"))


def census(report: dict) -> str:
    holding = sum((report.get("by_state") or {}).get(state, 0) for state in HOLDING)
    return (f"sandboxes {holding} (this run {report.get('tagged_this_run', 0)})   "
            f"snapshots {report.get('snapshots_total', 0)}")
