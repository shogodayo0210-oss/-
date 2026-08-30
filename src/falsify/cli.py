"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .check import Verdict, check
from .gitutil import GitError
from .report import render

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_ERROR = 2

EPILOG = """\
falsify reconstructs the code as it was before your change, applies only the
test files you touched, and runs them there. A test that passes against the
broken code proves nothing, and falsify says so.

examples:
  falsify                            check the change in your working tree
  falsify --base main                check a whole branch
  falsify --test-cmd 'pytest {files}'
  falsify --json | jq .verdict       for CI
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="falsify",
        description="Prove a change's tests would have caught the bug it fixes.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base",
        metavar="REF",
        help="what to compare against (default: HEAD if you have uncommitted "
        "changes, otherwise the merge base with the default branch)",
    )
    parser.add_argument(
        "--test-cmd",
        metavar="CMD",
        help="how to run the tests; {files} is replaced with the test files "
        "this change touched",
    )
    parser.add_argument(
        "--test-glob",
        metavar="PATTERN",
        action="append",
        default=[],
        help="also treat paths matching PATTERN as tests (repeatable)",
    )
    parser.add_argument(
        "--setup",
        metavar="CMD",
        help="run CMD before the tests in each checkout (installs, codegen)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        metavar="SEC",
        help="per-run timeout in seconds (default: 600)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="include captured test output",
    )
    parser.add_argument(
        "--version", action="version", version=f"falsify {__version__}"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        report = check(
            base=args.base,
            test_cmd=args.test_cmd,
            test_globs=args.test_glob,
            setup=args.setup,
            timeout=args.timeout,
        )
    except GitError as exc:
        print(f"falsify: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        sys.stdout.write(render(report, verbose=args.verbose))

    if report.verdict is Verdict.INCONCLUSIVE:
        # Not a pass, but not the tool's call to make either.
        return EXIT_GATE_FAILED
    return EXIT_OK if report.verdict.ok else EXIT_GATE_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
