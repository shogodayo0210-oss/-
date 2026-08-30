# fp

**A first-principles decision protocol, with its own error bars.**

`fp` takes a decision — a project, a process, a research direction, a career
move — and runs it through a protocol assembled from a documented working
method: question every requirement, delete before you simplify, simplify before
you automate, and price what you pay against what the thing irreducibly
requires. Then it corrects your estimate for the method's own documented
optimism.

It analyses. **It does not speak in anyone's voice.**

## Why not a voice

The obvious version of this is a chatbot that answers in the first person as a
particular famous engineer. That version is worse, for two reasons.

The first is that it does not work. Cadence is the easy part and the useless
part. A convincing imitation of how someone talks tells you nothing about how
they decide, and the thing worth having is the decision procedure — which is
documented, checkable, and reusable by anyone.

The second is that fabricated first-person statements from a living, named,
market-moving person are a real problem regardless of intent. So `fp` is built
the other way round: every rule is traceable to a source in
[docs/analysis.md](analysis.md), and the tool's output is an assessment of
*your* decision rather than a performance of someone else's personality.

## Not just business

The screen was derived from a venture history, but the questions survive the
translation. "Price" becomes whatever a thing currently costs — money, hours,
attention. "Incumbent" becomes whatever currently occupies the ground.

The shipped example that best makes the point is a weekly status report:

```console
$ fp examples/weekly-report.json
```

Six hours a week producing thirty minutes of actual information is an index of
12×. Same machinery as a $1,500 door latch, different unit.

## Two halves

**Where to point effort** — six screens, with one of them acting as a gate:

| Screen | Question |
|---|---|
| `cost_detached` | Is what this costs set by habit rather than by a real limit? |
| `absorbable` | Is the expensive part something you could take on directly? |
| `soft_barrier` | Is the barrier capital, regulation or convention rather than a technical wall? |
| `existing_need` | Does the need already exist, so you never have to manufacture it? |
| `pulls_help` | Would the honest framing pull in people you could not otherwise get? |
| `reachable_proof` | Can you reach a convincing proof point with what you already control? |

`cost_detached` is a gate, not just a weight. If nothing here costs more than
it must, the verdict is `OFF_PATTERN` no matter how well everything else
scores — because every other rule in the tool is machinery for closing a gap,
and there is no gap.

**How you are running it** — four checks:

- A requirement with no *named person* behind it is a blocker. A department
  cannot be asked why.
- A requirement from a **senior** person that nobody has questioned is raised
  in severity, not lowered. This is the inversion worth having: requirements
  from smart people survive longest precisely because nobody challenges them.
- A step automated or optimised without ever being considered for deletion is
  flagged. Automating a step that should not exist makes the waste permanent
  and fast.
- Deleting things and never putting any back means you stopped early. The
  floor is 10%.

## The error bars

This is the part most treatments of the method leave out. Independent trackers
put its timeline overshoot at roughly **2× to 5×**. A model that reproduces
only the wins is not a model.

`fp` scales the correction by the kind of work, because the documented
mechanism is specific: the technical problem usually does get solved, and the
slip is between a working solution and deployment at scale, at cost, under a
regulator.

| Phase | Correction |
|---|---|
| `prototype` | 1.2–2.0× |
| `production` | 2.0–3.0× |
| `regulated` | 3.0–5.0× |

The hardest declared phase sets the correction — work does not finish when its
easiest part finishes.

Every report also carries one standing line noting that the method's throughput
came alongside high attrition, a cost its own accounting never charges itself.

## Does the screen mean anything?

A screen built only from things that worked will approve of everything. So the
repository ships a counter-example.

```console
$ fp examples/tesla-2004.json   # STRONG      93%
$ fp examples/x-2022.json       # OFF_PATTERN 30%
```

The rejection comes from the gate, not from a low total: there was no thesis
that running a social network costs more than it must, so there was no gap to
close. A test asserts exactly that, so the claim cannot quietly stop being true.

**This is a consistency check, not independent evidence.** The scores in those
files are one reading of the public record, assigned by the author of the tool,
after the outcomes were known. It shows the screen *can* reject something. It
does not show the screen is right.

## Use

```console
$ pip install -e .
$ fp examples/falsify-v1.json
$ fp decision.json --explain      # why each screen is there
$ fp decision.json --json         # machine-readable
$ fp decision.json --fail-on high # exit non-zero at HIGH and above
$ cat decision.json | fp          # reads stdin
```

Input is plain JSON so the file a team argues over stays diffable. Every
example in `examples/` is a working template.

Exit codes: `0` clean, `1` findings at or above `--fail-on` (default
`blocker`), `2` bad input.

## What it does not do

- **It does not decide.** It produces findings and an adjusted estimate. Every
  score in the screen is a judgement you make, and the tool will faithfully
  report whatever you tell it.
- **It cannot check your evidence.** Writing `"cost_detached": 2` with no
  basis produces a confident, worthless report. The `evidence` field exists so
  that a reader can catch you; nothing catches you automatically.
- **It has no opinion about the person.** See [docs/analysis.md](analysis.md)
  for where each rule comes from and where the method demonstrably fails.
