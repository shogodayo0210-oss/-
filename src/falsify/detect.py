"""Working out which files are tests, and how to run them.

Both answers are guesses, and both are overridable from the command line.
When falsify guesses, it says so in the report — a verdict that rests on a
bad guess is worth less than no verdict at all.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# Ordered most- to least-specific. A path matching any of these is a test.
TEST_PATTERNS = (
    "test_*.py",
    "*_test.py",
    "conftest.py",
    "*_test.go",
    "*.test.js",
    "*.test.jsx",
    "*.test.ts",
    "*.test.tsx",
    "*.spec.js",
    "*.spec.jsx",
    "*.spec.ts",
    "*.spec.tsx",
    "*_spec.rb",
    "*Test.java",
    "*Tests.cs",
)

# Any path with one of these as a directory component is a test.
TEST_DIRS = ("test", "tests", "spec", "specs", "__tests__", "testdata", "fixtures")

# Build output and vendored code live inside test directories often enough
# that classifying by location alone is not safe. A compiled artefact is
# never the test that proves something.
IGNORED_DIRS = (
    "__pycache__",
    "node_modules",
    ".git",
    ".pytest_cache",
    ".tox",
    ".venv",
    "venv",
    "build",
    "dist",
    "target",
    "vendor",
)

IGNORED_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dll",
    ".dylib",
    ".o",
    ".a",
    ".class",
    ".jar",
    ".log",
)


def is_ignorable_path(path: str) -> bool:
    """True for build output, caches and vendored code."""
    p = Path(path)
    if any(part in IGNORED_DIRS for part in p.parts):
        return True
    return p.suffix.lower() in IGNORED_SUFFIXES


@dataclass(frozen=True)
class Runner:
    """How to invoke a project's tests.

    `template` may contain `{files}`; when it does, falsify narrows the
    counterfactual run to just the test files the change touched, which keeps
    an unrelated pre-existing failure from being mistaken for evidence.
    """

    name: str
    template: str
    # pytest distinguishes "tests failed" (1) from "the run itself broke"
    # (2, 3, 4). Runners without that distinction leave this empty and every
    # non-zero exit is read as a plain failure.
    failure_exit_codes: tuple[int, ...] = ()

    @property
    def scopes_to_files(self) -> bool:
        return "{files}" in self.template


PYTEST = Runner("pytest", "python -m pytest {files}", failure_exit_codes=(1,))

# Checked in order; the first whose marker file exists wins.
RUNNER_MARKERS: tuple[tuple[str, Runner], ...] = (
    ("pytest.ini", PYTEST),
    ("tox.ini", PYTEST),
    ("setup.cfg", PYTEST),
    ("pyproject.toml", PYTEST),
    ("go.mod", Runner("go", "go test ./...")),
    ("Cargo.toml", Runner("cargo", "cargo test")),
    ("package.json", Runner("npm", "npm test -- {files}")),
    ("Gemfile", Runner("rspec", "bundle exec rspec {files}")),
)


def is_test_path(path: str, extra_globs: Sequence[str] = ()) -> bool:
    """True if `path` looks like a test rather than production code."""
    if is_ignorable_path(path):
        return False

    p = Path(path)
    name = p.name

    for pattern in extra_globs:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(name, pattern):
            return True

    if any(part.lower() in TEST_DIRS for part in p.parts[:-1]):
        return True

    return any(fnmatch.fnmatch(name, pattern) for pattern in TEST_PATTERNS)


def split_paths(
    paths: Sequence[str],
    extra_globs: Sequence[str] = (),
) -> tuple[list[str], list[str]]:
    """Partition changed paths into (tests, source)."""
    tests: list[str] = []
    source: list[str] = []
    for path in paths:
        (tests if is_test_path(path, extra_globs) else source).append(path)
    return tests, source


def detect_runner(repo: Path | str) -> Runner | None:
    """Guess how to run this project's tests, or None if nothing fits."""
    repo = Path(repo)
    for marker, runner in RUNNER_MARKERS:
        if (repo / marker).exists():
            return runner
    if any(repo.glob("test_*.py")) or (repo / "tests").is_dir():
        return PYTEST
    return None


#: Substrings that identify a known runner inside a user-supplied command,
#: paired with the exit codes that runner uses for "tests failed".
COMMAND_SIGNATURES: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("pytest", (1,)),
)


def custom_runner(template: str) -> Runner:
    """Wrap a user-supplied command, keeping exit-code meaning where we can.

    `--test-cmd 'pytest {files}'` is still pytest. Forgetting that would cost
    us the difference between a test failing and the run collapsing, which is
    the difference between evidence and noise.
    """
    lowered = template.lower()
    for needle, codes in COMMAND_SIGNATURES:
        if needle in lowered:
            return Runner("custom", template, failure_exit_codes=codes)
    return Runner("custom", template)


def build_command(runner: Runner, test_files: Sequence[str]) -> str:
    """Fill a runner template in, quoting paths that need it."""
    if not runner.scopes_to_files:
        return runner.template
    quoted = " ".join(_quote(f) for f in test_files)
    return runner.template.replace("{files}", quoted).strip()


def _quote(path: str) -> str:
    return f"'{path}'" if any(c in path for c in " \t\"'$`\\") else path
