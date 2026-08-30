#!/usr/bin/env python3
"""Run the engine forward, on claims whose outcomes nobody knows yet.

Every result in backtests/ is retrospective. The outcome was public before
the case was written, which caps what any of it can prove: the engine has
only ever been graded on decisions whose answers were already in.

This is the other half. Each file in claims/ takes a public, dated,
unresolved claim about the future, encodes it as a decision, and records what
the engine says — with a resolution date, so it can be marked right or wrong
later by someone who is not the author.

    python3 forecasts/run.py [--json]

Predictions are committed. That is the point of them.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from firstprinciples.audit import audit  # noqa: E402
from firstprinciples.calibrate import calibrate  # noqa: E402
from firstprinciples.model import Decision  # noqa: E402

CLAIMS = Path(__file__).resolve().parent / "claims"


def months_after(iso: str, months: float) -> str:
    """Add a number of months to a YYYY-MM (or YYYY-MM-DD) date."""
    parts = iso.split("-")
    year, month = int(parts[0]), int(parts[1])
    total = (year * 12 + (month - 1)) + round(months)
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def evaluate(path: Path) -> dict:
    raw = json.loads(path.read_text())
    decision = Decision.from_dict(raw["decision"])
    result = audit(decision)
    calibration = calibrate(decision)

    predicted_from = raw["claimed_on"]
    prediction = {
        "claim": raw["claim"],
        "claimed_by": raw["claimed_by"],
        "claimed_on": predicted_from,
        "target": raw["target"],
        "resolves_on": raw["resolves_on"],
        "source": raw["sources"][0],
        "phase": calibration.driver.value if calibration.driver else None,
        "correction": f"{calibration.low_multiplier:.1f}-{calibration.high_multiplier:.1f}x",
        "flags": sorted({f.rule for f in result.findings}),
        "outcome": raw.get("outcome", "UNRESOLVED"),
        "caveat": raw.get("caveat"),
    }

    if calibration.months_low is not None:
        prediction["engine_window"] = (
            f"{months_after(predicted_from, calibration.months_low)} to "
            f"{months_after(predicted_from, calibration.months_high)}"
        )
        prediction["engine_earliest"] = months_after(
            predicted_from, calibration.months_low
        )

    return prediction


def main(argv: list[str]) -> int:
    paths = sorted(CLAIMS.glob("*.json"))
    if not paths:
        print("no claims found", file=sys.stderr)
        return 2

    predictions = [evaluate(p) for p in paths]

    if "--json" in argv:
        print(json.dumps(predictions, indent=2))
        return 0

    print(f"\n  FORWARD RUN — generated {date.today().isoformat()}")
    print("  Nothing here is resolved. That is what makes it a test.\n")

    for p in predictions:
        print(f"  {p['claim']}")
        print(f"    claimed    {p['claimed_by']}, {p['claimed_on']} → {p['target']}")
        print(f"    engine     {p.get('engine_window', 'no schedule given')}"
              f"   ({p['correction']}, {p['phase']})")
        if p["flags"]:
            print(f"    flags      {', '.join(p['flags'])}")
        if p["caveat"]:
            for line in _wrap(p["caveat"], 66):
                print(f"    ! {line}")
        print(f"    resolves   {p['resolves_on']}   [{p['outcome']}]")
        print()

    print("  To grade: set \"outcome\" in the claim file once the date passes.\n")
    return 0


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], []
    for word in words:
        if current and sum(len(w) + 1 for w in current) + len(word) > width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
