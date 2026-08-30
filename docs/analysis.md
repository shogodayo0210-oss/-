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

Secondary sources dominate the online material on all of this, and much of it
is either promotional or hostile. The four rules above are the ones that appear
consistently across independent accounts and are specific enough to implement
and check. Treat anything softer than that — and especially any claim about what
he privately thinks — as unverified.
