#!/bin/bash
# Rebuild the SPV panels from whatever daily/monthly u10 is on disk, refresh
# the site registry and pages, commit and publish to GitHub Pages.
#
#   ./refresh_site.sh <github-token> [commit-message]
#
# The token is only used for the push; it is never written to disk.
set -e
cd "$(dirname "$0")"

TOKEN="${1:-}"
MSG="${2:-Refresh seasonal graphics}"
if [ -z "$TOKEN" ]; then
  echo "usage: $0 <github-token> [message]" >&2
  exit 1
fi

echo ">> rendering SPV panels"
python3 build_spv_panels.py

echo ">> rebuilding the registry"
python3 build_registry.py

echo ">> rebuilding the site"
python3 build_site.py

echo ">> committing"
git add -A
if git diff --cached --quiet; then
  echo "   nothing to commit"
else
  git -c user.name="MCode" -c user.email="mcode@local" commit -q -m "$MSG"
fi

echo ">> publishing"
./push_to_github.sh "$TOKEN"
