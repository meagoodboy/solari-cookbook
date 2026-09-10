"""Command line entry points.

Subcommands import what they need at call time. That keeps `crux live`
from importing the sandbox SDK unless it is actually invoked, and it
lets `crux --help` work even while sibling modules are still landing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # Hand everything after "live" straight through. argparse REMAINDER
    # mangles leading flags on some Python versions, and this path must
    # not parse or import anything it does not need.
    if argv[:1] == ["live"]:
        return _run_live(argv[1:])
    if argv[:1] == ["sandboxes"]:
        from . import sandboxes

        return int(sandboxes.main(argv[1:]) or 0)
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def _run_live(live_args: list[str]) -> int:
    from . import live

    result = live.main(live_args)
    return int(result or 0)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crux",
        description="Find the minimal change that flips a stochastic agent's outcome.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run the invoice fixture investigation")
    demo.add_argument("--seed", type=int, default=7, help="investigation seed (default 7)")
    demo.add_argument("--out", default="runs", help="parent directory for bundles (default runs/)")
    demo.set_defaults(func=_cmd_demo)

    bench = sub.add_parser(
        "bench", help="run the operating-characteristics study over local worlds"
    )
    bench.add_argument(
        "--seeds", type=int, default=200, help="instances per family (default 200)"
    )
    bench.add_argument(
        "--out", default="bench", help="output directory (default bench/)"
    )
    bench.add_argument(
        "--master-seed", type=int, default=7, help="master seed (default 7)"
    )
    bench.set_defaults(func=_cmd_bench)

    serve_p = sub.add_parser("serve", help="serve the dashboard for a bundle")
    serve_p.add_argument(
        "--directory",
        default=None,
        help="bundle directory (default: newest runs/* with an investigation.json)",
    )
    serve_p.add_argument("--port", type=int, default=8123)
    serve_p.set_defaults(func=_cmd_serve)

    verify = sub.add_parser("verify", help="rerun a saved investigation and compare verdicts")
    verify.add_argument("directory", help="bundle directory holding investigation.json")
    verify.set_defaults(func=_cmd_verify)

    flaky = sub.add_parser(
        "flaky",
        help="investigate a flaky test command with the built-in suspect lineup",
        description=(
            "Investigate a flaky test command with the built-in suspect "
            "lineup. Exit codes: 0 cause confirmed, 1 investigated but no "
            "suspect met the bar, 2 usage error, 3 the command never failed "
            "in the probe, 4 the command failed every probe run with no "
            "passing hash pin (broken, not flaky)."
        ),
    )
    flaky.add_argument("--cwd", default=".", help="directory to run the command in")
    flaky.add_argument("--seed", type=int, default=7, help="investigation seed (default 7)")
    flaky.add_argument("--out", default="runs", help="parent directory for bundles (default runs/)")
    flaky.add_argument("--timeout-s", type=float, default=120.0, help="per-trial timeout (default 120)")
    flaky.add_argument("--probe", type=int, default=8, help="baseline probe runs (default 8)")
    flaky.add_argument(
        "--parallel", type=int, default=1,
        help="trial processes to run at once (default 1)",
    )
    flaky.add_argument(
        "cmd", nargs=argparse.REMAINDER,
        help="the test command, after --, or as one quoted string",
    )
    flaky.set_defaults(func=_cmd_flaky)

    live = sub.add_parser(
        "live",
        help="run a small investigation on real sandboxes (charges apply)",
        add_help=False,
    )
    live.add_argument("live_args", nargs=argparse.REMAINDER)
    live.set_defaults(func=_cmd_live)

    return parser


def _cmd_demo(args: argparse.Namespace) -> int:
    from .backends.local import LocalWorld
    from .fixture import FACTORS, oracle
    from .models import InvestigationConfig
    from .report import write_bundle
    from .search import investigate

    config = InvestigationConfig(seed=args.seed)
    world = LocalWorld()
    try:
        inv = investigate(world, oracle, FACTORS, config, scenario_name="demo")
    finally:
        world.close()

    out_dir = Path(args.out) / f"demo-seed{config.seed}"
    bundle = write_bundle(inv, out_dir)

    if inv.verdict is None:
        print(
            "The investigation ended without a verdict; that is an engine "
            "failure, not a null result.",
            file=sys.stderr,
        )
        print(f"Bundle written to {bundle}")
        return 1
    print(inv.verdict.summary)
    print(f"Bundle written to {bundle}")
    print(f"Next: crux serve --directory {bundle}")
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    from .bench import run_bench, write_outputs

    results = run_bench(
        seeds=args.seeds, master_seed=args.master_seed, progress=print
    )
    out_dir = write_outputs(results, Path(args.out))
    print(f"Wrote {out_dir / 'results.json'}")
    print(f"Wrote {out_dir / 'RESULTS.md'}")
    return 0


def _newest_bundle(root: Path) -> Path | None:
    if not root.is_dir():
        return None
    candidates = [
        child for child in root.iterdir() if (child / "investigation.json").is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda c: (c / "investigation.json").stat().st_mtime)


def _cmd_serve(args: argparse.Namespace) -> int:
    from .serve import serve

    if args.directory is not None:
        directory = Path(args.directory)
    else:
        directory = _newest_bundle(Path("runs"))
        if directory is None:
            print("No bundle found under runs/. Run `crux demo` first.", file=sys.stderr)
            return 2
    if not (directory / "investigation.json").is_file():
        print(f"No investigation.json in {directory}.", file=sys.stderr)
        return 2
    serve(directory, port=args.port)
    return 0


def _world_for_scenario(scenario: str):
    """Pick the local world class that matches a saved scenario name.

    Returns None for a scenario with no local replay world. Silently
    substituting LocalWorld here would replay a bundle against a world
    that never produced it, so unknown names are refused by the caller.
    """
    from .backends import local

    by_name = {
        "demo": local.LocalWorld,
        "": local.LocalWorld,
        "no-effect": getattr(local, "NoEffectWorld", None),
        "conjunction": getattr(local, "ConjunctionWorld", None),
    }
    cls = by_name.get(scenario)
    return None if cls is None else cls()


def _cause_text(cause) -> str:
    if cause is None:
        return "none"
    return ", ".join(cause)


def _cmd_verify(args: argparse.Namespace) -> int:
    from .fixture import FACTORS, oracle
    from .models import Investigation
    from .search import investigate

    path = Path(args.directory) / "investigation.json"
    if not path.is_file():
        print(f"No investigation.json in {args.directory}.", file=sys.stderr)
        return 2
    saved = Investigation.from_dict(json.loads(path.read_text(encoding="utf-8")))
    factors = saved.factors or FACTORS

    world = None
    replay_oracle = oracle
    world_path = Path(args.directory) / "world.json"
    if world_path.is_file():
        from .backends.command import CommandWorld, command_oracle

        spec = json.loads(world_path.read_text(encoding="utf-8"))
        if spec.get("kind") != "command":
            print(
                f"world.json has unknown kind {spec.get('kind')!r}; "
                "cannot rebuild that world here.",
                file=sys.stderr,
            )
            return 3
        cwd = Path(str(spec.get("cwd", "")))
        if not cwd.is_dir():
            print(
                f"world.json points at {cwd}, which does not exist on this "
                "machine. Recreate the checkout there and rerun.",
                file=sys.stderr,
            )
            return 3
        world = CommandWorld.from_spec(spec)
        replay_oracle = command_oracle
    else:
        world = _world_for_scenario(saved.scenario)
        if world is None:
            print(
                f"Cannot verify scenario '{saved.scenario}': the bundle has "
                "no world.json and no local replay world matches the name. "
                "Simulated bundles (demo, no-effect, conjunction) replay "
                "anywhere; command bundles need their world.json and the "
                "original checkout.",
                file=sys.stderr,
            )
            return 3
    try:
        fresh = investigate(
            world, replay_oracle, factors, saved.config, scenario_name=saved.scenario
        )
    finally:
        world.close()

    saved_cause = saved.verdict.cause if saved.verdict else None
    fresh_cause = fresh.verdict.cause if fresh.verdict else None
    print(f"Saved cause:    {_cause_text(saved_cause)}")
    print(f"Replayed cause: {_cause_text(fresh_cause)}")

    same_shape = (saved_cause is None) == (fresh_cause is None)
    if same_shape and tuple(saved_cause or ()) == tuple(fresh_cause or ()):
        print("Verify passed. The replay reached the same cause.")
        return 0
    print("Verify failed. The replay reached a different cause.")
    return 1


def _cmd_flaky(args: argparse.Namespace) -> int:
    from .flaky import parse_command, run_flaky
    from .models import InvestigationConfig
    from .report import write_bundle

    try:
        cmd = parse_command(args.cmd)
    except ValueError as exc:
        if "no command given" in str(exc):
            print("Give the test command after --, for example:")
            print("  crux flaky -- python -m pytest tests/test_x.py::test_y")
        else:
            print(f"Could not parse the command: {exc}")
        return 2

    config = InvestigationConfig(seed=args.seed)
    print(f"Command: {' '.join(cmd)}")
    print("Probing for a passing hash pin and a reproducible failure...")
    investigation, probe = run_flaky(
        cmd, args.cwd, config, timeout_s=args.timeout_s, probe_runs=args.probe,
        parallel=args.parallel,
    )
    pin_note = "" if probe.hash_pin_passed else " (no probed pin passed; using it anyway)"
    print(f"Hash pin: PYTHONHASHSEED={probe.hash_pin}{pin_note}")
    print(f"Baseline probe: {probe.baseline_failures} of "
          f"{probe.baseline_runs} runs failed")
    if investigation is None:
        if probe.always_failed:
            print("The command failed every probe run and no pinned hash seed")
            print("passed either. That is a plain failure, not a flake; fix")
            print("the command first, then come back if it turns intermittent.")
            return 4
        print("The command never failed in the probe, so there is nothing to")
        print(f"investigate. Raise --probe past {probe.baseline_runs} if the")
        print("flake is rarer than that.")
        return 3
    print(f"\n{investigation.verdict.summary}")
    from .backends.command import CommandWorld
    from .flaky import build_flaky_specs

    world_spec = CommandWorld(
        cmd=cmd,
        cwd=str(Path(args.cwd).resolve()),
        specs=build_flaky_specs(probe.hash_pin),
        timeout_s=args.timeout_s,
        concurrency=args.parallel,
    ).to_spec()
    out_dir = Path(args.out) / investigation.investigation_id
    write_bundle(investigation, out_dir, world_spec=world_spec)
    print(f"Bundle written to {out_dir}")
    print(f"Next: crux serve --directory {out_dir}")
    return 0 if investigation.verdict.cause else 1


def _cmd_live(args: argparse.Namespace) -> int:
    # Reached only if main() was bypassed; forwards the same way.
    return _run_live(args.live_args)


if __name__ == "__main__":
    raise SystemExit(main())
