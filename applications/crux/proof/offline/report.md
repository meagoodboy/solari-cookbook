# Crux report: demo-seed7

Scenario demo, seed 7, alpha 0.05.

## Verdict

Neutralizing long line-item tables render in two columns flipped the outcome. The baseline passed 32 of 48 trials, a rate of 67%, while this branch passed 48 of 48, a rate of 100%; those totals include the confirmation trials, and the search phase alone tends to flatter the winner. The fresh confirmation batch is the unbiased read: 24 of 24 passed on this branch against 17 of 24 at baseline, with p = 0.004701 against an alpha of 0.05.

Cause: two_column_layout
Confirmation p: 0.004701
Success rate moved from 0.667 at baseline to 1.000 with the cause neutralized.
Spent 184 trials over 3 rounds, within a budget of 240 trials and 6 rounds.

## Branches

| branch | neutralized | trials | successes | rate | Wilson 95% CI | p vs baseline | status |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- |
| baseline | (none) | 48 | 32 | 0.667 | [0.525, 0.783] |  | baseline |
| no-context_trim | context_trim | 24 | 16 | 0.667 | [0.467, 0.820] | 0.5 | live |
| no-cookie_banner | cookie_banner | 24 | 12 | 0.500 | [0.314, 0.686] | 0.8778 | dropped for futility |
| no-model_temperature | model_temperature | 16 | 8 | 0.500 | [0.280, 0.720] | 0.7603 | dropped for futility |
| no-network_latency | network_latency | 24 | 15 | 0.625 | [0.427, 0.788] | 0.6169 | dropped for futility |
| no-two_column_layout | two_column_layout | 48 | 48 | 1.000 | [0.926, 1.000] | 0.0007796 | cause |

The p column is the value from each branch's last exploratory look. Trial and success counts also include any confirmation batch run afterwards, so recomputing Fisher from a row's own counts will not reproduce its p. The round log below carries the per-look counts and the confirmation batch tallies.

## Round log

### Round 1

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-context_trim=8, no-cookie_banner=8, no-model_temperature=8, no-network_latency=8, no-two_column_layout=8.
P values: no-two_column_layout=0.1, no-cookie_banner=0.8427, no-model_temperature=0.6958, no-network_latency=0.6958, no-context_trim=0.5.

### Round 2

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-context_trim=8, no-cookie_banner=8, no-model_temperature=8, no-network_latency=8, no-two_column_layout=8.
P values: no-two_column_layout=0.003399, no-cookie_banner=0.5, no-model_temperature=0.7603, no-network_latency=0.358, no-context_trim=0.358.

### Round 3

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-context_trim=8, no-cookie_banner=8, no-network_latency=8, no-two_column_layout=8.
P values: no-two_column_layout=0.0007796, no-cookie_banner=0.8778, no-network_latency=0.6169, no-context_trim=0.5.
confirmations: [{"branch": "no-two_column_layout", "trials_per_arm": 24, "branch_successes": 24, "baseline_successes": 17, "p": 0.0047006432459178625, "passed": true}]

## How to replay

Run `crux verify proof/offline` to rerun the investigation from its saved seed and check that the same cause comes back. Run `crux serve --directory proof/offline` to open the dashboard.
