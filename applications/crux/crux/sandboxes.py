"""List and clean up Solari sandboxes owned by this API key.

A create call that times out client-side can still provision a VM
server-side, and that orphan then squats on the account's concurrent
session limit while billing quietly. This happened to us mid-build:
every later create was refused with "Too many concurrent sessions"
until the orphan was found and killed. `crux sandboxes` makes that
visible and fixable without writing SDK code:

  crux sandboxes            list running sandboxes
  crux sandboxes --kill-all kill everything listed (asks for --yes)
  crux sandboxes --kill ID  kill one

Killing is per sandbox and explicit; nothing here runs automatically,
because the account may have sandboxes that belong to another job.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

BASE_URL = "https://api.getsolari.com"


def _views(listing) -> list:
    if isinstance(listing, dict):
        return list(listing.get("sandboxes") or [])
    return list(getattr(listing, "sandboxes", []) or [])


def _field(view, name: str):
    if isinstance(view, dict):
        return view.get(name)
    return getattr(view, name, None)


async def _run(args: argparse.Namespace, api_key: str) -> int:
    from solari_sandbox import SandboxClient

    async with SandboxClient(api_key=api_key, base_url=BASE_URL) as client:
        views = _views(await client.list())
        if not views:
            print("No running sandboxes.")
            return 0
        for view in views:
            sid = _field(view, "sandboxId") or ""
            print(f"{sid}")
            print(f"    state {_field(view, 'state')}"
                  f"  expires {_field(view, 'expiresAt')}"
                  f"  cpu {_field(view, 'cpu')}  memMb {_field(view, 'memMb')}")
        targets: list[str] = []
        if args.kill_all:
            targets = [_field(view, "sandboxId") for view in views]
        elif args.kill:
            targets = [args.kill]
        if not targets:
            return 0
        if not args.yes:
            print(f"\nWould kill {len(targets)} sandbox(es). "
                  "Rerun with --yes to actually do it.")
            return 2
        failures = 0
        for sid in targets:
            try:
                await client.kill(sid)
                print(f"killed {sid[:40]}")
            except Exception as exc:
                failures += 1
                print(f"kill failed for {sid[:40]}: {exc}")
        return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="crux sandboxes",
        description="List and clean up Solari sandboxes for this API key.",
    )
    parser.add_argument("--kill", help="sandbox id to kill")
    parser.add_argument(
        "--kill-all", action="store_true", help="kill every listed sandbox"
    )
    parser.add_argument("--yes", action="store_true", help="confirm the kill")
    args = parser.parse_args(argv)

    api_key = os.environ.get("SOLARI_API_KEY", "")
    if not api_key:
        print("SOLARI_API_KEY is not set; export it and rerun.")
        return 2
    return asyncio.run(_run(args, api_key))


if __name__ == "__main__":
    sys.exit(main())
