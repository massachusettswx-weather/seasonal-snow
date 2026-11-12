#!/bin/bash
# Rebuild the SPV panels from whatever daily/monthly u10 is on disk, refresh
# the site registry and pages, commit and publish to GitHub Pages.
#
#   ./refresh_site.sh <github-token> [commit-message]
#
# The token is only used for the push; it is never written to disk.
set -e
cd "$(dirname "$0")"

MSG="${2:-Refresh seasonal graphics}"
# The token is read from data/.github_token (mode 600, gitignored) so it
# never appears in the process list.  An argument is only used when it is a
# real token.
TOKEN="${1:-}"
if [ -z "$TOKEN" ] || [ "$TOKEN" = "none" ]; then
    TOKEN="$(cat data/.github_token 2>/dev/null || true)"
    PUSH_ARG=""
else
    PUSH_ARG="$TOKEN"
fi
if [ -z "$TOKEN" ]; then
  echo "usage: $0 <github-token|empty> [message]" >&2
  echo "   (or put the token in data/.github_token)" >&2
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

# SKIP_PUSH=1 builds and commits everything but does not push - used when the
# token has been revoked, so the site stays current locally and one push
# publishes it.
if [ "${SKIP_PUSH:-0}" = "1" ]; then
    echo ">> not pushing (no working token) - the site is current locally"
else
    echo ">> publishing"
    ./push_to_github.sh "$PUSH_ARG"
fi
