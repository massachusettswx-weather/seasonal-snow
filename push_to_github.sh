#!/usr/bin/env bash
# Create the GitHub repo (if needed), push this project and enable Pages.
#
#   ./push_to_github.sh <github_token> [repo_name]
#
# The token needs the "repo" scope (classic) or Contents:Read+write
# (fine-grained).  It is used once and then scrubbed from the git remote.
#
# How to get a token:
#   1. https://github.com/settings/tokens  ->  "Generate new token (classic)"
#   2. Tick the "repo" scope (and "workflow" if you want Actions).
#   3. Copy it once - GitHub only shows it at creation time.
set -euo pipefail

TOKEN="${1:?usage: ./push_to_github.sh <github_token> [repo_name]}"
REPO="${2:-seasonal-snow}"
OWNER="${GITHUB_OWNER:-massachusettswx-weather}"
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

if [ -z "$(git status --porcelain)" ]; then
  echo ">> working tree clean"
else
  git add -A
  git -c user.name="MCode" -c user.email="mcode@local" commit -q -m "Update site assets"
  echo ">> committed outstanding changes"
fi

echo ">> ensuring repo ${OWNER}/${REPO} exists"
code=$(curl -s -o /tmp/repo.json -w '%{http_code}' -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/user/repos" \
  -d "{\"name\":\"${REPO}\",\"private\":false,\"has_pages\":true,\"description\":\"Seasonal snowfall and 10 hPa zonal wind graphics from ECMWF SEAS5 and other seasonal prediction systems\"}")
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
git remote add origin "https://${TOKEN}@github.com/${OWNER}/${REPO}.git"
git push -u origin main
git remote set-url origin "https://github.com/${OWNER}/${REPO}.git"

echo
echo "Pushed to https://github.com/${OWNER}/${REPO}"

# enable GitHub Pages (source: main / root)
code=$(curl -s -o /tmp/pages.json -w '%{http_code}' -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${OWNER}/${REPO}/pages" \
  -d '{"source":{"branch":"main","path":"/"}}')
if [ "$code" = "201" ]; then
  echo "Pages enabled (source: main / root)"
elif [ "$code" = "409" ]; then
  echo "Pages already enabled"
else
  echo "NOTE: could not enable Pages automatically (HTTP $code) - enable it in"
  echo "      Settings -> Pages -> Source: main / (root) by hand."
  head -c 300 /tmp/pages.json; echo
fi

echo ">> waiting for the site to publish"
for i in $(seq 1 20); do
  sleep 15
  url=$(curl -s -H "Authorization: Bearer ${TOKEN}" \
    "https://api.github.com/repos/${OWNER}/${REPO}/pages" | \
    python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('html_url',''))" 2>/dev/null || true)
  if [ -n "$url" ]; then
    echo
    echo "Site live at: ${url}"
    exit 0
  fi
  printf "."
done
echo
echo "Pages is building - check https://github.com/${OWNER}/${REPO}/pages"
