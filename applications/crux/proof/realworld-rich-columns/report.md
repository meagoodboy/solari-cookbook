# Crux report: rich-columns-env-seed7

Scenario rich-columns-env, seed 7, alpha 0.05.

## Verdict

Neutralizing COLUMNS and LINES exported in the shell flipped the outcome. The baseline passed 0 of 32 trials, a rate of 0%, while this branch passed 32 of 32, a rate of 100%; those totals include the confirmation trials, and the search phase alone tends to flatter the winner. The fresh confirmation batch is the unbiased read: 24 of 24 passed on this branch against 0 of 24 at baseline, with p = 3.101e-14 against an alpha of 0.05.

Cause: columns_exported
Confirmation p: 3.101e-14
Success rate moved from 0.000 at baseline to 1.000 with the cause neutralized.
Spent 88 trials over 1 rounds, within a budget of 240 trials and 6 rounds.

## Branches

| branch | neutralized | trials | successes | rate | Wilson 95% CI | p vs baseline | status |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- |
| baseline | (none) | 32 | 0 | 0.000 | [0.000, 0.107] |  | baseline |
| no-columns_exported | columns_exported | 32 | 32 | 1.000 | [0.893, 1.000] | 7.77e-05 | cause |
| no-hash_randomization | hash_randomization | 8 | 0 | 0.000 | [0.000, 0.324] | 1 | live |
| no-locale | locale | 8 | 0 | 0.000 | [0.000, 0.324] | 1 | live |
| no-timezone | timezone | 8 | 0 | 0.000 | [0.000, 0.324] | 1 | live |

The p column is the value from each branch's last exploratory look. Trial and success counts also include any confirmation batch run afterwards, so recomputing Fisher from a row's own counts will not reproduce its p. The round log below carries the per-look counts and the confirmation batch tallies.

## Round log

### Round 1

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-columns_exported=8, no-hash_randomization=8, no-locale=8, no-timezone=8.
P values: no-columns_exported=7.77e-05, no-hash_randomization=1, no-timezone=1, no-locale=1.
confirmations: [{"branch": "no-columns_exported", "trials_per_arm": 24, "branch_successes": 24, "baseline_successes": 0, "p": 3.101005612159858e-14, "passed": true}]

## How to replay

Run `crux verify proof/realworld-rich-columns` to rerun the investigation from its saved seed and check that the same cause comes back. Run `crux serve --directory proof/realworld-rich-columns` to open the dashboard.
