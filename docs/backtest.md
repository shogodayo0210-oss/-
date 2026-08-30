# Backtest

The engine was built from what Musk *says* he does. This is what happened when
it was run against what he actually did, at moments when getting it wrong would
have ended everything.

Seven cases. Four rounds. Three rules exist because the engine failed here
first.

```console
$ python3 backtests/run.py --verbose
```

Each case in `backtests/cases/` reconstructs a decision point using only what
was knowable *then*, and records what was actually done, how it turned out, and
sources. The harness runs the engine against the reconstruction and checks
whether it flagged what mattered.

## What this is not

The reconstructions were written by the same person who wrote the rules, after
the outcomes were public. A case can be phrased until it passes. So the hit
rate is not evidence, and is not presented as any.

What the harness is actually good for is the reverse: finding cases the engine
**cannot** get right however they are phrased. Those became the findings.
Everything below that says "gap" is a place the engine was wrong in a way no
amount of wording fixed.

Two safeguards keep the rest honest:

- **A control case.** `control-well-run` is a healthy decision the engine must
  stay silent on. It lists every rule in `must_not_flag`, so any new rule that
  fires on a well-run decision breaks the suite instead of quietly inflating
  the score elsewhere.
- **An overfitting check.** `twitter-2022` was added *after* the reversibility
  rule was written, from a different decade and a different failure mode, to
  see whether the rule generalised or had just memorised its origin case.

## Round 1 — the engine as originally built

| Case | Result |
|---|---|
| Tesla 2017, automate general assembly | **hit** |
| Tesla 2018, the GA4 tent | **miss** — schedule |
| Tesla 2008, three days from bankruptcy | **noise** |
| 2018, "funding secured" | **partial hit** |

**The hit.** The 2017 decision to automate Model 3 general assembly before the
manual process was proven fired `automated-too-early`, plus
`unquestioned-authority` on "the line must be the most automated in the world."
This is the rule's textbook violation, and it is one the person who made it
publicly agrees was a mistake. The schedule correction was right too: a
six-month plan corrected to 12–18 months, against a reality he described as
"6 to 9 months worse" than planned.

**The schedule miss.** The GA4 tent was planned in three weeks and delivered in
three weeks. The engine applied its flat 2–3× production correction and
returned 1.5–2.25 months — calling a success late by a month. The correction
was being applied to the wrong thing.

**The noise.** December 2008, three days of cash, and the engine's only finding
was that the reinstatement ratio was below 10%. Not merely unhelpful:
misdirection. It audited process hygiene at a company about to stop existing.

**The partial hit.** The `$420` tweet fired `unquestioned-authority` — the
engine's most counterintuitive rule catching the most famous unforced error,
because the requirement to announce came from the most senior person present
and nobody challenged it. But it rated a tweet identically to a decision that
could be walked back on Monday, and being unable to walk it back is the entire
reason that one cost $40M.

## Round 2 — three additions

**Runway, and a mode that changes with it.** Below three months, process
hygiene findings are dropped and reported as suppressed, a `no-runway` blocker
leads the report, and cost-ratio findings are softened rather than pressed —
paying well over the odds for speed is correct when you are dying. What
survives untouched is everything that can still kill you on its own: an unowned
requirement, an unchallenged senior one, anything automated before it was
questioned.

**Reversibility, as a multiplier rather than a separate concern.** An
irreversible step resting on an unchallenged senior requirement is a blocker.
No way back, no second opinion — that pairing is what turns an ordinary
misjudgement into an expensive one.

**Stopgaps are barely corrected.** This one matters because of *why*. The
documented 2–5× overshoot lives in scale, cost and regulation. A tent you
intend to tear down meets none of the three, so the correction does not apply
to it. That is derived from the mechanism, not fitted to the outcome — and it
is what turns 1.5–2.25 months back into 0.75–0.98.

**Ruin risk, surfaced and deliberately unresolved.** The 2008 decision — bet
the last personal money, accept total loss if wrong — is one the engine now
names and explicitly refuses to answer. The method it implements has a
documented history of taking such bets and winning, which is not evidence they
are correct: the people who took them and lost are not around to be studied.

## Round 3 — testing whether any of it generalises

Adding cases the engine had not been built around.

`twitter-2022` **passed**. The reversibility rule, written from a 2018 tweet,
fired correctly on a 2022 acquisition — a different decade, a different failure
mode, the same structure. It is a rule, not a memorised answer.

`control-well-run` **passed**. The engine stayed completely silent on a healthy
decision, which is what makes the other results mean anything at all.

`spacex-2008-fourth-launch` **failed**, and produced the last finding. Three
Falcon 1 failures, under $200K in the bank, and the engine said: no runway,
ruin risk, decide it yourself. All true. All useless. The reasoning that
actually settled it was narrower and reusable — **another vehicle cost less
than the analysis that would have replaced it**, so the careful option was also
the expensive one.

## Round 4 — the last rule

`cheaper-to-try`: when one more attempt costs less than the analysis that would
replace it, deliberating is the expensive path. This is the idiot index pointed
at learning, which is why it belongs here rather than being a separate idea.

