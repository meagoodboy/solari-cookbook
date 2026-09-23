"""What attest, probe-429 and reap share: tags, redaction, bounds, census, sweep."""

import asyncio
import hashlib
import os
import re
import secrets
from importlib import resources

BASE_URL = "https://api.getsolari.com"
APP = "flake-conviction"
TAG_SHAPE = re.compile(r"^fc-[0-9a-f]{12}$")
HOLDING = frozenset({"starting", "running", "paused"})
WORLD_DIR = "/root/flake-fixture"
SUITE_PATH, EXPECTED_PATH = WORLD_DIR + "/ledger_suite.py", WORLD_DIR + "/expected.txt"
LIST_BUDGET_S = 120


def new_run_tag() -> str:
    return "fc-" + secrets.token_hex(6)


def tag(run_tag: str, role: str) -> dict[str, str]:
    return {"app": APP, "run": run_tag, "role": role}


def fixture_bytes(name: str) -> bytes:
    return resources.files("flake_conviction").joinpath("fixture", name).read_bytes()


class Redactor:
    """A sandbox id decodes to an internal host id, so it is hashed, not shortened,
    with a salt drawn per process and never written: one raw id gives one ref for
    the length of the run, and nothing on disk turns a ref back into the id."""

    def __init__(self) -> None:
        self._salt = os.urandom(16)
        self._seen: dict[str, str] = {}

    def ref(self, raw: str, kind: str) -> str:
        digest = hashlib.sha256(self._salt + raw.encode("utf-8")).hexdigest()[:12]
        return self._seen.setdefault(raw, f"{kind}-{digest}")

    def scrub(self, text: str) -> str:
        for raw in sorted(self._seen, key=len, reverse=True):
            text = text.replace(raw, self._seen[raw])
        return text


async def bounded(coro, seconds: float):
    """Every SDK await goes through here: `commands.run` drops its timeout_ms and
    `call_timeout_ms` bounds the request, not the reply (crux PLATFORM.md D2, H2)."""
    return await asyncio.wait_for(coro, seconds)


async def kill(client, sandbox_id: str) -> None:
    await bounded(client.kill(sandbox_id), 90)


async def delete_snapshot(client, snapshot_id: str) -> None:
    await bounded(client.delete_snapshot(snapshot_id), 90)


def new_client(key: str):
    from solari_sandbox import SandboxClient

    return SandboxClient(api_key=key, base_url=BASE_URL, call_timeout_ms=60_000)


async def inventory(client, run_tag: str) -> dict:
    """A census of the account, counts only. A walk that ran out of time reports
    `truncated` rather than a number it did not finish: a partial census presented
    as a full one is how a run that left something behind gets called clean."""
    counts = dict.fromkeys(("sandboxes", "this_run", "snapshots", "snapshots_this_run"), 0)
    counts["truncated"] = False
    try:
        async with asyncio.timeout(LIST_BUDGET_S):
            async for view in client.list_all():
                if view.state in HOLDING:
                    counts["sandboxes"] += 1
                    counts["this_run"] += (view.metadata or {}).get("run") == run_tag
            for snap in await client.list_snapshots(limit=1000):
                counts["snapshots"] += 1
                counts["snapshots_this_run"] += (snap.name or "").startswith(run_tag)
    except TimeoutError:
        counts["truncated"] = True
    return counts


def inventory_line(phase: str, counts: dict) -> str:
    if counts["truncated"]:
        return f"{phase:<8} truncated: the listing did not finish within {LIST_BUDGET_S} s"
    return (f"{phase:<8} sandboxes {counts['sandboxes']} (this run {counts['this_run']})"
            f"   snapshots {counts['snapshots']} (this run {counts['snapshots_this_run']})")


async def attempt(coro, counts: dict) -> bool:
    """A kill or delete that raises is counted, never printed: the SDK puts the
    raw sandbox id in its message, and an orphan's id never met the redactor."""
    try:
        await coro
        return True
    except Exception:  # noqa: BLE001 - see above; the sweep must reach the next view
        counts["failed"] += 1
        return False


async def sweep(client, run_tag: str, known_ids: set[str]) -> dict:
    """Kills by tag, counts only. The metadata filter is a query parameter and
    nothing on the client checks that the server honoured it, so every returned
    view is matched again before it is killed; one that fails is a leak, left
    alone. `beyond` counts kills of sandboxes the caller never learned the id of."""
    counts = dict.fromkeys(("killed", "beyond", "leaks", "deleted", "failed"), 0)
    counts["truncated"] = False
    try:
        async with asyncio.timeout(LIST_BUDGET_S):
            async for view in client.list_all(metadata={"app": APP, "run": run_tag}):
                metadata = view.metadata or {}
                if metadata.get("app") != APP or metadata.get("run") != run_tag:
                    counts["leaks"] += 1
                elif view.state in HOLDING and await attempt(kill(client, view.sandboxId), counts):
                    counts["killed"] += 1
                    counts["beyond"] += view.sandboxId not in known_ids
            for snap in await client.list_snapshots(limit=1000):
                if (snap.name or "").startswith(run_tag):
                    counts["deleted"] += await attempt(delete_snapshot(client, snap.id), counts)
    except TimeoutError:
        counts["truncated"] = True
    return counts


def sweep_line(phase: str, counts: dict) -> str:
    note = f"; listing cut off at {LIST_BUDGET_S} s, rerun reap" if counts["truncated"] else ""
    return (f"{phase:<8} killed {counts['killed']} with this tag ({counts['beyond']} beyond the "
            f"ledger), deleted {counts['deleted']} snapshots, {counts['leaks']} filter leaks, "
            f"{counts['failed']} kill or delete calls failed{note}")
