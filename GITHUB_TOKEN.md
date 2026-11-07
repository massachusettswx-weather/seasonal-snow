# Getting a GitHub token (2 minutes)

I need a **Personal Access Token** so I can create the repo, push the site and
turn on GitHub Pages. Here's the exact path:

## 1. Open the token page
Go to **https://github.com/settings/tokens**

## 2. Create one
- Click **"Generate new token"** → **"Generate new token (classic)"**
- Give it a name, e.g. `seasonal-snow-push`
- **Set an expiry** (30 or 90 days is fine — the token is only used once, then
  scrubbed from the remote, but a short expiry is good hygiene anyway)
- **Tick the `repo` scope** — that's the box under "repo" that grants full
  control of private repositories. Public repos need `public_repo`, but tick
  `repo` to be safe. You don't need `workflow` or `delete_repo`.
- Click **Generate token**

## 3. Copy it
GitHub shows the token **once**. It starts with `ghp_` and is about 40
characters. Copy it immediately.

## 4. Paste it here
Reply with the token and I'll run:

```
./push_to_github.sh ghp_yourtoken_here
```

which will:
1. create **`massachusettswx-weather/seasonal-snow`** (public, with Pages on)
2. push `main` (114 files: the site HTML, CSS, JSON and every rendered PNG)
3. enable **Pages → source: main / (root)**
4. wait for the build and give you the live URL

**Security note:** the token goes straight into the git remote URL for the one
push, then the script rewrites the remote back to a clean
`https://github.com/massachusettswx-weather/seasonal-snow.git`. The token is
never written into any committed file, and `.cdsapirc` (your CDS key) is
already excluded by `.gitignore`.

---

## If you'd rather not hand over a token

The site is a plain static folder — `site/` — with no build step and no
server-side code. If you clone or copy that folder to your own machine and
push it yourself, GitHub Pages will serve it as-is. Everything is already
committed on `main` at `/workspace/seas5`.

To regenerate the site after new model data arrives:

```bash
python3 build_registry.py     # collect rendered panels into the registry
python3 build_site.py         # rebuild the HTML/JS
```
