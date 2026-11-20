#!/usr/bin/env python3
"""Build site/data/coastline.json for the locator map on the Warming Adriatic site.

Source: Natural Earth 50m Land (ne_50m_land) — public domain (no rights
reserved), an accepted source per AGENTS.md rule 6. 50m resolution is what
makes the Adriatic islands (Krk, Cres, Pag, Rab, Hvar, Vis, Brač, Korčula,
Lastovo, Mljet, Palagruža, …) visible; 110m was too coarse and rendered the
coast as a blob with no islands.

The raw GeoJSON is downloaded once to cache/ne_50m_land.geojson (gitignored)
and reused on later runs; pass --url to override. Features whose bounding box
intersects the map box are kept (the SVG viewBox does the visual clipping),
coordinates rounded to 0.001 deg (~100 m) to keep the file small. Output is
written to site/data/coastline.json and the coastline entry in
site/LICENSE-MANIFEST.json is updated with the exact source URL and fetch date.

Stdlib only. Run:  python3 scripts/build_coastline.py [--url URL]
"""

import argparse
import json
import os
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
              "master/geojson/ne_50m_land.geojson")
# map box shown in site/index.html drawMap(): lon 11.5-20.5, lat 39.8-47.0
BOX = (11.5, 39.8, 20.5, 47.0)
MARGIN = 0.6
OUT = os.path.join(REPO, "site", "data", "coastline.json")
MANIFEST = os.path.join(REPO, "site", "LICENSE-MANIFEST.json")
CACHE = os.path.join(REPO, "cache", "ne_50m_land.geojson")
UA = {"User-Agent": "adriatic-warming/1.0 (static site map data; Natural Earth public domain)"}


def bbox_of(geom):
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for x in c:
                walk(x)
    walk(geom["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def count_points(c):
    if isinstance(c[0], (int, float)):
        return 1
    return sum(count_points(x) for x in c)


def round_coords(c):
    if isinstance(c[0], (int, float)):
        return [round(c[0], 3), round(c[1], 3)]
    return [round_coords(x) for x in c]


def _perp_dist(p, a, b):
    if a == b:
        return ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2) ** 0.5
    dx, dy = b[0] - a[0], b[1] - a[1]
    return abs(dy * p[0] - dx * p[1] + b[0] * a[1] - b[1] * a[0]) / (dx * dx + dy * dy) ** 0.5


def rdp(ring, eps):
    """Ramer-Douglas-Peucker on a closed ring; endpoints (shared) always kept."""
    if len(ring) < 4:
        return ring
    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        i0, i1 = stack.pop()
        dmax, imax = -1.0, -1
        for i in range(i0 + 1, i1):
            d = _perp_dist(ring[i], ring[i0], ring[i1])
            if d > dmax:
                dmax, imax = d, i
        if dmax > eps:
            keep[imax] = True
            stack.append((i0, imax))
            stack.append((imax, i1))
    return [p for p, k in zip(ring, keep) if k]


def simplify_geom(geom, eps):
    c = geom["coordinates"]
    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [rdp(round_coords(r), eps) for r in c]}
    return {"type": "MultiPolygon", "coordinates": [[rdp(round_coords(r), eps) for r in poly] for poly in c]}


def fetch(url):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    if os.path.exists(CACHE) and os.path.getsize(CACHE) > 100000:
        print(f"using cached {CACHE}")
        return
    print(f"GET {url}")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    open(CACHE, "wb").write(data)
    print(f"cached {len(data)} B -> {CACHE}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=SOURCE_URL)
    ap.add_argument("--eps", type=float, default=0.002,
                    help="Douglas-Peucker tolerance in degrees (~0.002 deg ~ 220 m); keeps islands")
    args = ap.parse_args()
    fetch(args.url)
    raw = json.load(open(CACHE, encoding="utf-8"))
    lo0, la0, lo1, la1 = BOX[0] - MARGIN, BOX[1] - MARGIN, BOX[2] + MARGIN, BOX[3] + MARGIN

    def intersects(b):
        return not (b[2] < lo0 or b[0] > lo1 or b[3] < la0 or b[1] > la1)

    kept = []
    npts = 0
    for f in raw["features"]:
        g = f["geometry"]
        if g["type"] not in ("Polygon", "MultiPolygon"):
            continue
        if not intersects(bbox_of(g)):
            continue
        geom = simplify_geom(g, args.eps)
        npts += count_points(geom["coordinates"])
        kept.append({"type": "Feature", "properties": {}, "geometry": geom})
    out = {"type": "FeatureCollection",
           "meta": {"source": "Natural Earth 50m Land (ne_50m_land), public domain",
                    "source_url": args.url,
                    "fetched": time.strftime("%Y-%m-%d", time.gmtime()),
                    "box": list(BOX)},
           "features": kept}
    json.dump(out, open(OUT, "w"), separators=(",", ":"), ensure_ascii=False)
    size = os.path.getsize(OUT)
    print(f"wrote {OUT}: {len(kept)} land features, {npts} points, {size} B "
          f"(box lon {BOX[0]}-{BOX[2]}, lat {BOX[1]}-{BOX[3]})")

    man = json.load(open(MANIFEST, encoding="utf-8"))
    fetched = time.strftime("%Y-%m-%d", time.gmtime())
    for d in man["data"]:
        if d["file"].endswith("coastline.json"):
            d.update({
                "source": "Natural Earth 50m Land (ne_50m_land), clipped to the Adriatic map box "
                          f"lon {BOX[0]}-{BOX[2]}, lat {BOX[1]}-{BOX[3]}",
                "author": "Natural Earth (naturalearthdata.com)",
                "license": "Public domain (no rights reserved)",
                "url": args.url,
                "fetched": fetched,
                "note": "50m resolution chosen so the Adriatic islands render (110m was a blob); "
                        "rings simplified with Douglas-Peucker (eps 0.002 deg) to keep the file small. "
                        "Regenerate with `make coastline` (scripts/build_coastline.py, stdlib only); "
                        "raw GeoJSON cached in cache/ (gitignored).",
                "displayed": "region locator map",
            })
    man["updated"] = fetched
    json.dump(man, open(MANIFEST, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    open(MANIFEST, "a", encoding="utf-8").write("\n")
    print(f"updated {MANIFEST} coastline entry (url + fetched {fetched})")


if __name__ == "__main__":
    main()
