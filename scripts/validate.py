#!/usr/bin/env python3
"""QA gate for Warming Adriatic. Run: make validate.

Checks (all must pass before deploy):
  1. site/data/sst.json exists, parses, and meta.placeholder is false
     (placeholder data is a release blocker).
  2. sst.json ≤ 400 KB.
  3. Every region has years, t and a arrays of the same length (12 per year).
  4. index.html references no external scripts (static, no CDN).
  5. Footer credit string present exactly once.
  6. site/LICENSE-MANIFEST.json parses and lists every file in site/data/.
  7. meta.source names ICOADS (the footer data line renders from it) and the
     manifest's sst.json entry is the real ICOADS source with the exact
     ERDDAP query URL and a fetch date — no PLACEHOLDER anywhere in the
     data provenance (release blocker, AGENTS.md rules 4 and 6).
  8. On-page full disclosure: index.html contains the "Data & method" section
     and sst.json meta carries the provenance fields it renders (query_url,
     fetched date, dataset title, license, coverage cell counts).
  9. SEO/GEO: Open Graph + Twitter cards, theme-color/robots meta, JSON-LD
     (WebSite + Dataset with the exact query URL + FAQPage), robots.txt with
     sitemap line, sitemap.xml, llms.txt with the query URL and license.
  10. Crawler-visible key facts: the static (non-script) numbers in
      index.html (Key facts / FAQ / noscript) are recomputed here from
      sst.json and must match exactly, so they can never drift from the data.
  11. Freshness dates: article:modified_time, sitemap lastmod and the
      llms.txt fetch date must equal meta.fetched.
  12. Landmarks: <main> wraps the content, the fixed status bar has
      role="status", and the horizontal scrollers are keyboard-focusable.
"""

import json
import os
import re
import sys

FAILURES = []


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        FAILURES.append(msg)


