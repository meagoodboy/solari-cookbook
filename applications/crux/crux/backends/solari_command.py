"""Run any command as Crux trials inside cloned Solari sandboxes.

Same skeleton as SolariWorld: build one base sandbox, snapshot it, kill
the base, fork a clone per trial. The difference is what a trial is.
Here setup is a list of shell script stages that prepare a real
repository inside the VM (clone it, install its deps, sanity-run the
target once), and a trial is a subprocess inside the clone (a pytest
node, a build, any command) with the branch's factor overrides applied
to its environment. That lets a real project's flaky test be
investigated on real forked infrastructure instead of local processes.

solari_sandbox stays an optional extra, imported inside functions.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Mapping, Sequence
from contextlib import AsyncExitStack

from ..models import RawRun
from .command import FactorSpec, resolve_overrides
from .solari import (
    BASE_URL,
    SolariWorldError,
    _field,
    _raise_on_error,
    parse_artifact,
)

SETUP_STAGE_TIMEOUT_S = 900.0


def build_stage_source(script: str, timeout_s: float = SETUP_STAGE_TIMEOUT_S) -> str:
    """Build the driver that runs one setup stage inside the base sandbox.

    The stage is a bash script executed with subprocess so it can use
    pipes, env exports and apt without fighting the python kernel. A
    nonzero exit raises inside the kernel, which surfaces through
    run_code's error field with the output tail attached.
    """
    lines = [
        "import subprocess",
        f"_p = subprocess.run(['bash', '-c', {script!r}],",
        f"    capture_output=True, text=True, timeout={timeout_s!r})",
        "_tail = ((_p.stdout or '') + (_p.stderr or ''))[-2000:]",
        "if _p.returncode != 0:",
        "    raise RuntimeError('setup stage failed rc=%d tail=%s'"
        " % (_p.returncode, _tail))",
        "print(_tail)",
        "print('stage-ok')",
    ]
    return "\n".join(lines) + "\n"


def build_command_trial_source(
    cmd: Sequence[str],
    cwd: str,
    overrides: Mapping[str, str],
    seed: int,
    timeout_s: float,
) -> str:
    """Build the one-trial driver a clone runs.

    It launches the command as a subprocess with the resolved env
    overrides applied and prints a single JSON artifact line with the
    same keys CommandWorld produces, so command_oracle scores both
    backends identically.
    """
    if not isinstance(seed, int):
        raise TypeError(f"seed must be an int, got {type(seed).__name__}")
    plain_overrides = {str(k): str(v) for k, v in sorted(overrides.items())}
    lines = [
        "import json",
        "import os",
        "import subprocess",
        "_env = dict(os.environ)",
        f"_overrides = {plain_overrides!r}",
        "_env.update(_overrides)",
        "_timed_out = False",
        "try:",
        f"    _p = subprocess.run({list(cmd)!r}, cwd={cwd!r}, env=_env,",
        f"        capture_output=True, text=True, timeout={timeout_s!r})",
        "    _exit = _p.returncode",
        "    _tail = ((_p.stdout or '') + (_p.stderr or ''))[-2000:]",
        "except subprocess.TimeoutExpired as _exc:",
        "    _timed_out = True",
        "    _exit = -1",
        "    _tail = str(_exc)[-2000:]",
        "print(json.dumps({",
        "    'exit_code': _exit,",
        "    'timed_out': _timed_out,",
        f"    'seed': {seed!r},",
        "    'env_overrides': _overrides,",
        "    'output_tail': _tail,",
        "}))",
    ]
    return "\n".join(lines) + "\n"


class SolariCommandWorld:
    """Sync World running command trials in Solari clones.

    Cleanup mirrors SolariWorld: kill and delete_snapshot register on an
    AsyncExitStack the moment each resource exists, so a failure at any
    stage still tears everything down.
    """

    def __init__(
        self,
        api_key: str,
        setup_stages: Sequence[str],
        trial_cmd: Sequence[str],
        trial_cwd: str,
        specs: Sequence[FactorSpec],
        snapshot_name: str = "crux-command-world",
        base_url: str = BASE_URL,
        template: str = "base",
        base_timeout_ms: int = 1_800_000,
        clone_timeout_ms: int = 300_000,
        trial_timeout_s: float = 240.0,
        stage_timeout_s: float = SETUP_STAGE_TIMEOUT_S,
        concurrency: int = 1,
        progress=None,
    ) -> None:
        if not api_key:
            raise SolariWorldError("SolariCommandWorld needs a non-empty api_key")
        if not setup_stages:
            raise SolariWorldError("setup_stages must not be empty")
        self._api_key = api_key
        self._setup_stages = tuple(setup_stages)
        self._trial_cmd = tuple(trial_cmd)
        self._trial_cwd = trial_cwd
        self._specs = tuple(specs)
        self._snapshot_name = snapshot_name
        self._base_url = base_url
        self._template = template
        self._base_timeout_ms = base_timeout_ms
        self._clone_timeout_ms = clone_timeout_ms
        self._trial_timeout_s = trial_timeout_s
        self._stage_timeout_s = stage_timeout_s
        self._concurrency = max(1, int(concurrency))
        # Every sandbox this world creates carries this tag in its
        # metadata. A create call can error client-side while the VM
        # still comes up server-side; such a phantom occupies a session
        # slot, blocks every retry, and is invisible without the tag.
        self._run_tag = f"{snapshot_name}-{uuid.uuid4().hex[:8]}"
        self._active_ids: set[str] = set()
        self._progress = progress or (lambda line: None)
        self._loop = asyncio.new_event_loop()
        self._stack: AsyncExitStack | None = None
        self._client = None
        self._snapshot_ref: str | None = None
        self._closed = False

    def snapshot(self) -> str:
        if self._closed:
            raise SolariWorldError("SolariCommandWorld is closed")
        if self._snapshot_ref is None:
            self._snapshot_ref = self._loop.run_until_complete(self._setup())
        return self._snapshot_ref

    def run_trial(
        self, snapshot: str, assignment: dict[str, bool], seed: int
    ) -> RawRun:
        if self._closed:
            raise SolariWorldError("SolariCommandWorld is closed")
        if self._client is None:
            raise SolariWorldError("call snapshot() before run_trial()")
        return self._loop.run_until_complete(
            self._run_trial(snapshot, assignment, seed)
        )

    def run_trials(
        self, snapshot: str, jobs: Sequence[tuple[dict[str, bool], int]]
    ) -> list[RawRun]:
        """Run a batch of trials, forking up to `concurrency` clones at once.

        Results come back in job order regardless of completion order.
        Seeds fully determine each trial, so a concurrent batch produces
        the same investigation a sequential walk would.
        """
        if self._closed:
            raise SolariWorldError("SolariCommandWorld is closed")
        if self._client is None:
            raise SolariWorldError("call snapshot() before run_trials()")
        if self._concurrency <= 1 or len(jobs) <= 1:
            return [
                self.run_trial(snapshot, assignment, seed)
                for assignment, seed in jobs
            ]
        return self._loop.run_until_complete(self._run_batch(snapshot, jobs))

    async def _run_batch(
        self, snapshot: str, jobs: Sequence[tuple[dict[str, bool], int]]
    ) -> list[RawRun]:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def bounded(assignment: dict[str, bool], seed: int) -> RawRun:
            async with semaphore:
                return await self._run_trial(snapshot, assignment, seed)

        return list(
            await asyncio.gather(
                *(bounded(assignment, seed) for assignment, seed in jobs)
            )
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
        from solari_sandbox import SandboxClient

        stack = AsyncExitStack()
        try:
            client = await stack.enter_async_context(
                SandboxClient(api_key=self._api_key, base_url=self._base_url)
            )
            snapshot = await self._build_snapshot(stack, client)
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        self._client = client
        return snapshot

    async def _reap_phantoms(self, client) -> int:
        """Kill sandboxes carrying our tag that we are not tracking.

        Called after a create failure and during teardown. Only our own
        tag is touched, so other jobs on the same account are safe.
        """
        try:
            listing = await client.list()
        except Exception:
            return 0
        views = (
            listing.get("sandboxes", [])
            if isinstance(listing, dict)
            else getattr(listing, "sandboxes", []) or []
        )
        reaped = 0
        for view in views:
            sid = (
                view.get("sandboxId")
                if isinstance(view, dict)
                else getattr(view, "sandboxId", None)
            )
            meta = (
                view.get("metadata")
                if isinstance(view, dict)
                else getattr(view, "metadata", None)
            ) or {}
            if not sid or sid in self._active_ids:
                continue
            if meta.get("crux_run") != self._run_tag:
                continue
            try:
                await client.kill(sid)
                reaped += 1
                self._progress(f"reaped phantom sandbox {sid[:24]}")
            except Exception:
                pass
        return reaped

    async def _teardown_snapshot(self, client, snapshot: str) -> None:
        """Delete the snapshot, sweeping phantom children out first."""
        for attempt in range(3):
            await self._reap_phantoms(client)
            try:
                await client.delete_snapshot(snapshot)
                return
            except Exception as exc:
                if attempt == 2:
                    self._progress(
                        f"snapshot {snapshot} not deleted ({exc}); it expires "
                        "on its own"
                    )
                    return
                await asyncio.sleep(10)

    async def _build_snapshot(self, stack: AsyncExitStack, client) -> str:
        base = None
        last_exc: Exception | None = None
        # Session slots from a previous run can linger for minutes after
        # its sandboxes die, so the base create gets the same patience as
        # clone creation instead of failing on the first refusal.
        for attempt in range(6):
            try:
                base = await client.create(
                    template=self._template,
                    timeout_ms=self._base_timeout_ms,
                    metadata={"crux_run": self._run_tag},
                )
                break
            except Exception as exc:
                last_exc = exc
                await self._reap_phantoms(client)
                if attempt < 5:
                    self._progress(
                        f"base creation refused ({exc}); retrying in "
                        f"{20 * (attempt + 1)}s"
                    )
                    await asyncio.sleep(20 * (attempt + 1))
        if base is None:
            raise SolariWorldError(
                f"base sandbox creation failed after 6 attempts: {last_exc}"
            ) from last_exc
        base_id = base.sandboxId
        self._active_ids.add(base_id)
        self._progress(f"base sandbox {base_id} created")
        async with AsyncExitStack() as base_cleanup:
            base_cleanup.push_async_callback(base.close)
            base_cleanup.callback(self._active_ids.discard, base_id)
            base_cleanup.push_async_callback(client.kill, base_id)
            try:
                await base.connect()
                ctx = await base.create_code_context("python")
            except Exception as exc:
                raise SolariWorldError(
                    f"sandbox {base_id}: connect failed: {exc}"
                ) from exc
            for index, script in enumerate(self._setup_stages, start=1):
                label = f"setup stage {index}/{len(self._setup_stages)}"
                self._progress(f"{label} starting")
                started = time.monotonic()
                try:
                    result = await base.run_code(
                        build_stage_source(script, self._stage_timeout_s),
                        context_id=ctx,
                    )
                except Exception as exc:
                    raise SolariWorldError(
                        f"sandbox {base_id}: {label} failed: {exc}"
                    ) from exc
                _raise_on_error(result, base_id, label)
                elapsed = time.monotonic() - started
                self._progress(f"{label} done in {elapsed:.0f}s")
            try:
                snapshot = await base.snapshot(self._snapshot_name)
            except Exception as exc:
                raise SolariWorldError(
                    f"sandbox {base_id}: snapshot failed: {exc}"
                ) from exc
            stack.push_async_callback(self._teardown_snapshot, client, snapshot)
            self._progress(f"snapshot {snapshot} taken; base retired")
        return snapshot

    async def _run_trial(
        self, snapshot: str, assignment: dict[str, bool], seed: int
    ) -> RawRun:
        client = self._client
        overrides = resolve_overrides(self._specs, assignment, seed)
        started = time.monotonic()
        clone = None
        last_exc: Exception | None = None
        # Session slots free up with a lag after a clone is killed, so a
        # concurrent batch can transiently overflow the account limit.
        # Patient growing backoff (up to ~2.5 minutes total) rides that
        # out; a truly exhausted account still fails with the SDK error.
        for attempt in range(6):
            try:
                clone = await client.create(
                    template=self._template,
                    from_snapshot=snapshot,
                    timeout_ms=self._clone_timeout_ms,
                    metadata={"crux_run": self._run_tag},
                )
                break
            except Exception as exc:
                last_exc = exc
                # The failed create may still have provisioned a VM that
                # now occupies the very slot the retry needs. Reap our
                # own untracked sandboxes before waiting.
                await self._reap_phantoms(client)
                if attempt < 5:
                    await asyncio.sleep(10 * (attempt + 1))
        if clone is None:
            raise SolariWorldError(
                f"clone creation from snapshot {snapshot} failed "
                f"after 6 attempts: {last_exc}"
            ) from last_exc
        clone_id = clone.sandboxId
        self._active_ids.add(clone_id)
        async with AsyncExitStack() as worker_cleanup:
            worker_cleanup.push_async_callback(clone.close)
            worker_cleanup.callback(self._active_ids.discard, clone_id)
            worker_cleanup.push_async_callback(client.kill, clone_id)
            try:
                await clone.connect()
                ctx = await clone.create_code_context("python")
                result = await clone.run_code(
                    build_command_trial_source(
                        self._trial_cmd,
                        self._trial_cwd,
                        overrides,
                        seed,
                        self._trial_timeout_s,
                    ),
                    context_id=ctx,
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
        transcript = tuple(
            f"env {key}={value}" for key, value in sorted(overrides.items())
        ) + (f"exit {artifact.get('exit_code')}",)
        return RawRun(
            artifact=artifact, transcript=transcript, duration_ms=duration_ms
        )
