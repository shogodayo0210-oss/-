#!/usr/bin/env python3
"""Run the engine against decisions whose outcomes are already known.

Each case reconstructs a real decision point — what was true *then*, not what
we learned later — and records what was actually done and how it turned out.
The engine is run against the reconstruction and scored on whether it flagged
what mattered.

This is not validation. The reconstructions are written by the same person who
wrote the rules, after the outcomes were public, and a case can be tuned until
it passes. What the harness is good for is the opposite: catching the cases the
engine *cannot* get right however they are phrased. Those are the real findings,
and they are recorded as EXPECTED MISS rather than quietly dropped.

    python3 backtests/run.py [--verbose]
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from firstprinciples.audit import audit  # noqa: E402
from firstprinciples.calibrate import calibrate  # noqa: E402
from firstprinciples.model import Decision  # noqa: E402
from firstprinciples.opportunity import Assessment  # noqa: E402

CASES = Path(__file__).resolve().parent / "cases"


@dataclass
class Score:
    name: str
    passed: bool
    expected_miss: bool
    detail: str

    @property
    def mark(self) -> str:
        if self.expected_miss:
            return "KNOWN GAP" if not self.passed else "NOW FIXED"
        return "HIT" if self.passed else "MISS"


def run_case(path: Path, verbose: bool = False) -> Score:
    raw = json.loads(path.read_text())
    expect = raw.get("expect", {})
    decision = Decision.from_dict(raw["decision"])
    if raw["decision"].get("opportunity"):
        Assessment.from_dict(raw["decision"]["opportunity"])

    result = audit(decision)
    calibration = calibrate(decision)
    fired = {f.rule for f in result.findings}

    problems: list[str] = []

    missing = [r for r in expect.get("must_flag", []) if r not in fired]
    if missing:
        problems.append(f"did not flag {', '.join(missing)}")

    wrongly = [r for r in expect.get("must_not_flag", []) if r in fired]
    if wrongly:
        problems.append(f"wrongly flagged {', '.join(wrongly)}")

    # Some cases turn on the corrected schedule rather than on any finding.
    bounds = expect.get("months_within")
    if bounds and calibration.months_high is not None:
        low, high = bounds
        if not (low <= calibration.months_high <= high):
            problems.append(
                f"corrected schedule {calibration.months_low:.2f}"
                f"-{calibration.months_high:.2f}mo outside expected {low}-{high}mo"
            )

    score = Score(
        name=raw["case"],
        passed=not problems,
        expected_miss=bool(expect.get("known_gap")),
        detail="; ".join(problems) or "as expected",
    )

    if verbose:
        print(f"\n  {raw['case']}  ({raw['date']})")
        print(f"    did:      {raw['what_he_actually_did']}")
        print(f"    outcome:  {raw['outcome']} — {raw['outcome_detail']}")
        print(f"    flagged:  {', '.join(sorted(fired)) or 'nothing'}")
        if calibration.months_high is not None:
            print(
                f"    schedule: {calibration.months_low:.2f}"
                f"-{calibration.months_high:.2f} months"
            )

    return score


def main(argv: list[str]) -> int:
    verbose = "--verbose" in argv or "-v" in argv
    paths = sorted(CASES.glob("*.json"))
    if not paths:
        print("no cases found", file=sys.stderr)
        return 2

    scores = [run_case(p, verbose) for p in paths]

    print("\n  BACKTEST\n")
    width = max(len(s.name) for s in scores)
    for score in scores:
        print(f"  {score.mark:<10} {score.name:<{width}}  {score.detail}")

    hits = sum(1 for s in scores if s.passed and not s.expected_miss)
    gaps = sum(1 for s in scores if s.expected_miss)
    misses = sum(1 for s in scores if not s.passed and not s.expected_miss)
    fixed = sum(1 for s in scores if s.expected_miss and s.passed)

    print(
        f"\n  {hits} hit, {misses} unexpected miss, {gaps} known gap"
        + (f", {fixed} of those now fixed" if fixed else "")
        + "\n"
    )

    # Unexpected misses fail the run. Known gaps do not: they are the honest
    # record of what this engine cannot do yet.
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
