"""Check the published site: pages load, no broken images, no console errors.

    python3 verify_site.py [base-url]
"""
import asyncio
import sys

BASE = sys.argv[1] if len(sys.argv) > 1 else \
    "https://massachusettswx-weather.github.io/seasonal-snow/"
PAGES = ("index.html", "model.html", "snow.html", "spv.html")


async def main():
    from playwright.async_api import async_playwright
    ok = True
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1400, "height": 1000})
        errs, bad = [], []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("response", lambda r: bad.append((r.status, r.url)) if r.status >= 400 else None)
        for page in PAGES:
            r = await pg.goto(BASE + page, wait_until="networkidle", timeout=90000)
            await pg.wait_for_timeout(1200)
            widths = await pg.evaluate(
                "Array.from(document.images).map(i=>i.naturalWidth)")
            broken = sum(1 for w in widths if w == 0)
            body = (await pg.inner_text("body")).lower()
            note = []
            if "weathermodels" in body:
                note.append("mentions weathermodels")
                ok = False
            if broken:
                note.append("%d broken image(s)" % broken)
                ok = False
            if r.status != 200:
                note.append("HTTP %s" % r.status)
                ok = False
            print("%-12s status %s  images %3d  broken %d %s"
                  % (page, r.status, len(widths), broken,
                     ("  <-- " + "; ".join(note)) if note else ""))
        if errs:
            ok = False
        if bad:
            ok = False
        print("console errors: %d   http>=400: %d" % (len(errs), len(bad)))
        for e in errs[:5]:
            print("   ERR", e)
        for s, u in bad[:5]:
            print("   HTTP", s, u)
        await b.close()
    print("SITE OK" if ok else "SITE HAS PROBLEMS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
