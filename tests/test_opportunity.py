"""The screen, the gate, and whether it can reject anything."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firstprinciples.model import SpecError
from firstprinciples.opportunity import (
    WEIGHTS,
    Assessment,
    Fit,
    Screen,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def build(**scores) -> Assessment:
    """An assessment with every screen at 2 unless overridden."""
    return Assessment.from_dict(
        {
            "subject": "test",
            "screens": {s.value: scores.get(s.value, 2) for s in Screen},
        }
    )


def test_everything_scoring_full_is_a_strong_fit():
    assessment = build()
    assert assessment.fit is Fit.STRONG
    assert assessment.percentage == pytest.approx(100.0)


def test_a_closed_gate_overrides_everything_else():
    # Five perfect screens and no gap between price and reality still means
    # the method has nothing to attack. This is the whole point of a gate.
    assessment = build(cost_detached=0)
    assert not assessment.gate_passed
    assert assessment.fit is Fit.OFF_PATTERN
    assert assessment.percentage > 50, "still scores well, and is still rejected"


def test_a_partial_gap_opens_the_gate():
    assert build(cost_detached=1).gate_passed


def test_cost_detached_carries_the_most_weight():
    assert WEIGHTS[Screen.COST_DETACHED] == max(WEIGHTS.values())


@pytest.mark.parametrize(
    "scores, expected",
    [
        ({}, Fit.STRONG),
        ({"pulls_help": 0, "reachable_proof": 0}, Fit.STRONG),
        (
            {"absorbable": 0, "soft_barrier": 0, "pulls_help": 0},
            Fit.PARTIAL,
        ),
        (
            {
                "cost_detached": 1,
                "absorbable": 0,
                "soft_barrier": 0,
                "existing_need": 0,
                "pulls_help": 0,
                "reachable_proof": 0,
            },
            Fit.WEAK,
        ),
        ({"cost_detached": 0}, Fit.OFF_PATTERN),
    ],
)
def test_fit_bands(scores, expected):
    assert build(**scores).fit is expected


def test_the_weakest_screens_come_back_worst_first():
    assessment = build(pulls_help=0, absorbable=1)
    weakest = assessment.weakest()
    assert weakest[0].screen is Screen.PULLS_HELP
    assert weakest[1].screen is Screen.ABSORBABLE


def test_a_missing_screen_names_itself_and_asks_the_question():
    partial = {s.value: 2 for s in Screen if s is not Screen.SOFT_BARRIER}
    with pytest.raises(SpecError, match="soft_barrier"):
        Assessment.from_dict({"subject": "x", "screens": partial})


@pytest.mark.parametrize("bad", [3, -1, "yes", None, 1.5, True, [2], {"x": 2}])
def test_scores_outside_zero_to_two_are_rejected(bad):
    # 1.5 and True both survive int() as 1. A score that quietly moves is
    # worse than one that is refused.
    screens = {s.value: 2 for s in Screen}
    screens[Screen.ABSORBABLE.value] = bad
    with pytest.raises(SpecError, match="0, 1 or 2"):
        Assessment.from_dict({"subject": "x", "screens": screens})


def test_evidence_is_optional_and_preserved():
    screens = {s.value: 2 for s in Screen}
    screens[Screen.COST_DETACHED.value] = {"score": 2, "evidence": "the battery case"}
    assessment = Assessment.from_dict({"subject": "x", "screens": screens})
    assert assessment.results[0].evidence == "the battery case"


def test_a_subject_is_required():
    with pytest.raises(SpecError, match="subject"):
        Assessment.from_dict({"screens": {s.value: 2 for s in Screen}})


# --- the screen run against its own source material ----------------------
#
# The screen was assembled from the ventures that worked. If it cannot reject
# one that did not, it is describing nothing. These are the author's readings
# of the public record rather than measurements, so this is a consistency
# check on the shipped files, not independent evidence.


def load(name: str) -> Assessment:
    raw = json.loads((EXAMPLES / name).read_text())
    return Assessment.from_dict(raw["opportunity"])


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("tesla-2004.json", Fit.STRONG),
        ("x-2022.json", Fit.OFF_PATTERN),
        ("dev-tool.json", Fit.STRONG),
        ("weekly-report.json", Fit.STRONG),
    ],
)
def test_shipped_examples_reach_their_stated_verdicts(filename, expected):
    assert load(filename).fit is expected


def test_the_rejection_comes_from_the_gate_not_from_a_low_total():
    # If X were rejected merely by scoring badly, the screen would be a
    # popularity contest. It is rejected because there was no gap to close.
    x = load("x-2022.json")
    assert not x.gate_passed
    assert x.results[0].screen is Screen.COST_DETACHED
    assert x.results[0].score == 0


def test_the_control_scores_far_above_the_counterexample():
    assert load("tesla-2004.json").percentage - load("x-2022.json").percentage > 50


def test_a_non_commercial_subject_scores_on_the_same_scale():
    # "Do not limit this to business" is a claim the examples have to carry:
    # a weekly status report is scored by the identical machinery.
    report = load("weekly-report.json")
    assert report.gate_passed
    assert report.fit is Fit.STRONG