It carries a deliberate caveat. Under ruin risk the message changes to *cheaper
only holds if you survive it* — the rule argues for trying **sooner**, never
for trying regardless.

All seven cases now behave as recorded, and the whole backtest runs inside the
unit suite so a later change cannot quietly undo one of these.

## Rounds 5–7 — the last three years

The first four rounds used 2008–2022. Three cases from 2024–2026 test whether
the rules describe the person as he is now.

`colossus-2024` **passed unmodified**, and it is the most useful pass in the
suite. The stopgap correction and the unowned-requirement rule were both
written from a tent in a Fremont car park in 2018. Six years later and three
orders of magnitude larger — a dead appliance factory, temporary gas turbines
because the grid offered 8MW against a need near 130MW, 100,000 GPUs in 122
days — they score it correctly with nothing changed. Rules, not curve-fitting.

`doge-2025` **failed**, and produced the only rule here that is not about
thinking better. Every earlier mistake put the cost where the decision was
made. This one did not: decided personally and politically, paid for by
Tesla's shareholders and customers, who had no vote. `cost-lands-elsewhere`
fires when the decider and the payer differ, and it leads the report, because
the usual corrective — the people paying say no — is unavailable.

`robotaxi-2025` **failed on schedule**, and the fix is the weakest thing in
this repository. The engine's largest band, 3–5× for regulated work, gave
18–30 months against a programme that promised a million vehicles for 2020 and
was running twenty in 2026. A `safety_critical` phase at 5–10× now covers it:
where a regulator needs statistical evidence, the schedule is set by how fast
reality can be sampled.

**That last one is fitted and is labelled as such.** The band was added and the
case assigned to it by the same hand, in the same sitting. Unlike
`irreversible-unquestioned`, it has not yet fired correctly on a case it was
not built for. Treat it as a hypothesis.

One more thing the period forced: the screen now accepts **-1**. `pulls_help`
was always the mission working as a recruiting instrument. In 2025 it ran
backwards — European sales down 49% into a market up 34% — and a scale that
bottoms out at zero cannot express a liability.

## Round 8 — the fitted band, tested properly

`safety_critical` was the one change labelled a hypothesis: the band was added
and the case assigned to it in the same sitting. Round 8 tested it under
pre-registration — **both cases written and their expected ranges fixed from
the historical record before the engine was run once.**

Two cases, chosen to attack it from different sides.

**Waymo passed, and it is the strongest single result here.** The band claims
something about a *kind of work*, not about a person — so it has to hold for an
organisation with the opposite temperament, no reality-distortion field, and a
reputation built on caution. Waymo said a public robotaxi service in Phoenix
during 2018; genuine driverless service at multi-city scale arrived around 2024.
Twelve months planned, about 84 actual. The band's 60–120 contains it. If this
band were merely a measure of one man's optimism, it should have missed badly
here. It did not.

**Neuralink failed, and falsified the band as written.** Stated in 2019, FDA
clearance wanted by end-2020, human trials in 2020 — about 18 months. First
human implant January 2024, about 55 months. That is roughly **3×**. Classified
as safety-critical, the engine returned **90–180 months**: seven to fifteen
years for something that took four and a half.

### What the failure was actually telling us

The two cases differ in a way that is not a fudge. Waymo had to prove a
statistical claim **across a fleet, accumulated over time** — miles driven,
incidents not had. Neuralink had to get **one device into one volunteer**, which
is a regulator reviewing a submission: hard, slow, and a different shape.

So the band was narrowed to the first kind. Neuralink's first implant is
regulated work, and at 3–5× the corrected 54–90 months contains the 55 it took.

**This narrowing is post-hoc.** It was drawn after seeing the result, by the
same hand that drew the band. Its only independent support is Waymo. The wide
version is dead; the narrow version is a better hypothesis and is still a
hypothesis.

And one thing this round could not settle: `robotaxi-2025` is unfinished, so it
cannot discriminate between the two bands — both reach past where things stand.
All the discrimination came from the two cases added here.

### The harness had a bug, and the band's first pass was fake

Checking `months_within` only looked at where the corrected *upper bound* fell.
Robotaxi originally "passed" by grazing the boundary of its expected range —
6 months × 5 = exactly 30, against a range starting at 30. The engine had not
got it right; the arithmetic had landed on the edge.

The honest test of a calibration is whether **reality falls inside the band it
produced**, and the harness now checks that. It is a better test and it is
harder to pass by accident.

## Round 9 — the last two untested rules

`cheaper-to-try` and `cost-lands-elsewhere` each described exactly one event.
Round 9 put them in front of cases with no connection to Musk at all, again
under pre-registration: four predictions written down before the engine ran.

**All four predictions were correct, including the one that said a rule would
fail.**

**Boeing 737 MAX — `cost-lands-elsewhere` fired.** A different company, a
different industry, a decade before DOGE, and the same structure: the MAX was
sold on not needing simulator training, MCAS went undocumented, and Boeing
contracted a $1M-per-aircraft rebate with Southwest should training turn out to
be required. That rebate is the decision made legible — a financial structure
whose purpose was to keep the cost off the party deciding. The people who bore
it were not in the room and were not aboard.

