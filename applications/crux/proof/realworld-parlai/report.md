# Crux report: parlai-unseeded-rng-seed7

Scenario parlai-unseeded-rng, seed 7, alpha 0.05.

## Verdict

Neutralizing global random module left on OS entropy flipped the outcome. The baseline passed 21 of 40 trials, a rate of 52%, while this branch passed 40 of 40, a rate of 100%; those totals include the confirmation trials, and the search phase alone tends to flatter the winner. The fresh confirmation batch is the unbiased read: 24 of 24 passed on this branch against 13 of 24 at baseline, with p = 0.0001105 against an alpha of 0.05.

Cause: unseeded_global_rng
Confirmation p: 0.0001105
Success rate moved from 0.525 at baseline to 1.000 with the cause neutralized.
Spent 144 trials over 2 rounds, within a budget of 240 trials and 6 rounds.

## Branches

| branch | neutralized | trials | successes | rate | Wilson 95% CI | p vs baseline | status |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- |
| baseline | (none) | 40 | 21 | 0.525 | [0.375, 0.671] |  | baseline |
| no-hash_randomization | hash_randomization | 16 | 7 | 0.438 | [0.231, 0.668] | 0.7603 | dropped for futility |
| no-locale | locale | 16 | 7 | 0.438 | [0.231, 0.668] | 0.7603 | dropped for futility |
| no-malloc_allocator | malloc_allocator | 16 | 6 | 0.375 | [0.185, 0.614] | 0.8574 | dropped for futility |
| no-timezone | timezone | 16 | 9 | 0.562 | [0.332, 0.769] | 0.5 | live |
| no-unseeded_global_rng | unseeded_global_rng | 40 | 40 | 1.000 | [0.912, 1.000] | 0.001224 | cause |

The p column is the value from each branch's last exploratory look. Trial and success counts also include any confirmation batch run afterwards, so recomputing Fisher from a row's own counts will not reproduce its p. The round log below carries the per-look counts and the confirmation batch tallies.

## Round log

### Round 1

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-hash_randomization=8, no-locale=8, no-malloc_allocator=8, no-timezone=8, no-unseeded_global_rng=8.
P values: no-unseeded_global_rng=0.03846, no-hash_randomization=0.6904, no-timezone=0.3042, no-locale=0.8427, no-malloc_allocator=0.6904.

### Round 2

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-hash_randomization=8, no-locale=8, no-malloc_allocator=8, no-timezone=8, no-unseeded_global_rng=8.
P values: no-unseeded_global_rng=0.001224, no-hash_randomization=0.7603, no-timezone=0.5, no-locale=0.7603, no-malloc_allocator=0.8574.
confirmations: [{"branch": "no-unseeded_global_rng", "trials_per_arm": 24, "branch_successes": 24, "baseline_successes": 13, "p": 0.00011047231090435976, "passed": true}]

## How to replay

Run `crux verify /Users/aswin/Project/crux/proof/realworld-parlai` to rerun the investigation from its saved seed and check that the same cause comes back. Run `crux serve --directory /Users/aswin/Project/crux/proof/realworld-parlai` to open the dashboard.
