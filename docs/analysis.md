# The method behind `fp`

`fp` implements a decision protocol assembled from the documented working
methods of Elon Musk. This document says where each rule comes from, what the
evidence for it is, and — the part most treatments skip — where the method
demonstrably fails.

It is an analysis of a **method**, not a portrait of a person, and `fp` never
speaks in anyone's voice.

## What he actually knows

Worth establishing plainly, because both the hagiography and the backlash get
it wrong.

- **Training**: dual degrees at the University of Pennsylvania — BA in physics,
  BS in economics (Wharton). That pairing matters more than either half: the
  protocol below is consistently *physics applied to cost*.
- **Publication record**: essentially none as a scientist. Google Scholar lists
  around three items, including a paper on NASA's commercial cargo and crew
  approach. He is not a research scientist and does not claim to be.
- **Patents**: roughly 25 patents across ~8 families — vehicle design,
  autonomous vehicles, geospatial systems. Selective rather than prolific.
- **Reading**: the biographies converge on an unusual childhood reading volume
  — encyclopedias, science fiction, and later targeted domain immersion
  (reading banking texts while building X.com, propulsion texts before SpaceX).

The accurate summary is not "genius scientist" and not "just a financier."
It is: **an unusually fast domain-immersion generalist who reasons about
engineering problems in the currency of cost.** That is what the protocol
below encodes, and it is reproducible in a way that personality is not.

## The arc, and what the screens were derived from

The six screens in `fp` are not a philosophy. They are what is left when you
line up the ventures and ask what the winners have in common.

| | | The shape |
|---|---|---|
| **Zip2** | 1995–99 | Newspaper listings — an existing need, sold to papers that already wanted it. Compaq paid $307M. |
| **X.com → PayPal** | 1999–2002 | Bank transfers, "make money move like email". eBay paid $1.5B; his share about $165M. |
| **SpaceX** | 2002– | Launch, where the stated problem was *cost*, not capability. |
| **Tesla** | 2004– | Cars, entered on a $6.3M investment, on the thesis that packs cost $600/kWh only because they always had. |
| **SolarCity** | 2006– | Generation, later folded into Tesla. |
| **Neuralink / Boring** | 2016– | Interfaces and tunnels — same screen, applied to costs nobody had questioned. |
| **X (Twitter)** | 2022 | The one that does not fit. See below. |
| **xAI** | 2023– | Models, merged into SpaceX in 2026. |

Four things recur in every one that worked, and they became screens 1–4: a
price set by history rather than physics, an expensive part that could be
brought in-house, a barrier made of capital or convention rather than physics,
and a need that already existed. The remaining two are how it was funded and
staffed — a mission that recruited below market rate, and capital from the
previous exit that answered to nobody.

### Where it stands now

As of late 2026 the pattern is still running, and one move is the clearest
example of screen 2 in the whole history.

- **SpaceX acquired xAI** on 2 February 2026, valuing the combination at about
  $1.25 trillion ($1T SpaceX, $250B xAI). The stated motive is orbital data
  centres: launch and compute under one roof. SpaceX's own announcement calls
  the result a "vertically integrated innovation engine" — screen 2, in their
  words, at the largest scale it has ever been attempted.
- **SpaceX went public** on 12 June 2026 on the Nasdaq as `SPCX`, pricing at
  $135 and raising roughly $85.7B gross against an implied valuation near
  $1.77T. It traded around $141.50 in late August 2026.
- Neuralink's N1 had been implanted in three people as of May 2025, with the
  Blindsight vision implant slated for a first trial in 2026. The Boring
  Company's Nashville Loop and Tesla's Cybercab and Optimus Gen 3 all carry
  2026 dates.

### What he says comes next

Mars as "life insurance for life collectively", not a flag-planting exercise
but a self-sustaining city — with Optimus sent first to build infrastructure
before any human arrives — and xAI aimed at AGI. Whether one believes the
destination or not, the *structure* of the claim is the same as every previous
one: an existing need, a cost asserted to be reducible, and a mission framed to
recruit.

### Two observations the arc supports

**The merger confirms the pattern.** Buying the compute side of your own launch
business is screen 2 executed at maximum scale. Nothing about it is a departure.

**The IPO weakens screen 6, for him.** `reachable_proof` — capital that answers
to nobody — is the condition that made the earlier bets possible: Zip2 funded
X.com, PayPal funded SpaceX and Tesla, and none of it required convincing a
public market first. A listed company answers to shareholders on a quarterly
cadence. The sixth condition of the method is now materially weaker for its own
originator than it was for any venture that produced it. That is worth watching,
and it is the one part of this document that is a prediction rather than a
record.

### A caveat this document has to apply to itself

The dated items above split into two kinds. The merger and the IPO are settled
facts with primary sources — a company announcement, an SEC filing, an investor
relations release. The product dates are *announcements*: Cybercab in April,
Blindsight in 2026, Nashville in spring.

Announcements are precisely the class of claim the 2×–5× correction below
exists for. Applying this document's own rule to this document's own sources:
treat the first kind as recorded and the second kind as an estimate that has
not yet been corrected.

