"""Detecting installs that let the changed code into the counterfactual.

The counterfactual is only worth anything if the code it runs is the code from
before the change. An editable install — `pip install -e .` — drops a path
entry in site-packages pointing at the *working tree*, so a scratch checkout
that imports the package by name can silently get the new source instead of
the old.

That failure is invisible and it fabricates evidence: the run goes red or green
for reasons that have nothing to do with the base commit. It bites hardest for
a package that does not exist at the base at all, which is exactly when a clean
red matters most.

So falsify looks for it and says so.
"""

from __future__ import annotations

import site
import sysconfig
from pathlib import Path
from typing import Iterable

#: Files that can add an import path without appearing in any config we read.
PATH_FILE_GLOBS = ("*.pth", "__editable__*")


def candidate_site_dirs() -> list[Path]:
    """Every directory this interpreter might load path files from."""
    found: set[str] = set()

    paths = sysconfig.get_paths()
    for key in ("purelib", "platlib"):
        value = paths.get(key)
        if value:
            found.add(value)

    for getter in (site.getsitepackages, site.getusersitepackages):
        try:
            value = getter()
        except (AttributeError, TypeError):
            continue
        if isinstance(value, str):
            found.add(value)
        elif value:
            found.update(value)

    return [Path(p) for p in sorted(found)]


def editable_installs_pointing_at(
    root: Path | str,
    search_dirs: Iterable[Path | str] | None = None,
) -> list[str]:
    """Names of path files that would import code from `root`.

    Returns file names rather than paths so the warning stays readable; the
    point is to tell someone what to uninstall, not where it lives.
    """
    root_str = str(Path(root).resolve())
    dirs = (
        [Path(d) for d in search_dirs]
        if search_dirs is not None
        else candidate_site_dirs()
    )

    hits: set[str] = set()
    for directory in dirs:
        if not directory.is_dir():
            continue
        for pattern in PATH_FILE_GLOBS:
            for path_file in directory.glob(pattern):
                try:
                    text = path_file.read_text(errors="replace")
                except OSError:
                    continue
                if root_str in text:
                    hits.add(path_file.name)
    return sorted(hits)
