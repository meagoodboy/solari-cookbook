# Crux

Crux finds the minimal change that flips a stochastic agent's outcome, and backs
the answer with statistics you can replay. For the plain-words version of
everything tested here and what came of it, read [FINDINGS.md](FINDINGS.md).

## The problem it is built around

An invoice-intake agent reads a rendered invoice page and types two things into a
form: the PO number and the total. It fails about a third of the time. Two engineers
have spent a day in the traces. One is sure model temperature is causing typos,
and has a trace with a mangled PO to prove it. The other blames the cookie
banner, because a different failing trace shows a click that landed on the banner
instead of the field. Both have evidence. Both are wrong.

The real defect: when an invoice is long enough to render in two columns, the
extractor sums only the first column, so the entered total is short on every
large two-column invoice. No single trace says this. Each failure looks like its
own small accident, and the noise sources (an occasional typo, a rare intercepted
click, a rarer timeout) hand every reader a plausible wrong story.

Crux answers the question by experiment instead of by reading. It freezes the
world once, then reruns the agent many times with individual suspects turned
off. If failures track a factor, turning that factor off makes the agent pass,
and the effect has to survive a corrected significance test plus an independent
confirmation batch before Crux will say so. The output is a verdict: the
smallest set of factors whose removal flips the outcome, with counts, confidence
intervals, and a p-value you can recompute yourself.

## Your flaky test, one command

```
crux flaky -- python -m pytest tests/test_x.py::test_y
```

No scenario file, no configuration. The built-in suspect lineup is the same
five that convicted the Home Assistant bug below: hash randomization,
timezone, locale, bytecode caching, and the allocator. The command first
probes for a fixed hash seed your test passes with, then runs the test a few
times as-is; if it never fails it says so and stops rather than billing you
an investigation. Otherwise it runs the full sequential procedure and writes
a bundle you can serve and replay. Add `--parallel 4` to run that many trial
processes at once; seeds fully determine each trial, so parallelism changes
wall-clock time and nothing else.

Run against the real Home Assistant checkout described below, this exact
command reproduced the flake in the probe (2 of 8 runs failed), convicted
hash randomization, and reported the same confirmation p of 0.0047 as the
hand-written scenario, because it is the same investigation. With
`--parallel 4` the whole thing, probes plus 144 trials, took 77 seconds.

## What it catches, with receipts

Nine investigations across five failure families, seven of them in real
well-known software, including an open PyTorch bug and three previously
unreported findings at the current tips of fastapi and rich. Every verdict
beat a lineup that included decoy suspects, the p value is always the one
from the fresh confirmation batch, and each bundle replays.

| Failure family | Where | Verdict | Confirmation p | Receipts |
| --- | --- | --- | --- | --- |
| Test-order dependence, new find | fastapi/fastapi HEAD, ~102k stars, previously unreported | reversed_test_order | 3.1e-14 | [proof/realworld-fastapi/](proof/realworld-fastapi/) |
| Hash randomization | pytorch/pytorch, ~103k stars, OPEN issue 196512, unfixed at HEAD | hash_randomization | 0.000013 | [proof/realworld-pytorch/](proof/realworld-pytorch/) |
| Hash randomization | home-assistant/core, ~90k stars, real July 2026 bug | hash_randomization | 0.0047 | [proof/realworld/](proof/realworld/) |
| Env-conditional, new find | Textualize/rich HEAD, ~57k stars, previously unreported | columns_exported | 3.1e-14 | [proof/realworld-rich-columns/](proof/realworld-rich-columns/) |
| Test-order dependence, new find | Textualize/rich HEAD, previously unreported | test_order_shuffle | 0.000013 | [proof/realworld-rich-order/](proof/realworld-rich-order/) |
| Test-order dependence | encode/uvicorn 0.16.0, ~11k stars | test_order_shuffle | 0.000000018 | [proof/realworld-uvicorn/](proof/realworld-uvicorn/) |
| Unseeded global RNG | facebookresearch/ParlAI, ~10.6k stars, FLEX dataset row | unseeded_global_rng | 0.00011 | [proof/realworld-parlai/](proof/realworld-parlai/) |
| Agent context truncation | a real sampled LLM on a Solari cloud browser | context_trim | 0.0000226 | [proof/agent/](proof/agent/) |
| Environment and layout factors | the calibrated offline demo and the Solari sandbox run | two_column_layout | 0.0047 and 0.0012 | [proof/offline/](proof/offline/), [proof/live/](proof/live/) |

