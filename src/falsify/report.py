"""Rendering a report for a human.

The evidence log is the product. Someone reading it should be able to see,
without trusting falsify at all, that the test was run against the broken
code and went red.
"""

from __future__ import annotations

import os
import sys

from .check import Report, Verdict

_MARK = {
    Verdict.PROVEN: "PASS",
    Verdict.VACUOUS: "SKIP",
    Verdict.EMPTY: "SKIP",
    Verdict.NO_EVIDENCE: "FAIL",
    Verdict.NO_TESTS: "FAIL",
    Verdict.BROKEN: "FAIL",
    Verdict.INCONCLUSIVE: "WARN",
}

_COLOR = {
    "PASS": "\033[32m",
    "FAIL": "\033[31m",
    "WARN": "\033[33m",
    "SKIP": "\033[90m",
}
_DIM = "\033[90m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def use_color(stream=sys.stdout) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def render(report: Report, verbose: bool = False, color: bool | None = None) -> str:
    if color is None:
        color = use_color()

    def paint(text: str, code: str) -> str:
        return f"{code}{text}{_RESET}" if color else text

    mark = _MARK[report.verdict]
    lines: list[str] = []

    lines.append(
        f"{paint(mark, _COLOR[mark])} {paint(report.verdict.value, _BOLD)} "
        f"— {report.summary}"
    )
    lines.append("")

    lines.append(paint(f"  base      {report.base[:12]}  ({report.base_reason})", _DIM))
    if report.command:
        guessed = " (guessed)" if report.runner_guessed else ""
        lines.append(paint(f"  runner    {report.runner_name}{guessed}", _DIM))
        lines.append(paint(f"  command   {report.command}", _DIM))
    lines.append(
        paint(
            f"  changed   {len(report.source_files)} source, "
            f"{len(report.test_files)} test",
            _DIM,
        )
    )
    lines.append("")

    if report.counterfactual or report.actual:
        lines.append(f"  {paint('evidence', _BOLD)}")
        lines.append(_evidence_line("without the fix", report.counterfactual, want_red=True, paint=paint))
        lines.append(_evidence_line("with the fix", report.actual, want_red=False, paint=paint))
        lines.append("")

    if report.detail:
        for line in _wrap(report.detail, width=76):
            lines.append(f"  {line}")
        lines.append("")

    for warning in report.warnings:
        for i, line in enumerate(_wrap(warning, width=72)):
            prefix = paint("  warning: ", _COLOR["WARN"]) if i == 0 else "           "
            lines.append(f"{prefix}{line}")
    if report.warnings:
        lines.append("")

    if verbose:
        for label, result in (
            ("without the fix", report.counterfactual),
            ("with the fix", report.actual),
        ):
            if result is None:
                continue
            lines.append(paint(f"  ── output: {label} " + "─" * 30, _DIM))
            for line in result.tail().splitlines():
                lines.append(f"  {line}")
            lines.append("")

    if report.verdict is Verdict.NO_EVIDENCE:
        lines.append(_next_step(paint))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _evidence_line(label: str, result, want_red: bool, paint) -> str:
    if result is None:
        return f"    {label:<18} {paint('not run', _DIM)}"

    if result.timed_out:
        state, code = "timed out", _COLOR["WARN"]
    elif result.passed:
        state, code = "green", _COLOR["PASS"] if not want_red else _COLOR["FAIL"]
    else:
        state, code = "red", _COLOR["PASS"] if want_red else _COLOR["FAIL"]

    expected = "want red" if want_red else "want green"
    return (
        f"    {label:<18} {paint(state, code):<20} "
        f"{paint(f'exit {result.exit_code}  ({expected})', _DIM)}"
    )


def _next_step(paint) -> str:
    return (
        f"  {paint('What to do:', _BOLD)} write a test that fails against the code "
        "as it\n  was before this change, then re-run. If you cannot write one, "
        "the\n  change may not be fixing what it claims to fix."
    )


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    length = 0
    for word in words:
        if current and length + 1 + len(word) > width:
            lines.append(" ".join(current))
            current, length = [word], len(word)
        else:
            current.append(word)
            length += (1 if length else 0) + len(word)
    if current:
        lines.append(" ".join(current))
    return lines or [""]
