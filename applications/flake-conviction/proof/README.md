# Proof

Live runs pending. `probe-429.txt` is real: produced 2026-09-22 with no key
against solari-sandbox 0.2.1, solari-core 0.2.1 and crux 0.2.0. The attest and
convict transcripts and the bundle's `report.md` do not exist yet; the owner
produces them from `applications/flake-conviction` with `SOLARI_API_KEY`
exported, then records the versions and date here:

```bash
python -m flake_conviction attest --clones 5 --yes > proof/attest.txt
python -m flake_conviction convict --yes > proof/convict.txt
crux verify runs/flake-conviction-seed11 --recorded >> proof/convict.txt
cp runs/flake-conviction-seed11/report.md proof/convict-report.md
python -m flake_conviction probe-429 > proof/probe-429.txt
```

Redaction: ids this application prints are salted sha256 prefixes joined with
a hyphen, and the salt is drawn per process and never written; the `[crux]`
lines in convict.txt carry crux's own refs, the same prefixes joined with an
underscore to exactly 12 hex characters. A real id is longer, so before
committing run
`grep -nE "(sbx|snap)_" proof/* | grep -vE "(sbx|snap)_[0-9a-f]{12}([^0-9a-f]|$)"`
and `grep -n "s[l]r_" proof/*` (bracketed so this file does not match its own
check); both must print nothing. Run tags (`fc-`) are the application's own.

The bundle's `investigation.json` is not committed: at about 56 lines per trial
it is larger than this whole directory. `convict` regenerates it, and `crux
verify --recorded` on it is what the transcript in convict.txt will record.
