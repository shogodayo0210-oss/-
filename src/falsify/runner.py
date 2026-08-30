"""Running a test command and classifying what came back."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .detect import Runner

# How much captured output to keep. Enough to see the failing assertion,
# little enough to paste into a review.
OUTPUT_TAIL_LINES = 40


@dataclass
class RunResult:
    command: str
    cwd: str
    exit_code: int
    output: str
    timed_out: bool = False
    #: Set when this result came from the setup step, not the tests. A setup
    #: step that depends on the change (an install, a codegen pass) fails in
    #: the counterfactual for reasons that say nothing about the tests.
    is_setup_failure: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def is_clean_failure(self, runner: Runner | None) -> bool:
        """True if this looks like *tests failing* rather than the run breaking.

        A counterfactual that dies on an import error is red, but it is red
        for the wrong reason: it tells us nothing about whether the new test
        catches the bug. Only runners that report the difference can answer.
        """
        if self.passed or self.timed_out or self.is_setup_failure:
            return False
        if runner is None or not runner.failure_exit_codes:
            return True
        return self.exit_code in runner.failure_exit_codes

    def tail(self, lines: int = OUTPUT_TAIL_LINES) -> str:
        kept = self.output.strip().splitlines()[-lines:]
        return "\n".join(kept)


@dataclass
class Environment:
    """Where and how to run commands."""

    cwd: Path
    timeout: int = 600
    setup: str | None = None
    setup_result: RunResult | None = field(default=None, init=False)


def run(command: str, env: Environment) -> RunResult:
    """Run `command` through the shell in `env.cwd`, capturing everything."""
    child_env = dict(os.environ)
    # Keep pytest's own cache out of the scratch worktree, and stop colour
    # codes from landing in the evidence log.
    child_env["PY_COLORS"] = "0"
    child_env["NO_COLOR"] = "1"
    child_env.pop("PYTEST_ADDOPTS", None)

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(env.cwd),
            capture_output=True,
            text=True,
            timeout=env.timeout,
            env=child_env,
        )
    except subprocess.TimeoutExpired as exc:
        captured = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(captured, bytes):
            captured = captured.decode("utf-8", "replace")
        return RunResult(
            command=command,
            cwd=str(env.cwd),
            exit_code=-1,
            output=captured + f"\n[falsify] timed out after {env.timeout}s",
            timed_out=True,
        )

    return RunResult(
        command=command,
        cwd=str(env.cwd),
        exit_code=proc.returncode,
        output=proc.stdout + proc.stderr,
    )


def run_with_setup(command: str, env: Environment) -> RunResult:
    """Run an optional setup command first, failing fast if it errors."""
    if env.setup:
        env.setup_result = run(env.setup, env)
        if not env.setup_result.passed:
            env.setup_result.is_setup_failure = True
            return env.setup_result
    return run(command, env)
