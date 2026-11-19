#!/usr/bin/env python3
"""Generate site/data/sst.json for the Warming Adriatic site.

Real mode (default):
  Fetches monthly-mean sea surface temperature for the Adriatic box
  (lon 12.5-19.5, lat 40.5-45.5) from NOAA's public ERDDAP at
  upwell.pfeg.noaa.gov -> dataset "ICOADS 1-degree Enhanced (sst.mean),
  1960-present" (public domain, US Government work, no key required).
  Aggregates the 1-degree cells into three sub-basins, computes monthly
  anomalies against the 1991-2020 baseline, and writes compact JSON.

Placeholder mode (--placeholder):
  Generates a deterministic, clearly-labeled SAMPLE series (seasonal cycle +
  plausible warming trend) so the layout can be previewed before the real
  pipeline runs. Shipping placeholder data to production is FORBIDDEN
  (see AGENTS.md rule 4).

Stdlib only: no pandas / numpy / pip. Run:  python3 scripts/fetch_sst.py [--placeholder]
"""

import argparse
import csv
import io
import json
import math
import random
import sys
import time
import urllib.request

ERDDAP = ("https://upwell.pfeg.noaa.gov/erddap/griddap/"
          "noaa_psl_3a7b_f45b_d09a.csv"
          "?sst[(1960-01-01T00:00:00Z):(2025-12-31T00:00:00Z)]"
          "[(40.5):(45.5)][(12.5):(19.5)]")

# Median month dates ICOADS uses, e.g. 1960-01-16T00:00:00Z

REGIONS = [
    ("north", "North Adriatic", "The shallow basin: Gulf of Trieste to the Kvarner and Zadar archipelago. Warms fastest in a warming climate.", 43.6),
    ("central", "Central Adriatic", "From the Kornati and Split channel down to the Palagru\u017ea sill.", 41.8),
    ("south", "South Adriatic", "The deep southern basin and Otranto Strait. Most stable of the three.", 0.0),
]

BASELINE = (1991, 2020)  # WMO standard climate normal period


def region_for(lat):
    for key, name, desc, cutoff in REGIONS:
        if lat >= cutoff:
            return key
    return REGIONS[-1][0]


def fetch_real():
    req = urllib.request.Request(ERDDAP, headers={"User-Agent": "adriatic-warming/0.1 (static site data pipeline)"})
    with urllib.request.urlopen(req, timeout=240) as r:
        raw = r.read().decode("utf-8")
    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)
    # ERDDAP griddap CSV: row 0 = variable names, row 1 = units, then data
    data = {}   # (region, year, month) -> [temps]
    labels = {} # (region, year, month) -> [lat, lon]
    n = 0
    for row in rows[2:]:
        ts, lat_s, lon_s, sst_s = row[0], row[1], row[2], row[3]
        lat, lon = float(lat_s), float(lon_s)
        year = int(ts[0:4]); month = int(ts[5:7])
        if sst_s in ("NaN", ""):
            continue
        t = float(sst_s)
        if t < -2.0 or t > 40.0:  # bogus value hygiene
            continue
        key = region_for(lat)
        data.setdefault((key, year, month), []).append(t)
        labels.setdefault((key, year, month), set()).add((lat, lon))  # type: ignore
        n += 1
    if not data:
        raise SystemExit("No data rows returned from ERDDAP. "
                         "Endpoint may be down or rate-limited; retry later.")
    cells = {}
    for (key, _, _), cellset in labels.items():  # type: ignore
        cells[key] = max(cells.get(key, 0), len(cellset))
    print(f"parsed {n} valid cell-months; cells per region: {cells}")
    return data, cells


def monthly_series(data):
    """(region) -> { (year, month): (mean_temp, n_cells) }"""
    out = {}
    for (key, year, month), temps in data.items():
        out.setdefault(key, {})[(year, month)] = (sum(temps) / len(temps), len(temps))
    return out


def climatology(series):
    """region -> { month: baseline_mean } over BASELINE period"""
    clim = {}
    for key, months in series.items():
        acc = {}
        for (year, month), (t, _n) in months.items():
            if BASELINE[0] <= year <= BASELINE[1]:
                acc.setdefault(month, []).append(t)
        clim[key] = {m: sum(v) / len(v) for m, v in acc.items()}
    return clim


def years_span(series):
    ylo = min(y for k in series for (y, m) in series[k])
    yhi = max(y for k in series for (y, m) in series[k])
    # keep full years only
    yhi = min(yhi, time.gmtime().tm_year - 1) if yhi >= time.gmtime().tm_year else yhi
    return ylo, yhi


