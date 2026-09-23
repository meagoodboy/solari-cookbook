# flake-conviction

Reruns a flaky test many times in forked Solari snapshot clones, one suspected
cause neutralized per arm, and convicts the cause with a corrected test and a
fresh confirmation batch. It shows two things a fork makes possible, and one
measured platform finding: every clone is attested (the world is read back
through the files API and its digest compared with the base's, so a clone that
merely booted is refused rather than scored), the conviction comes with a
p-value a reader can re-derive from the recorded trials without a key, and the
finding is reproduced offline: the SDK retries a concurrency 429 that its own
docstring says is never retried.

Worldline, in the directory beside this one, picks the best plan forward from
one checkpoint; this convicts a cause backward from many clones of one
checkpoint. Same primitive, opposite direction. The statistics, the fork
backend and the bundle format are [crux](https://github.com/meagoodboy/crux);
this directory holds only the fixture, the attestation, the probe and the sweep.

## Install

```bash
cd applications/flake-conviction
python -m venv .venv
source .venv/bin/activate
python -m pip install git+https://github.com/meagoodboy/crux
python -m pip install .
```

Needs Python 3.11 or newer for the venv line. On Windows PowerShell, replace
the activation command with `.venv\Scripts\Activate.ps1`; the rest is the same.

crux is declared as an ordinary dependency, `crux>=0.2,<1`, but its repository
is private at the time of writing, so the crux line above needs access to it.
The `crux` on PyPI is an unrelated client whose releases the pin excludes, so
`pip install .` alone stops at that requirement rather than installing the
wrong package, and `convict` names the crux it found if the wrong one is there.

## Run

`attest`, `convict` and `reap` read `SOLARI_API_KEY` from the environment.
`attest` and `convict` print their plan and create nothing without `--yes`;
`reap` has no gate and only kills and deletes what carries the `fc-` run tag
you name, which every live run prints first. A dead convict run is recovered
with crux's own tooling: `~/.crux/runs` and `crux sandboxes --kill-all --yes`.

```bash
export SOLARI_API_KEY=slr_live_...
python -m flake_conviction attest --clones 3 --yes
python -m flake_conviction convict --yes
python -m flake_conviction probe-429
```

**attest** builds a base, writes the fixture into it, records the expected
output under `PYTHONHASHSEED=0`, snapshots, kills the base, then forks clones
one at a time. Each clone's world is read back through `files.read`, digested,
and compared with the base's digest, itself taken over bytes read back through
the same channel; after the read the clone overwrites `expected.txt`, which
changes the digest, so the next clone has to restore from the snapshot and not
from its predecessor. It prints a per-clone table,
sweeps by run tag (a kill the sweep could not finish is counted, not printed),
and prints the account census before and after. Cost: 1 base, 1 snapshot, N
clones; on the account crux measured (PLATFORM.md, 2026-09-19) a snapshot takes
about 28 s and a clone about 23 s.

**convict** runs one crux investigation of the planted fixture: four suspects
(hash randomization, test order, timezone, locale), six trials per branch, ten
confirmation trials per arm, one clone per trial with content-level attestation.
The build stage is a static script shipped as a file; the suite travels into
the sandbox as an env value, and both are recorded verbatim in the bundle's
`world.json`. The bundle lands in `runs/` and replays two ways: `crux verify
<bundle> --recorded` re-derives the verdict from the recorded trials with no
key, and `crux verify <bundle> --yes` rebuilds the same world and reruns it.
Cost: 1 base plus up to 50 clones; crux's own 50-clone run took 1,410 s.

**probe-429** needs no key: the SDK is handed an `httpx.MockTransport` that
answers every request with the gateway's concurrency refusal body, and the
requests that reach it are counted. `create()` (a POST with an Idempotency-Key)
is sent six times with backoff; `promote_snapshot()` (no key) once. Exit 0 when
it reproduces, 1 when the installed SDK sends a refused create once. The live
measurement behind the mock's `retryable: true` is crux's: 15 refused creates
on 2026-09-19, each 6 HTTP attempts and about 7.25 s, first reply in 0.32 s.

## Test

```bash
python -m unittest discover -s tests -v
```

Twenty-one tests, no key, no network. The Solari client is an in-memory fake
with five faults (a clone restored one byte wrong, a refused create, an orphan
whose id the caller never learned, a foreign sandbox the tag filter leaked, a
kill that raises with the raw id in its message); the crux world is a stub
whose bundle `crux verify --recorded` then checks in-process; the fixture runs
locally under twelve hash seeds before anyone pays for a sandbox; the 429 tests
run the real SDK over the mock transport, about five seconds of its backoff.

## Proof

The live transcripts are pending. `proof/probe-429.txt` needs no key and is
real; `proof/README.md` holds the commands that produce the others, which the
owner runs with a key before this is merged, and names the versions behind each
file. Until then every cost line above cites crux's own receipt, not this one.

## Limits

The fixture is planted and the conviction is of the fixture, not of your suite;
for your own suite, `crux flaky` is the command. The 429 finding is against
solari-sandbox 0.2.1, and the probe's exit code says whether it still reproduces
on the version installed. Trials run one clone at a time, which leaves one of
the measured account's two slots free and keeps the timing comparable to crux's.
