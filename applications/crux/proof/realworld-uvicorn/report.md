# Crux report: uvicorn-test-order-seed7

Scenario uvicorn-test-order, seed 7, alpha 0.05.

## Verdict

Neutralizing pytest-randomly shuffles test order per run flipped the outcome. The baseline passed 8 of 40 trials, a rate of 20%, while this branch passed 40 of 40, a rate of 100%; those totals include the confirmation trials, and the search phase alone tends to flatter the winner. The fresh confirmation batch is the unbiased read: 24 of 24 passed on this branch against 6 of 24 at baseline, with p = 1.841e-08 against an alpha of 0.05.

Cause: test_order_shuffle
Confirmation p: 1.841e-08
Success rate moved from 0.200 at baseline to 1.000 with the cause neutralized.
Spent 144 trials over 2 rounds, within a budget of 240 trials and 6 rounds.

## Branches

| branch | neutralized | trials | successes | rate | Wilson 95% CI | p vs baseline | status |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- |
| baseline | (none) | 40 | 8 | 0.200 | [0.105, 0.348] |  | baseline |
| no-hash_randomization | hash_randomization | 16 | 3 | 0.188 | [0.066, 0.430] | 0.5 | live |
| no-locale | locale | 16 | 2 | 0.125 | [0.035, 0.360] | 0.7002 | dropped for futility |
| no-malloc_allocator | malloc_allocator | 16 | 0 | 0.000 | [0.000, 0.194] | 1 | dropped for futility |
| no-test_order_shuffle | test_order_shuffle | 40 | 40 | 1.000 | [0.912, 1.000] | 2.545e-07 | cause |
| no-timezone | timezone | 16 | 2 | 0.125 | [0.035, 0.360] | 0.7002 | dropped for futility |

The p column is the value from each branch's last exploratory look. Trial and success counts also include any confirmation batch run afterwards, so recomputing Fisher from a row's own counts will not reproduce its p. The round log below carries the per-look counts and the confirmation batch tallies.

## Round log

### Round 1

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-hash_randomization=8, no-locale=8, no-malloc_allocator=8, no-test_order_shuffle=8, no-timezone=8.
P values: no-test_order_shuffle=0.003497, no-hash_randomization=1, no-timezone=0.9, no-locale=1, no-malloc_allocator=1.

### Round 2

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-hash_randomization=8, no-locale=8, no-malloc_allocator=8, no-test_order_shuffle=8, no-timezone=8.
P values: no-test_order_shuffle=2.545e-07, no-hash_randomization=0.5, no-timezone=0.7002, no-locale=0.7002, no-malloc_allocator=1.
confirmations: [{"branch": "no-test_order_shuffle", "trials_per_arm": 24, "branch_successes": 24, "baseline_successes": 6, "p": 1.8412996073602196e-08, "passed": true}]

## How to replay

Run `crux verify proof/realworld-uvicorn` to rerun the investigation from its saved seed and check that the same cause comes back. Run `crux serve --directory proof/realworld-uvicorn` to open the dashboard.
