# Crux report: flake-conviction-seed11

Scenario flake-conviction, engine sequential, seed 11, alpha 0.05.

## Verdict

Neutralizing per-process string hash randomization flipped the outcome. The baseline passed 0 of 16 trials, a rate of 0%, while this branch passed 16 of 16, a rate of 100%; those totals include the confirmation trials, and the search phase alone tends to flatter the winner. The fresh confirmation batch is the unbiased read: 10 of 10 passed on this branch against 0 of 10 at baseline, with p = 5.413e-06 against an alpha of 0.05.

Cause: hash_randomization
Confirmation p: 5.413e-06
Success rate moved from 0.000 at baseline to 1.000 with the cause neutralized.
Spent 50 trials over 1 rounds, within a budget of 50 trials and 1 rounds.

## Platform

- isolation: unknown
- attestation: level content, 0 refused trial(s)
- concurrency: asked for 1, ran 1
- cleanup: clean
- session seconds: 1253.6 (an upper bound on slot-holding time as seen from the client, not a bill)

## Clones and attestation

Counted from the platform and attestation records in each trial's artifact in investigation.json.

- clones: 50 clones for 50 trials, one clone per trial
- attestation: content on 50 of 50 trials, all 50 passed
- digests: 1 content digest across 50 attested trials: every one of those clones hashed to the same tree of 5 files
- nonce echoed: 50 of 50 trials returned this run's nonce, so the clone came from this run's snapshot
- canary read back by the host: 50 of 50 checked
- clone cycle, from the create request to the kill: p50 19.25 s, p90 20.70 s over 50 trials (linear interpolation)

## Branches

| branch | neutralized | trials | successes | rate | Wilson 95% CI | p vs baseline | status |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- |
| baseline | (none) | 16 | 0 | 0.000 | [0.000, 0.194] |  | baseline |
| no-hash_randomization | hash_randomization | 16 | 16 | 1.000 | [0.806, 1.000] | 0.001082 | cause |
| no-locale | locale | 6 | 2 | 0.333 | [0.097, 0.700] | 0.2273 | live |
| no-test_order | test_order | 6 | 1 | 0.167 | [0.030, 0.564] | 0.5 | live |
| no-timezone | timezone | 6 | 0 | 0.000 | [0.000, 0.390] | 1 | live |

The p column is the value from each branch's last exploratory look. Trial and success counts also include any confirmation batch run afterwards, so recomputing Fisher from a row's own counts will not reproduce its p. The round log below carries the per-look counts and the confirmation batch tallies.

## What failed

| Outcome | Trials |
| --- | ---: |
| exit 1 | 31 |

## Round log

### Round 1

Alpha spent this look: 0.05.
Allocations: baseline=6, no-hash_randomization=6, no-locale=6, no-test_order=6, no-timezone=6.
P values: no-hash_randomization=0.001082, no-test_order=0.5, no-timezone=1, no-locale=0.2273.
Confirmation of no-hash_randomization: 10 fresh trials per arm; 10 passed on the branch against 0 at baseline, p = 5.413e-06, which clears alpha 0.05, so the branch was confirmed.

## How to replay

Run `crux verify --recorded runs/flake-conviction-seed11` to re-derive this verdict from the 50 trials recorded in investigation.json. Nothing is rerun and no key or network is needed: the sequential procedure runs again with each trial it asks for answered from the recording, and it passes only if it asks for exactly those trials and reaches the same verdict, branch tallies and round log. That checks the statistics against the recorded outcomes; it does not measure the world again.

To measure the world again, run `crux verify runs/flake-conviction-seed11 --yes`: it reruns every trial on Solari, which needs SOLARI_API_KEY and is a paid run; --yes accepts that cost.

Run `crux serve --directory runs/flake-conviction-seed11` to open the dashboard.
