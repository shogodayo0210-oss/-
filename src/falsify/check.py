"""The gate itself.

A change that claims to fix something should come with a test that would
have caught it. The only way to know a test would have caught it is to run
that test against the broken code and watch it fail.

So falsify reconstructs exactly that state — the new tests, the old source —
runs the tests there, and requires red. A test that passes against the code
it was written to police is not evidence of anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Sequence

from . import detect, gitutil
from .detect import Runner
from .runner import Environment, RunResult, run_with_setup


class Verdict(str, Enum):
    #: Red without the fix, green with it. The test earns its place.
    PROVEN = "PROVEN"
    #: The test passes even against the broken code, so it proves nothing.
    NO_EVIDENCE = "NO_EVIDENCE"
    #: Source changed and nothing tests it.
    NO_TESTS = "NO_TESTS"
    #: The tests do not pass in their current state.
    BROKEN = "BROKEN"
    #: Only tests changed; there is no fix to falsify.
    VACUOUS = "VACUOUS"
    #: The counterfactual run collapsed instead of failing cleanly.
    INCONCLUSIVE = "INCONCLUSIVE"
    #: Nothing changed at all.
    EMPTY = "EMPTY"

    @property
    def ok(self) -> bool:
        """Whether this verdict should let a change through the gate."""
        return self in (Verdict.PROVEN, Verdict.VACUOUS, Verdict.EMPTY)


#: One line explaining each verdict, shown verbatim in the report.
SUMMARIES: dict[Verdict, str] = {
    Verdict.PROVEN: "the test fails without the fix and passes with it",
    Verdict.NO_EVIDENCE: "the test passes even without the fix, so it proves nothing",
    Verdict.NO_TESTS: "source changed but no test changed alongside it",
    Verdict.BROKEN: "the tests do not pass as things stand",
    Verdict.VACUOUS: "only tests changed; there is no fix to falsify",
    Verdict.INCONCLUSIVE: "the run without the fix broke instead of failing",
    Verdict.EMPTY: "no changes to check",
}


@dataclass
class Report:
    verdict: Verdict
    base: str
    base_reason: str
    test_files: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    command: str | None = None
    runner_name: str | None = None
    runner_guessed: bool = True
    counterfactual: RunResult | None = None
    actual: RunResult | None = None
    warnings: list[str] = field(default_factory=list)
    detail: str | None = None

    @property
    def summary(self) -> str:
        return SUMMARIES[self.verdict]

    def to_dict(self) -> dict:
        def run_dict(result: RunResult | None) -> dict | None:
            if result is None:
                return None
            return {
                "command": result.command,
                "exit_code": result.exit_code,
                "passed": result.passed,
                "timed_out": result.timed_out,
                "output_tail": result.tail(),
            }

        return {
            "verdict": self.verdict.value,
            "ok": self.verdict.ok,
            "summary": self.summary,
            "detail": self.detail,
            "base": self.base,
            "base_reason": self.base_reason,
            "test_files": self.test_files,
            "source_files": self.source_files,
            "command": self.command,
            "runner": self.runner_name,
            "runner_guessed": self.runner_guessed,
            "evidence": {
                "without_fix": run_dict(self.counterfactual),
                "with_fix": run_dict(self.actual),
            },
            "warnings": self.warnings,
        }


def check(
    repo: Path | str | None = None,
    base: str | None = None,
    test_cmd: str | None = None,
    test_globs: Sequence[str] = (),
    setup: str | None = None,
    timeout: int = 600,
) -> Report:
    """Run the gate and return what happened."""
    root = gitutil.repo_root(cwd=repo)

    if base:
        resolved_base, base_reason = gitutil.rev_parse(base, cwd=root), f"--base {base}"
    else:
        resolved_base, base_reason = gitutil.resolve_base(cwd=root)

    changed = gitutil.changed_files(resolved_base, cwd=root)
    test_files, source_files = detect.split_paths(changed, test_globs)

    report = Report(
        verdict=Verdict.EMPTY,
        base=resolved_base,
        base_reason=base_reason,
        test_files=test_files,
        source_files=source_files,
    )

    _warn_about_untracked_tests(report, root, test_globs)

    if not changed:
        return report

    if not source_files:
        report.verdict = Verdict.VACUOUS
        return report

    if not test_files:
        report.verdict = Verdict.NO_TESTS
        report.detail = (
            "Nothing in this change would fail if the change were wrong. "
            "Add a test that fails without it."
        )
        return report

    runner, command, guessed = _resolve_command(root, test_cmd, test_files)
    if command is None:
        report.verdict = Verdict.INCONCLUSIVE
        report.detail = (
            "Could not work out how to run this project's tests. "
            "Pass --test-cmd, optionally using {files} to scope the run."
        )
        return report

    report.command = command
    report.runner_name = runner.name if runner else "custom"
    report.runner_guessed = guessed

    if runner is not None and not runner.scopes_to_files:
        report.warnings.append(
            f"{runner.name} runs the whole suite, so an unrelated failing test "
            f"would look like evidence. Pass --test-cmd with {{files}} to narrow it."
        )

    # 1. The counterfactual: the new tests, the old source.
    patch = gitutil.diff_patch(resolved_base, test_files, cwd=root)
    with gitutil.counterfactual_worktree(resolved_base, root) as worktree:
        try:
            gitutil.apply_patch(patch, cwd=worktree)
        except gitutil.GitError as exc:
            report.verdict = Verdict.INCONCLUSIVE
            report.detail = str(exc)
            return report

        report.counterfactual = run_with_setup(
            command, Environment(cwd=worktree, timeout=timeout, setup=setup)
        )

    # 2. Reality: everything applied, in the user's own worktree.
    report.actual = run_with_setup(
        command, Environment(cwd=root, timeout=timeout, setup=setup)
    )

    report.verdict, report.detail = _judge(report.counterfactual, report.actual, runner)
    return report


def _judge(
    counterfactual: RunResult,
    actual: RunResult,
    runner: Runner | None,
) -> tuple[Verdict, str | None]:
    """Turn two runs into a verdict.

    Order matters. The counterfactual is checked first because it is the
    question worth asking: a suite that is green both with and without the
    fix is the failure mode this tool exists to catch, and reporting it as
    "tests pass" would be exactly the mistake everything else makes.
    """
    if counterfactual.passed:
        return (
            Verdict.NO_EVIDENCE,
            "The tests pass against the code from before this change. "
            "Whatever this change fixes, this test would not have caught it.",
        )

    if counterfactual.timed_out:
        return (
            Verdict.INCONCLUSIVE,
            "The run without the fix timed out, so its result says nothing. "
            "Raise --timeout or narrow the test command.",
        )

    if counterfactual.is_setup_failure:
        return (
            Verdict.INCONCLUSIVE,
            "The setup step failed without the fix, so the tests never ran. "
            "A setup step that depends on the change — an install, a codegen "
            "pass — cannot run in the counterfactual, and its failure is not "
            "evidence that the tests would have caught anything.",
        )

    if not counterfactual.is_clean_failure(runner):
        return (
            Verdict.INCONCLUSIVE,
            f"The run without the fix exited {counterfactual.exit_code}, which "
            "signals a broken run rather than a failing test. It went red for "
            "the wrong reason, so it is not evidence. Check that the new test "
            "can import and collect against the older code.",
        )

    if not actual.passed:
        return (
            Verdict.BROKEN,
            "The test fails without the fix, which is right, but it fails with "
            "the fix too. The change does not actually resolve it.",
        )

    return Verdict.PROVEN, None


def _resolve_command(
    root: Path,
    test_cmd: str | None,
    test_files: Sequence[str],
) -> tuple[Runner | None, str | None, bool]:
    """Settle on a command, reporting whether it was guessed."""
    if test_cmd:
        custom = detect.custom_runner(test_cmd)
        return custom, detect.build_command(custom, test_files), False

    runner = detect.detect_runner(root)
    if runner is None:
        return None, None, True
    return runner, detect.build_command(runner, test_files), True


def _warn_about_untracked_tests(
    report: Report,
    root: Path,
    test_globs: Sequence[str],
) -> None:
    """A brand new test file git has never seen is invisible to `git diff`.

    Staying silent here would be the worst kind of failure: the change gets
    waved through precisely because its test could not be found.
    """
    untracked = [
        path
        for path in gitutil.untracked_files(cwd=root)
        if detect.is_test_path(path, test_globs)
    ]
    if untracked:
        listed = ", ".join(untracked[:5])
        more = f" (+{len(untracked) - 5} more)" if len(untracked) > 5 else ""
        report.warnings.append(
            f"Untracked test files are invisible to this check: {listed}{more}. "
            f"Run: git add -N {untracked[0]}"
        )
