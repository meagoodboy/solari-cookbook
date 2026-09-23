# Proof

Every file here is from one live run of this application on 2026-09-23,
against solari-sandbox 0.2.1, solari-core 0.2.1 and crux 0.2.0 (commit
bc310a5, installed non-editable from a `git archive` of that commit), on
Python 3.13.11, with the application itself installed non-editable from this
directory. The commands, in the order they ran, with `SOLARI_API_KEY`
exported and nothing else changed:

```bash
python -m flake_conviction attest --clones 5 --yes > proof/attest.txt
python -m flake_conviction convict --yes > proof/convict.txt
crux verify runs/flake-conviction-seed11 --recorded >> proof/convict.txt
cp runs/flake-conviction-seed11/report.md proof/convict-report.md
python -m flake_conviction probe-429 > proof/probe-429.txt
```

What each file records:

- `attest.txt`: 06:16:50Z to 06:19:01Z, exit 0. One base, one snapshot
  (28.1 s), five clones, five of five restored the world byte for byte. The
  sweep found nothing to kill and the census is identical before and after.
- `convict.txt`: 06:19:26Z to 06:40:39Z, exit 0, followed by the
  `crux verify --recorded` transcript, exit 0. One base plus 50 clones, one
  per trial, all 50 attested at content level, 0 refusals, 0 retries, cleanup
  clean and the snapshot deleted. One thing did not go to plan: the snapshot
  call did not return within crux's 290 s bound, crux looked the finished
  snapshot up by name and adopted it, and every clone's attestation then
  passed against it. The identical snapshot in attest.txt took 28.1 s five
  minutes earlier.
- `convict-report.md`: the bundle's own report, copied unchanged.
- `probe-429.txt`: no key, no network; exit 0, reproduced on the SDK it names.

Timings quoted in the README come from these files and from the bundle's
`platform.json` (`timing_ms` per trial, `snapshot.ms`, `session_seconds`).

The account census was taken with the SDK before the first command and after
the last one, with a reap of the attest run tag in between that found nothing:
0 sandboxes and 6 snapshots both times, the 6 being the owner's and none of
them this application's. Create calls across the three commands: 57, which is
6 in attest and 51 in convict; probe-429 creates nothing.

Redaction: ids this application prints are salted sha256 prefixes joined with
a hyphen, and the salt is drawn per process and never written; the `[crux]`
lines in convict.txt carry crux's own refs, the same prefixes joined with an
underscore to exactly 12 hex characters. A real id is longer, so before
committing run
`grep -nE "(sbx|snap)_" proof/* | grep -vE "(sbx|snap)_[0-9a-f]{12}([^0-9a-f]|$)"`
and `grep -n "s[l]r_" proof/*` (bracketed so this file does not match its own
check); both must print nothing, and both printed nothing for this run. Run
tags (`fc-`) are the application's own.

The bundle's `investigation.json` is not committed: at about 56 lines per trial
it is larger than this whole directory. `convict` regenerates it, and `crux
verify --recorded` on it is what the transcript in convict.txt records.
