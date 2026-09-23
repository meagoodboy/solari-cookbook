"""Four verbs; the plan and the key check come before any import of the SDK."""

import argparse
import asyncio
import os
from importlib import metadata
from pathlib import Path

from .probe429 import main_offline
from .session import TAG_SHAPE, Redactor, inventory, inventory_line, new_client, sweep, sweep_line


def say(line: str) -> None:
    print(line, flush=True)


def load_key() -> str:
    key = os.environ.get("SOLARI_API_KEY", "")
    if not key:
        say("SOLARI_API_KEY is not set; export it and rerun. Nothing was created.")
    return key


def gate(args, plan: str) -> bool:
    say("plan     " + plan + "; normal Solari charges apply")
    if not args.yes:
        say("refusing to run without --yes; nothing was created")
    return args.yes


def wrong_crux() -> str:
    """Says which distribution answered, since the bare name on PyPI is somebody else's.

    The package this needs is crux-flaky and it imports as crux. A reader who
    types `pip install crux` gets an unrelated API client whose releases reach
    1.4, and the import then fails somewhere deep. Naming the version that
    answered turns that into one readable line.
    """
    try:
        metadata.version("crux-flaky")
    except metadata.PackageNotFoundError:
        pass
    else:
        return "crux-flaky is installed but crux did not import; the install looks broken"
    try:
        found = f"the crux {metadata.version('crux')} on this interpreter is a different project"
    except metadata.PackageNotFoundError:
        found = "crux is not installed"
    return f"{found}; this needs crux-flaky (pip install crux-flaky), which imports as crux"


def with_client(key: str, verb, redactor: Redactor) -> int:
    async def go() -> int:
        from solari_sandbox import SolariError

        client = new_client(key)
        try:
            return await verb(client)
        except SolariError as exc:
            #  A listing or auth failure the verb did not handle, scrubbed of every id printed.
            say(f"failed   {type(exc).__name__}: {redactor.scrub(str(exc))}")
            return 3
        finally:
            await client.aclose()

    return asyncio.run(go())


def attest_verb(args) -> int:
    key = load_key()
    if not key or not gate(args, f"1 base sandbox, 1 snapshot, {args.clones} clones one at a time"):
        return 2
    from .attest import attest

    redactor = Redactor()
    return with_client(key, lambda client: attest(
        client, clones=args.clones, say=say, redactor=redactor), redactor)


def convict_verb(args) -> int:
    if not (key := load_key()):
        return 2
    try:
        from crux.backends.solari import SolariWorldError

        from .convict import SCENARIO, build_config, build_world, run, worst_case
    except ImportError:
        say(wrong_crux())
        return 2
    plan = (f"1 base sandbox plus up to {worst_case(args.round_trials, args.confirm)} trial "
            f"clones (5 branches x {args.round_trials}, then 2 x {args.confirm} to confirm)")
    if not gate(args, plan):
        return 2
    out = Path(args.out or f"runs/{SCENARIO}-seed{args.seed}")
    try:
        return run(build_world(key, say), out,
                   build_config(args.seed, args.round_trials, args.confirm), say)
    except SolariWorldError as exc:
        #  crux scrubs its own messages, so this line carries no id or key.
        say(f"failed   {exc}")
        return 3


def reap_verb(args) -> int:
    if not TAG_SHAPE.match(args.run_tag):
        say(f"{args.run_tag} is not a tag this application wrote (fc- plus 12 hex); "
            "for crux's own clones use: crux sandboxes --kill-all --yes")
        return 2
    if not (key := load_key()):
        return 2

    async def reap(client) -> int:
        say(sweep_line("reap", await sweep(client, args.run_tag, set())))
        say(inventory_line("after", await inventory(client, args.run_tag)))
        return 0

    return with_client(key, reap, Redactor())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m flake_conviction",
        description="Convict the cause of a flaky test in attested Solari snapshot clones")
    verbs = parser.add_subparsers(dest="verb", required=True)
    attest_p = verbs.add_parser("attest", help="fork N clones and prove each restored the world")
    attest_p.add_argument("--clones", type=int, default=3)
    convict_p = verbs.add_parser("convict", help="run the crux investigation and write a bundle")
    for name, default in (("--seed", 11), ("--round-trials", 6), ("--confirm", 10)):
        convict_p.add_argument(name, type=int, default=default)
    convict_p.add_argument("--out", help="bundle directory (default runs/<scenario>-seed<seed>)")
    verbs.add_parser("probe-429", help="reproduce the retried concurrency 429 offline, no key")
    verbs.add_parser("reap", help="kill and delete what a dead run left behind").add_argument("run_tag")
    for sub in (attest_p, convict_p):
        sub.add_argument("--yes", action="store_true", help="accept sandbox charges")
    args = parser.parse_args(argv)
    handlers = {"attest": attest_verb, "convict": convict_verb,
                "probe-429": lambda args: main_offline(say), "reap": reap_verb}
    return handlers[args.verb](args)
