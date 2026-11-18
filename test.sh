#!/bin/sh
# Runs script-scout's tests on the newest stable CPython that uv offers.
# Pre-releases (3.16.0a1) and free-threaded builds are left out; uv downloads the version if needed.
# uv's version comes from one place: VibeConsole's mise.toml (`uv = "<version>"`). The
# Actions workflow reads the same file, so both runs use the same uv (claude-scripts 64).
set -eu
pin_url=https://raw.githubusercontent.com/7kim/VibeConsole/master/mise.toml
pin=$(curl -fsSL "$pin_url" | sed -n 's/^uv = "\([^"]*\)".*/\1/p') || pin=""
if [ -z "$pin" ]; then
    echo "test.sh: can't read uv's version from $pin_url (no network, or no uv = line); nothing was run" >&2
    exit 1
fi
if [ "$(uv --version 2>/dev/null | cut -d' ' -f2)" = "$pin" ]; then
    uv() { command uv "$@"; }
elif command -v mise >/dev/null; then
    uv() { mise exec "uv@$pin" -- uv "$@"; }
else
    echo "test.sh: needs uv $pin (VibeConsole's pin); install it, or install mise" >&2
    exit 1
fi
cd "$(dirname "$0")/skills/script-scout"
latest=$(uv python list --only-downloads | grep -oE '^cpython-[0-9]+\.[0-9]+\.[0-9]+-' | sort -uV | tail -1 | sed 's/^cpython-//; s/-$//')
if [ -z "$latest" ]; then
    echo "test.sh: uv lists no stable CPython to download" >&2
    exit 1
fi
echo "Python $latest (the newest stable uv $(uv --version | cut -d' ' -f2) offers)"
uv run --no-project --python "$latest" python -m unittest -v test_scout 2>&1
