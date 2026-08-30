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


#: Below this much runway, the protocol's own priorities inconvenient.
#: Backtesting put the number here: Tesla built the GA4 tent with about two
#: months of room, and the 2008 decision was made with three days.
SURVIVAL_RUNWAY_MONTHS = 3.0

#: Process hygiene. Correct in normal times; misdirection when the thing is
#: weeks from ending. Nobody audits a reinstatement ratio with payroll about
#: to bounce, and a report that leads with one is worse than no report.
HYGIENE_RULES = frozenset({"no-deletion", "under-deletion", "optimised-too-early"})


class Mode(str, Enum):
    NORMAL = "NORMAL"
    SURVIVAL = "SURVIVAL"


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
    #: Sorts ahead of severity. Only the runway finding uses it: everything
    #: else in a report is conditional on there being a next quarter, so it
    #: has to lead even among other blockers.
    priority: int = 0

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
    mode: Mode = Mode.NORMAL
    suppressed: list[str] = field(default_factory=list)

    def sorted_findings(self) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (f.priority, f.severity.rank, f.rule, f.subject),
        )

    def worst(self) -> Severity | None:
        if not self.findings:
            return None
        return min((f.severity for f in self.findings), key=lambda s: s.rank)


def audit(decision: Decision) -> AuditResult:
    result = AuditResult(mode=_mode(decision))

    for requirement in decision.requirements:
        result.findings.extend(_check_requirement(requirement))

    result.findings.extend(_check_order(decision.steps))
    result.findings.extend(_check_reversibility(decision))
    result.findings.extend(_check_learning_cost(decision))

    ratio, deletion_findings = _check_deletion(decision.steps)
    result.reinstatement_ratio = ratio
    result.findings.extend(deletion_findings)

    for component in decision.components:
        findings, recoverable = _check_component(component, decision.unit)
        result.findings.extend(findings)
        result.recoverable += recoverable

    if decision.ruin_risk:
        result.findings.append(_ruin_finding())

    if result.mode is Mode.SURVIVAL:
        result.findings, result.suppressed = _apply_survival_mode(
            result.findings, decision
        )

    return result


def _mode(decision: Decision) -> Mode:
    if decision.runway_months is None:
        return Mode.NORMAL
    return (
        Mode.SURVIVAL
        if decision.runway_months <= SURVIVAL_RUNWAY_MONTHS
        else Mode.NORMAL
    )


def _apply_survival_mode(
    findings: list[Finding], decision: Decision
) -> tuple[list[Finding], list[str]]:
    """Re-rank for a decision that may not have a next quarter.

    Two things change. Process-hygiene findings are dropped, because acting on
    them costs time that does not exist. And paying well over the odds stops
    being a defect: a tent built from warehouse scrap in three weeks has a
    terrible cost ratio and was the right call, so the index is reported and
    softened rather than pressed.

    What survives untouched is everything that can still kill you on its own:
    an unowned requirement, an unchallenged senior one, something automated
    before anyone asked whether it should exist, and anything irreversible.
    """
    kept: list[Finding] = []
    suppressed: list[str] = []

    for finding in findings:
        if finding.rule in HYGIENE_RULES:
            suppressed.append(finding.rule)
            continue
        if finding.rule == "idiot-index":
            kept.append(_soften(finding))
            continue
        kept.append(finding)

    runway = decision.runway_months or 0.0
    kept.insert(
        0,
        Finding(
            rule="no-runway",
            severity=Severity.BLOCKER,
            subject=f"{runway:.2g} months of runway",
            message=(
                "There may be no next quarter. Every other finding here is "
                "secondary to staying alive long enough to act on it."
            ),
            action="Fix the runway first. Then re-run this against the plan.",
            priority=-1,
        ),
    )
    return kept, sorted(set(suppressed))


