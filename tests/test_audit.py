"""The four rules, and the parsing they rest on."""

from __future__ import annotations

import pytest

from firstprinciples.audit import (
    IDIOT_INDEX_TARGET,
    REINSTATEMENT_FLOOR,
    Severity,
    amount,
    audit,
)
from firstprinciples.calibrate import COST_MULTIPLIER, calibrate
from firstprinciples.model import (
    Authority,
    Component,
    Decision,
    Estimate,
    Grounding,
    Phase,
    Requirement,
    SpecError,
    Step,
)


def rules(result) -> set[str]:
    return {f.rule for f in result.findings}


def find(result, rule: str):
    matches = [f for f in result.findings if f.rule == rule]
    assert matches, f"expected a {rule} finding, got {sorted(rules(result))}"
    return matches[0]


# --- rule 2: requirements belong to named people -------------------------


@pytest.mark.parametrize(
    "owner",
    [None, "", "legal department", "The Legal Department", "safety", "TBD", "unknown"],
)
def test_a_requirement_without_a_person_is_a_blocker(owner):
    decision = Decision(
        title="d", requirements=[Requirement(text="Must be reviewed", owner=owner)]
    )
    finding = find(audit(decision), "requirement-owner")
    assert finding.severity is Severity.BLOCKER


def test_a_named_person_satisfies_the_owner_rule():
    decision = Decision(
        title="d",
        requirements=[
            Requirement(
                text="Must be reviewed",
                owner="Dana Whitfield",
                grounded_in=Grounding.CONTRACT,
            )
        ],
    )
    assert "requirement-owner" not in rules(audit(decision))


def test_seniority_raises_severity_rather_than_settling_the_question():
    # The inversion that makes this rule worth implementing: normal practice
    # treats a senior source as more settled, this treats it as less.
    decision = Decision(
        title="d",
        requirements=[
            Requirement(
                text="Must ship with the dashboard",
                owner="Priya Raman",
                authority=Authority.HIGH,
                grounded_in=Grounding.CONTRACT,
                questioned=False,
            )
        ],
    )
    finding = find(audit(decision), "unquestioned-authority")
    assert finding.severity is Severity.HIGH
    assert "Priya Raman" in finding.action


def test_questioning_a_senior_requirement_clears_it():
    decision = Decision(
        title="d",
        requirements=[
            Requirement(
                text="Must ship with the dashboard",
                owner="Priya Raman",
                authority=Authority.HIGH,
                grounded_in=Grounding.CONTRACT,
                questioned=True,
            )
        ],
    )
    assert "unquestioned-authority" not in rules(audit(decision))


@pytest.mark.parametrize(
    "grounding, flagged",
    [
        (Grounding.PHYSICS, False),
        (Grounding.CONTRACT, False),
        (Grounding.REGULATION, False),
        (Grounding.ASSUMPTION, True),
        (Grounding.UNKNOWN, True),
    ],
)
def test_only_ungrounded_requirements_are_delete_candidates(grounding, flagged):
    decision = Decision(
        title="d",
        requirements=[Requirement(text="r", owner="Sam Ito", grounded_in=grounding)],
    )
    assert ("ungrounded-requirement" in rules(audit(decision))) is flagged


# --- rule 3: delete before you simplify, simplify before you automate ----


def test_automating_a_step_never_considered_for_deletion_is_a_blocker():
    decision = Decision(title="d", steps=[Step(name="Compile metrics", automated=True)])
    finding = find(audit(decision), "automated-too-early")
    assert finding.severity is Severity.BLOCKER


def test_optimising_before_considering_deletion_is_flagged_more_softly():
    decision = Decision(title="d", steps=[Step(name="Chase stragglers", optimised=True)])
    assert find(audit(decision), "optimised-too-early").severity is Severity.MEDIUM


def test_automating_something_that_survived_deletion_is_fine():
    decision = Decision(
        title="d",
        steps=[Step(name="Run tests", automated=True, considered_for_deletion=True)],
    )
    assert "automated-too-early" not in rules(audit(decision))


def test_deleting_a_step_counts_as_having_considered_it():
    # Otherwise the strongest possible consideration would fail the check.
    step = Step(name="x", deleted=True)
    assert step.considered_for_deletion


def test_deleting_nothing_at_all_is_flagged():
    decision = Decision(title="d", steps=[Step(name="a"), Step(name="b")])
    assert find(audit(decision), "no-deletion").severity is Severity.HIGH


def test_a_decision_with_no_steps_is_not_nagged_about_deletion():
    assert "no-deletion" not in rules(audit(Decision(title="d")))


def test_cutting_only_the_safe_things_trips_the_ten_percent_floor():
    steps = [Step(name=f"s{i}", deleted=True) for i in range(10)]
    result = audit(Decision(title="d", steps=steps))
    assert result.reinstatement_ratio == 0.0
    assert "under-deletion" in rules(result)