## The four rules `fp` implements

### 1. First principles, not analogy

> "First principles is a kind of physics way of looking at the world... you boil
> things down to the most fundamental truths and then reason up from there."

The canonical worked example is battery packs. Told that packs cost \$600/kWh
and always would, he decomposed to constituent materials — cobalt, nickel,
aluminium, carbon, polymers — priced them at spot market, and got roughly
\$80/kWh. The gap between the two numbers is the whole method: the market price
was tracking history, not physics.

**Implemented as**: every requirement must declare what it is *grounded in* —
physics, a contract, or an assumption. Assumptions are delete candidates by
default.

### 2. Requirements belong to named people

> "You should never accept that a requirement came from a department... You need
> to know the name of the real person who made that requirement."

And the inversion that most people drop when they repeat this:

> "Requirements from smart people are the most dangerous, because people are
> less likely to question them."

This is genuinely counterintuitive and it is the single most implementable
idea in the whole method. Normal engineering practice treats a requirement from
a senior figure as *more* settled. This treats it as *less*.

**Implemented as**: a requirement with no named owner is a blocker. A
requirement from a high-authority owner that nobody has questioned is raised in
severity, not lowered.

### 3. The Algorithm, and its order

Five steps, and the order is the content:

1. Question every requirement
2. Delete every part and process you can
3. Simplify and optimise — *only what survived*
4. Accelerate cycle time
5. Automate — **last**

With a self-check on step 2: if you don't end up putting back at least 10% of
what you deleted, you didn't delete enough.

The stated failure mode is automating or optimising a step that should not
exist. That is the most expensive mistake available, because it makes waste
permanent and fast.

**Implemented as**: a deletion audit computing the reinstatement ratio against
the 10% floor, and an order check that flags any step automated without ever
having been considered for deletion.

### 4. The idiot index

The ratio of a finished component's cost to the cost of its raw materials. A
high ratio means you are paying for process, not for matter. The documented
example: a \$1,500 space-station-grade door latch, replaced by a modified
bathroom stall latch at \$30 — an index of 50.

**Implemented as**: a per-component index with severity bands, and the cash
figure recoverable if the component were brought to a target ratio.

## Where the method fails — and why `fp` models that too

Most "think like X" material copies the wins and quietly drops the error rate.
A model that only reproduces the successes is not a model of the person. It is
fan fiction with footnotes.

Two failure modes are well enough documented to be quantified, so `fp`
quantifies them.

### Timeline optimism is systematic, not occasional

Independent trackers converge on the same finding: stated timelines overshoot
by roughly **2× to 5×**, with a commonly used rule of thumb of 2–3× on schedule
plus about 50% on cost. Robotaxis promised for 2020 are the standard example.

The important nuance is the *mechanism*, not the size. The gap is not in
solving the technical problem — that part is often delivered. The gap is
between a working technical solution and **deployment at scale, at cost, in a
regulated world**.

That mechanism is what makes the bias modellable rather than just noted.
`fp` scales the correction by the phases your work actually involves:

| Phase | Multiplier | Why |
|---|---|---|
| `prototype` | 1.2–2.0× | Demonstrating it can work is the part he is good at |
| `production` | 2.0–3.0× | Making it repeatedly, at cost, is where it slips |
| `regulated` | 3.0–5.0× | A regulator who must agree is not an engineering problem |

So the same estimate gets a different correction depending on what kind of work
it actually is. A flat "multiply by three" would be less useful and less true.

### The organisational cost is real and usually unpriced

Isaacson documents a "demon mode" — periods of cold, brutal treatment of staff,
described as producing breakthroughs that gentler management would not have
produced, while also driving out senior people and creating chaos that *delayed*
projects. Grimes coined the term; Isaacson observed it over two years.

`fp` does not attempt to simulate this and does not recommend it. It carries one
line in every report reminding you that the method's throughput figures come
from an environment with high attrition, and that the attrition is a cost the
method's own accounting never charges itself.

If you adopt the protocol, adopt the corrections with it. That is the whole
argument for building this as an analysis engine rather than a voice.

## Sources

- Walter Isaacson, *Elon Musk* (2023) — the Algorithm, the requirements rule,
  the idiot index, "demon mode"
- Ashlee Vance, *Elon Musk: Tesla, SpaceX, and the Quest for a Fantastic
  Future* (2015) — education, reading, early domain immersion
- Musk's own 2012–2013 interview remarks on first principles and battery cost
  decomposition
- Independent prediction trackers and a WIRED analysis (May 2025) for the
  2×–5× timeline overshoot
- For the 2026 corporate events, primary and near-primary sources only:
  SpaceX's and xAI's own announcements of the February 2026 merger, CNBC and
  TechCrunch reporting on its valuation, SpaceX's investor-relations release
  and S-1 for the June 2026 Nasdaq listing
- Google Scholar and patent databases for the publication and patent counts

Secondary sources dominate the online material on all of this, and much of it
is either promotional or hostile. The four rules above are the ones that appear
consistently across independent accounts and are specific enough to implement
and check. Treat anything softer than that — and especially any claim about what
he privately thinks — as unverified.
