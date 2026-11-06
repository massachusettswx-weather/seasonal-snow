#!/usr/bin/env bash
# Create the GitHub repo (if needed) and push this project.
#
#   ./push_to_github.sh <github_token> [repo_name]
#
# The token needs the "repo" scope (classic) or Contents:Read-write
# (fine-grained).  It is used once and then scrubbed from the git remote.
set -euo pipefail

TOKEN="${1:?usage: ./push_to_github.sh <github_token> [repo_name]}"
REPO="${2:-seasonal-snow}"
ORG="${GITHUB_ORG:-massachusettswx-weather}"
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

echo ">> ensuring repo ${ORG}/${REPO} exists"
code=$(curl -s -o /tmp/repo.json -w '%{http_code}' -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/orgs/${ORG}/repos" \
  -d "{\"name\":\"${REPO}\",\"private\":false,\"has_pages\":true,\"description\":\"Seasonal snowfall anomaly maps from ECMWF SEAS5 and other seasonal prediction systems\"}")
if [ "$code" = "201" ]; then
  echo "   created"
elif [ "$code" = "422" ]; then
  echo "   already exists"
else
  echo "   WARNING: could not confirm repo creation (HTTP $code):"
  head -c 400 /tmp/repo.json; echo
fi

echo ">> pushing"
git remote remove origin 2>/dev/null || true
git remote add origin "https://${TOKEN}@github.com/${ORG}/${REPO}.git"
git push -u origin main
git remote set-url origin "https://github.com/${ORG}/${REPO}.git"

echo
echo "Pushed to https://github.com/${ORG}/${REPO}"
echo "Enable Pages: Settings -> Pages -> Source: main / (root)"