def build_real(series, clim, cells, out_path):
    ylo, yhi = years_span(series)
    out = {"meta": {"placeholder": False, "generated": time.strftime("%Y-%m-%d"),
                    "source": "NOAA/ERSL ICOADS 1-degree Enhanced monthly SST (public domain), via upwell.pfeg.noaa.gov ERDDAP",
                    "baseline": f"{BASELINE[0]}\u2013{BASELINE[1]} monthly means",
                    "years": [ylo, yhi], "unit": "deg C",
                    "cells": cells},
           "regions": {}}
    for key, name, desc, _c in REGIONS:
        months = series.get(key, {})
        cl = clim.get(key, {})
        years, ts, As, cov = [], [], [], []
        for y in range(ylo, yhi + 1):
            row_t, row_a, row_n = [], [], []
            for m in range(1, 13):
                if (y, m) in months and m in cl:
                    t, n = months[(y, m)]
                    a = t - cl[m]
                    row_t.append(round(t, 1)); row_a.append(round(a, 2)); row_n.append(n)
                else:
                    row_t.append(None); row_a.append(None); row_n.append(0)
            years.append(y); ts.append(row_t); As.append(row_a); cov.append(row_n)
        out["regions"][key] = {"name": name, "desc": desc, "years": years,
                              "t": ts, "a": As, "n": cov}
    json.dump(out, open(out_path, "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"wrote {out_path} ({ylo}-{yhi})")
    qa(out)


def build_placeholder(out_path):
    rng = random.Random(42)
    ylo, yhi = 1960, 2025
    prof = {"north": (16.6, 10.6, 0.030), "central": (18.0, 9.6, 0.024), "south": (19.4, 8.6, 0.018)}
    # deterministic warm-summer touches (European heatwave years), north-heavier
    bumps = {(2003, m): (1.3, 1.0, 0.8) for m in (6, 7, 8)}
    bumps.update({(2022, m): (1.0, 0.8, 0.6) for m in (7, 8)})
    bumps.update({(2024, m): (1.1, 0.9, 0.7) for m in (6, 7, 8)})
    raw = {}
    for key, (mean, amp, trend) in prof.items():
        for y in range(ylo, yhi + 1):
            for m in range(1, 13):
                seas = math.cos((m - 8) / 12 * 2 * math.pi) * amp  # peak ~August
                t = mean + seas + trend * (y - ylo) + rng.gauss(0, 0.35)
                t += bumps.get((y, m), (0, 0, 0))[{"north": 0, "central": 1, "south": 2}[key]]
                raw.setdefault(key, {})[(y, m)] = (t, 4)
    series = monthly_series({(k, y, m): [t] for k, d in raw.items() for (y, m), (t, _n) in d.items()})
    clim = climatology(series)
    # placeholder meta then reuse real builder for structure
    cells = {"north": 9, "central": 8, "south": 6}
    out_path_write = out_path
    build_real_with_meta = True
    # generate structure by calling build_real, then patch meta
    build_real(series, clim, cells, out_path_write)
    doc = json.load(open(out_path_write))
    doc["meta"].update({"placeholder": True,
                        "source": "PLACEHOLDER: deterministic sample series generated by scripts/fetch_sst.py --placeholder (CC0, by this project). Illustrative numbers, not measurements."})
    doc["meta"]["cells"] = cells
    json.dump(doc, open(out_path_write, "w"), separators=(",", ":"), ensure_ascii=False)
    print("wrote PLACEHOLDER data; meta.placeholder = true (must be false at launch)")


def qa(doc):
    print("\nQA summary (trend = linear slope of annual means, per decade):")
    for key in ("north", "central", "south"):
        r = doc["regions"][key]
        years = r["years"]; ts = r["t"]
        pts = [(y, sum(x for x in row if x is not None) / sum(1 for x in row if x is not None))
               for y, row in zip(years, ts) if any(x is not None for x in row)]
        n = len(pts)
        mx = sum(p[0] for p in pts) / n; my = sum(p[1] for p in pts) / n
        num = sum((p[0] - mx) * (p[1] - my) for p in pts)
        den = sum((p[0] - mx) ** 2 for p in pts)
        slope_per_decade = (num / den) * 10 if den else 0
        print(f"  {key:8s}: {n} years, {slope_per_decade:+.2f} \u00b0C/decade")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placeholder", action="store_true", help="generate labeled sample data instead of fetching")
    ap.add_argument("--out", default="site/data/sst.json")
    args = ap.parse_args()
    if args.placeholder:
        build_placeholder(args.out)
    else:
        data, cells = fetch_real()
        series = monthly_series(data)
        clim = climatology(series)
        build_real(series, clim, cells, args.out)


if __name__ == "__main__":
    main()
