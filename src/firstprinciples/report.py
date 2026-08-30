"""Rendering an assessment.

Two halves, kept visibly apart: whether this is worth pointing effort at, and
whether you are running it the way the method says. A proposal can fail the
first and pass the second, and being told so is the useful case.
"""

from __future__ import annotations

import os
import sys

from .audit import AuditResult, Finding, Severity, amount
from .calibrate import Calibration
from .model import Decision
from .opportunity import FIT_SUMMARY, QUESTIONS, WHY, Assessment, Fit, MAX_SCORE

_SEVERITY_COLOR = {
    Severity.BLOCKER: "\033[31m",
    Severity.HIGH: "\033[31m",
    Severity.MEDIUM: "\033[33m",
    Severity.LOW: "\033[90m",
    Severity.INFO: "\033[90m",
}

_FIT_COLOR = {
    Fit.STRONG: "\033[32m",
    Fit.PARTIAL: "\033[33m",
    Fit.WEAK: "\033[33m",
    Fit.OFF_PATTERN: "\033[31m",
}

_DIM = "\033[90m"
_BOLD = "\033[1m"
_RESET = "\033[0m"

#: Printed on every report. The throughput figures this method is famous for
#: come from an environment with documented high attrition, and the method's
#: own accounting never charges itself for that.
STANDING_NOTE = (
    "This protocol is drawn from a working method whose documented results "
    "came alongside high attrition and organisational churn. That cost is real "
    "and is not counted anywhere above."
)


def use_color(stream=sys.stdout) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def render(
    decision: Decision,
    result: AuditResult,
    calibration: Calibration,
    assessment: Assessment | None = None,
    explain: bool = False,
    color: bool | None = None,
) -> str:
    if color is None:
        color = use_color()

    def paint(text: str, code: str) -> str:
        return f"{code}{text}{_RESET}" if color else text

    lines: list[str] = []
    lines.append(paint(decision.title, _BOLD))
    lines.append("")

    if assessment is not None:
        lines.extend(_render_opportunity(assessment, explain, paint))

    lines.extend(_render_findings(result, decision.unit, paint))
    lines.extend(_render_calibration(calibration, paint))

    lines.append(paint("  " + "─" * 68, _DIM))
    for line in _wrap(STANDING_NOTE, 68):
        lines.append(paint(f"  {line}", _DIM))
    lines.append("")

    return "\n".join(lines)


def _render_opportunity(assessment: Assessment, explain: bool, paint) -> list[str]:
    lines = [paint("  WHERE TO POINT EFFORT", _BOLD), ""]

    fit = assessment.fit
    lines.append(
        f"    {paint(fit.value, _FIT_COLOR[fit])} — {FIT_SUMMARY[fit]}"
    )
    lines.append(
        paint(
            f"    {assessment.subject}  ·  {assessment.percentage:.0f}% "
            f"({assessment.score:.1f} of {assessment.max_score:.0f})",
            _DIM,
        )
    )
    lines.append("")

    for result in assessment.results:
        bar = "█" * result.score + "·" * (MAX_SCORE - result.score)
        label = result.screen.value.replace("_", " ")
        head = f"    {bar}  {label:<16}"
        hang = " " * len(head)

        question = _wrap(QUESTIONS[result.screen], 44)
        lines.append(f"{head}{paint(question[0], _DIM)}")
        for line in question[1:]:
            lines.append(f"{hang}{paint(line, _DIM)}")

        if result.evidence:
            for line in _wrap(result.evidence, 60):
                lines.append(paint(f"          {line}", _DIM))
        if explain:
            lines.append("")
            for line in _wrap(WHY[result.screen], 60):
                lines.append(paint(f"          {line}", _DIM))
        lines.append("")

    if not assessment.gate_passed:
        for line in _wrap(
            "The gate is closed: nothing here costs more than it must. Every "
            "other rule in this tool is machinery for closing a gap, and there "
            "is no gap. A strong mission does not substitute for one.",
            66,
        ):
            lines.append(f"    {line}")
        lines.append("")
    else:
        weakest = assessment.weakest()[:2]
        if weakest:
            names = ", ".join(r.screen.value.replace("_", " ") for r in weakest)
            lines.append(f"    {paint('Thinnest:', _BOLD)} {names}")
            lines.append("")

    return lines


def _render_findings(result: AuditResult, unit: str, paint) -> list[str]:
    lines = [paint("  HOW YOU ARE RUNNING IT", _BOLD), ""]

    findings = result.sorted_findings()
    if not findings:
        lines.append(paint("    Nothing flagged.", _DIM))
        lines.append("")
        return lines

    counts: dict[Severity, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    tally = "  ".join(
        paint(f"{count} {severity.value.lower()}", _SEVERITY_COLOR[severity])
        for severity, count in sorted(counts.items(), key=lambda kv: kv[0].rank)
    )
    lines.append(f"    {tally}")
    lines.append("")

    for finding in findings:
        lines.extend(_render_finding(finding, paint))

    if result.recoverable > 0:
        lines.append(
            f"    {paint('On the table:', _BOLD)} "
            f"{amount(result.recoverable, unit)} across flagged items"
        )
        lines.append("")

    if result.reinstatement_ratio is not None:
        lines.append(
            paint(
                f"    Reinstatement ratio {result.reinstatement_ratio:.0%} "
                "(want 10% or more — putting nothing back means you stopped early)",
                _DIM,
            )
        )
        lines.append("")

    return lines


def _render_finding(finding: Finding, paint) -> list[str]:
    lines: list[str] = []
    tag = paint(f"{finding.severity.value:<8}", _SEVERITY_COLOR[finding.severity])
    lines.append(f"    {tag} {finding.subject}")
    lines.append(paint(f"             {finding.rule}", _DIM))
    for line in _wrap(finding.message, 62):
        lines.append(f"             {line}")
    if finding.action:
        for i, line in enumerate(_wrap(finding.action, 58)):
            prefix = "          →  " if i == 0 else "             "
            lines.append(f"{prefix}{line}")
    lines.append("")
    return lines


def _render_calibration(calibration: Calibration, paint) -> list[str]:
    lines = [paint("  WHAT IT WILL ACTUALLY TAKE", _BOLD), ""]

    lines.append(
        f"    correction  {calibration.low_multiplier:.1f}×–"
        f"{calibration.high_multiplier:.1f}×"
        + (f"  ({calibration.driver.value})" if calibration.driver else "")
    )
    for line in _wrap(calibration.reason, 62):
        lines.append(paint(f"                {line}", _DIM))
    lines.append("")

    if calibration.months_low is not None:
        lines.append(
            f"    schedule    {calibration.months_low:.1f}–"
            f"{calibration.months_high:.1f} months"
        )
    if calibration.cost_adjusted is not None:
        lines.append(f"    cost        {calibration.cost_adjusted:,.0f}")
    if calibration.months_low is None and calibration.cost_adjusted is None:
        lines.append(paint("    No estimate given, so nothing to correct.", _DIM))
    lines.append("")

    return lines


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
