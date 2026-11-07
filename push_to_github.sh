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

# enable GitHub Pages (source: main / root) - needs a public repo
code=$(curl -s -o /tmp/pages.json -w '%{http_code}' -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${ORG}/${REPO}/pages" \
  -d '{"source":{"branch":"main","path":"/"}}')
if [ "$code" = "201" ] || [ "$code" = "409" ]; then
  echo "Pages enabled (source: main / root)"
  for i in $(seq 1 12); do
    sleep 15
    url=$(curl -s -H "Authorization: Bearer ${TOKEN}" \
      "https://api.github.com/repos/${ORG}/${REPO}/pages" | \
      python3 -c "import json,sys;print(json.load(sys.stdin).get('html_url',''))" 2>/dev/null || true)
    if [ -n "$url" ]; then
      echo "Site live at: ${url}"
      break
    fi
  done
else
  echo "NOTE: could not enable Pages automatically (HTTP $code) - enable it in"
  echo "      Settings -> Pages -> Source: main / (root) by hand."
  head -c 300 /tmp/pages.json; echo
fi
