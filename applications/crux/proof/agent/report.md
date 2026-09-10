# Crux report: invoice-agent-browser-seed7

Scenario invoice-agent-browser, seed 7, alpha 0.05.

## Verdict

Neutralizing page text cut to the first 500 characters flipped the outcome. The baseline passed 14 of 36 trials, a rate of 39%, while this branch passed 36 of 36, a rate of 100%; those totals include the confirmation trials, and the search phase alone tends to flatter the winner. The fresh confirmation batch is the unbiased read: 20 of 20 passed on this branch against 8 of 20 at baseline, with p = 2.255e-05 against an alpha of 0.05.

Cause: context_trim
Confirmation p: 2.255e-05
Success rate moved from 0.389 at baseline to 1.000 with the cause neutralized.
Spent 136 trials over 2 rounds, within a budget of 240 trials and 6 rounds.

## Branches

| branch | neutralized | trials | successes | rate | Wilson 95% CI | p vs baseline | status |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- |
| baseline | (none) | 36 | 14 | 0.389 | [0.248, 0.551] |  | baseline |
| no-context_trim | context_trim | 36 | 36 | 1.000 | [0.904, 1.000] | 0.0001241 | cause |
| no-distractor_boilerplate | distractor_boilerplate | 16 | 4 | 0.250 | [0.102, 0.495] | 0.8738 | dropped for futility |
| no-model_temperature | model_temperature | 16 | 8 | 0.500 | [0.280, 0.720] | 0.3612 | live |
| no-terse_prompt | terse_prompt | 16 | 3 | 0.188 | [0.066, 0.430] | 0.9433 | dropped for futility |
| no-two_column_layout | two_column_layout | 16 | 6 | 0.375 | [0.185, 0.614] | 0.642 | dropped for futility |

The p column is the value from each branch's last exploratory look. Trial and success counts also include any confirmation batch run afterwards, so recomputing Fisher from a row's own counts will not reproduce its p. The round log below carries the per-look counts and the confirmation batch tallies.

## Round log

### Round 1

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-context_trim=8, no-distractor_boilerplate=8, no-model_temperature=8, no-terse_prompt=8, no-two_column_layout=8.
P values: no-model_temperature=0.859, no-two_column_layout=0.6958, no-context_trim=0.01282, no-terse_prompt=0.9615, no-distractor_boilerplate=0.9615.

### Round 2

Alpha spent this look: 0.008333.
Allocations: baseline=8, no-context_trim=8, no-distractor_boilerplate=8, no-model_temperature=8, no-terse_prompt=8, no-two_column_layout=8.
P values: no-model_temperature=0.3612, no-two_column_layout=0.642, no-context_trim=0.0001241, no-terse_prompt=0.9433, no-distractor_boilerplate=0.8738.
confirmations: [{"branch": "no-context_trim", "trials_per_arm": 20, "branch_successes": 20, "baseline_successes": 8, "p": 2.2547575384060367e-05, "passed": true}]

## How to replay

Run `crux verify proof/agent` to rerun the investigation from its saved seed and check that the same cause comes back. Run `crux serve --directory proof/agent` to open the dashboard.