**Wells Fargo — fired again**, in a third industry. An unreachable target set by
people who did not have to meet it; 5,300 dismissals over five years while the
target-setters kept their jobs. Executives did eventually pay — fines,
clawbacks, dismissals — but half a decade later and only once it was public,
which is not the feedback path the rule is about.

**The Wright brothers, 1901 — `cheaper-to-try` fired.** A different century and
a domain with no rockets and no runway pressure. Lilienthal's tables predicted
three times the lift the glider produced; deriving the correction was not
purchasable at any price in 1901, and a wind tunnel was scrap lumber and a
fortnight. Measuring was the cheap option and analysis was the expensive one.

### Kodak broke the rule, exactly as predicted

The prediction written before the run: **Kodak should not fire, and will.**

Kodak's management protected film, and 47,000 people lost their jobs. A rule
comparing `decided_by` against `cost_borne_by` as strings fires on that. But
almost every corporate failure eventually costs employees, and **a rule that
fires on all of them is a famous-disaster detector, not a rule.**

The distinction is **insulation, not identity**. Kodak's management lost the
company they ran. Boeing's executives were not aboard those aircraft; Wells
Fargo's were not fired for missing a quota. The rule now asks whether the
decider is in the blast radius, and stays quiet when they are — shared downside
is a real concern and a different one, and blurring the two costs the rule its
meaning.

### The meta-finding

Two of the three rules tested against an independent case this round and last
needed **narrowing**, in the same direction: `safety_critical` was too wide
until Neuralink, `cost-lands-elsewhere` was too wide until Kodak.

That is not a coincidence. **A rule derived from one event is systematically
too general**, because the single case cannot show you which of its features
were doing the work. The only thing that separates them is a case that shares
some features and not others — which is what an independent test is for, and
why "it explains everything I have looked at" is close to worthless as
evidence.

## What the nine rounds actually taught

**The engine was built from the good weather.** Every original rule assumed
time to think. Three of the four additions are about pressure: what to ignore
when there is no time, what cannot be undone, and when thinking is the more
expensive option. None of that appears in how the method is usually described,
including by him — but all of it appears in what he did.

**The protocol's own order inverts under pressure.** In normal times the
sequence is question, delete, simplify, accelerate, automate — acceleration
fourth. In every crisis case here, cycle time came *first* and the cleanup came
after. The tent was not an optimised solution; it was a fast one that was
allowed to be ugly because it was temporary.

**The most expensive mistakes share one shape.** Over-automation, the tweet,
the acquisition: each was irreversible, each rested on a requirement from the
most senior person present, and in each case nobody challenged it. That is one
pattern, not three, and it is now one rule.

**And one thing did not move.** Whether to accept a bet that ends everything if
it loses is not a question a protocol should answer, and this one does not. It
names it and hands it back.

**He learned one of the two lessons.** The engineering correction took
completely: nothing in 2024–26 shows him building the perfect automated thing
before the crude version works. The judgement one did not. Over-automation,
"funding secured", Twitter, DOGE — irreversible, senior, unchallenged, four
times across eight years, at rising cost.

**And the rule that made the method self-correcting is the one his own scale
broke.** Requirements work because you can go and ask the named person why. By
2026 the named person owns SpaceX, Tesla, xAI, Neuralink, Boring and X, and
above him at any of them there is nobody to ask.

## Sixteen cases, ten rules — a summary

| Rule | Came from | Tested against something it was not built for |
|---|---|---|
| `stopgap` correction | GA4 tent, 2018 | **survived — Colossus 2024, six years and 3 orders of magnitude away** |
| `irreversible-unquestioned` | the 2018 tweet | **survived — Twitter 2022, Boeing 737 MAX** |
| `cheaper-to-try` | Falcon 1, 2008 | **survived — the Wright brothers, 1901** |
| `cost-lands-elsewhere` | DOGE, 2025 | **passed Boeing and Wells Fargo, broke on Kodak; narrowed** |
| `safety_critical` band | robotaxi, 2025 | **passed Waymo, broke on Neuralink; narrowed** |
| `requirement-owner` | stated method | held on 2018 and 2024 |
| `unquestioned-authority` | stated method | held on 2017, 2018, 2025, Wells Fargo |
| `automated-too-early` | stated method | held on 2017 |
| `runway` / survival mode | Tesla, 2008 | **only ever tested on Musk cases** |
| `ruin-risk` | Tesla, 2008 | surfaces, does not resolve — nothing to test |

Every rule that was a description of one event has now been put in front of a
case it was not built for. Three survived unchanged; two broke and survive in a
narrower form. Three cases in the suite have nothing to do with Musk at all —
Boeing, Wells Fargo, Kodak — plus Waymo and the Wright brothers, which is five
of sixteen.

**What remains untested is `runway` / survival mode.** Every case that exercises
it is one of his. Until a company that is not his is watched deciding under
three months of cash, that rule describes a temperament as much as a situation.
