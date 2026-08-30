"""The rules that backtesting forced in.

Every rule here exists because the engine got a real decision wrong. The
docstrings name which one, because a rule whose origin is forgotten is a rule
nobody can argue with later.
"""

from __future__ import annotations

import pytest

from firstprinciples.audit import (
    HYGIENE_RULES,
    SURVIVAL_RUNWAY_MONTHS,
    Mode,
    Severity,
    audit,
)
from firstprinciples.calibrate import STOPGAP_MULTIPLIER, calibrate
from firstprinciples.model import (
    Authority,
    Component,
    Decision,
    Estimate,
    Grounding,
    Phase,
    Requirement,
    Step,
)


def rules(result) -> set[str]:
    return {f.rule for f in result.findings}


def find(result, rule: str):
    matches = [f for f in result.findings if f.rule == rule]
    assert matches, f"expected {rule}, got {sorted(rules(result))}"
    return matches[0]


def unquestioned_senior(text: str = "Ship it my way") -> Requirement:
    return Requirement(
        text=text,
        owner="Elon Musk",
        authority=Authority.HIGH,
        grounded_in=Grounding.CONTRACT,
        questioned=False,
    )


# --- survival mode -------------------------------------------------------
# From Tesla, December 2008: three days from bankruptcy. The engine's only
# finding was that the reinstatement ratio was low.


@pytest.mark.parametrize(
    "runway, expected",
    [
        (None, Mode.NORMAL),
        (0.1, Mode.SURVIVAL),
        (SURVIVAL_RUNWAY_MONTHS, Mode.SURVIVAL),
        (SURVIVAL_RUNWAY_MONTHS + 0.01, Mode.NORMAL),
        (18, Mode.NORMAL),
    ],
)
def test_runway_decides_the_mode(runway, expected):
    assert audit(Decision(title="d", runway_months=runway)).mode is expected


def test_short_runway_leads_the_report_and_blocks():
    result = audit(Decision(title="d", runway_months=0.1))
    assert result.findings[0].rule == "no-runway"
    assert result.findings[0].severity is Severity.BLOCKER


def test_process_hygiene_is_dropped_when_the_thing_may_not_survive():
    # Ten deleted steps, none put back: normally an under-deletion finding.
    steps = [Step(name=f"s{i}", deleted=True) for i in range(10)]

    normal = audit(Decision(title="d", steps=steps))
    assert "under-deletion" in rules(normal)

    dying = audit(Decision(title="d", steps=steps, runway_months=0.1))
    assert "under-deletion" not in rules(dying)
    assert "under-deletion" in dying.suppressed


def test_every_suppressed_rule_is_hygiene_and_is_reported_as_suppressed():
    steps = [Step(name="a"), Step(name="b", optimised=True)]
    result = audit(Decision(title="d", steps=steps, runway_months=1))
    assert set(result.suppressed) <= HYGIENE_RULES
    assert result.suppressed, "suppression must be visible, not silent"


def test_overpaying_for_speed_is_softened_not_dropped():
    # Tesla's GA4 tent had a terrible cost ratio and was the right call.
    component = Component(name="tent line", finished_cost=6_000_000, material_cost=200_000)

    normal = audit(Decision(title="d", components=[component]))
    assert find(normal, "idiot-index").severity is Severity.HIGH

    dying = audit(Decision(title="d", components=[component], runway_months=1))
    softened = find(dying, "idiot-index")
    assert softened.severity is Severity.MEDIUM
    assert "runway is short" in softened.message


@pytest.mark.parametrize(
    "rule, decision",
    [
        ("requirement-owner", Decision(title="d", runway_months=0.1, requirements=[Requirement(text="r")])),
        ("unquestioned-authority", Decision(title="d", runway_months=0.1, requirements=[unquestioned_senior()])),
        ("automated-too-early", Decision(title="d", runway_months=0.1, steps=[Step(name="s", automated=True)])),
    ],
)
def test_what_can_still_kill_you_survives_survival_mode(rule, decision):
    assert rule in rules(audit(decision))


