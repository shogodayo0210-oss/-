# fp

**A first-principles decision protocol, with its own error bars.**

This repository is an attempt to reproduce Elon Musk's decision-making — as a
method you can run, not a personality you can imitate.

It contains two things: [an analysis](docs/analysis.md) of his documented
working method, with sources and with the places it demonstrably fails, and
`fp`, a tool that runs that method against a decision of your own.

It analyses. **It does not speak in anyone's voice.**

## Why not a voice

The obvious version of this is a chatbot answering in the first person as him.
That version is worse, and the first reason matters more than the second.

**It doesn't work.** Cadence is the easy part and the useless part. A
convincing imitation of how someone talks tells you nothing about how they
decide. The thing worth having is the decision procedure — and that part is
documented, checkable, and reusable by anyone.

**And fabricated first-person statements from a living, market-moving person
are a problem regardless of intent.** So this is built the other way round:
every rule traces to a source, and the output is an assessment of *your*
decision rather than a performance of someone else's personality.

## Quick start

Python 3.9+. No dependencies.

```console
$ pip install -e .
$ fp examples/weekly-report.json
```

Or straight out of the tree:

```console
$ PYTHONPATH=src python3 -m firstprinciples examples/weekly-report.json
```

## Not just business

The screen was derived from a venture history, but the questions survive
translation. "Price" becomes whatever a thing currently costs — money, hours,
attention. "Incumbent" becomes whatever occupies the ground now.

The example that makes the point best is a weekly status report:

```
Index 12.0× — 6.00 hours spent on 0.50 hours of irreducible content.
You are paying for process, not for substance.
  →  At 3× this would be 1.50 hours each, 216 hours across 48.
```

Six hours a week producing thirty minutes of information nobody already had.
Same machinery as a $1,500 door latch, different unit.

## Two halves

### Where to point effort

Six screens, one of which is a gate.

| Screen | Question |
|---|---|
| `cost_detached` | Is what this costs set by habit rather than by a real limit? |
| `absorbable` | Is the expensive part something you could take on directly? |
| `soft_barrier` | Is the barrier capital, regulation or convention rather than a technical wall? |
| `existing_need` | Does the need already exist, so you never have to manufacture it? |
| `pulls_help` | Would the honest framing pull in people you could not otherwise get? |
| `reachable_proof` | Can you reach a convincing proof point with what you already control? |

`cost_detached` is a **gate**, not just a heavy weight. If nothing here costs
more than it must, the verdict is `OFF_PATTERN` however well everything else
scores — because every other rule in the tool is machinery for closing a gap,
and there is no gap. Conviction is not a substitute for one.

### How you are running it

- A requirement with no **named person** behind it is a blocker. A department
  cannot be asked why.
- A requirement from a **senior** person that nobody has questioned is raised
  in severity, **not lowered**. This is the inversion worth having:
  requirements from smart people survive longest precisely because nobody
  challenges them.
- A step **automated or optimised before being considered for deletion** is
  flagged. Automating a step that should not exist makes the waste permanent
  and fast.
- Deleting things and **never putting any back** means you stopped early. The
  floor is 10%.

## The error bars

The part most treatments of this method leave out. Independent trackers put
its timeline overshoot at roughly **2× to 5×**.

A flat multiplier would be easy and slightly wrong. The documented mechanism is
specific: the technical problem usually does get solved, and the slip is
between a working solution and deployment at scale, at cost, under a regulator.
So the correction scales with the kind of work:

| Phase | Correction |
|---|---|
| `prototype` | 1.2–2.0× |
| `production` | 2.0–3.0× |
| `regulated` | 3.0–5.0× |

The hardest declared phase sets it. Work does not finish when its easiest part
finishes.

Every report also carries one standing line: this method's throughput came
alongside high attrition and organisational churn, and that cost is not counted
anywhere in the numbers above.

**A model that reproduces only the wins is not a model.** It is fan fiction
with footnotes.

## It was backtested, and it lost

The engine was built from what he *says* he does. Then it was run against what
he actually did, at seven decision points where getting it wrong would have
ended everything.

```console
$ python3 backtests/run.py --verbose
```

It got the 2017 over-automation right — including a schedule correction of
12–18 months against a reality he called "6 to 9 months worse" than planned.
It caught the `$420` tweet through its most counterintuitive rule.

It also got three things wrong, and each failure became a rule:

| It failed at | Now |
|---|---|
| Tesla's GA4 tent — called a three-week success a month late | `stopgap` work is barely corrected |
| Tesla 2008, three days from bankruptcy — audited deletion ratios | `runway` changes what gets reported at all |
| The `$420` tweet — rated a tweet like a decision you could undo | `irreversible-unquestioned` |
| The fourth Falcon 1 — said "decide it yourself", which was useless | `cheaper-to-try` |

Three of the additions are about **pressure**, and none of them appear in how
this method is usually described — including by him. But all of them appear in
what he did.

The full record, including what the backtest is *not* evidence of, is in
[docs/backtest.md](docs/backtest.md).

## Does the screen mean anything?

A screen built only from things that worked will approve of everything. So the
repository ships a counter-example.

```console
$ fp examples/tesla-2004.json   # STRONG      93%
$ fp examples/x-2022.json       # OFF_PATTERN 30%
```

The rejection comes from the **gate**, not from a low total: there was no
thesis that running a social network costs more than it must, so there was no
gap to close. A test asserts exactly that, so the claim cannot quietly stop
being true.

**This is a consistency check, not independent evidence.** Those scores are one
reading of the public record, assigned by the author, after the outcomes were
known. It shows the screen *can* reject something. It does not show the screen
is right.

## Use

```console
$ fp decision.json                # report
$ fp decision.json --explain      # why each screen is there
$ fp decision.json --json         # machine-readable
$ fp decision.json --fail-on high # exit non-zero at HIGH and above
$ cat decision.json | fp          # reads stdin
```

Input is plain JSON so the file a team argues over stays diffable. Everything
in `examples/` is a working template:

| File | |
|---|---|
| `weekly-report.json` | an internal process, counted in hours |
| `dev-tool.json` | an open-source project, no money involved |
| `tesla-2004.json` | the control — the pattern the screen came from |
| `x-2022.json` | the counter-example the gate rejects |

Exit codes: `0` clean, `1` findings at or above `--fail-on` (default
`blocker`), `2` bad input.

## What it does not do

- **It does not decide.** It produces findings and an adjusted estimate. Every
  score is a judgement you make, and the tool faithfully reports whatever you
  tell it.
- **It cannot check your evidence.** Writing `"cost_detached": 2` with no basis
  produces a confident, worthless report. The `evidence` field exists so a
  reader can catch you. Nothing catches you automatically.
- **It is not a portrait.** See [docs/analysis.md](docs/analysis.md) for what
  he actually knows, where every rule comes from, and where the method fails.

## Development

```console
$ pip install -e '.[dev]'
$ pytest
```

## License

MIT
