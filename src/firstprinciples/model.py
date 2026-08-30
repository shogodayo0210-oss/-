"""The shape of a decision under review.

Input is plain JSON so the tool stays dependency-free and the file a team
argues over stays diffable. See examples/decision.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SpecError(ValueError):
    """The decision file is not usable."""


class Grounding(str, Enum):
    """What a requirement rests on.

    The distinction is the whole of rule 1: a requirement grounded in physics
    is a fact, and a requirement grounded in an assumption is a habit wearing
    a fact's clothes.
    """

    PHYSICS = "physics"
    CONTRACT = "contract"
    REGULATION = "regulation"
    ASSUMPTION = "assumption"
    UNKNOWN = "unknown"

    @property
    def is_negotiable(self) -> bool:
        return self in (Grounding.ASSUMPTION, Grounding.UNKNOWN)


class Authority(str, Enum):
    """How senior the person behind a requirement is.

    Deliberately inverted downstream: high authority raises severity rather
    than settling the question. Requirements from smart people are the ones
    nobody thinks to check.
    """

    HIGH = "high"
    NORMAL = "normal"
    UNKNOWN = "unknown"


class Phase(str, Enum):
    """What kind of work this is, which decides the timeline correction."""

    PROTOTYPE = "prototype"
    PRODUCTION = "production"
    REGULATED = "regulated"
    #: Where the evidence must be **accumulated across a fleet or population
    #: over time** — miles driven, incidents not had, patients followed —
    #: before the thing can operate at all.
    #:
    #: Not merely "a regulator is involved". Getting one device into one
    #: volunteer is a regulator reviewing a submission, and belongs in
    #: REGULATED; Neuralink's first implant ran about 3x, which REGULATED
    #: covers and this band badly overshoots. Removing the safety driver
    #: across a public fleet is this band, and Waymo ran about 7x.
    #:
    #: The distinction is post-hoc — it was drawn after Neuralink falsified
    #: the wider version. See docs/backtest.md.
    SAFETY_CRITICAL = "safety_critical"


#: Department names are not people. A requirement owned by one of these has
#: no owner, which is the point of the rule.
NON_PERSON_OWNERS = frozenset(
    {
        "legal",
        "the legal department",
        "legal department",
        "safety",
        "the safety department",
        "safety department",
        "compliance",
        "engineering",
        "management",
        "leadership",
        "the business",
        "product",
        "security",
        "policy",
        "hr",
        "finance",
        "unknown",
        "n/a",
        "tbd",
        "",
    }
)


@dataclass
class Requirement:
    text: str
    owner: str | None = None
    authority: Authority = Authority.UNKNOWN
    grounded_in: Grounding = Grounding.UNKNOWN
    questioned: bool = False

    @property
    def has_named_owner(self) -> bool:
        if not self.owner:
            return False
        return self.owner.strip().lower() not in NON_PERSON_OWNERS


@dataclass
class Step:
    name: str
    deleted: bool = False
    reinstated: bool = False
    considered_for_deletion: bool = False
    automated: bool = False
    optimised: bool = False
    #: Whether this can be undone cheaply. Most things can, so that is the
    #: default; the ones that cannot deserve a different bar entirely.
    reversible: bool = True

    def __post_init__(self) -> None:
        # Deleting a step is the strongest possible form of considering it.
        if self.deleted:
            self.considered_for_deletion = True


@dataclass
class Component:
    name: str
    finished_cost: float
    material_cost: float
    quantity: int = 1

    @property
    def idiot_index(self) -> float | None:
        """Finished cost over raw material cost. None if materials are free."""
        if self.material_cost <= 0:
            return None
        return self.finished_cost / self.material_cost


@dataclass
class Estimate:
    months: float | None = None
    cost: float | None = None


@dataclass
class Decision:
    title: str
    estimate: Estimate = field(default_factory=Estimate)
    phases: list[Phase] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    #: What costs are counted in. Money is the obvious case, but the ratio
    #: works just as well on hours, and a process is the commonest subject.
    unit: str = ""
    #: How long before this runs out of money, time or patience. Added after
    #: backtesting: with three days of runway, an audit of deletion ratios is
    #: not merely unhelpful, it is misdirection.
    runway_months: float | None = None
    #: Spacing, in months, when opportunities to finish only occur at
    #: intervals — a Mars transfer window every 26 months, a growing season,
    #: an annual certification cycle. Found by running the engine forward:
    #: it corrected an uncrewed Mars launch into a band containing no launch
    #: window at all, which is not a late prediction but an impossible one.
    window_months: float | None = None
    #: True when this is a deliberate stopgap that can be torn down. The
    #: documented schedule overshoot comes from scale, cost and regulation,
    #: and a stopgap sidesteps all three, so it must not carry the same
    #: correction as the permanent version.
    stopgap: bool = False
    #: True when failure here ends the whole enterprise. The engine surfaces
    #: this and deliberately declines to resolve it.
    ruin_risk: bool = False
    #: What one more attempt costs, against what the analysis that would
    #: replace it costs. When trying is cheaper than deciding, deliberation is
    #: the expensive option — the idiot index, applied to learning.
    attempt_cost: float | None = None
    analysis_cost: float | None = None
    #: Who makes the call, and who gets the bill. When they differ and the
    #: same person controls both, the ordinary corrective — the people paying
    #: push back — is switched off.
    decided_by: str | None = None
    cost_borne_by: str | None = None
    #: Whether the decider is in the blast radius too. Kodak forced this in:
    #: its management lost the company they ran, which is shared downside, not
    #: insulation. Without the distinction the rule fires on every corporate
    #: failure that ever cost anyone a job — which is all of them.
    decider_shares_cost: bool = False
    #: Populated separately by opportunity.Assessment to keep the two halves
    #: of the tool — what to do, and how to do it — independent.
    opportunity: Any = None

    @classmethod
    def from_dict(cls, raw: Any) -> "Decision":
        if not isinstance(raw, dict):
            raise SpecError("the decision file must contain a JSON object")

        title = raw.get("decision") or raw.get("title")
        if not title:
            raise SpecError('missing "decision": name what you are deciding')

        estimate_raw = raw.get("estimate") or {}
        if not isinstance(estimate_raw, dict):
            raise SpecError('"estimate" must be an object with months and/or cost')

        return cls(
            title=str(title),
            unit=str(raw.get("unit", "")),
            runway_months=_optional_number(
                raw.get("runway_months"), "runway_months"
            ),
            window_months=_optional_number(
                raw.get("window_months"), "window_months"
            ),
            stopgap=bool(raw.get("stopgap", False)),
            ruin_risk=bool(raw.get("ruin_risk", False)),
            attempt_cost=_optional_number(raw.get("attempt_cost"), "attempt_cost"),
            analysis_cost=_optional_number(raw.get("analysis_cost"), "analysis_cost"),
            decided_by=raw.get("decided_by"),
            cost_borne_by=raw.get("cost_borne_by"),
            decider_shares_cost=bool(raw.get("decider_shares_cost", False)),
            estimate=Estimate(
                months=_optional_number(estimate_raw.get("months"), "estimate.months"),
                cost=_optional_number(estimate_raw.get("cost"), "estimate.cost"),
            ),
            phases=[_enum(Phase, p, "phases") for p in raw.get("phases", [])],
            requirements=[
                _requirement(item, i) for i, item in enumerate(raw.get("requirements", []))
            ],
            steps=[_step(item, i) for i, item in enumerate(raw.get("steps", []))],
            components=[
                _component(item, i) for i, item in enumerate(raw.get("components", []))
            ],
        )


def _requirement(raw: Any, index: int) -> Requirement:
    where = f"requirements[{index}]"
    if not isinstance(raw, dict):
        raise SpecError(f"{where} must be an object")
    text = raw.get("text")
    if not text:
        raise SpecError(f'{where} needs "text"')
    return Requirement(
        text=str(text),
        owner=raw.get("owner"),
        authority=_enum(Authority, raw.get("authority", "unknown"), f"{where}.authority"),
        grounded_in=_enum(
            Grounding, raw.get("grounded_in", "unknown"), f"{where}.grounded_in"
        ),
        questioned=bool(raw.get("questioned", False)),
    )


def _step(raw: Any, index: int) -> Step:
    where = f"steps[{index}]"
    if not isinstance(raw, dict):
        raise SpecError(f"{where} must be an object")
    name = raw.get("name")
    if not name:
        raise SpecError(f'{where} needs "name"')
    return Step(
        name=str(name),
        deleted=bool(raw.get("deleted", False)),
        reinstated=bool(raw.get("reinstated", False)),
        considered_for_deletion=bool(raw.get("considered_for_deletion", False)),
        automated=bool(raw.get("automated", False)),
        optimised=bool(raw.get("optimised", raw.get("optimized", False))),
        reversible=bool(raw.get("reversible", True)),
    )


def _component(raw: Any, index: int) -> Component:
    where = f"components[{index}]"
    if not isinstance(raw, dict):
        raise SpecError(f"{where} must be an object")
    name = raw.get("name")
    if not name:
        raise SpecError(f'{where} needs "name"')
    finished = _optional_number(raw.get("finished_cost"), f"{where}.finished_cost")
    material = _optional_number(raw.get("material_cost"), f"{where}.material_cost")
    if finished is None or material is None:
        raise SpecError(f"{where} needs both finished_cost and material_cost")
    return Component(
        name=str(name),
        finished_cost=finished,
        material_cost=material,
        quantity=int(raw.get("quantity", 1)),
    )


def _optional_number(value: Any, where: str) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise SpecError(f"{where} must be a number, got {value!r}") from None
    if number < 0:
        raise SpecError(f"{where} must not be negative")
    return number


def _enum(enum_cls, value: Any, where: str):
    try:
        return enum_cls(str(value).strip().lower())
    except ValueError:
        allowed = ", ".join(member.value for member in enum_cls)
        raise SpecError(f"{where}: {value!r} is not one of {allowed}") from None
