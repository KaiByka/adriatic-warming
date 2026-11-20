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

    # 4: no external scripts
    html = open("site/index.html").read()
    ext = re.findall(r"<script[^>]+src=[\"']http", html, re.I)
    check(not ext, "no external script tags")

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

    print()
    if FAILURES:
        print("VALIDATION FAILED — do not deploy:")
        for f in FAILURES:
            print(" -", f)
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
