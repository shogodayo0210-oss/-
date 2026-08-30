"""Correcting the estimate for the method's own documented bias.

Independent trackers put the timeline overshoot at roughly 2× to 5×. Applying
a flat multiplier would be easy and slightly wrong, because the overshoot is
not uniform: the technical problem usually does get solved. What slips is the
distance between a working solution and deployment at scale, at cost, under a
regulator.

So the correction is scaled by the kind of work, not just its size.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import Decision, Phase

#: Low and high multipliers per phase. The first three sit inside the
#: documented 2-5x overall finding; safety-critical work exceeds it, and the
#: robotaxi record is why.
PHASE_MULTIPLIERS: dict[Phase, tuple[float, float]] = {
    Phase.PROTOTYPE: (1.2, 2.0),
    Phase.PRODUCTION: (2.0, 3.0),
    Phase.REGULATED: (3.0, 5.0),
    Phase.SAFETY_CRITICAL: (5.0, 10.0),
}

PHASE_REASONS: dict[Phase, str] = {
    Phase.PROTOTYPE: "showing it can work at all is the part this method is good at",
    Phase.PRODUCTION: "making it repeatedly, at cost, is where schedules start to slip",
    Phase.REGULATED: "a regulator who has to agree is not an engineering problem",
    Phase.SAFETY_CRITICAL: (
        "the evidence has to be accumulated across a fleet over time, so the "
        "schedule is set by how fast reality can be sampled rather than by how "
        "fast anyone works — if a regulator is merely reviewing a submission, "
        "that is the regulated band and this one overshoots it"
    ),
}

#: Used when no phase is declared, so the tool still says something honest.
DEFAULT_MULTIPLIER = (2.0, 3.0)

#: A deliberate stopgap barely slips at all, and the reason is the mechanism
#: rather than optimism. The documented 2-5x comes from scale, cost and
#: regulation; something temporary, torn down afterwards and not required to
#: be cheap sidesteps all three. Backtesting forced this in: Tesla's GA4 tent
#: went up in about three weeks against a three-week plan, and a flat 2-3x
#: correction called that success late by a month.
STOPGAP_MULTIPLIER = (1.0, 1.3)

#: The commonly cited cost companion to the 2–3× schedule rule.
COST_MULTIPLIER = 1.5


@dataclass
class Calibration:
    low_multiplier: float
    high_multiplier: float
    driver: Phase | None
    reason: str
    months_low: float | None = None
    months_high: float | None = None
    cost_adjusted: float | None = None
    #: Set when the band was moved onto a real opportunity rather than left
    #: sitting between two.
    window_months: float | None = None

    def to_dict(self) -> dict:
        return {
            "low_multiplier": self.low_multiplier,
            "high_multiplier": self.high_multiplier,
            "driver": self.driver.value if self.driver else None,
            "reason": self.reason,
            "months_low": self.months_low,
            "months_high": self.months_high,
            "cost_adjusted": self.cost_adjusted,
            "window_months": self.window_months,
        }


def calibrate(decision: Decision) -> Calibration:
    """Widen an estimate by the correction its phases earn."""
    driver = _dominant_phase(decision.phases)

    if decision.stopgap:
        low, high = STOPGAP_MULTIPLIER
        reason = (
            "declared a stopgap, so the correction barely applies: the "
            "documented overshoot lives in scale, cost and regulation, and a "
            "temporary thing you intend to tear down meets none of them"
        )
    elif driver is None:
        low, high = DEFAULT_MULTIPLIER
        reason = (
            "no phase declared, so the general 2–3× correction applies; "
            "declare phases for a tighter answer"
        )
    else:
        low, high = PHASE_MULTIPLIERS[driver]
        reason = PHASE_REASONS[driver]

    calibration = Calibration(
        low_multiplier=low, high_multiplier=high, driver=driver, reason=reason
    )

    if decision.estimate.months is not None:
        calibration.months_low = decision.estimate.months * low
        calibration.months_high = decision.estimate.months * high
        _snap_to_window(calibration, decision)

    if decision.estimate.cost is not None:
        calibration.cost_adjusted = decision.estimate.cost * COST_MULTIPLIER

    return calibration


def _snap_to_window(calibration: "Calibration", decision: Decision) -> None:
    """Move a corrected band onto the next real opportunity.

    Some schedules are not continuous. A Mars transfer window opens roughly
    every 26 months; miss it and the next chance is two years later, not two
    months. Running the engine forward exposed this: it corrected an uncrewed
    Mars launch aimed at late 2026 into a band running March 2027 to May 2028,
    which contains no launch window at all. That is not a pessimistic
    prediction, it is an impossible one.

    Windows are assumed to fall on the original target and every
    `window_months` after it.
    """
    spacing = decision.window_months
    target = decision.estimate.months
    if not spacing or spacing <= 0 or target is None:
        return

    def next_window(months: float) -> float:
        if months <= target:
            return target
        missed = math.ceil((months - target) / spacing)
        return target + missed * spacing

    calibration.months_low = next_window(calibration.months_low)
    calibration.months_high = next_window(calibration.months_high)
    calibration.window_months = spacing
    calibration.reason += (
        f"; and chances come only every {spacing:g} months, so the band is "
        "moved onto the next one rather than landing between two"
    )


def _dominant_phase(phases: list[Phase]) -> Phase | None:
    """The hardest phase sets the correction.

    Work that is part prototype and part regulated deployment does not average
    out. It finishes when the regulated part finishes.
    """
    if not phases:
        return None
    return max(phases, key=lambda p: PHASE_MULTIPLIERS[p][1])
