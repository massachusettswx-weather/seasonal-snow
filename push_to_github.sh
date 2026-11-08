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

# GitHub Pages: the static site lives in docs/ -> publish from branch main, path /docs
# (the repo root holds the pipeline code and must NOT be the published root).
pages_set () {
  curl -s -o /tmp/pages.json -w '%{http_code}' -X "$1" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${OWNER}/${REPO}/pages" \
    -d '{"source":{"branch":"main","path":"/docs"},"build_type":"legacy"}'
}
code=$(pages_set POST)
if [ "$code" = "409" ]; then
  code=$(pages_set PUT)          # already enabled -> update the source path
fi
case "$code" in
  200|201|204) echo "Pages configured (source: main /docs)" ;;
  *) echo "NOTE: could not set Pages automatically (HTTP $code) - set it in"
     echo "      Settings -> Pages -> Source: Deploy from a branch -> main /docs."
     head -c 300 /tmp/pages.json; echo ;;
esac

echo ">> waiting for the build to finish"
url=""
for i in $(seq 1 40); do
  sleep 15
  read -r st url < <(curl -s -H "Authorization: Bearer ${TOKEN}" \
    "https://api.github.com/repos/${OWNER}/${REPO}/pages" | \
    python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('status',''),d.get('html_url',''))" 2>/dev/null || echo " ")
  if [ "$st" = "built" ] && [ -n "$url" ]; then break; fi
  printf "."
done
echo
echo "Pages status: ${st:-unknown}"

# html_url exists even when the build failed, so check the content actually serves.
echo ">> verifying the published pages"
for p in "" "model.html" "snow.html" "spv.html" "assets/css/style.css"; do
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 30 "${url}${p}")
  printf "  %-28s %s\n" "/${p}" "$c"
  [ "$c" = "200" ] || echo "  WARNING: ${p} did not serve (HTTP ${c})"
done

echo
echo "Site live at: ${url}"
