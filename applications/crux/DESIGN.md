# Design notes

Crux turns "why does my agent fail sometimes" into an intervention question:
which condition, if removed, stops the failures. Observation cannot answer that.
Traces from a stochastic agent are full of coincidences, and the most memorable
coincidence wins the argument. Interventions settle it, and they become cheap
once the world can be frozen and forked: snapshot the state once, then rerun the
agent from that snapshot as many times as the budget allows, each time with a
chosen set of factors neutralized and a chosen seed.

The rest of this document explains the sequential procedure piece by piece, what
can still go wrong, how Crux relates to Worldline, and why the live backend
creates one sandbox clone per trial.

## The sequential procedure

### Branches and the basic test

The baseline keeps every factor active, matching the world in which the failure
was observed. Each single-factor branch turns exactly one factor off. After each
round, every live branch is compared to baseline with a one-sided Fisher exact
test, where the alternative is "this branch passes more often than baseline".

One-sided because the question has a direction. A factor whose removal makes the
agent worse is not a cause of the failure we are investigating, so spending
power on that tail buys nothing. Fisher exact because the counts at any single
look are small, eight trials per branch per round by default, and normal
approximations are unreliable down there. The exact hypergeometric tail costs a
few calls to `math.comb` and needs no dependencies.

### Rounds, looks, and alpha spending

Trials are allocated in rounds so the procedure can stop early. That creates the
classic peeking problem: testing after every round means many chances for noise
to cross the line, and the false positive rate climbs well above the nominal
alpha. Crux uses the bluntest correction that works, Bonferroni over looks: with
`max_rounds` looks, each look tests at `alpha / max_rounds`.

