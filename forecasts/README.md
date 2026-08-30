# Forward run

Everything in [`backtests/`](../backtests) is retrospective. The outcome was
public before the case was written, which caps what any of it can prove: the
engine has only ever been graded on decisions whose answers were already in.

This is the other half. Five public, dated, **unresolved** claims about the
future, encoded as decisions and run through the engine. The predictions are
committed so someone else can mark them right or wrong later.

```console
$ python3 forecasts/run.py
```

## What is being predicted

| Claim | Claimed | Engine | Resolves |
|---|---|---|---|
| Uncrewed Starship departs for Mars | Musk, 2025-05 → late 2026 | **2029-01** | 2027-01 |
| Optimus at ~1M units/year | Musk, 2026-01 → 2027 | **2029-01 to 2030-07** | 2028-01 |
| Powerful AI systems emerge | Anthropic, 2025-03 → late 2026/early 2027 | 2027-05 to 2028-11 | 2027-06 |
| SPARC reaches Q>1 | CFS, 2026-06 → 2027 | **2027-08 to 2028-06** | 2028-06 |
| Helion delivers 50MW to Microsoft | Helion, 2023-05 → 2028 | **2032-11 to 2037-08** | 2029-01 |

## What the forward run already found

Running it forward broke something on the first attempt, which is the whole
argument for doing it.

Aimed at the late-2026 Mars window, the engine returned **March 2027 to May
2028** — a band containing no launch window at all. Mars transfer windows open
roughly every 26 months. That is not a pessimistic prediction; it is an
impossible one.

Schedules are not always continuous. Launch windows, growing seasons, annual
certification cycles, academic years: miss one and the next chance is a whole
period away, not a few weeks. `window_months` now moves a corrected band onto
the next real opportunity, and the Mars claim reads **2029-01** — precisely the
window after the one aimed at.

It also makes a stark thing explicit: **near-misses do not exist on a quantised
schedule.** Every corrected band except a stopgap's lower bound starts above
the target, so the original window is always missed — and missing it by a week
costs exactly what missing it by a year costs.

## What this is not

- **It is not a forecast of whether these things happen.** The engine corrects
  *schedules*. It has nothing to say about whether fusion works or what AGI
  means, and the AGI entry is included specifically to show where the tool
  ends: its band there is close to meaningless and says so in the output.
- **The encodings are the author's.** Phase classification, what counts as a
  requirement, which steps exist — all judgements, all arguable. A different
  encoding gives different numbers.
- **`no-deletion` fires on most of these as an artefact.** The step lists are
  thin because these are public claims rather than internal plans, not because
  the programmes delete nothing. Left visible rather than suppressed, because
  hiding it would be worse.
- **Five claims is not a sample.** Whatever happens, the result will be
  suggestive at best.

## Grading

When a resolution date passes, set `"outcome"` in the claim file to `HIT`,
`MISS` or `PARTIAL`, with a note and a source. The point is that the prediction
was written down first, in public, by someone who did not know the answer.
