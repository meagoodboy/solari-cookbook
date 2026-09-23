"""Prove that every clone of a snapshot restored the world byte for byte. The
world is the two files convict investigates, and the base's digest is taken over
bytes read back through the files API, not over the bytes the client sent, so a
clone is checked against a number that came through the same channel."""

import hashlib
import time
from contextlib import AsyncExitStack

from .session import (EXPECTED_PATH, SUITE_PATH, WORLD_DIR, Redactor, bounded,
                      delete_snapshot, fixture_bytes, inventory, inventory_line,
                      kill, new_run_tag, sweep, sweep_line, tag)

LIFECYCLE = {"onTimeout": "kill"}
HEADER = f"{'clone':<6} {'id':<17} {'restored':<9} {'digest':<13} {'create s':<9} read ms"


async def world_digest(handle) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    for path in sorted((SUITE_PATH, EXPECTED_PATH)):
        data = await bounded(handle.files.read(path), 60)
        hasher.update(data)
        size += len(data)
    return hasher.hexdigest(), size


async def seed_world(base, say, redactor) -> str:
    await bounded(base.files.mkdir(WORLD_DIR), 60)
    await bounded(base.files.write(SUITE_PATH, fixture_bytes("ledger_suite.py")), 60)
    result = await bounded(
        base.commands.run("python3", args=["ledger_suite.py", "--record"],
                          cwd=WORLD_DIR, env={"PYTHONHASHSEED": "0"}), 60)
    if result.exitCode != 0:
        raise RuntimeError(f"recording the expectation exited {result.exitCode}")
    await bounded(base.files.write(EXPECTED_PATH, result.stdout), 60)
    digest, size = await world_digest(base)
    say(f"base     {redactor.ref(base.sandboxId, 'sbx')}   world {WORLD_DIR}: "
        f"2 files, {size} bytes, sha256 {digest[:12]}")
    return digest


async def fork_and_check(client, snapshot_id, n, digest, run_tag, say, redactor, known):
    started = time.monotonic()
    clone = await bounded(client.create(
        template="base", from_snapshot=snapshot_id, timeout_ms=300_000,
        lifecycle=LIFECYCLE, metadata=tag(run_tag, "clone")), 180)
    create_s = time.monotonic() - started
    known.add(clone.sandboxId)
    async with AsyncExitStack() as stack:
        stack.push_async_callback(clone.close)
        stack.push_async_callback(kill, client, clone.sandboxId)
        await bounded(clone.connect(), 60)
        started = time.monotonic()
        seen, _ = await world_digest(clone)
        read_ms = round((time.monotonic() - started) * 1000)
        restored = seen == digest
        say(f"{n:<6} {redactor.ref(clone.sandboxId, 'sbx'):<17} "
            f"{'yes' if restored else 'no':<9} {seen[:12]:<13} {create_s:<9.1f} {read_ms}")
        #  Overwritten after the read: a clone that inherited this write fails its check.
        await bounded(clone.files.write(EXPECTED_PATH, f"overwritten by clone {n}\n"), 60)
    return restored


async def attest(client, *, clones: int, say, redactor: Redactor, run_tag=None) -> int:
    run_tag = run_tag or new_run_tag()
    say(f"run {run_tag}   (if this process dies: python -m flake_conviction reap {run_tag})")
    known: set[str] = set()
    restored = 0
    code = 0
    try:
        say(inventory_line("before", await inventory(client, run_tag)))
        async with AsyncExitStack() as run_stack:
            async with AsyncExitStack() as base_stack:
                base = await bounded(client.create(
                    template="base", timeout_ms=600_000, lifecycle=LIFECYCLE,
                    metadata=tag(run_tag, "base")), 180)
                known.add(base.sandboxId)
                base_stack.push_async_callback(base.close)
                base_stack.push_async_callback(kill, client, base.sandboxId)
                await bounded(base.connect(), 60)
                digest = await seed_world(base, say, redactor)
                started = time.monotonic()
                snapshot_id = await bounded(base.snapshot(f"{run_tag}-world"), 290)
                run_stack.push_async_callback(delete_snapshot, client, snapshot_id)
                snapshot_s = time.monotonic() - started
            say(f"snapshot {redactor.ref(snapshot_id, 'snap')}  {snapshot_s:.1f} s, base killed")
            say(HEADER)
            for n in range(1, clones + 1):
                restored += await fork_and_check(
                    client, snapshot_id, n, digest, run_tag, say, redactor, known)
        if restored == clones:
            say(f"{restored} of {clones} clones restored the world byte for byte; each was "
                "overwritten after its read, so every later clone restored from the "
                "snapshot and not from its predecessor")
        else:
            say(f"{restored} of {clones} clones restored the world; the rest were killed unscored")
            code = 1
    except Exception as exc:  # noqa: BLE001 - the sweep and census below must still run
        say(f"failed   {redactor.scrub(f'{type(exc).__name__}: {exc}')}")
        code = 3
    finally:
        say(sweep_line("sweep", await sweep(client, run_tag, known)))
        say(inventory_line("after", await inventory(client, run_tag)))
    return code