The fastapi row is a discovery made while building this tool: at v0.141.1,
tests/test_dependency_contextmanager.py keeps a module-level state dict that
yield-dependencies mutate, test_async_state asserts the pristine
precondition at line 217, and any order that runs a sibling first breaks it;
three more test files carry the same pattern, so shuffled runs of their
suite fail with 7 to 12 errors depending on the seed. No issue or pull
request mentions any of it. The same sweep that found this reported clean
nulls on flask, click, jinja, numpy and pandas across dozens of documented
runs each, which is worth as much as the find: the method does not
manufacture findings where there are none.

Three more rows deserve a word. The PyTorch case is a live bug: issue 196512,
filed two days before this investigation ran, still open, reproduced through
the same public API the issue names, where node names collected into a set
make the simulated backward schedule follow string-hash order. The two rich
rows were not reported anywhere before this work found them: exported
COLUMNS bypasses the terminal-size mock in their console tests, and one
table test permanently rewrites the shared rich.box.ASCII singleton so later
box tests fail under shuffled order. The COLUMNS case also settles a fair
methodological objection: its guilty factor is a constant while a decoy
varies per trial, and the constant was convicted at p = 3.1e-14 while the
varying decoy walked.

The two newest cases each convicted on the first run with the default
configuration. In ParlAI, a test fails about half its runs because the code
samples tasks from Python's unseeded global random module; reseeding it per
trial was the guilty factor and the four decoys walked. In uvicorn 0.16.0,
shuffling test order breaks a test that asserts on the shared
LOGGING_CONFIG dict, which earlier tests mutate in place; the shuffle
factor was convicted at the smallest p in this repository while hash seed,
timezone, locale, and allocator theories were all released. Both are one
script each under [examples/](examples/).

On replaying these bundles: simulated bundles (the demo) replay anywhere
with `crux verify`. Command bundles carry a `world.json` describing the
exact command, checkout path, and factor lineup, and `crux verify` rebuilds
that world and replays the investigation when the checkout exists at the
recorded path; without it, verify says exactly what is missing and exits
nonzero rather than pretending. The agent and Solari bundles are receipts
of paid runs; their replay is the example script that produced them.

## Quickstart

Python 3.11 or newer. The runtime uses only the standard library; pytest is the
one dev extra.

With uv, from the repo root:

```
uv venv
uv pip install -e .
uv run python -m crux demo
uv run python -m crux serve
```

