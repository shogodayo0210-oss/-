"""The backtest, as a regression suite.

Running it by hand is how findings are discovered. Running it here is what
stops a later change from quietly undoing one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backtests"))

from run import CASES, run_case  # noqa: E402

CASE_FILES = sorted(CASES.glob("*.json"))


def test_there_are_cases_to_run():
    assert CASE_FILES, "the backtest is meaningless with no cases"


@pytest.mark.parametrize("path", CASE_FILES, ids=lambda p: p.stem)
def test_case_behaves_as_recorded(path):
    score = run_case(path)
    assert score.passed, f"{score.name}: {score.detail}"


@pytest.mark.parametrize("path", CASE_FILES, ids=lambda p: p.stem)
def test_every_case_records_what_happened_and_where_it_came_from(path):
    raw = json.loads(path.read_text())
    for key in ("case", "date", "situation", "what_he_actually_did", "outcome"):
        assert raw.get(key), f"{path.name} is missing {key}"

    # A historical claim without a source is an assertion, and this whole
    # exercise is about not accepting those.
    if raw["outcome"] != "CONTROL":
        assert raw.get("sources"), f"{path.name} cites nothing"


def test_the_control_case_exists_and_expects_silence():
    controls = [
        json.loads(p.read_text())
        for p in CASE_FILES
        if json.loads(p.read_text())["outcome"] == "CONTROL"
    ]
    assert controls, (
        "without a case the engine should stay quiet on, a rule that fires on "
        "everything would score perfectly"
    )
    for control in controls:
        assert not control["expect"].get("must_flag")
        assert control["expect"]["must_not_flag"]