# --- irreversibility -----------------------------------------------------
# From the 2018 "funding secured" tweet. The engine caught the unchallenged
# senior requirement but rated a tweet the same as a decision you could walk
# back on Monday.


def test_irreversible_plus_unquestioned_authority_is_a_blocker():
    decision = Decision(
        title="d",
        requirements=[unquestioned_senior()],
        steps=[Step(name="Post the announcement", reversible=False)],
    )
    finding = find(audit(decision), "irreversible-unquestioned")
    assert finding.severity is Severity.BLOCKER
    assert "Elon Musk" in finding.message


def test_questioning_the_requirement_clears_the_irreversible_step():
    requirement = unquestioned_senior()
    requirement.questioned = True
    decision = Decision(
        title="d",
        requirements=[requirement],
        steps=[Step(name="Post the announcement", reversible=False)],
    )
    assert "irreversible-unquestioned" not in rules(audit(decision))


def test_a_reversible_step_is_not_flagged_however_senior_the_requirement():
    decision = Decision(
        title="d",
        requirements=[unquestioned_senior()],
        steps=[Step(name="Try it on staging", reversible=True)],
    )
    assert "irreversible-unquestioned" not in rules(audit(decision))


def test_a_deleted_irreversible_step_is_not_flagged():
    # It is not going to happen, so there is nothing to warn about.
    decision = Decision(
        title="d",
        requirements=[unquestioned_senior()],
        steps=[Step(name="Sign it", reversible=False, deleted=True)],
    )
    assert "irreversible-unquestioned" not in rules(audit(decision))


def test_steps_are_reversible_unless_stated():
    assert Step(name="s").reversible


# --- ruin ----------------------------------------------------------------


def test_ruin_risk_is_surfaced_and_explicitly_not_resolved():
    finding = find(audit(Decision(title="d", ruin_risk=True)), "ruin-risk")
    assert finding.severity is Severity.HIGH
    assert "Decide this yourself" in finding.action


def test_ruin_risk_survives_survival_mode():
    result = audit(Decision(title="d", ruin_risk=True, runway_months=0.1))
    assert "ruin-risk" in rules(result)


# --- trying versus deciding ----------------------------------------------
# From the fourth Falcon 1 launch: another vehicle cost less than the analysis
# that would have replaced it.


def test_when_trying_is_cheaper_than_deciding_it_says_so():
    decision = Decision(
        title="d", unit="USD", attempt_cost=7_000_000, analysis_cost=20_000_000
    )
    finding = find(audit(decision), "cheaper-to-try")
    assert "2.9×" in finding.message
    assert "Run the attempt" in finding.action


def test_no_finding_when_analysis_is_the_cheaper_route():
    decision = Decision(title="d", attempt_cost=20_000_000, analysis_cost=7_000_000)
    assert "cheaper-to-try" not in rules(audit(decision))


def test_no_finding_without_both_numbers():
    assert "cheaper-to-try" not in rules(audit(Decision(title="d", attempt_cost=1)))
    assert "cheaper-to-try" not in rules(audit(Decision(title="d", analysis_cost=1)))


def test_under_ruin_risk_it_argues_for_sooner_not_regardless():
    # The rule must not read as permission to bet the company on a hunch.
    decision = Decision(
        title="d", attempt_cost=1, analysis_cost=10, ruin_risk=True
    )
    action = find(audit(decision), "cheaper-to-try").action
    assert "survive" in action
    assert "regardless" in action


# --- stopgap calibration -------------------------------------------------
# From the GA4 tent: three weeks planned, three weeks delivered, and a flat
# 2-3x correction called it a month late.