def test_putting_one_in_ten_back_clears_the_floor():
    steps = [Step(name=f"s{i}", deleted=True) for i in range(10)]
    steps[0].reinstated = True
    result = audit(Decision(title="d", steps=steps))
    assert result.reinstatement_ratio == pytest.approx(REINSTATEMENT_FLOOR)
    assert "under-deletion" not in rules(result)


# --- rule 4: the idiot index ---------------------------------------------


def test_a_modest_ratio_is_not_flagged():
    decision = Decision(
        title="d", components=[Component(name="c", finished_cost=20, material_cost=10)]
    )
    assert "idiot-index" not in rules(audit(decision))


def test_the_door_latch_case():
    # $1,500 for a part a $30 one replaced: an index of 50.
    decision = Decision(
        title="d",
        components=[Component(name="latch", finished_cost=1500, material_cost=30)],
    )
    finding = find(audit(decision), "idiot-index")
    assert finding.severity is Severity.HIGH
    assert "50.0×" in finding.message


def test_recoverable_is_summed_across_quantity():
    decision = Decision(
        title="d",
        components=[
            Component(name="latch", finished_cost=1500, material_cost=30, quantity=10)
        ],
    )
    result = audit(decision)
    expected = (1500 - 30 * IDIOT_INDEX_TARGET) * 10
    assert result.recoverable == pytest.approx(expected)


def test_the_ratio_works_on_hours_not_just_money():
    decision = Decision(
        title="d",
        unit="hours",
        components=[Component(name="weekly report", finished_cost=6, material_cost=0.5)],
    )
    finding = find(audit(decision), "idiot-index")
    assert "12.0×" in finding.message
    assert "hours" in finding.message


def test_zero_irreducible_cost_yields_no_ratio():
    decision = Decision(
        title="d", components=[Component(name="c", finished_cost=10, material_cost=0)]
    )
    assert find(audit(decision), "idiot-index").severity is Severity.LOW


def test_amount_carries_the_unit_when_there_is_one():
    assert amount(216, "hours") == "216 hours"
    assert amount(216) == "216"


# --- calibration ----------------------------------------------------------


@pytest.mark.parametrize(
    "phases, low, high",
    [
        ([Phase.PROTOTYPE], 1.2, 2.0),
        ([Phase.PRODUCTION], 2.0, 3.0),
        ([Phase.REGULATED], 3.0, 5.0),
        ([Phase.SAFETY_CRITICAL], 5.0, 10.0),
        # The hardest phase sets the correction; work does not finish when
        # its easiest part finishes.
        ([Phase.PROTOTYPE, Phase.REGULATED], 3.0, 5.0),
        ([Phase.PROTOTYPE, Phase.PRODUCTION], 2.0, 3.0),
        ([Phase.REGULATED, Phase.SAFETY_CRITICAL], 5.0, 10.0),
    ],
)
def test_the_hardest_declared_phase_sets_the_correction(phases, low, high):
    calibration = calibrate(Decision(title="d", phases=phases))
    assert (calibration.low_multiplier, calibration.high_multiplier) == (low, high)


def test_ordinary_work_stays_inside_the_documented_two_to_five_range():
    for phase in (Phase.PROTOTYPE, Phase.PRODUCTION, Phase.REGULATED):
        calibration = calibrate(Decision(title="d", phases=[phase]))
        assert calibration.high_multiplier <= 5.0
        assert calibration.low_multiplier >= 1.2


def test_safety_critical_work_is_the_one_band_that_exceeds_the_record():
    # Justified by Waymo: 12 months planned to remove the safety driver at
    # public scale, about 84 months actual. Nothing else in the record needs
    # a band this wide.
    calibration = calibrate(Decision(title="d", phases=[Phase.SAFETY_CRITICAL]))
    assert calibration.high_multiplier == 10.0
    assert "sampled" in calibration.reason


def test_the_wide_band_would_have_been_wrong_for_a_submission_review():
    """Neuralink falsified the band as first written, and this pins the result.

    18 months planned to a first human implant, 55 months actual — about 3x.
    Calling that safety-critical returns 90-180 months, seven to fifteen years
    for something that took four and a half. The band now applies only where
    evidence accumulates across a fleet over time; a regulator reviewing one
    submission is regulated work.
    """
    planned, actual = 18, 55

    as_regulated = calibrate(
        Decision(title="d", phases=[Phase.REGULATED], estimate=Estimate(months=planned))
    )
    assert as_regulated.months_low <= actual <= as_regulated.months_high

    as_safety_critical = calibrate(
        Decision(
            title="d",
            phases=[Phase.SAFETY_CRITICAL],
            estimate=Estimate(months=planned),
        )
    )
    assert actual < as_safety_critical.months_low, "the wide band overshoots it"


def test_the_wide_band_is_right_where_evidence_accumulates_over_a_fleet():
    # Waymo, the only independent support the narrowed band has.
    planned, actual = 12, 84
    calibration = calibrate(
        Decision(
            title="d",
            phases=[Phase.SAFETY_CRITICAL],
            estimate=Estimate(months=planned),
        )
    )
    assert calibration.months_low <= actual <= calibration.months_high

    narrower = calibrate(
        Decision(title="d", phases=[Phase.REGULATED], estimate=Estimate(months=planned))
    )
    assert actual > narrower.months_high, "the regulated band is too tight here"


