#!/bin/sh
# Runs script-scout's tests on the newest stable CPython that uv offers.
# Pre-releases (3.16.0a1) and free-threaded builds are left out; uv downloads the version if needed.
set -eu
cd "$(dirname "$0")/skills/script-scout"
latest=$(uv python list --only-downloads | grep -oE '^cpython-[0-9]+\.[0-9]+\.[0-9]+-' | sort -uV | tail -1 | sed 's/^cpython-//; s/-$//')
if [ -z "$latest" ]; then
    echo "test.sh: uv lists no stable CPython to download" >&2
    exit 1
fi
echo "Python $latest (the newest stable uv $(uv --version | cut -d' ' -f2) offers)"
uv run --no-project --python "$latest" python -m unittest -v test_scout 2>&1
