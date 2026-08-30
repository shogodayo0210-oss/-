"""Classifying paths and picking a runner."""

from __future__ import annotations

import pytest

from falsify.detect import (
    PYTEST,
    Runner,
    build_command,
    custom_runner,
    detect_runner,
    is_test_path,
    split_paths,
)


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_calc.py",
        "test_calc.py",
        "calc_test.py",
        "conftest.py",
        "internal/server_test.go",
        "src/components/Button.test.tsx",
        "src/components/Button.spec.ts",
        "spec/models/user_spec.rb",
        "__tests__/helpers.js",
        "src/test/java/AppTest.java",
    ],
)
def test_recognised_as_tests(path):
    assert is_test_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "calc.py",
        "src/falsify/check.py",
        "README.md",
        "internal/server.go",
        "src/components/Button.tsx",
        # "latest" contains "test" as a substring; it is not a test directory.
        "src/latest/index.ts",
        # A protest module is not a test module.
        "src/protest.py",
    ],
)
def test_not_mistaken_for_tests(path):
    assert not is_test_path(path)


@pytest.mark.parametrize(
    "path",
    [
        # Sits under tests/ and would otherwise classify as a test, which was
        # enough to make the tool warn about its own bytecode.
        "tests/__pycache__/test_calc.cpython-311.pyc",
        "tests/fixtures/build/artifact.so",
        "node_modules/some-lib/__tests__/index.js",
        "spec/vendor/thing.class",
    ],
)
def test_build_output_under_a_test_directory_is_not_a_test(path):
    assert not is_test_path(path)


def test_extra_globs_extend_the_rule():
    assert not is_test_path("checks/smoke_check.py")
    assert is_test_path("checks/smoke_check.py", ["*_check.py"])
    assert is_test_path("checks/smoke_check.py", ["checks/*"])


def test_split_keeps_order_within_each_side():
    tests, source = split_paths(
        ["calc.py", "tests/test_calc.py", "util.py", "test_extra.py"]
    )
    assert tests == ["tests/test_calc.py", "test_extra.py"]
    assert source == ["calc.py", "util.py"]


def test_command_is_scoped_to_the_changed_tests():
    assert (
        build_command(PYTEST, ["tests/test_a.py", "tests/test_b.py"])
        == "python -m pytest tests/test_a.py tests/test_b.py"
    )


def test_paths_with_spaces_are_quoted():
    command = build_command(PYTEST, ["tests/my tests/test_a.py"])
    assert "'tests/my tests/test_a.py'" in command


def test_a_runner_without_the_placeholder_runs_everything():
    whole_suite = Runner("cargo", "cargo test")
    assert not whole_suite.scopes_to_files
    assert build_command(whole_suite, ["tests/a.rs"]) == "cargo test"


def test_pytest_separates_failing_tests_from_a_broken_run():
    assert PYTEST.failure_exit_codes == (1,)


@pytest.mark.parametrize(
    "marker, expected",
    [
        ("pyproject.toml", "pytest"),
        ("go.mod", "go"),
        ("Cargo.toml", "cargo"),
        ("package.json", "npm"),
    ],
)
def test_runner_detected_from_marker_files(tmp_path, marker, expected):
    (tmp_path / marker).write_text("")
    runner = detect_runner(tmp_path)
    assert runner is not None and runner.name == expected


def test_a_bare_tests_directory_is_enough_for_pytest(tmp_path):
    (tmp_path / "tests").mkdir()
    runner = detect_runner(tmp_path)
    assert runner is not None and runner.name == "pytest"


def test_nothing_recognisable_gives_no_runner(tmp_path):
    assert detect_runner(tmp_path) is None


@pytest.mark.parametrize(
    "template",
    [
        "pytest {files}",
        "python -m pytest -q {files}",
        "uv run PyTest {files}",
    ],
)
def test_a_custom_pytest_command_keeps_pytest_exit_codes(template):
    # Otherwise a collection error (exit 2) would be read as a failing test,
    # and a run that broke would be reported as evidence.
    assert custom_runner(template).failure_exit_codes == (1,)


def test_an_unrecognised_custom_command_treats_any_failure_as_a_failure():
    runner = custom_runner("./run-my-tests.sh {files}")
    assert runner.failure_exit_codes == ()
    assert runner.scopes_to_files
