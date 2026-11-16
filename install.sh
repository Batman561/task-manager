#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1 \
        && "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
        exec "$candidate" install.py "$@"
    fi
done

echo "پایتون ۳.۱۰ یا جدیدتر پیدا نشد. اول پایتون را نصب کن." >&2
exit 1
