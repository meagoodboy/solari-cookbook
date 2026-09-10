# Crux operating characteristics

Master seed 7, 200 seeded instances per family. Each instance runs three methods on the same world construction: the full crux investigation, a naive gap read of 5 trials per arm, and a single fixed-budget look of 240 trials.

## Scoring

A conviction is correct only when it names the true factor set exactly. For the no-cause family the right outcome is no conviction at all, so any conviction there counts as wrong. For the conjunction family a single-factor conviction is wrong, with no partial credit. Note that the two baseline methods only ever test single-factor arms, so on the conjunction family their correct rate is zero by construction and the comparison there measures the crux pairwise escalation alone. A wrong conviction is worse than no conviction: wrong aims the fix at an innocent factor, while none just says keep looking.

## Aggregate table

| Family | Method | Correct % | Wrong % | None % | Mean trials | Median trials | Mean rounds | Mean confirmations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| layout-cause | crux | 88 | 0.5 | 11.5 | 181.9 | 176 | 3.5 | 0.98 |
| layout-cause | naive-gap | 57.5 | 32.5 | 10 | 30 | 30 |  |  |
| layout-cause | fixed-budget | 99 | 0 | 1 | 240 | 240 |  |  |
| no-cause | crux | 0 | 0 | 100 | 216.9 | 216 | 5.88 | 0.01 |
| no-cause | naive-gap | 0 | 68 | 32 | 30 | 30 |  |  |
| no-cause | fixed-budget | 0 | 0.5 | 99.5 | 240 | 240 |  |  |
| conjunction-cause | crux | 19 | 0 | 81 | 218.7 | 224 | 5.63 | 0.2 |
| conjunction-cause | naive-gap | 0 | 69.5 | 30.5 | 30 | 30 |  |  |
| conjunction-cause | fixed-budget | 0 | 2 | 98 | 240 | 240 |  |  |
| weak-cause | crux | 0 | 0 | 100 | 221.6 | 232 | 5.86 | 0.03 |
| weak-cause | naive-gap | 1.5 | 48 | 50.5 | 30 | 30 |  |  |
| weak-cause | fixed-budget | 9 | 2 | 89 | 240 | 240 |  |  |

## Reading the table

Rounds and confirmations apply to crux only; the naive method takes one implicit look and the fixed-budget method exactly one planned look. Trial counts for crux vary because the procedure stops early once a cause is confirmed or every suspect is retired. Rerunning with the same master seed reproduces every number here.

Running `python -m crux bench` writes the full per-instance records to
results.json beside this file. The run is deterministic from the master
seed, so the raw file stays out of the repository; every number in this
table can be regenerated on demand.
