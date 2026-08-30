# falsify

**Red before green, or it didn't happen.**

A test that passes against the code it was written to police is not evidence of
anything. `falsify` checks the one thing that makes a test meaningful: that it
fails without the fix.

---

## The problem

Your agent hands you a change. It says it fixed a bug. It added a test. The
test is green.

So is a test that asserts nothing.

Every tool in the pipeline — CI, coverage, the review bot — looks at the code
*after* the change and reports green. None of them ask the only question that
matters: **would this test have caught the bug?** Answering it means running the
test against the broken code, and nobody does that, because by the time anyone
looks the broken code is gone.

That gap is where "almost right, but not quite" lives. It is the single most
common complaint about agent-written code, and it is invisible to a green
checkmark.

## The trick

`falsify` reconstructs the state nobody keeps around:

```
   your change  =  [ source edits ]  +  [ test edits ]

   counterfactual  =  old source  +  NEW tests     ← run this
```

It checks the base commit out into a scratch worktree, applies **only** your
test changes there, and runs them. They must go **red**. Then it runs the same
tests in your real worktree, where they must go **green**.

Red without the fix, green with it. Anything else is not evidence.

Your own working tree is never modified.

## See it

```console
$ ./examples/demo.sh
```

The demo builds a throwaway repo with a real bug — a `clamp()` that forgets its
upper bound — and shows the same genuine fix twice.

First, shipped with a test that only exercises the half that already worked.
This is what every other tool calls green:

```
FAIL NO_EVIDENCE — the test passes even without the fix, so it proves nothing

  base      38e087d52219  (uncommitted changes present; comparing against HEAD)
  command   python -m pytest -q tests/test_calc.py
  changed   1 source, 1 test

  evidence
    without the fix    green                exit 0  (want red)
    with the fix       green                exit 0  (want green)

  The tests pass against the code from before this change. Whatever this
  change fixes, this test would not have caught it.

Exit code: 1 — CI stops here.
```

Then the same fix, with a test that actually pins the bug:

```
PASS PROVEN — the test fails without the fix and passes with it

  evidence
    without the fix    red                  exit 1  (want red)
    with the fix       green                exit 0  (want green)

Exit code: 0 — CI carries on.
```

Same source diff both times. The only thing that changed is whether the test
was ever capable of failing.

## It checks itself

`falsify` found a real bug in `falsify`, and the counterfactual is the proof.

A `--setup` step like `pip install -e .` depends on the changed source, so it
*always* fails in the counterfactual — and that failure was being read as "the
test went red". A change whose tests never ran at all would have come back
`PROVEN`. The fix, and the test that pins it, produce this:

```
PASS PROVEN — the test fails without the fix and passes with it

  evidence
    without the fix    red                  exit 1  (want red)
    with the fix       green                exit 0  (want green)
```

And `-v` shows *why* the counterfactual went red — not a crash, not an unrelated
test, but the assertion that names the bug:

```
E       AssertionError: assert <Verdict.PROVEN> is <Verdict.INCONCLUSIVE>
```

That is what evidence looks like: the old code reached the wrong verdict, in
writing, before anyone was asked to believe the new code reaches the right one.

## Install

Python 3.9+ and git. No dependencies.

```console
$ pip install -e .
```

Or run it straight out of the tree, with nothing installed at all:

```console
$ PYTHONPATH=src python3 -m falsify
```

## Use

```console
$ falsify                              # check what's in your working tree
$ falsify --base main                  # check a whole branch
$ falsify --test-cmd 'pytest {files}'  # say how to run the tests
$ falsify --json | jq .verdict         # for CI
$ falsify -v                           # include the captured test output
```

With no arguments it compares against `HEAD` if you have uncommitted changes,
and against the merge base with your default branch otherwise. It guesses your
test runner from the project layout and says so in the report — when it guesses
wrong, pass `--test-cmd`.

`{files}` in a test command is replaced with the test files your change
touched. Use it. Without it the whole suite runs in the counterfactual, and an
unrelated failing test looks exactly like evidence.

| Flag | |
|---|---|
| `--base REF` | what to compare against |
| `--test-cmd CMD` | how to run the tests; `{files}` is substituted |
| `--test-glob PAT` | also treat paths matching `PAT` as tests (repeatable) |
| `--setup CMD` | run before the tests in each checkout (installs, codegen) |
| `--timeout SEC` | per-run timeout, default 600 |
| `--json` | machine-readable output |
| `-v` | include captured test output |

## Verdicts

| Verdict | Exit | Meaning |
|---|---|---|
| `PROVEN` | 0 | Red without the fix, green with it. The test earns its place. |
| `VACUOUS` | 0 | Only tests changed. Nothing to falsify — adding tests is never blocked. |
| `EMPTY` | 0 | Nothing changed. |
| `NO_EVIDENCE` | 1 | The test passes against the broken code. **This is the one.** |
| `NO_TESTS` | 1 | Source changed and nothing would fail if it were wrong. |
| `BROKEN` | 1 | The test fails without the fix *and* with it. The change doesn't work. |
| `INCONCLUSIVE` | 1 | The counterfactual broke instead of failing. Red for the wrong reason. |

`INCONCLUSIVE` matters more than it looks. If the new test can't even import
against the older code, it went red for a reason that has nothing to do with
the fix — and calling that evidence would be the exact mistake this tool
exists to prevent. So it refuses to.

## In CI

```yaml
- name: Tests must be capable of failing
  run: |
    pip install -e .
    falsify --base "origin/${{ github.base_ref }}" \
            --test-cmd 'pytest -q {files}'
```

## What it does not do

Being clear about this matters more than the feature list.

- **It does not judge whether the fix is correct.** It only establishes that
  the test could have caught something. A test can be red for the wrong reason
  and still pass this gate.
- **It needs a runner that can be pointed at specific files** to be precise.
  `cargo test` and `go test ./...` run everything, and `falsify` warns you when
  the command it's using can't be narrowed.
- **It cannot see untracked files.** A brand new test file git has never heard
  of is invisible to `git diff`, so `falsify` looks for them and warns loudly
  rather than waving the change through. `git add -N` is enough.
- **It runs your tests twice.** On a slow suite, scope the command with
  `{files}`.
- **It is not mutation testing.** Mutation testing invents synthetic breakage
  to score a suite. This checks the one real counterfactual you actually care
  about: the code as it was, five minutes ago.

## Why this, and why now

Generating code got cheap. Checking it didn't. Every number points the same
way: the top complaint about coding agents is output that is *almost* right;
curl shut down its bug bounty after AI-assisted reports drove the valid rate to
roughly one in thirty; enterprise agent fleets doubled in four months while the
monitoring around them barely moved.

The industry's answer has been to make claims more persuasive — better
summaries, confidence scores, tidier reports. But a better-argued claim is
still a claim. The scarce thing now is **evidence**: a record that something
was actually run and actually came back the way it should have.

This tool is one small, boring instance of that. It produces four lines of
evidence and refuses to produce them when it can't. If that norm spreads
further than this program does, that's the better outcome.

## Development

```console
$ pip install -e '.[dev]'
$ pytest
```

`falsify` is subject to its own gate. If you send a patch, it should pass.

## License

MIT
