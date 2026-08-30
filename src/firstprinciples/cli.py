"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .audit import Severity, audit
from .calibrate import calibrate
from .model import Decision, SpecError
from .opportunity import Assessment
from .report import render

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

EPILOG = """\
fp runs a decision through a protocol assembled from documented working
methods: question every requirement, delete before you simplify, simplify
before you automate, and price what you pay against what the thing
irreducibly requires. It then corrects your estimate for the method's own
documented optimism.

It analyses. It does not speak in anyone's voice.

examples:
  fp decision.json              read a decision and report on it
  fp decision.json --explain    include why each screen is there
  fp decision.json --json       machine-readable
  fp examples/portfolio.json    the screen run against its own source

See docs/analysis.md for where every rule comes from.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fp",
        description="Run a decision through a first-principles protocol.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="JSON decision file; reads stdin when omitted or given as -",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="include the reasoning behind each screen",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead")
    parser.add_argument(
        "--fail-on",
        choices=[s.value.lower() for s in Severity],
        default="blocker",
        help="lowest severity that exits non-zero (default: blocker)",
    )
    parser.add_argument("--version", action="version", version=f"fp {__version__}")
    return parser


def _read(path: str | None) -> str:
    if path is None or path == "-":
        return sys.stdin.read()
    return Path(path).read_text()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        raw = json.loads(_read(args.file))
    except FileNotFoundError:
        print(f"fp: no such file: {args.file}", file=sys.stderr)
        return EXIT_ERROR
    except json.JSONDecodeError as exc:
        print(f"fp: {args.file or 'stdin'} is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        decision = Decision.from_dict(raw)
        assessment = (
            Assessment.from_dict(raw["opportunity"]) if raw.get("opportunity") else None
        )
    except SpecError as exc:
        print(f"fp: {exc}", file=sys.stderr)
        return EXIT_ERROR

    result = audit(decision)
    calibration = calibrate(decision)

    if args.json:
        print(
            json.dumps(
                {
                    "decision": decision.title,
                    "opportunity": assessment.to_dict() if assessment else None,
                    "findings": [f.to_dict() for f in result.sorted_findings()],
                    "reinstatement_ratio": result.reinstatement_ratio,
                    "recoverable": round(result.recoverable, 2),
                    "calibration": calibration.to_dict(),
                },
                indent=2,
            )
        )
    else:
        sys.stdout.write(
            render(decision, result, calibration, assessment, explain=args.explain)
        )

    threshold = Severity(args.fail_on.upper())
    if any(f.severity.rank <= threshold.rank for f in result.findings):
        return EXIT_FINDINGS
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
