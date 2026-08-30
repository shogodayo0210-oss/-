"""End-to-end: does the gate reach the verdict a reviewer would?"""

from __future__ import annotations

import pytest

from falsify.check import Verdict, check

from conftest import BUGGY_SOURCE, FIXED_SOURCE, STRONG_TEST, TEST_CMD, WEAK_TEST


def run(repo, **kwargs):
    return check(repo=repo.path, test_cmd=TEST_CMD, **kwargs)


def test_a_real_fix_with_a_test_that_catches_it_is_proven(repo):
    repo.write("calc.py", FIXED_SOURCE)
    repo.write("tests/test_calc.py", STRONG_TEST)

    report = run(repo)

    assert report.verdict is Verdict.PROVEN
    assert report.verdict.ok
    assert not report.counterfactual.passed, "must go red without the fix"
    assert report.actual.passed, "must go green with the fix"
    assert report.source_files == ["calc.py"]
    assert report.test_files == ["tests/test_calc.py"]


def test_a_test_that_passes_without_the_fix_is_no_evidence(repo):
    # The fix is genuine. The test that ships with it is not evidence of it:
    # it only ever exercised the half that already worked.
    repo.write("calc.py", FIXED_SOURCE)
    repo.write("tests/test_calc.py", WEAK_TEST + "\n\ndef test_midrange():\n    assert clamp(5, 0, 10) == 5\n")

    report = run(repo)

    assert report.verdict is Verdict.NO_EVIDENCE
    assert not report.verdict.ok
    assert report.counterfactual.passed
    assert "would not have caught it" in report.detail


def test_source_changed_with_no_test_at_all(repo):
    repo.write("calc.py", FIXED_SOURCE)

    report = run(repo)

    assert report.verdict is Verdict.NO_TESTS
    assert not report.verdict.ok
    assert report.counterfactual is None, "no point running anything"


def test_a_test_that_still_fails_after_the_fix_is_broken(repo):
    # A plausible-looking change that does not actually fix the bug.
    repo.write("calc.py", BUGGY_SOURCE.replace("if value < lo:", "if value <= lo:"))
    repo.write("tests/test_calc.py", STRONG_TEST)

    report = run(repo)

    assert report.verdict is Verdict.BROKEN
    assert not report.verdict.ok
    assert not report.counterfactual.passed
    assert not report.actual.passed


def test_changing_only_tests_is_vacuous(repo):
    repo.write("tests/test_calc.py", STRONG_TEST)

    report = run(repo)

    assert report.verdict is Verdict.VACUOUS
    assert report.verdict.ok, "adding tests should never be blocked"


def test_no_changes_at_all(repo):
    report = run(repo)

    assert report.verdict is Verdict.EMPTY
    assert report.verdict.ok


def test_committed_changes_are_checked_against_an_explicit_base(repo):
    base = repo.git("rev-parse", "HEAD").strip()
    repo.write("calc.py", FIXED_SOURCE)
    repo.write("tests/test_calc.py", STRONG_TEST)
    repo.commit("fix clamp upper bound")

    report = run(repo, base=base)

    assert report.verdict is Verdict.PROVEN
    assert report.base == base


def test_an_untracked_test_file_is_warned_about_not_silently_ignored(repo):
    repo.write("calc.py", FIXED_SOURCE)
    repo.write("tests/test_new.py", STRONG_TEST)  # never added to git

    report = run(repo)

    # Without the warning this would read as "you changed source and wrote no
    # test", when in fact the test is sitting right there.
    assert report.verdict is Verdict.NO_TESTS
    assert any("Untracked test files" in w for w in report.warnings)
    assert any("tests/test_new.py" in w for w in report.warnings)


def test_the_users_working_tree_is_never_modified(repo):
    repo.write("calc.py", FIXED_SOURCE)
    repo.write("tests/test_calc.py", STRONG_TEST)
    before = (repo.path / "calc.py").read_text()

    run(repo)

    assert (repo.path / "calc.py").read_text() == before
    assert repo.git("status", "--porcelain=v1")  # still dirty, as we found it
    # And no scratch worktrees left registered.
    assert "counterfactual" not in repo.git("worktree", "list")


def test_a_run_that_breaks_instead_of_failing_is_inconclusive(repo):
    # The new test cannot even import, so the counterfactual is red for a
    # reason that says nothing about the fix.
    repo.write("calc.py", FIXED_SOURCE)
    repo.write("tests/test_calc.py", "import nonexistent_module_xyz\n\n\ndef test_x():\n    assert True\n")

    report = run(repo)

    assert report.verdict is Verdict.INCONCLUSIVE
    assert not report.verdict.ok
    assert "wrong reason" in report.detail


@pytest.mark.parametrize(
    "verdict, expected",
    [
        (Verdict.PROVEN, True),
        (Verdict.VACUOUS, True),
        (Verdict.EMPTY, True),
        (Verdict.NO_EVIDENCE, False),
        (Verdict.NO_TESTS, False),
        (Verdict.BROKEN, False),
        (Verdict.INCONCLUSIVE, False),
    ],
)
def test_which_verdicts_open_the_gate(verdict, expected):
    assert verdict.ok is expected
