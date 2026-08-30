"""Correcting the estimate for the method's own documented bias.

Independent trackers put the timeline overshoot at roughly 2× to 5×. Applying
a flat multiplier would be easy and slightly wrong, because the overshoot is
not uniform: the technical problem usually does get solved. What slips is the
distance between a working solution and deployment at scale, at cost, under a
regulator.

So the correction is scaled by the kind of work, not just its size.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Decision, Phase

#: Low and high multipliers per phase, bounded by the 2×–5× overall finding.
PHASE_MULTIPLIERS: dict[Phase, tuple[float, float]] = {
    Phase.PROTOTYPE: (1.2, 2.0),
    Phase.PRODUCTION: (2.0, 3.0),
    Phase.REGULATED: (3.0, 5.0),
}

PHASE_REASONS: dict[Phase, str] = {
    Phase.PROTOTYPE: "showing it can work at all is the part this method is good at",
    Phase.PRODUCTION: "making it repeatedly, at cost, is where schedules start to slip",
    Phase.REGULATED: "a regulator who has to agree is not an engineering problem",
}

#: Used when no phase is declared, so the tool still says something honest.
DEFAULT_MULTIPLIER = (2.0, 3.0)

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

    def to_dict(self) -> dict:
        return {
            "low_multiplier": self.low_multiplier,
            "high_multiplier": self.high_multiplier,
            "driver": self.driver.value if self.driver else None,
            "reason": self.reason,
            "months_low": self.months_low,
            "months_high": self.months_high,
            "cost_adjusted": self.cost_adjusted,
        }


def calibrate(decision: Decision) -> Calibration:
    """Widen an estimate by the correction its phases earn."""
    driver = _dominant_phase(decision.phases)

    if driver is None:
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

    if decision.estimate.cost is not None:
        calibration.cost_adjusted = decision.estimate.cost * COST_MULTIPLIER

    return calibration


def _dominant_phase(phases: list[Phase]) -> Phase | None:
    """The hardest phase sets the correction.

    Work that is part prototype and part regulated deployment does not average
    out. It finishes when the regulated part finishes.
    """
    if not phases:
        return None
    return max(phases, key=lambda p: PHASE_MULTIPLIERS[p][1])
