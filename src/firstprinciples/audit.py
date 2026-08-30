"""The four rules, as checks that produce findings.

Each rule is stated in docs/analysis.md with its source. Nothing here is
generative: given the same decision file, the same findings come out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .model import Authority, Component, Decision, Requirement, Step

#: Musk's stated self-check on deletion: if you never put anything back, you
#: did not cut deep enough.
REINSTATEMENT_FLOOR = 0.10

#: Bands for the finished-cost-to-materials ratio. The documented example — a
#: $1,500 door latch replaced by a $30 one — sits at 50.
IDIOT_INDEX_WATCH = 3.0
IDIOT_INDEX_INVESTIGATE = 10.0

#: What a flagged component is assumed to be reducible to, for sizing the
#: prize. Deliberately unambitious; it is a floor on the opportunity.
IDIOT_INDEX_TARGET = 3.0


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    @property
    def rank(self) -> int:
        return _SEVERITY_ORDER[self]


_SEVERITY_ORDER = {
    Severity.BLOCKER: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


@dataclass
class Finding:
    rule: str
    severity: Severity
    subject: str
    message: str
    action: str | None = None
    #: Cash this finding puts on the table, where it can be estimated.
    value: float | None = None

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "subject": self.subject,
            "message": self.message,
            "action": self.action,
            "value": self.value,
        }


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    reinstatement_ratio: float | None = None
    recoverable: float = 0.0

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: (f.severity.rank, f.rule, f.subject))

    def worst(self) -> Severity | None:
        if not self.findings:
            return None
        return min((f.severity for f in self.findings), key=lambda s: s.rank)


def audit(decision: Decision) -> AuditResult:
    result = AuditResult()

    for requirement in decision.requirements:
        result.findings.extend(_check_requirement(requirement))

    result.findings.extend(_check_order(decision.steps))

    ratio, deletion_findings = _check_deletion(decision.steps)
    result.reinstatement_ratio = ratio
    result.findings.extend(deletion_findings)

    for component in decision.components:
        findings, recoverable = _check_component(component, decision.unit)
        result.findings.extend(findings)
        result.recoverable += recoverable

    return result


def _check_requirement(requirement: Requirement) -> list[Finding]:
    """Rule 2: requirements belong to named people, and senior names are worse."""
    findings: list[Finding] = []
    subject = _shorten(requirement.text)

    if not requirement.has_named_owner:
        findings.append(
            Finding(
                rule="requirement-owner",
                severity=Severity.BLOCKER,
                subject=subject,
                message=(
                    f"No person owns this requirement (owner: {requirement.owner or 'none'}). "
                    "A department cannot be asked why."
                ),
                action="Find the individual who asked for it, or drop it.",
            )
        )
    elif requirement.authority is requirement.authority.HIGH and not requirement.questioned:
        # The inversion. Normal practice treats a senior source as settled;
        # here it is the reason to look harder, because nobody else will.
        findings.append(
            Finding(
                rule="unquestioned-authority",
                severity=Severity.HIGH,
                subject=subject,
                message=(
                    f"{requirement.owner} is senior and nobody has questioned this. "
                    "Requirements from smart people survive longest precisely "
                    "because they go unchallenged."
                ),
                action=f"Ask {requirement.owner} directly what breaks without it.",
            )
        )

    if requirement.grounded_in.is_negotiable:
        findings.append(
            Finding(
                rule="ungrounded-requirement",
                severity=Severity.MEDIUM,
                subject=subject,
                message=(
                    f"Grounded in {requirement.grounded_in.value}, not in physics, "
                    "a contract or a regulation. This is a delete candidate."
                ),
                action="Establish what it actually rests on, then keep or delete.",
            )
        )

    return findings


def _check_deletion(steps: list[Step]) -> tuple[float | None, list[Finding]]:
    """Rule 3, step 2: the 10% reinstatement floor."""
    deleted = [s for s in steps if s.deleted]
    if not deleted:
        if steps:
            return None, [
                Finding(
                    rule="no-deletion",
                    severity=Severity.HIGH,
                    subject=f"{len(steps)} steps",
                    message="Nothing has been deleted. Step 2 has not happened.",
                    action="Delete the least defensible step and see what breaks.",
                )
            ]
        return None, []

    reinstated = [s for s in deleted if s.reinstated]
    ratio = len(reinstated) / len(deleted)

    if ratio < REINSTATEMENT_FLOOR:
        return ratio, [
            Finding(
                rule="under-deletion",
                severity=Severity.MEDIUM,
                subject=f"{len(deleted)} deleted, {len(reinstated)} put back",
                message=(
                    f"Reinstatement ratio is {ratio:.0%}, below the {REINSTATEMENT_FLOOR:.0%} "
                    "floor. Cutting only what is obviously safe means you stopped early."
                ),
                action="Delete more, until roughly one in ten has to come back.",
            )
        ]

    return ratio, []


def _check_order(steps: list[Step]) -> list[Finding]:
    """Rule 3, the ordering: automate last, and only what survived deletion.

    This is the expensive mistake. Automating a step that should not exist
    makes the waste permanent and fast, and it is the one the method names
    explicitly.
    """
    findings: list[Finding] = []
    for step in steps:
        if step.automated and not step.considered_for_deletion:
            findings.append(
                Finding(
                    rule="automated-too-early",
                    severity=Severity.BLOCKER,
                    subject=step.name,
                    message=(
                        "Automated without ever being considered for deletion. "
                        "Automating a step that should not exist makes the waste "
                        "permanent and fast."
                    ),
                    action="Try deleting it. Automate only what survives.",
                )
            )
        elif step.optimised and not step.considered_for_deletion:
            findings.append(
                Finding(
                    rule="optimised-too-early",
                    severity=Severity.MEDIUM,
                    subject=step.name,
                    message=(
                        "Optimised without being considered for deletion. "
                        "The best version of an unnecessary step is no step."
                    ),
                    action="Ask what happens if it simply does not run.",
                )
            )
    return findings


def _check_component(component: Component, unit: str = "") -> tuple[list[Finding], float]:
    """Rule 4: the idiot index.

    Nothing here is specific to money. The ratio asks what you pay for a
    finished thing against what it irreducibly contains, and hours spent on a
    process against the hours the process actually requires is the same
    question in a different unit.
    """
    index = component.idiot_index
    if index is None:
        return [
            Finding(
                rule="idiot-index",
                severity=Severity.LOW,
                subject=component.name,
                message="Irreducible cost is zero, so no ratio can be computed.",
                action="Put a number on what it irreducibly requires, even roughly.",
            )
        ], 0.0

    if index < IDIOT_INDEX_WATCH:
        return [], 0.0

    severity = (
        Severity.HIGH if index >= IDIOT_INDEX_INVESTIGATE else Severity.MEDIUM
    )
    target_cost = component.material_cost * IDIOT_INDEX_TARGET
    recoverable = max(0.0, (component.finished_cost - target_cost) * component.quantity)

    return [
        Finding(
            rule="idiot-index",
            severity=severity,
            subject=component.name,
            message=(
                f"Index {index:.1f}× — {amount(component.finished_cost, unit)} spent "
                f"on {amount(component.material_cost, unit)} of irreducible content. "
                "You are paying for process, not for substance."
            ),
            action=(
                f"At {IDIOT_INDEX_TARGET:.0f}× this would be "
                f"{amount(target_cost, unit)}"
                + (
                    f" each, {amount(recoverable, unit)} across {component.quantity}."
                    if component.quantity > 1
                    else "."
                )
            ),
            value=recoverable,
        )
    ], recoverable


def _shorten(text: str, width: int = 56) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def amount(value: float, unit: str = "") -> str:
    """Format a quantity in whatever the decision is counted in."""
    rendered = f"{value:,.0f}" if value >= 10 else f"{value:,.2f}"
    return f"{rendered} {unit}".strip() if unit else rendered
