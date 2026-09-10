# Crux report: live-solari-seed7

Scenario live-solari, seed 7, alpha 0.05.

## Verdict

Neutralizing long line-item tables render in two columns flipped the outcome. The baseline passed 14 of 28 trials, a rate of 50%, while this branch passed 28 of 28, a rate of 100%; those totals include the confirmation trials, and the search phase alone tends to flatter the winner. The fresh confirmation batch is the unbiased read: 16 of 16 passed on this branch against 8 of 16 at baseline, with p = 0.001224 against an alpha of 0.05.

Cause: two_column_layout
Confirmation p: 0.001224
Success rate moved from 0.500 at baseline to 1.000 with the cause neutralized.
Spent 68 trials over 2 rounds, within a budget of 68 trials and 2 rounds.

## Branches

| branch | neutralized | trials | successes | rate | Wilson 95% CI | p vs baseline | status |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- |
| baseline | (none) | 28 | 14 | 0.500 | [0.326, 0.674] |  | baseline |
| no-cookie_banner | cookie_banner | 12 | 7 | 0.583 | [0.320, 0.807] | 0.5 | live |
| no-two_column_layout | two_column_layout | 28 | 28 | 1.000 | [0.879, 1.000] | 0.006865 | cause |

The p column is the value from each branch's last exploratory look. Trial and success counts also include any confirmation batch run afterwards, so recomputing Fisher from a row's own counts will not reproduce its p. The round log below carries the per-look counts and the confirmation batch tallies.

## Round log

### Round 1

Alpha spent this look: 0.025.
Allocations: baseline=6, no-cookie_banner=6, no-two_column_layout=6.
P values: no-two_column_layout=0.5, no-cookie_banner=0.9924.

### Round 2

Alpha spent this look: 0.025.
Allocations: baseline=6, no-cookie_banner=6, no-two_column_layout=6.
P values: no-two_column_layout=0.006865, no-cookie_banner=0.5.
confirmations: [{"branch": "no-two_column_layout", "trials_per_arm": 16, "branch_successes": 16, "baseline_successes": 8, "p": 0.0012235817575083426, "passed": true}]

## How to replay

Run `crux verify /Users/aswin/Project/crux/proof/live` to rerun the investigation from its saved seed and check that the same cause comes back. Run `crux serve --directory /Users/aswin/Project/crux/proof/live` to open the dashboard.