def test_a_stopgap_is_barely_corrected():
    decision = Decision(
        title="d",
        phases=[Phase.PRODUCTION],
        estimate=Estimate(months=0.75),
        stopgap=True,
    )
    calibration = calibrate(decision)
    assert (calibration.low_multiplier, calibration.high_multiplier) == STOPGAP_MULTIPLIER
    assert calibration.months_high < 1.0, "three weeks planned must not read as two months"


def test_the_same_work_as_a_permanent_build_is_corrected_normally():
    permanent = calibrate(
        Decision(title="d", phases=[Phase.PRODUCTION], estimate=Estimate(months=0.75))
    )
    assert permanent.high_multiplier == 3.0


def test_the_stopgap_reason_names_the_mechanism_not_the_optimism():
    reason = calibrate(Decision(title="d", stopgap=True)).reason
    assert "scale, cost and regulation" in reason


# --- who decides versus who pays -----------------------------------------
# From 2025. Every earlier mistake in the record put the cost where the
# decision was made. A personal, political decision whose bill arrived at
# Tesla's shareholders and customers did not.


def test_a_bill_that_lands_somewhere_else_is_a_blocker():
    decision = Decision(
        title="d",
        decided_by="Elon Musk, personally",
        cost_borne_by="Tesla shareholders and customers",
    )
    finding = find(audit(decision), "cost-lands-elsewhere")
    assert finding.severity is Severity.BLOCKER
    assert "Tesla shareholders and customers" in finding.action


def test_it_leads_the_report_because_no_one_is_positioned_to_stop_it():
    decision = Decision(
        title="d",
        decided_by="A",
        cost_borne_by="B",
        steps=[Step(name="s", automated=True)],
    )
    assert audit(decision).sorted_findings()[0].rule == "cost-lands-elsewhere"


@pytest.mark.parametrize(
    "decided_by, cost_borne_by",
    [
        ("Tesla", "Tesla"),
        ("Tesla", "  tesla  "),
        (None, "Tesla"),
        ("Tesla", None),
        (None, None),
    ],
)
def test_no_finding_when_the_decider_pays_or_it_was_not_stated(
    decided_by, cost_borne_by
):
    decision = Decision(
        title="d", decided_by=decided_by, cost_borne_by=cost_borne_by
    )
    assert "cost-lands-elsewhere" not in rules(audit(decision))


def test_it_is_about_a_missing_veto_not_about_bad_judgement():
    # The wording matters: nothing in the reasoning has to be wrong for this
    # to go badly, which is what makes it a different kind of finding.
    decision = Decision(title="d", decided_by="A", cost_borne_by="B")
    message = find(audit(decision), "cost-lands-elsewhere").message
    assert "cannot refuse" in message


def test_it_survives_survival_mode():
    decision = Decision(
        title="d", decided_by="A", cost_borne_by="B", runway_months=0.1
    )
    assert "cost-lands-elsewhere" in rules(audit(decision))


# --- the report has to agree with the audit ------------------------------


def rendered(decision: Decision) -> str:
    from firstprinciples.report import render

    return render(decision, audit(decision), calibrate(decision), color=False)


def test_survival_mode_stops_the_report_nagging_about_what_it_suppressed():
    # Printing "reinstatement ratio 0%" after deciding that ratio does not
    # matter right now is the exact mistake suppression exists to avoid.
    steps = [Step(name=f"s{i}", deleted=True) for i in range(10)]

    normal = rendered(Decision(title="d", steps=steps))
    assert "Reinstatement ratio" in normal
    assert "survival mode" not in normal

    dying = rendered(Decision(title="d", steps=steps, runway_months=0.1))
    assert "Reinstatement ratio" not in dying
    assert "survival mode" in dying
    assert "Set aside while the runway is short: under-deletion" in dying


def test_the_runway_blocker_is_the_first_thing_a_reader_sees():
    decision = Decision(
        title="d",
        runway_months=0.1,
        steps=[Step(name="s", automated=True)],
    )
    body = rendered(decision)
    assert body.index("no-runway") < body.index("automated-too-early")
