#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
build="$root/build"

rm -rf "$build"
mkdir -p "$build/ask"

uv export --project "$root" --frozen --no-dev --no-default-groups --no-emit-project --no-hashes \
    --output-file "$build/requirements.txt" >/dev/null
uv pip install --quiet \
    --requirements "$build/requirements.txt" \
    --target "$build/ask" \
    --python-platform aarch64-manylinux2014 \
    --python-version 3.13 \
    --only-binary :all:

cp -R "$root/src/rag" "$build/ask/rag"
cp "$root/src/ask/main.py" "$build/ask/"
find "$build/ask" -name "__pycache__" -type d -prune -exec rm -rf {} +

size_mb=$(du -sm "$build/ask" | cut -f1)
echo "build/ask: ${size_mb} MB"
test "$size_mb" -lt 240
