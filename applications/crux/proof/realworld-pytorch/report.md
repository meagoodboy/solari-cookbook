# Crux report: pytorch-knapsack-hashseed-seed7

Scenario pytorch-knapsack-hashseed, seed 7, alpha 0.05.

## Verdict

Neutralizing per-process string hash randomization flipped the outcome. The baseline passed 19 of 40 trials, a rate of 48%, while this branch passed 40 of 40, a rate of 100%; those totals include the confirmation trials, and the search phase alone tends to flatter the winner. The fresh confirmation batch is the unbiased read: 24 of 24 passed on this branch against 11 of 24 at baseline, with p = 1.294e-05 against an alpha of 0.05.

Cause: hash_randomization
Confirmation p: 1.294e-05
Success rate moved from 0.475 at baseline to 1.000 with the cause neutralized.
Spent 144 trials over 2 rounds, within a budget of 240 trials and 6 rounds.

## Branches

| branch | neutralized | trials | successes | rate | Wilson 95% CI | p vs baseline | status |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- |
| baseline | (none) | 40 | 19 | 0.475 | [0.329, 0.625] |  | baseline |
| no-bytecode_cache | bytecode_cache | 16 | 8 | 0.500 | [0.280, 0.720] | 0.6378 | dropped for futility |
| no-hash_randomization | hash_randomization | 40 | 40 | 1.000 | [0.912, 1.000] | 0.001224 | cause |
| no-locale | locale | 16 | 9 | 0.562 | [0.332, 0.769] | 0.5 | live |
| no-malloc_allocator | malloc_allocator | 16 | 8 | 0.500 | [0.280, 0.720] | 0.6378 | dropped for futility |
| no-timezone | timezone | 16 | 10 | 0.625 | [0.386, 0.815] | 0.3612 | live |

The p column is the value from each branch's last exploratory look. Trial and success counts also include any confirmation batch run afterwards, so recomputing Fisher from a row's own counts will not reproduce its p. The round log below carries the per-look counts and the confirmation batch tallies.

## Round log

### Round 1

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-bytecode_cache=8, no-hash_randomization=8, no-locale=8, no-malloc_allocator=8, no-timezone=8.
P values: no-hash_randomization=0.1, no-timezone=0.6958, no-locale=0.8427, no-malloc_allocator=0.6958, no-bytecode_cache=0.8427.

### Round 2

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-bytecode_cache=8, no-hash_randomization=8, no-locale=8, no-malloc_allocator=8, no-timezone=8.
P values: no-hash_randomization=0.001224, no-timezone=0.3612, no-locale=0.5, no-malloc_allocator=0.6378, no-bytecode_cache=0.6378.
confirmations: [{"branch": "no-hash_randomization", "trials_per_arm": 24, "branch_successes": 24, "baseline_successes": 11, "p": 1.2938198574384477e-05, "passed": true}]

## How to replay

Run `crux verify proof/realworld-pytorch` to rerun the investigation from its saved seed and check that the same cause comes back. Run `crux serve --directory proof/realworld-pytorch` to open the dashboard.