Sharper spending schemes exist (Pocock, O'Brien-Fleming). They buy power at the
cost of machinery that is harder to explain and to verify. Crux does not need
the power, because a look never accepts anything by itself. It only nominates a
branch for confirmation, and the confirmation batch is where acceptance happens.
For a nomination step, a conservative and one-line-explainable spend is the
right trade. I would rather be able to derive the correction on a whiteboard
than squeeze out one extra round of sensitivity.

### Holm across branches

Each look tests several branches at once, which is a second multiplicity axis,
independent of the looks. Within a look, the branch p-values go through the Holm
step-down procedure at the spent alpha. Holm makes no independence assumptions
and is never less powerful than plain Bonferroni across the same family, so it
is the safe default.

### Futility

A branch that has accumulated at least `futility_min_trials` trials and whose
pass rate sits at or below baseline's is dropped. If neutralizing a factor does
not raise the pass rate after sixteen trials, it is a poor use of what remains
of a 240-trial budget. Every trial a dead branch does not consume is a trial the
real contenders get, which is where the procedure's power actually comes from.
Dropped branches stay in the record and are shown greyed out in the viewer;
futility is an allocation decision, not an erasure.

The threshold matters. Dropping on rate alone at very low n would throw away
true causes on bad luck, so no branch can be dropped before sixteen trials.

### Confirmation

The exploratory winner was selected for being extreme, so its observed effect is
biased upward. This is the winner's curse, and it is the single biggest reason
tools like this overclaim. Crux therefore treats a significant look as a
nomination only. The nominated branch and the baseline each get
`confirm_trials` fresh trials under a separate seed namespace
(`confirm:<branch>`), so no exploratory trial is reused, and a single Fisher
test at the full, unspent alpha decides.

One attempt per branch. Retrying confirmation until it passes would quietly
rebuild the exact multiplicity problem the batch exists to remove. A branch that
fails confirmation is marked ineligible and the search continues without it.

### Pairwise escalation

Some failures need two conditions at once, and no single-factor branch can show
that: turn off either half of a conjunction and the failure persists, so every
single branch looks innocent. When all single-factor branches are dropped or
ineligible, or when 60% of the rounds have passed with no significant branch,
Crux adds pairwise branches over the `pairwise_top_k` single factors with the
smallest current p-values (ties broken by id). Pairs then compete like any other
branch.

Pairs come late and few because each added branch dilutes the per-branch budget
and widens the Holm family. Three factors give three pairs, which is enough to
catch a two-factor conjunction among the most suspicious candidates without
flooding the round.

### Exhaustion

The budget is 240 trials or six rounds, whichever runs out first. When it does,
the verdict is a null cause, and the summary names the closest branch and says
that no suspect met the bar. This outcome is on purpose. A cause-finding tool
that always finds a cause is a rumor generator with better formatting.

### Seeds and replay

Every trial's randomness comes from `random.Random(seed)` where the seed is the
first eight bytes of `sha256(f"{config_seed}:{branch_id}:{index}")`. Nothing
reads the global RNG or the clock. Branches cannot collide with each other, the
confirmation namespace cannot collide with exploration, and the whole
investigation is a pure function of its config. That is what makes
`crux verify` possible: it reruns everything from the stored seed and checks
that the same cause comes out.

Intervals shown in reports are Wilson intervals rather than the naive Wald
formula, because branch rates live near 0 and 1 at small n, exactly where Wald
intervals collapse or escape [0, 1].

## Threats to validity

Things the procedure defends against are covered above. These are the things it
cannot defend against, or only partly.

- The factor list is the hypothesis space. Crux tests the suspects it is given
  and pairs of the strongest ones. A cause outside that list, or a three-way
  conjunction, comes back as a null verdict at best and a misleading partial
  signal at worst.
- The oracle is trusted. Every statistic is computed over the oracle's pass or
  fail calls. An oracle that misses a failure mode makes that mode invisible; an
  oracle with its own noise adds variance the test attributes to the world.
- Independence across trials. Fisher assumes it. The seed scheme delivers it in
  the local world by construction. On live backends the risk is residue shared
  between trials, which is the main reason for clone-per-trial (below).
- World drift. Exploration and confirmation compare against baseline trials run
  at different times. If the world changes underneath (a dependency of the
  sandboxed service, say), rates move for reasons that are not factors.
  Snapshotting is the mitigation: every trial starts from the same frozen state,
  so drift can only enter through what a running trial reaches outside the
  snapshot.
- Futility can still discard a true cause whose early trials went badly. The
  sixteen-trial floor bounds this risk without eliminating it.
- Calibration transfer. The type-I and power targets (false-cause rate at most
  0.08 across 100 no-effect investigations, cause confirmed in at least 90% of
  60 demo seeds) are measured on the simulated world, end to end. They validate
  the procedure, not your agent. Margins on the demo say nothing about margins
  on a world with different effect sizes.
- Alpha is per investigation. Run Crux over twenty agents and expect the
  occasional false verdict across the fleet, confirmation batch or not.

## Crux and Worldline

Worldline and Crux are built on the same primitive, snapshot a world and fork
it, pointed in opposite directions. Worldline branches forward: given a goal, it
runs several candidate plans from the same snapshot, verifies their artifacts,
and replays only the winner, so it answers "which plan should we take". Crux
branches backward from a failure that already happened: it neutralizes suspected
conditions until the failure stops tracking one, and its confirmation batch
guards the fix by proving the effect on fresh trials. Same fork primitive,
different job, and the two compose naturally: one picks the path, the other
explains the crash and checks the repair.

## Why live clones once per trial

The live backend snapshots a base sandbox once, then, for every single trial,
creates a clone from that snapshot, runs one trial in it, and kills the clone.
This is the expensive option and it is the right one.

The trial is the unit of independence in every statistic Crux computes. Reuse a
sandbox across trials and trial n can leave residue for trial n+1: temp files, a
warmed cache, a half-dead process left over from a timeout. Residue correlated
with the assignment is exactly the kind of contamination Fisher cannot detect
and cannot forgive. A clone that lives for one trial cannot contaminate the
next one.

It also keeps the determinism promise honest. `run_trial` claims that the same
snapshot, assignment, and seed give the same run wherever the backend can honour
that. A long-lived sandbox mutates with every trial, which breaks the claim
silently. And it removes an entire class of cleanup code: there is no "restore
the shared sandbox to a known state" logic to write, test, and doubt, because
the known state is the snapshot itself. Crashed or timed-out trials are scored,
their clone is discarded, and the next clone starts clean.

The cost is real but bounded and visible. Cleanup follows the Solari cookbook
discipline: every clone is registered for kill the moment it is created, the
snapshot is deleted at the end, and any SDK error surfaces with the sandbox id
in the message. The live command prints the exact clone count before creating
anything and requires an explicit `--yes`.
