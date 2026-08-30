"""Where to point effort at all.

The rules in audit.py say how to run a thing. They say nothing about what to
run, and that choice is the larger part of the result.

The venture history has a shape, and the shape generalises past business.
Zip2 took newspaper listings, X.com took bank transfers, SpaceX took orbital
launch, Tesla took cars. None were new markets. Every one was a large existing
need whose price had drifted away from what materials and physics require,
defended by incumbents whose barrier was capital or habit rather than a
technical impossibility.

Strip the commercial vocabulary out and the same six questions apply to a
research direction, an open-source project, a career move, or a process inside
one team. "Price" becomes whatever it currently costs — money, hours,
attention. "Incumbent" becomes whatever currently occupies the ground.

The screen is descriptive, not prescriptive. It describes the shape of the
wins. Running it against the losses is how you find out it means something —
see examples/portfolio.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .model import SpecError


class Screen(str, Enum):
    """The six conditions the successful bets share."""

    COST_DETACHED = "cost_detached"
    ABSORBABLE = "absorbable"
    SOFT_BARRIER = "soft_barrier"
    EXISTING_NEED = "existing_need"
    PULLS_HELP = "pulls_help"
    REACHABLE_PROOF = "reachable_proof"


QUESTIONS: dict[Screen, str] = {
    Screen.COST_DETACHED: (
        "Is what this currently costs — in money, hours or attention — set by "
        "habit rather than by a real limit?"
    ),
    Screen.ABSORBABLE: "Is the expensive part something you could take on directly?",
    Screen.SOFT_BARRIER: (
        "Is the barrier that keeps others out capital, regulation or convention "
        "rather than a hard technical wall?"
    ),
    Screen.EXISTING_NEED: "Does the need already exist, so you never have to manufacture it?",
    Screen.PULLS_HELP: "Would the honest framing of this pull in people or attention you could not otherwise get?",
    Screen.REACHABLE_PROOF: "Can you reach a convincing proof point with what you already control?",
}

WHY: dict[Screen, str] = {
    Screen.COST_DETACHED: (
        "The load-bearing one. Battery packs 'cost $600/kWh and always will' "
        "until someone priced the constituent metals at about $80. Without that "
        "gap between what a thing costs and what it must cost, there is nothing "
        "for the method to attack. The gap need not be money: a reviewer reading "
        "thirty reports to find one real bug is the same shape."
    ),
    Screen.ABSORBABLE: (
        "A large gap is only an opportunity if you can go and close it yourself. "
        "SpaceX built engines, avionics and software in-house; Tesla brought "
        "cells and castings inside. If the expensive part stays someone else's, "
        "the gap stays theirs too."
    ),
    Screen.SOFT_BARRIER: (
        "Capital intensity, regulatory habit and 'that is how it is done' all "
        "look like walls and are not. Actual physics is a wall. Telling the two "
        "apart is most of the judgement in the whole method."
    ),
    Screen.EXISTING_NEED: (
        "Newspaper listings, bank transfers, satellite launch, cars — every one "
        "already had takers. The bet was on cost, never on whether anyone wanted "
        "the thing. Bets that require inventing the demand are a different, and "
        "much worse, game."
    ),
    Screen.PULLS_HELP: (
        "'Life insurance for the species' is a recruiting instrument as much as "
        "a belief: it buys effort that market rates would not. This is the piece "
        "imitators leave out most often, and it works outside business too — it "
        "is why some open-source projects attract contributors and others do not."
    ),
    Screen.REACHABLE_PROOF: (
        "Each venture was funded by the last exit; the pattern needs resources "
        "that answer to nobody. Generalised: if you cannot get to something "
        "undeniable on your own steam, you are dependent on being believed, and "
        "being believed is the thing this method is worst at buying."
    ),
}

#: Weights. COST_DETACHED is additionally a gate, below.
WEIGHTS: dict[Screen, float] = {
    Screen.COST_DETACHED: 3.0,
    Screen.ABSORBABLE: 2.0,
    Screen.SOFT_BARRIER: 2.0,
    Screen.EXISTING_NEED: 1.5,
    Screen.PULLS_HELP: 1.0,
    Screen.REACHABLE_PROOF: 1.5,
}

MAX_SCORE = 2  # per screen: 0 no, 1 partly, 2 yes


class Fit(str, Enum):
    STRONG = "STRONG"
    PARTIAL = "PARTIAL"
    WEAK = "WEAK"
    OFF_PATTERN = "OFF_PATTERN"


FIT_SUMMARY: dict[Fit, str] = {
    Fit.STRONG: "this is the shape the method was built for",
    Fit.PARTIAL: "the shape is there but thin in places",
    Fit.WEAK: "the gate is open but little else supports it",
    Fit.OFF_PATTERN: "nothing here costs more than it must, so the method has no purchase",
}


@dataclass
class ScreenResult:
    screen: Screen
    score: int
    evidence: str | None = None

    @property
    def weighted(self) -> float:
        return self.score * WEIGHTS[self.screen]


@dataclass
class Assessment:
    subject: str
    results: list[ScreenResult] = field(default_factory=list)
    notes: str | None = None

    @property
    def gate_passed(self) -> bool:
        """Without a cost detached from reality there is nothing to attack.

        This is the whole reason the screen can be wrong about something and
        say so: no amount of mission, capital or conviction substitutes for
        the gap between what a thing costs and what it must cost.
        """
        for result in self.results:
            if result.screen is Screen.COST_DETACHED:
                return result.score > 0
        return False

    @property
    def score(self) -> float:
        return sum(r.weighted for r in self.results)

    @property
    def max_score(self) -> float:
        return sum(WEIGHTS.values()) * MAX_SCORE

    @property
    def percentage(self) -> float:
        return 100.0 * self.score / self.max_score if self.max_score else 0.0

    @property
    def fit(self) -> Fit:
        if not self.gate_passed:
            return Fit.OFF_PATTERN
        pct = self.percentage
        if pct >= 75:
            return Fit.STRONG
        if pct >= 50:
            return Fit.PARTIAL
        return Fit.WEAK

    def weakest(self) -> list[ScreenResult]:
        """Where this is thinnest — lowest score first, heaviest weight first."""
        return sorted(
            (r for r in self.results if r.score < MAX_SCORE),
            key=lambda r: (r.score, -WEIGHTS[r.screen]),
        )

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "fit": self.fit.value,
            "summary": FIT_SUMMARY[self.fit],
            "gate_passed": self.gate_passed,
            "score": round(self.score, 2),
            "max_score": self.max_score,
            "percentage": round(self.percentage, 1),
            "screens": [
                {
                    "screen": r.screen.value,
                    "question": QUESTIONS[r.screen],
                    "score": r.score,
                    "weight": WEIGHTS[r.screen],
                    "evidence": r.evidence,
                }
                for r in self.results
            ],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "Assessment":
        if not isinstance(raw, dict):
            raise SpecError('"opportunity" must be an object')
        subject = raw.get("subject") or raw.get("market")
        if not subject:
            raise SpecError(
                'opportunity needs "subject": the ground you would be moving onto'
            )

        screens_raw = raw.get("screens")
        if not isinstance(screens_raw, dict):
            raise SpecError('opportunity needs "screens" as an object')

        results: list[ScreenResult] = []
        for screen in Screen:
            entry = screens_raw.get(screen.value)
            if entry is None:
                raise SpecError(
                    f'opportunity.screens is missing "{screen.value}" — '
                    f"{QUESTIONS[screen]} Answer 0, 1 or 2."
                )
            if isinstance(entry, dict):
                score = entry.get("score")
                evidence = entry.get("evidence")
            else:
                score, evidence = entry, None
            results.append(
                ScreenResult(
                    screen=screen,
                    score=_score(score, f"opportunity.screens.{screen.value}"),
                    evidence=str(evidence) if evidence else None,
                )
            )

        return cls(subject=str(subject), results=results, notes=raw.get("notes"))


def _score(value: Any, where: str) -> int:
    """Parse a screen score, refusing anything that is not exactly 0, 1 or 2.

    int(1.5) is 1, and silently rounding a score down would move the total
    without anyone being told. A half-answer means the question has not been
    answered; say so rather than picking a side.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise SpecError(f"{where} must be 0, 1 or 2, got {value!r}")
    try:
        number = float(value)
    except ValueError:
        raise SpecError(f"{where} must be 0, 1 or 2, got {value!r}") from None
    if number not in (0.0, 1.0, 2.0):
        raise SpecError(f"{where} must be 0, 1 or 2, got {value!r}")
    return int(number)