With plain pip:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m crux demo
python -m crux serve
```

Installing also gives you a `crux` console script, so `crux demo` works too.
Add `".[dev]"` to the install and run `pytest` if you want the test suite.

## The demo, step by step

```
python -m crux demo --seed 7 --out runs/
```

This runs a full investigation against the local simulated invoice world. Five
factors are on the suspect list: `two_column_layout`, `cookie_banner`,
`model_temperature`, `network_latency`, and `context_trim`. The engine allocates
trials round by round to a baseline (everything on) and one branch per factor
(that factor off), tests each branch against baseline after every round, drops
branches that are going nowhere, and sends the first significant branch to a
fresh confirmation batch. It prints the verdict summary and writes a bundle:

- `investigation.json`, the complete state, replayable
- `report.md`, the verdict, a branch table with rates, Wilson intervals and
  p-values, and the round log
- `branches.csv`, the branch table as plain data

```
python -m crux serve
```

This picks the newest bundle under `runs/` (or take `--directory` and `--port`)
and serves a small viewer at http://127.0.0.1:8123: verdict banner, branch bars
with confidence whiskers, futility-dropped branches greyed out, the round
timeline, and a collapsible trial table. No external assets.

```
python -m crux verify runs/<bundle-dir>
```

This re-runs the whole investigation from the saved config and seed and exits 0
only if it reaches the same cause. A verdict here is a computation, not an
anecdote, so you can check it.

## What the verdict means

The verdict names a cause: the factor, or pair of factors, whose removal moved
the agent from passing about two thirds of the time to passing nearly always. It shows
the baseline pass rate and the cause branch's pass rate side by side, with the
counts behind them.

The confirmation p is the number I would look at first. A branch that wins a
multi-way race tends to look better than it really is, so Crux treats
significance during the search as a nomination only. It then runs a fresh batch
of trials with new seeds, on that branch and on baseline, and applies a single
one-sided Fisher exact test. The confirmation p is the chance of seeing a gap at
least that large in the fresh batch if the factor actually made no difference.
Below alpha (0.05 by default) the verdict stands. A branch gets exactly one
confirmation attempt; failing it removes the branch from contention.

If nothing survives, the cause is null and the summary says which branch came
closest and that no suspect met the bar. I would rather ship a documented
non-answer than a confident guess.

## Running it live on Solari sandboxes

The live path runs the same engine, but each trial executes in a real sandbox
cloned from a snapshot, using the `solari-sandbox` SDK.

```
pip install -e ".[live]"
export SOLARI_API_KEY=slr_live_...
python -m crux live --yes
```

A cost warning first: every trial creates a sandbox clone, and clones bill at
normal usage rates. Before doing anything the command prints the exact number of
clones it will create and reminds you that charges apply, and it refuses to run
without `--yes`. There is no interactive prompt. The default live config is kept
small on purpose (two factors, up to two rounds, six trials per branch) but it
is sized so a real effect can reach significance; its job is to prove the
snapshot-and-clone mechanics on real infrastructure with a decision at the end,
not to be a full study. Without `SOLARI_API_KEY` set it exits immediately with one line
saying so. `.env.example` lists that variable, and it is the only one the code
reads. The bundle lands in `proof/live/` and serves like any other.

## Measured behavior

The numbers come from a 200 seed per family run of the operating-characteristics
study (`python -m crux bench`, master seed 7). Each seeded instance pits the
full crux procedure against a naive five-trials-per-arm gap read and a single
240-trial fixed-budget test. [bench/RESULTS.md](bench/RESULTS.md) holds the
full table and the scoring rules; this is the crux row for each scenario
family.

| Family | Correct % | Wrong % | None % | Mean trials |
| --- | --- | --- | --- | --- |
| layout-cause | 88 | 0.5 | 11.5 | 181.9 |
| no-cause | 0 | 0 | 100 | 216.9 |
| conjunction-cause | 19 | 0 | 81 | 218.7 |
| weak-cause | 0 | 0 | 100 | 221.6 |

On the planted layout bug crux names the true cause 88% of the time with one
wrong conviction in 200 runs, and on the no-cause world it convicts nobody at
all, where the naive gap read convicts an innocent factor 68% of the time. The
price of that caution shows on the hard families: the conjunction is caught in
19% of runs and the weakened signal in none, and in both cases crux answers
none rather than guessing.

## A real investigation: Home Assistant

The simulated numbers above are controlled; this one is not. Home Assistant
(home-assistant/core, about 90,000 stars) briefly carried a real bug in July
2026: at commit `de252d4b0db0570c69159fd576d6ae750004476f` the relative setup
order of two stage-0 components fell back to Python set iteration order, so
`tests/test_bootstrap.py::test_setup_frontend_before_recorder` failed on
roughly a third of hash seeds. The bug arrived in PR 176137 and was fixed the
same day by PR 176508. Pinning that commit makes the reproduction permanent.

`examples/home_assistant_hashseed.py` points Crux at a checkout through the
CommandWorld backend: every trial is a fresh pytest process, and each suspect
is an environment change. Five suspects went in: hash randomization (varied
per trial through PYTHONHASHSEED, pinned when neutralized), timezone, locale,
bytecode caching, and the allocator. Crux was not told which one mattered.

The verdict, from the bundle in [proof/realworld/](proof/realworld/): cause
`hash_randomization`, confirmation p = 0.0047, baseline passing 62% against
100% with the cause neutralized, decided in 144 trials and 182 seconds. The
four red herrings were released by futility. The naive five-per-arm gap read
on the same world also happened to point at hash randomization this run, but
it read the innocent locale at 80% against a 60% baseline along the way,
which is exactly the kind of gap that becomes a wrong conviction on another
day; the bench table above puts a number on how often.

To rerun it, clone home-assistant/core at the commit above, install its test
requirements into a venv, and run the example with `--repo-dir` and
`--python` pointing at them. The investigation needs nothing from the network.
None of this hangs on a lucky seed: rerun with `--seed 11` and the same cause
comes back, confirmation 24 of 24 against 18 of 24 at baseline, p = 0.011.

### The same investigation on Solari clones

`examples/home_assistant_hashseed_solari.py` reruns it with nothing on your
machine at all. Setup builds the whole world inside one Solari sandbox
(clones the pinned commit, installs Python 3.14 and the test requirements
with uv, sanity-runs the test once), which took 75 seconds in our run, then
snapshots it. Every trial is a fresh clone forked from that snapshot running
the real pytest node, about 20 seconds each. The full investigation used 144
clones over 53 minutes, sequential under the starter concurrency limit, and
landed the identical verdict at the identical confirmation p of 0.0047,
because trial seeds fully determine the outcome here and the engine replays
the same seeds on any backend. The bundle is in
[proof/realworld-solari/](proof/realworld-solari/). That backend,
`SolariCommandWorld`, generalizes: give it setup stages and a command, and
any repository's flaky test can be investigated on forked VMs. The command
prints its worst-case clone count and refuses to run without `--yes`.

On concurrency, the measured truth rather than the brochure version: the
engine batches each round's trials and both backends accept a `--parallel`
flag, with tests proving that execution order cannot change an
investigation (seeds decide everything). Locally that is a real speedup;
four processes took the whole Home Assistant investigation to 77 seconds.
On our starter Solari account it is not: the account boots three plain
sandboxes at once, but clones forked from a warm snapshot are a scarcer
resource, and a second concurrent clone was refused with "Too many
concurrent sessions" through every backoff we tried. So the committed
Solari bundle is a sequential run, and the parallel path is ready for an
account tier that allows more. Chasing this taught us a sharper lesson:
a create call that errors client-side can still provision a VM, and that
orphan then blocks its own retries. The backend now tags every sandbox it
creates and reaps untracked ones carrying its tag before retrying, and
`crux sandboxes` lists and kills leftovers by hand when a run dies badly.

## A real agent on a real browser

The case everything else builds toward, in
`examples/agent_invoice_browser.py`: the failing party is an actual language
model, and the page it misreads is rendered by a real Solari cloud browser.
A small local model (qwen2.5 1.5b through ollama, sampled at temperature 1.0
with a per-trial seed) reads an invoice page as the browser's own text
linearization and must return the PO number and the amount due. It fails
about six runs in ten. Five suspects went in: sampling temperature, a
two-column layout, a 500 character context cut, a terse prompt, and footer
boilerplate full of other dollar amounts.

The verdict, from [proof/agent/](proof/agent/): the cause is the context
cut. Baseline passed 14 of 36; with the cut removed the agent passed 36 of
36, and the fresh confirmation batch came in 20 of 20 against 8 of 20, with
p = 0.0000226. The other four suspects were released by futility. In plain
words: the agent was not too small for the task and the layout was not the
problem; its context cut off the field it was asked to read, and every
other theory an engineer might argue for is now measurably wrong.

Two things make this the honest version of an agent demo. The failure is
emergent, not scripted: nothing in the fixture decides pass or fail, only
the model's own reading of a rendered page. And an earlier run at a looser
cut ended undecided at p = 0.0119 rather than convicting, which is the
selection guard doing its job; the shipped verdict comes from a properly
powered rerun, and both behaviors are what you want from a measuring
instrument. Because ollama honors sampling seeds, even the stochastic runs
replay exactly on the same model build. The frozen protocol also holds at a
fresh seed: rerun with `--seed 11` and the context cut is convicted again,
confirmation 20 of 20 against 6 of 20, p = 0.0000017.

Running it needs SOLARI_API_KEY, ollama with the model pulled, and the
`[browser]` extra. One browser session is reused across all trials; the
whole investigation cost about five minutes of session time.

## Limits, stated plainly

- The demo agent is simulated. It is seeded Python that behaves like an intake
  agent, not an LLM driving a browser. The stochasticity is real and
  reproducible; the agent is not.
- The extraction bug is real code that the engine cannot see. The simulated
  agent genuinely sums only the first column of a two-column page. Crux never
  reads that code; it only toggles factors and scores pass or fail. So it
  convicts a factor, not a line. Finding the line is still your job, Crux tells
  you which door it is behind.
- The `crux live` path is a small run on real sandboxes: each clone executes
  the same simulated fixture, so the infrastructure is real and the agent
  still is not. Its config is sized to be decidable, and the committed
  [proof/live/](proof/live/) bundle did confirm the cause at p = 0.0012. The
  Home Assistant runs below it in scale of realism: real repository, real
  test, and in the Solari variant, real forked VMs.
- Crux can only convict suspects you name. The cause must be one of the supplied
  factors or a pair of them; a defect uncorrelated with every factor comes back
  as cause null.
- Trials are assumed independent. The seed scheme guarantees that in the local
  world; a live backend honours it as far as its world allows.

## Layout

```
crux/
  models.py     shared dataclasses (Factor, TrialResult, Verdict, ...)
  world.py      the World protocol and the Oracle type
  stats.py      Fisher exact, Holm, Wilson, seed derivation
  search.py     the sequential investigation loop
  fixture.py    the simulated invoice world and its planted bug
  backends/     LocalWorld, SolariWorld, and the test worlds
  report.py     bundle writer (json, markdown, csv)
  serve.py      local viewer over a bundle
  cli.py        demo, serve, verify, live
```

Why each statistical piece exists, what can still go wrong, and how Crux relates
to Worldline is in [DESIGN.md](DESIGN.md).
