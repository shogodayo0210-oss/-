"""Detecting installs that leak the working tree into the counterfactual.

Found the hard way: falsify reported PROVEN on a change that added a brand new
package, because `pip install -e .` had put the working tree on the import
path. The scratch checkout imported the new code, went red for an unrelated
reason, and the verdict looked like evidence.
"""

from __future__ import annotations

import pytest

from falsify.check import Verdict, check
from falsify.leaks import candidate_site_dirs, editable_installs_pointing_at

from conftest import FIXED_SOURCE, STRONG_TEST, TEST_CMD


def test_a_pth_file_naming_the_repo_is_found(tmp_path):
    repo = tmp_path / "project"
    (repo / "src").mkdir(parents=True)
    site_dir = tmp_path / "site-packages"
    site_dir.mkdir()
    (site_dir / "__editable__.thing-0.1.0.pth").write_text(f"{repo / 'src'}\n")

    assert editable_installs_pointing_at(repo, [site_dir]) == [
        "__editable__.thing-0.1.0.pth"
    ]


def test_an_editable_loader_module_is_found_too(tmp_path):
    # Newer pip writes a __editable___*.py finder rather than a bare path.
    repo = tmp_path / "project"
    repo.mkdir()
    site_dir = tmp_path / "site-packages"
    site_dir.mkdir()
    (site_dir / "__editable___thing_0_1_0_finder.py").write_text(
        f"MAPPING = {{'thing': '{repo}/src'}}\n"
    )

    assert editable_installs_pointing_at(repo, [site_dir]) == [
        "__editable___thing_0_1_0_finder.py"
    ]


def test_unrelated_path_files_are_ignored(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    site_dir = tmp_path / "site-packages"
    site_dir.mkdir()
    (site_dir / "other.pth").write_text("/somewhere/else\n")
    (site_dir / "distutils-precedence.pth").write_text("import os\n")

    assert editable_installs_pointing_at(repo, [site_dir]) == []


def test_a_missing_search_directory_is_not_an_error(tmp_path):
    assert editable_installs_pointing_at(tmp_path, [tmp_path / "nope"]) == []


def test_an_unreadable_path_file_does_not_crash_the_check(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    site_dir = tmp_path / "site-packages"
    site_dir.mkdir()
    unreadable = site_dir / "locked.pth"
    unreadable.write_text(str(repo))
    unreadable.chmod(0o000)
    try:
        # Whether it is readable depends on the user; either way, no exception.
        editable_installs_pointing_at(repo, [site_dir])
    finally:
        unreadable.chmod(0o644)


def test_candidate_dirs_are_real_paths():
    dirs = candidate_site_dirs()
    assert dirs, "an interpreter always has somewhere to install into"
    assert all(d.is_absolute() for d in dirs)


def test_the_warning_reaches_the_report(repo, tmp_path, monkeypatch):
    site_dir = tmp_path / "site-packages"
    site_dir.mkdir()
    (site_dir / "__editable__.demo-1.0.pth").write_text(f"{repo.path}/src\n")
    monkeypatch.setattr(
        "falsify.leaks.candidate_site_dirs", lambda: [site_dir]
    )

    repo.write("calc.py", FIXED_SOURCE)
    repo.write("tests/test_calc.py", STRONG_TEST)

    report = check(repo=repo.path, test_cmd=TEST_CMD)

    # The verdict still stands on the evidence; the warning tells the reader
    # how much that evidence is worth.
    assert report.verdict is Verdict.PROVEN
    assert any("editable install" in w for w in report.warnings)
    assert any("PYTHONPATH=src" in w for w in report.warnings)


def test_no_warning_when_nothing_points_at_the_repo(repo, tmp_path, monkeypatch):
    site_dir = tmp_path / "site-packages"
    site_dir.mkdir()
    monkeypatch.setattr("falsify.leaks.candidate_site_dirs", lambda: [site_dir])

    repo.write("calc.py", FIXED_SOURCE)
    repo.write("tests/test_calc.py", STRONG_TEST)

    report = check(repo=repo.path, test_cmd=TEST_CMD)

    assert not any("editable install" in w for w in report.warnings)
