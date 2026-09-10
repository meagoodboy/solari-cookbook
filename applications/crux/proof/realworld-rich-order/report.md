# Crux report: rich-box-order-seed7

Scenario rich-box-order, seed 7, alpha 0.05.

## Verdict

Neutralizing pytest-randomly shuffles test order per run flipped the outcome. The baseline passed 25 of 48 trials, a rate of 52%, while this branch passed 48 of 48, a rate of 100%; those totals include the confirmation trials, and the search phase alone tends to flatter the winner. The fresh confirmation batch is the unbiased read: 24 of 24 passed on this branch against 11 of 24 at baseline, with p = 1.294e-05 against an alpha of 0.05.

Cause: test_order_shuffle
Confirmation p: 1.294e-05
Success rate moved from 0.521 at baseline to 1.000 with the cause neutralized.
Spent 160 trials over 3 rounds, within a budget of 240 trials and 6 rounds.

## Branches

| branch | neutralized | trials | successes | rate | Wilson 95% CI | p vs baseline | status |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- |
| baseline | (none) | 48 | 25 | 0.521 | [0.383, 0.655] |  | baseline |
| no-hash_randomization | hash_randomization | 16 | 10 | 0.625 | [0.386, 0.815] | 0.642 | dropped for futility |
| no-locale | locale | 16 | 7 | 0.438 | [0.231, 0.668] | 0.9222 | dropped for futility |
| no-malloc_allocator | malloc_allocator | 16 | 6 | 0.375 | [0.185, 0.614] | 0.9622 | dropped for futility |
| no-test_order_shuffle | test_order_shuffle | 48 | 48 | 1.000 | [0.926, 1.000] | 0.0002999 | cause |
| no-timezone | timezone | 16 | 9 | 0.562 | [0.332, 0.769] | 0.7637 | dropped for futility |

The p column is the value from each branch's last exploratory look. Trial and success counts also include any confirmation batch run afterwards, so recomputing Fisher from a row's own counts will not reproduce its p. The round log below carries the per-look counts and the confirmation batch tallies.

## Round log

### Round 1

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-hash_randomization=8, no-locale=8, no-malloc_allocator=8, no-test_order_shuffle=8, no-timezone=8.
P values: no-test_order_shuffle=0.1, no-hash_randomization=0.6958, no-timezone=0.6958, no-locale=0.8427, no-malloc_allocator=0.934.

### Round 2

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-hash_randomization=8, no-locale=8, no-malloc_allocator=8, no-test_order_shuffle=8, no-timezone=8.
P values: no-test_order_shuffle=0.008837, no-hash_randomization=0.642, no-timezone=0.7637, no-locale=0.9222, no-malloc_allocator=0.9622.

### Round 3

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-test_order_shuffle=8.
P values: no-test_order_shuffle=0.0002999.
confirmations: [{"branch": "no-test_order_shuffle", "trials_per_arm": 24, "branch_successes": 24, "baseline_successes": 11, "p": 1.2938198574384477e-05, "passed": true}]

## How to replay

Run `crux verify proof/realworld-rich-order` to rerun the investigation from its saved seed and check that the same cause comes back. Run `crux serve --directory proof/realworld-rich-order` to open the dashboard.