def _soften(finding: Finding) -> Finding:
    """Lower a finding by one rank and say why."""
    order = [
        Severity.BLOCKER,
        Severity.HIGH,
        Severity.MEDIUM,
        Severity.LOW,
        Severity.INFO,
    ]
    lowered = order[min(order.index(finding.severity) + 1, len(order) - 1)]
    return Finding(
        rule=finding.rule,
        severity=lowered,
        subject=finding.subject,
        message=finding.message
        + " Overpaying for speed is not a defect while the runway is short.",
        action=finding.action,
        value=finding.value,
    )


def _ruin_finding() -> Finding:
    return Finding(
        rule="ruin-risk",
        severity=Severity.HIGH,
        subject="failure ends the whole thing",
        message=(
            "This bet cannot be repeated if it loses. The method this tool "
            "implements has a documented history of accepting exactly such "
            "bets and winning them, which is not evidence that taking them is "
            "correct — the losers are not around to be studied."
        ),
        action=(
            "Decide this yourself. No protocol should be allowed to tell you "
            "to risk everything, and this one is not going to."
        ),
    )


def _check_learning_cost(decision: Decision) -> list[Finding]:
    """When trying is cheaper than deciding, deliberation is the expensive path.

    Added after backtesting the fourth Falcon 1 launch. With three failures
    behind it and weeks of runway left, the engine's answer was 'no runway,
    ruin risk, decide it yourself' — true, and useless. The actual reasoning
    was narrower and reusable: another vehicle cost less than the analysis
    that would have replaced it, so the careful option was also the expensive
    one.

    This is the idiot index pointed at learning. It says nothing about whether
    the attempt is survivable, which is a separate question and stays with the
    person.
    """
    attempt, analysis = decision.attempt_cost, decision.analysis_cost
    if attempt is None or analysis is None or attempt >= analysis:
        return []

    ratio = analysis / attempt if attempt > 0 else float("inf")
    action = "Run the attempt. The analysis is the more expensive way to find out."
    if decision.ruin_risk:
        action = (
            "Cheaper only holds if you survive it. Failure here ends everything, "
            "so this argues for trying sooner, not for trying regardless."
        )

    return [
        Finding(
            rule="cheaper-to-try",
            severity=Severity.MEDIUM,
            subject="another attempt vs more analysis",
            message=(
                f"Analysis costs {ratio:.1f}× what one more attempt costs "
                f"({amount(analysis, decision.unit)} against "
                f"{amount(attempt, decision.unit)}). Deliberating is the "
                "expensive option here, and it buys a worse answer than the "
                "attempt would."
            ),
            action=action,
        )
    ]


def _check_reversibility(decision: Decision) -> list[Finding]:
    """Irreversible, and driven by a requirement nobody challenged.

    Added after backtesting the 2018 'funding secured' tweet. The engine
    already caught the unchallenged senior requirement, but rated the decision
    the same as one that could be walked back on Monday — and being unable to
    walk it back is the entire reason that one cost $40M. Irreversibility is
    not a separate concern from unquestioned authority; it is the multiplier
    on it.
    """
    unquestioned = [
        r
        for r in decision.requirements
        if r.authority is Authority.HIGH and not r.questioned
    ]
    if not unquestioned:
        return []

    findings: list[Finding] = []
    for step in decision.steps:
        if step.reversible or step.deleted:
            continue
        names = ", ".join(r.owner for r in unquestioned if r.owner) or "someone senior"
        findings.append(
            Finding(
                rule="irreversible-unquestioned",
                severity=Severity.BLOCKER,
                subject=step.name,
                message=(
                    f"This cannot be undone, and it rests on a requirement from "
                    f"{names} that nobody has challenged. That pairing — no way "
                    "back, no second opinion — is what turns an ordinary "
                    "misjudgement into an expensive one."
                ),
                action=(
                    "Get one person to argue against it before it happens, or "
                    "find a reversible version to do first."
                ),
            )
        )
    return findings


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
