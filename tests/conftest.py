"""Make the package importable from the checkout.

Deliberately not relying on an installed copy: an editable install resolves
to whatever is in the working tree, which is exactly the ambiguity these
tests should not have.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
