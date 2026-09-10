"""Solari sandbox backend: seed the fixture once, fork one clone per trial.

The World facade here is synchronous. Internally it owns a private event
loop and drives the async solari_sandbox SDK with run_until_complete, one
call at a time. setup creates a base sandbox, parks the fixture source on
disk inside it, snapshots, and kills the base. Every trial then forks a
fresh clone from that snapshot, runs a tiny driver that prints the
artifact as JSON, and kills the clone before returning.

solari_sandbox is an optional extra. It is imported inside functions so
the rest of the package works without it installed.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Iterable, Mapping
from contextlib import AsyncExitStack
from typing import Any

from ..models import RawRun

BASE_URL = "https://api.getsolari.com"
FIXTURE_PATH = "/root/crux_fixture.py"
SNAPSHOT_NAME = "crux-live-fixture"
_REQUIRED_NAMES = ("generate_invoice", "render_page", "run_agent", "oracle")


class SolariWorldError(RuntimeError):
    """A sandbox call failed. The message names the sandbox involved."""


def fixture_source() -> str:
    """Return standalone source for the fixture, ready to exec in a sandbox.

    The sandbox kernel execs one flat file with no package around it, so a
    relative import would blow up there. This inlines crux.models ahead of
    crux.fixture, drops the relative import, and hoists the single future
    import to the top where the compiler requires it.
    """
    from .. import fixture, models

    parts = []
    for module in (models, fixture):
        src = inspect.getsource(module)
        parts.append(src.replace("from __future__ import annotations\n", ""))
    combined = "\n".join(parts).replace("from .models import Factor\n", "")
    if combined.startswith("from .") or "\nfrom ." in combined:
        raise ValueError(
            "fixture source still holds a relative import; "
            "it would not exec inside a sandbox"
        )
    return "from __future__ import annotations\n\n" + combined


def build_setup_source(source: str, path: str = FIXTURE_PATH) -> str:
    """Build the program that installs the fixture inside the base sandbox.

    The program writes the fixture source to disk, then execs it once as a
    sanity check that every callable the trial driver needs is defined.
    Writing to disk matters: a clone gets a fresh kernel, so the file is
    what actually survives the snapshot.
    """
    lines = [
        "import pathlib",
        f"_src = {source!r}",
        f"_path = pathlib.Path({path!r})",
        "_path.parent.mkdir(parents=True, exist_ok=True)",
        "_path.write_text(_src, encoding='utf-8')",
        "_ns = {}",
        "exec(compile(_src, str(_path), 'exec'), _ns)",
        f"for _name in {_REQUIRED_NAMES!r}:",
        "    if _name not in _ns:",
        "        raise RuntimeError('fixture source is missing ' + _name)",
        "print('fixture-ready')",
    ]
    return "\n".join(lines) + "\n"


def build_trial_source(
    assignment: Mapping[str, bool], seed: int, path: str = FIXTURE_PATH
) -> str:
    """Build the one-trial driver a clone runs.

    It loads the fixture file written during setup, runs a single trial
    with the given assignment and seed, and prints the artifact as one
    JSON line on stdout.
    """
    if not isinstance(seed, int):
        raise TypeError(f"seed must be an int, got {type(seed).__name__}")
    normal = {str(key): bool(value) for key, value in sorted(assignment.items())}
    lines = [
        "import json",
        "import pathlib",
        "import random",
        f"_src = pathlib.Path({path!r}).read_text(encoding='utf-8')",
        "_ns = {}",
        f"exec(compile(_src, {path!r}, 'exec'), _ns)",
        f"_assignment = {normal!r}",
        f"_rng = random.Random({seed!r})",
        "_invoice = _ns['generate_invoice'](_rng)",
        "_page = _ns['render_page'](_invoice, _assignment)",
        "_artifact = _ns['run_agent'](_page, _assignment, _rng)",
        "print(json.dumps(_artifact))",
    ]
    return "\n".join(lines) + "\n"


def _field(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def parse_artifact(results: Iterable[Any] | None) -> dict[str, Any]:
    """Extract the trial artifact from run_code output items.

    Output arrives as a list of items typed "stdout", "stderr", "result"
    and so on; there is no top-level stdout. This scans the stdout and
    result items for the last line that parses as a JSON object and
    returns it. Raises ValueError when no such line exists.
    """
    texts: list[str] = []
    for item in results or ():
        kind = _field(item, "type")
        text = _field(item, "text")
        if kind in ("stdout", "result") and text:
            texts.append(str(text))
    for text in reversed(texts):
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not (line.startswith("{") and line.endswith("}")):
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    raise ValueError(
        "no JSON artifact found in run_code output "
        f"(saw {len(texts)} stdout/result item(s))"
    )


def _raise_on_error(result: Any, sandbox_id: str, stage: str) -> None:
    error = _field(result, "error")
    if error:
        raise SolariWorldError(
            f"sandbox {sandbox_id}: {stage} run_code error: {error}"
        )


class SolariWorld:
    """Sync World over Solari sandboxes: one snapshot, one clone per trial.

    Cleanup follows the cookbook examples. Kill and delete_snapshot are
    registered on an AsyncExitStack the moment each resource exists, so a
    failure at any point still tears everything down. The snapshot lives
    for the whole investigation and is deleted when close() runs.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = BASE_URL,
        template: str = "base",
        timeout_ms: int = 300_000,
    ) -> None:
        if not api_key:
            raise SolariWorldError("SolariWorld needs a non-empty api_key")
        self._api_key = api_key
        self._base_url = base_url
        self._template = template
        self._timeout_ms = timeout_ms
        self._loop = asyncio.new_event_loop()
        self._stack: AsyncExitStack | None = None
        self._client: Any = None
        self._snapshot_ref: str | None = None
        self._closed = False

    def snapshot(self) -> str:
        if self._closed:
            raise SolariWorldError("SolariWorld is closed")
        if self._snapshot_ref is None:
            self._snapshot_ref = self._loop.run_until_complete(self._setup())
        return self._snapshot_ref

    def run_trial(
        self, snapshot: str, assignment: dict[str, bool], seed: int
    ) -> RawRun:
        if self._closed:
            raise SolariWorldError("SolariWorld is closed")
        if self._client is None:
            raise SolariWorldError("call snapshot() before run_trial()")
        return self._loop.run_until_complete(
            self._run_trial(snapshot, assignment, seed)
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._stack is not None:
                self._loop.run_until_complete(self._stack.aclose())
        finally:
            self._stack = None
            self._client = None
            self._snapshot_ref = None
            self._loop.close()

    async def _setup(self) -> str:
        # Imported here, not at module top, so the package works without
        # the live extra installed.
        from solari_sandbox import SandboxClient

        stack = AsyncExitStack()
        try:
            client = await stack.enter_async_context(
                SandboxClient(api_key=self._api_key, base_url=self._base_url)
            )
            snapshot = await self._seed_snapshot(stack, client)
        except BaseException:
            # Unwind whatever was registered: snapshot deletion if it got
            # that far, then the client itself.
            await stack.aclose()
            raise
        self._stack = stack
        self._client = client
        return snapshot

    async def _seed_snapshot(self, stack: AsyncExitStack, client: Any) -> str:
        try:
            base = await client.create(
                template=self._template, timeout_ms=self._timeout_ms
            )
        except Exception as exc:
            raise SolariWorldError(
                f"base sandbox creation failed: {exc}"
            ) from exc
        base_id = base.sandboxId
        async with AsyncExitStack() as base_cleanup:
            # Registered before any use, mirroring the cookbook. The stack
            # unwinds LIFO, so kill runs first and close follows.
            base_cleanup.push_async_callback(base.close)
            base_cleanup.push_async_callback(client.kill, base_id)
            try:
                await base.connect()
                ctx = await base.create_code_context("python")
                result = await base.run_code(
                    build_setup_source(fixture_source()), context_id=ctx
                )
            except Exception as exc:
                raise SolariWorldError(
                    f"sandbox {base_id}: fixture setup failed: {exc}"
                ) from exc
            _raise_on_error(result, base_id, "fixture setup")
            try:
                snapshot = await base.snapshot(SNAPSHOT_NAME)
            except Exception as exc:
                raise SolariWorldError(
                    f"sandbox {base_id}: snapshot failed: {exc}"
                ) from exc
            # Register deletion the moment the snapshot exists. It runs
            # when close() unwinds the world-level stack.
            stack.push_async_callback(client.delete_snapshot, snapshot)
        return snapshot

    async def _run_trial(
        self, snapshot: str, assignment: dict[str, bool], seed: int
    ) -> RawRun:
        client = self._client
        started = time.monotonic()
        try:
            clone = await client.create(
                template=self._template,
                from_snapshot=snapshot,
                timeout_ms=self._timeout_ms,
            )
        except Exception as exc:
            raise SolariWorldError(
                f"clone creation from snapshot {snapshot} failed: {exc}"
            ) from exc
        clone_id = clone.sandboxId
        async with AsyncExitStack() as worker_cleanup:
            worker_cleanup.push_async_callback(clone.close)
            worker_cleanup.push_async_callback(client.kill, clone_id)
            try:
                await clone.connect()
                ctx = await clone.create_code_context("python")
                result = await clone.run_code(
                    build_trial_source(assignment, seed), context_id=ctx
                )
            except Exception as exc:
                raise SolariWorldError(
                    f"sandbox {clone_id}: trial run failed: {exc}"
                ) from exc
            _raise_on_error(result, clone_id, "trial")
            try:
                artifact = parse_artifact(_field(result, "results"))
            except ValueError as exc:
                raise SolariWorldError(f"sandbox {clone_id}: {exc}") from exc
        duration_ms = int((time.monotonic() - started) * 1000)
        steps = artifact.get("steps") or []
        return RawRun(
            artifact=artifact,
            transcript=tuple(str(step) for step in steps),
            duration_ms=duration_ms,
        )
