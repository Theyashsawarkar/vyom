#!/bin/bash
# vendor-keys.sh: copies Vyom's keys module (vyom/keys.py: vim keys as data,
# pure Python) into another repo, for the Python tools outside Vyom (vesha,
# vishvakarma, nada, drishya, vinyasa, dvarapala, pramana). A vendored copy
# because those tools install by symlink or kosha copy, and dvarapala and
# pramana load root-owned files by path under `python3 -I`: they can't import
# anything from a home directory. The copy starts with a header naming the
# version and the hash of the source, so a stale copy is easy to find.
#
#   scripts/vendor-keys.sh <target-file>           write (or update) the copy
#   scripts/vendor-keys.sh --check <target-file>   exit 1 if the copy isn't this keys.py
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
src="$here/vyom/keys.py"
check=0
if [ "${1:-}" = "--check" ]; then check=1; shift; fi
case "${1:-}" in -h|--help|-*) echo "usage: $0 [--check] <target-file>" >&2; exit 2;; esac
[ $# -eq 1 ] || { echo "usage: $0 [--check] <target-file>" >&2; exit 2; }
target=$1
version=$(sed -n 's/^KEYS_VERSION = "\(.*\)"/\1/p' "$src")
hash=$(sha256sum "$src" | cut -c1-16)
header="# Vendored from Vyom's vyom/keys.py v$version (sha256 $hash) by scripts/vendor-keys.sh: don't edit here, change it in Vyom and vendor it again."
if [ $check = 1 ]; then
  [ -f "$target" ] || { echo "$target: missing (run $0 $target)" >&2; exit 1; }
  if [ "$(head -1 "$target")" = "$header" ] && diff -q <(tail -n +2 "$target") "$src" >/dev/null; then
    echo "$target: up to date (keys v$version)"
    exit 0
  fi
  echo "$target: not Vyom's keys.py v$version ($hash): run $0 $target" >&2
  exit 1
fi
mkdir -p "$(dirname "$target")"
{ echo "$header"; cat "$src"; } > "$target"
echo "wrote $target (keys v$version)"
