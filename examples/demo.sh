#!/usr/bin/env bash
# Build a throwaway repository with a real bug, then show falsify telling the
# difference between a test that catches it and a test that only looks like it.
#
#   ./examples/demo.sh
#
# Nothing outside the scratch directory is touched.

set -euo pipefail

FALSIFY_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/src"
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT

falsify() {
  PYTHONPATH="$FALSIFY_SRC" python3 -m falsify "$@"
}

cd "$SCRATCH"
git init -q -b main .
git config user.email demo@example.com
git config user.name Demo

# --- the bug ------------------------------------------------------------
touch conftest.py
cat > calc.py <<'EOF'
def clamp(value, lo, hi):
    """Constrain value to the range [lo, hi]."""
    if value < lo:
        return lo
    return value
EOF

mkdir -p tests
cat > tests/test_calc.py <<'EOF'
from calc import clamp


def test_below_the_floor_is_raised():
    assert clamp(-5, 0, 10) == 0
EOF

git add -A && git commit -qm "clamp (with a missing upper bound)"

# --- the fix, with a test that does not actually check it ---------------
cat > calc.py <<'EOF'
def clamp(value, lo, hi):
    """Constrain value to the range [lo, hi]."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
EOF

cat > tests/test_calc.py <<'EOF'
from calc import clamp


def test_below_the_floor_is_raised():
    assert clamp(-5, 0, 10) == 0


def test_inside_the_range_is_untouched():
    assert clamp(5, 0, 10) == 5
EOF

echo
echo "=============================================================="
echo " 1. A real fix, shipped with a test that never touches it."
echo "    Every other tool reports this as green."
echo "=============================================================="
echo
set +e
falsify --test-cmd 'python -m pytest -p no:cacheprovider -q {files}'
blocked=$?
set -e
echo "Exit code: $blocked — CI stops here."

# --- the same fix, with a test that would have caught the bug -----------
cat > tests/test_calc.py <<'EOF'
from calc import clamp


def test_below_the_floor_is_raised():
    assert clamp(-5, 0, 10) == 0


def test_above_the_ceiling_is_lowered():
    assert clamp(99, 0, 10) == 10
EOF

echo
echo "=============================================================="
echo " 2. The same fix, with a test that goes red without it."
echo "=============================================================="
echo
set +e
falsify --test-cmd 'python -m pytest -p no:cacheprovider -q {files}'
allowed=$?
set -e
echo "Exit code: $allowed — CI carries on."