def test_an_estimate_is_widened_not_replaced():
    decision = Decision(
        title="d", phases=[Phase.PRODUCTION], estimate=Estimate(months=4, cost=100_000)
    )
    calibration = calibrate(decision)
    assert calibration.months_low == pytest.approx(8.0)
    assert calibration.months_high == pytest.approx(12.0)
    assert calibration.cost_adjusted == pytest.approx(100_000 * COST_MULTIPLIER)


def test_no_phase_still_gives_an_honest_default():
    calibration = calibrate(Decision(title="d", estimate=Estimate(months=1)))
    assert calibration.driver is None
    assert (calibration.low_multiplier, calibration.high_multiplier) == (2.0, 3.0)
    assert "declare phases" in calibration.reason


# --- quantised schedules -------------------------------------------------
# Found by running the engine forward. Aimed at a late-2026 Mars window, it
# returned March 2027 to May 2028 — a band containing no launch window at all.


def test_a_band_lands_on_a_real_opportunity_not_between_two():
    # Mars windows every 26 months, target at 18. The next one is 18+26=44.
    decision = Decision(
        title="d",
        phases=[Phase.PROTOTYPE],
        estimate=Estimate(months=18),
        window_months=26,
    )
    calibration = calibrate(decision)
    assert calibration.months_low == 44
    assert calibration.months_high == 44
    assert calibration.window_months == 26


def test_a_correction_that_still_fits_keeps_the_original_window():
    # A stopgap's lower bound is 1.0x, so the earliest case still makes the
    # window it aimed at and must not be pushed to the next one.
    decision = Decision(
        title="d",
        estimate=Estimate(months=30),
        window_months=26,
        stopgap=True,
    )
    calibration = calibrate(decision)
    assert calibration.months_low == 30


def test_any_real_slip_costs_you_the_whole_window():
    """The stark implication, worth pinning: near-misses do not exist here.

    Every band except a stopgap's lower bound starts above the target, so the
    original window is always missed, and missing it by a week costs the same
    as missing it by a year.
    """
    decision = Decision(
        title="d",
        phases=[Phase.PROTOTYPE],
        estimate=Estimate(months=30),
        window_months=26,
    )
    calibration = calibrate(decision)
    assert calibration.months_low == 56, "1.2x of 30 is 36, which misses 30"


def test_missing_several_windows_snaps_to_the_right_one():
    # 3x of 12 is 36; with windows at 12, 24, 36 the band lands on 36.
    decision = Decision(
        title="d",
        phases=[Phase.PRODUCTION],
        estimate=Estimate(months=12),
        window_months=12,
    )
    calibration = calibrate(decision)
    assert calibration.months_low == 24
    assert calibration.months_high == 36


def test_the_reason_says_the_band_was_moved():
    reason = calibrate(
        Decision(
            title="d",
            phases=[Phase.PROTOTYPE],
            estimate=Estimate(months=18),
            window_months=26,
        )
    ).reason
    assert "every 26 months" in reason


@pytest.mark.parametrize("spacing", [None, 0])
def test_continuous_schedules_are_left_alone(spacing):
    decision = Decision(
        title="d",
        phases=[Phase.PROTOTYPE],
        estimate=Estimate(months=18),
        window_months=spacing,
    )
    calibration = calibrate(decision)
    assert calibration.months_low == pytest.approx(21.6)
    assert calibration.window_months is None


def test_no_estimate_means_nothing_to_correct():
    calibration = calibrate(Decision(title="d", phases=[Phase.PRODUCTION]))
    assert calibration.months_low is None
    assert calibration.cost_adjusted is None


# --- parsing --------------------------------------------------------------


def test_a_decision_needs_a_title():
    with pytest.raises(SpecError, match="missing"):
        Decision.from_dict({})


@pytest.mark.parametrize(
    "raw, message",
    [
        ({"decision": "d", "phases": ["launch"]}, "not one of"),
        ({"decision": "d", "estimate": {"months": "soon"}}, "must be a number"),
        ({"decision": "d", "estimate": {"months": -1}}, "must not be negative"),
        ({"decision": "d", "requirements": [{}]}, 'needs "text"'),
        ({"decision": "d", "components": [{"name": "c"}]}, "needs both"),
        ({"decision": "d", "steps": ["not an object"]}, "must be an object"),
    ],
)
def test_bad_input_is_rejected_with_a_message_that_says_where(raw, message):
    with pytest.raises(SpecError, match=message):
        Decision.from_dict(raw)


def test_american_spelling_of_optimised_is_accepted():
    decision = Decision.from_dict(
        {"decision": "d", "steps": [{"name": "s", "optimized": True}]}
    )
    assert decision.steps[0].optimised
