# Findings, in plain words

This file is the non-technical summary of every investigation in this
repository: what we tested, what came out, and why it matters. Each claim
has a replayable evidence bundle under [proof/](proof/), and the README
carries the full detail.

## What we tested

Crux answers one question: when software fails randomly, what exactly is
causing it? To prove it works, we pointed it at five different kinds of
random failure and made it find the cause without being told the answer.
In every case the true cause was hidden inside a lineup of equally
believable suspects.

1. Home Assistant, the most starred Python application on GitHub: a test
   failing on some runs and passing on others with no visible pattern.
2. ParlAI, Meta AI's dialogue framework: a test failing about half its runs.
3. uvicorn, a web server used across the Python world: tests that pass in
   their natural order and break when the order is shuffled.
4. A real language model reading invoices in a Solari cloud browser,
   getting the numbers wrong six runs out of ten.
5. A controlled simulated agent we could run 800 times, to measure how
   often the tool itself is right and wrong.

## What we found

Each failure had a different hidden cause. Crux convicted all of them and
released the innocent suspects every time.

- Home Assistant failed because Python shuffles its internal data ordering
  on every run and the code accidentally depended on that order. Convicted
  at confirmation p = 0.0047 in 144 trials, then again with every trial in
  a forked Solari sandbox with the identical verdict.
- ParlAI failed because the code drew from Python's global random module
  without ever seeding it. Convicted at p = 0.00011.
- uvicorn failed because one test mutates shared logging settings in place
  and a later test asserts on them, so only some orders break. Convicted
  at p = 0.000000018, the strongest verdict in this repository.
- The browser agent failed not because the model was weak or too random,
  but because its context cut off the part of the page holding the answer.
  Convicted at p = 0.0000226; temperature, layout, prompt wording, and
  distractor theories were all measured and released.
- The 800-run study showed the procedure never once blamed an innocent
  factor on pure noise, while the usual run-it-five-times-and-eyeball
  approach accused an innocent factor 68 percent of the time.

## How it helped

Days of engineer guesswork become minutes of automated experiment, and the
answer arrives with proof: pass rates with and without the cause, the odds
the conclusion is a fluke, and a replay command anyone can run. Once a
cause is fixed, `crux verify` can re-run the case forever and catch the
bug if anyone reintroduces it.

## How it is different

Existing tools detect flaky failures; Crux explains them, which is the
part that actually fixes anything. It treats debugging like a controlled
trial: freeze the world, clone it, change one suspect per group, count,
and confirm on fresh runs before accusing anyone, so it prefers an honest
"not decided yet" over a confident wrong answer. And it runs the same
investigation on local processes or on Solari's snapshot-and-fork
infrastructure, because cloning the world is exactly what that platform
is built to do.

One line: your software fails randomly, everyone has a theory, and Crux
runs the experiment that tells you whose theory survives.