def main():
    # 1-2: sst.json
    p = "site/data/sst.json"
    check(os.path.exists(p), "site/data/sst.json exists")
    doc = json.load(open(p))
    meta = doc.get("meta", {})
    check(meta.get("placeholder") is False,
          "meta.placeholder is false (real data at launch; currently %s)" % meta.get("placeholder"))
    size = os.path.getsize(p)
    check(size <= 400 * 1024, f"sst.json size {size} B ≤ 400 KB")

    # 3: structure
    for key in ("north", "central", "south"):
        r = doc["regions"][key]
        n = len(r["years"])
        check(len(r["t"]) == n and len(r["a"]) == n,
              f"{key}: rows aligned ({n} years)")
        check(all(len(row) == 12 for row in r["t"]) and all(len(row) == 12 for row in r["a"]),
              f"{key}: 12 months per year")

    # 4: no external scripts/styles/fonts/CDN — nothing fetched at runtime
    html = open("site/index.html").read()
    # data-honesty: banned claim words must not appear in the static (non-script)
    # markup; JS-rendered text is built from the loaded data only (AGENTS.md rule 5)
    static_html = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
    banned = re.findall(r"\b(record|fastest|unprecedented)\b", static_html, re.I)
    check(not banned, f"no banned claim words in static markup: {banned}")
    ext = re.findall(r"<script[^>]+src=[\"']http", html, re.I)
    check(not ext, "no external script tags")
    extcss = re.findall(r"<link[^>]+href=[\"']http", html, re.I)
    check(not extcss, "no external stylesheets/fonts (link href=http)")
    exturl = re.findall(r"url\(\s*[\"']?https?://", html, re.I)
    check(not exturl, "no external url() in CSS (fonts/images/fonts)")
    extimp = re.findall(r"@import", html, re.I)
    check(not extimp, "no @import in CSS")

    # 5: footer credit exactly once
    credit = "A MareSpot experiment — live Adriatic wind, shelter &amp; sea temperature at"
    check(html.count(credit) == 1, "footer credit rendered exactly once")

    # 6: manifest lists every shipped data file
    man = json.load(open("site/LICENSE-MANIFEST.json"))
    listed = {d["file"].split("/")[-1] for d in man["data"]}
    shipped = {f for f in os.listdir("site/data")}
    check(shipped <= listed, f"all shipped data files are in LICENSE-MANIFEST ({sorted(shipped)})")

    # 7: real-data provenance — footer source names ICOADS, manifest records exact URL + date
    src = str(meta.get("source", ""))
    check("icoads" in src.lower(), f"meta.source names ICOADS (footer renders from it): {src[:90]}")
    coast_entry = next((d for d in man["data"] if d["file"].endswith("coastline.json")), None)
    check(coast_entry is not None and "natural earth" in json.dumps(coast_entry).lower()
          and bool(coast_entry.get("url")) and bool(coast_entry.get("fetched")),
          f"manifest coastline entry names Natural Earth with url+fetched date: "
          f"{str(coast_entry)[:120] if coast_entry else None}")
    sst_entry = next((d for d in man["data"] if d["file"].endswith("sst.json")), None)
    check(sst_entry is not None, "manifest has a data/sst.json entry")
    if sst_entry:
        blob = json.dumps(sst_entry).lower()
        check("placeholder" not in blob, "manifest sst.json entry is not PLACEHOLDER")
        check("upwell.pfeg.noaa.gov/erddap/griddap/" in sst_entry.get("url", ""),
              "manifest sst.json entry has exact ERDDAP query URL")
        check("?sst[(" in sst_entry.get("url", "") and "[(40.5):(45.5)][(12.5):(19.5)]" in sst_entry.get("url", ""),
              "manifest URL carries the Adriatic-box sst query")
        check(bool(sst_entry.get("fetched")), f"manifest sst.json entry has fetch date: {sst_entry.get('fetched')}")
        check("public domain" in sst_entry.get("license", "").lower(),
              f"manifest sst.json license is public domain: {sst_entry.get('license')}")

    # 8: on-page full disclosure — section present in HTML, provenance fields in meta
    check('id="data-method"' in html, "index.html has the Data & method disclosure section")
    check(str(meta.get("query_url", "")).startswith("https://upwell.pfeg.noaa.gov/erddap/griddap/"),
          f"meta.query_url is the exact ERDDAP griddap URL: {str(meta.get('query_url'))[:100]}")
    import re as _re
    check(bool(_re.match(r"^\d{4}-\d{2}-\d{2}$", str(meta.get("fetched", "")))),
          f"meta.fetched is a UTC date: {meta.get('fetched')}")
    check("icoads" in str(meta.get("dataset_title", "")).lower(),
          f"meta.dataset_title names ICOADS: {meta.get('dataset_title')}")
    check(bool(meta.get("license")), "meta.license present")
    cov = meta.get("coverage", {})
    check(isinstance(cov, dict) and cov.get("grid_cells", 0) > 0 and cov.get("sea_cells", 0) > 0,
          f"meta.coverage records grid/sea cell counts: {cov}")

    # 9: SEO/GEO files + structured data
    check('property="og:title"' in html and 'property="og:image"' in html and 'name="twitter:card"' in html,
          "Open Graph + Twitter card meta present (self-contained data-URI image, no external asset)")
    check('name="theme-color"' in html and 'name="robots"' in html and 'name="description"' in html,
          "theme-color + robots + description meta present")
    ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S | re.I)
    check(ld is not None, "JSON-LD structured data present")
    if ld:
        blob = ld.group(1)
        check('"Dataset"' in blob and str(meta.get("query_url", "")) in blob,
              "JSON-LD Dataset distribution carries the exact ERDDAP query URL")
        check('"FAQPage"' in blob and '"WebSite"' in blob, "JSON-LD has WebSite + FAQPage")
    robots = open("site/robots.txt").read() if os.path.exists("site/robots.txt") else ""
    check("Sitemap: https://warming.marespot.com/sitemap.xml" in robots, "robots.txt points at the sitemap")
    sm = open("site/sitemap.xml").read() if os.path.exists("site/sitemap.xml") else ""
    check("<loc>https://warming.marespot.com/</loc>" in sm, "sitemap.xml lists the canonical page URL")
    ll = open("site/llms.txt").read() if os.path.exists("site/llms.txt") else ""
    check(bool(ll) and str(meta.get("query_url", "")) in ll and "public domain" in ll.lower(),
          "llms.txt exists with the exact query URL + license")

    # 10: crawler-visible key facts must equal the shipped data
    y0, y1 = meta["years"]

    def _trend(rows, summer):
        pts = []
        for i, r in enumerate(rows):
            use = [v for j, v in enumerate(r) if (not summer or 5 <= j <= 7) and v is not None]
            if use:
                pts.append([y0 + i, sum(use) / len(use)])
        n = len(pts)
        mx = sum(p[0] for p in pts) / n
        my = sum(p[1] for p in pts) / n
        num = sum((p[0] - mx) * (p[1] - my) for p in pts)
        den = sum((p[0] - mx) ** 2 for p in pts)
        return num / den

    for k in ("north", "central", "south"):
        r = doc["regions"][k]
        ts = _trend(r["a"], True) * 10
        ta = _trend(r["a"], False) * 10
        span = _trend(r["a"], True) * (y1 - y0)
        miss = sum(1 for row in r["a"] for v in row if v is None)
        longest = run = 0
        for row in r["a"]:
            for v in row:
                if v is None:
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 0
        best = by = None
        for i, row in enumerate(r["a"]):
            nn = [v for v in row if v is not None]
            if len(nn) < 9:
                continue
            a = sum(nn) / len(nn)
            if best is None or a > best:
                best, by = a, y0 + i
        facts = [f"{ts:+.2f} °C/decade", f"{span:+.2f} °C", f"{ta:+.2f} °C/decade",
                 f"{by} ({best:+.2f} °C)", f"{miss} of {len(r['a']) * 12}"]
        for s in facts:
            check(s in html, f"static key fact in index.html matches sst.json ({k}): {s!r}")
        for s in (facts[0], facts[4]):
            check(s in ll, f"llms.txt carries the data-matched fact ({k}): {s!r}")

    # 11: freshness dates consistent with the data fetch
    fetched = str(meta.get("fetched", ""))
    check(f'property="article:modified_time" content="{fetched}"' in html, "article:modified_time equals meta.fetched")
    check(f"<lastmod>{fetched}</lastmod>" in sm, "sitemap lastmod equals meta.fetched")
    check(f"Fetched: {fetched}" in ll, "llms.txt fetch date equals meta.fetched")

    # 12: landmarks / keyboard access for scrollers
    check('<main id="main">' in html, "content wrapped in a single <main> landmark")
    check('id="info" role="status"' in html, "fixed status bar has role=status")
    check('tabindex="0"' in html and "row.tabIndex=0" in html, "horizontal scrollers are keyboard-focusable")

    print()
    if FAILURES:
        print("VALIDATION FAILED — do not deploy:")
        for f in FAILURES:
            print(" -", f)
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
