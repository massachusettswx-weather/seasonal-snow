#!/usr/bin/env bash
# Store the GitHub token and restart the publisher with it.
#
#   ./set_github_token.sh <github-token>
#
# The token is written to data/.github_token with mode 600 (gitignored), so it
# never appears in the git history, in a committed file, or in the process
# list - the publisher reads it from the file.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

TOKEN="${1:?usage: ./set_github_token.sh <github-token>}"
TOKFILE="data/.github_token"
mkdir -p data
printf '%s' "$TOKEN" > "$TOKFILE"
chmod 600 "$TOKFILE"

code=$(curl -s -o /dev/null -w '%{http_code}' -m 25 \
    -H "Authorization: token $TOKEN" https://api.github.com/user)
if [ "$code" != "200" ]; then
    echo "the token was not accepted (HTTP $code) - it has been stored but the publisher was not restarted" >&2
    exit 1
fi
echo "the token works."

# stop only the publisher; the CDS pool must keep running
python3 tools/stopall.py auto_publish 2>/dev/null || true
sleep 2
(setsid nohup ./auto_publish.sh > /dev/null 2>&1 < /dev/null &)
sleep 3
echo "the publisher is running again."
