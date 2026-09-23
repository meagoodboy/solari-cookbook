"""In-memory stand-in for the subset of SandboxClient this application calls.
crux's own fake lives in its tests directory and is not installable. Raw ids use
underscores like the real ones, so a leaked id and a hyphenated ref differ by prefix."""

import secrets
from types import SimpleNamespace

from solari_sandbox import ConcurrencyLimitError
from solari_sandbox import ConnectionError as SdkConnectionError

RECORDED = "usd=10.00 eur=20.00 gbp=30.00 jpy=40.00\n"


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def record(metadata: dict, foreign: bool = False) -> SimpleNamespace:
    """A server-side sandbox record; listings return these as views."""
    return SimpleNamespace(sandboxId=new_id("sbx"), metadata=metadata, files={},
                           state="running", foreign=foreign)


class FakeSandbox:
    def __init__(self, client: "FakeClient", box: SimpleNamespace) -> None:
        self.client, self.box, self.sandboxId, self.connected = client, box, box.sandboxId, False
        self.files = SimpleNamespace(mkdir=self.mkdir, read=self.read, write=self.write)
        self.commands = SimpleNamespace(run=self.run)

    def live(self) -> None:
        if self.box.state != "running" or not self.connected:
            raise RuntimeError("no live control channel")

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.connected = False

    async def mkdir(self, path: str) -> None:
        self.live()

    async def read(self, path: str) -> bytes:
        self.live()
        return self.box.files[path]

    async def write(self, path: str, data) -> None:
        self.live()
        self.box.files[path] = data if isinstance(data, bytes) else data.encode("utf-8")

    async def run(self, cmd: str, *, args=None, cwd=None, env=None):
        self.live()
        return SimpleNamespace(exitCode=0, stdout=RECORDED if "--record" in (args or []) else "",
                               stderr="")

    async def snapshot(self, name: str) -> str:
        self.live()
        snap = SimpleNamespace(id=new_id("snap"), name=name, files=dict(self.box.files))
        self.client.snapshots[snap.id] = snap
        return snap.id


class FakeClient:
    """Faults, one per constructor argument: corrupt_clone=n flips a byte in the
    nth clone's restored world; fail_create_at=n makes the nth create raise the
    SDK's ConcurrencyLimitError; orphan_create_at=n provisions the nth record and
    then raises a connection error, so the caller never learns its id;
    leak_foreign adds somebody else's sandbox that a tag-filtered listing also
    returns, which is the failure the client-side metadata check exists for;
    kill_raises_at=n makes the nth kill raise the SDK's ConnectionError with the
    raw id in its message, as solari_core builds it, and leaves the sandbox up."""

    def __init__(self, *, corrupt_clone=0, fail_create_at=0, orphan_create_at=0,
                 leak_foreign=False, kill_raises_at=0) -> None:
        self.corrupt_clone, self.fail_create_at = corrupt_clone, fail_create_at
        self.orphan_create_at, self.leak_foreign = orphan_create_at, leak_foreign
        self.kill_raises_at = kill_raises_at
        self.records: dict[str, SimpleNamespace] = {}
        self.snapshots: dict[str, SimpleNamespace] = {}
        self.creates = self.clones = self.kills = 0
        self.closed = False
        if leak_foreign:
            foreign = record({"app": "someone-else", "run": "theirs"}, foreign=True)
            self.records[foreign.sandboxId] = foreign

    async def create(self, *, template=None, from_snapshot=None, timeout_ms=None,
                     lifecycle=None, metadata=None) -> FakeSandbox:
        self.creates += 1
        if self.creates == self.fail_create_at:
            raise ConcurrencyLimitError()
        box = record(dict(metadata or {}))
        if from_snapshot is not None:
            box.files = dict(self.snapshots[from_snapshot].files)
            self.clones += 1
            if self.clones == self.corrupt_clone:
                path = sorted(box.files)[0]
                box.files[path] = bytes([box.files[path][0] ^ 1]) + box.files[path][1:]
        self.records[box.sandboxId] = box
        if self.creates == self.orphan_create_at:
            raise ConnectionError("connection reset before the create reply arrived")
        return FakeSandbox(self, box)

    async def kill(self, sandbox_id: str) -> None:
        self.kills += 1
        if self.kills == self.kill_raises_at:
            raise SdkConnectionError(f"DELETE /sandboxes/{sandbox_id} failed: connection reset")
        self.records[sandbox_id].state = "gone"

    async def list_all(self, *, metadata=None, state=None):
        wanted = dict(metadata or {})
        for box in self.records.values():
            matches = all(box.metadata.get(k) == v for k, v in wanted.items())
            if (matches or (wanted and box.foreign)) and (state is None or box.state == state):
                yield box

    async def list_snapshots(self, *, limit=None) -> list:
        return list(self.snapshots.values())

    async def delete_snapshot(self, snapshot_id: str) -> None:
        del self.snapshots[snapshot_id]

    async def aclose(self) -> None:
        self.closed = True

    def alive(self) -> list[str]:
        return [i for i, box in self.records.items() if box.state == "running"]
