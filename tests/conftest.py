"""Throwaway git repositories to run the gate against.

The end-to-end tests build a real repository with a real bug, a real fix and
a real test, then check that falsify reaches the verdict a reviewer would.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Deterministic, and it never touches the developer's pytest cache.
TEST_CMD = "python -m pytest -p no:cacheprovider {files}"

# A bug with an obvious upper half missing.
BUGGY_SOURCE = '''\
def clamp(value, lo, hi):
    """Constrain value to the range [lo, hi]."""
    if value < lo:
        return lo
    return value
'''

FIXED_SOURCE = '''\
def clamp(value, lo, hi):
    """Constrain value to the range [lo, hi]."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
'''

# Only ever exercises the lower bound, so it passes against the bug.
WEAK_TEST = '''\
from calc import clamp


def test_below_the_floor_is_raised():
    assert clamp(-5, 0, 10) == 0
'''

# Catches the missing upper bound.
STRONG_TEST = '''\
from calc import clamp


def test_below_the_floor_is_raised():
    assert clamp(-5, 0, 10) == 0


def test_above_the_ceiling_is_lowered():
    assert clamp(99, 0, 10) == 10
'''


@dataclass
class Repo:
    path: Path

    def git(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout

    def write(self, relpath: str, content: str) -> Path:
        target = self.path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    """A repository holding the bug, with a test that does not catch it."""
    r = Repo(tmp_path / "project")
    r.path.mkdir()
    r.git("init", "-q", "-b", "main")
    r.git("config", "user.email", "test@example.com")
    r.git("config", "user.name", "Test")
    r.git("config", "commit.gpgsign", "false")

    # An empty root conftest puts the repo root on sys.path for the inner run,
    # so `from calc import clamp` resolves from tests/.
    r.write("conftest.py", "")
    r.write("calc.py", BUGGY_SOURCE)
    r.write("tests/test_calc.py", WEAK_TEST)
    r.commit("initial")
    return r
