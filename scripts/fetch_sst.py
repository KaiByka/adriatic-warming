#!/usr/bin/env python3
"""Generate site/data/sst.json for the Warming Adriatic site.

Real mode (default):
  Fetches monthly-mean sea surface temperature for the Adriatic box
  (lon 12.5-19.5, lat 40.5-45.5) from NOAA's public ERDDAP at
  upwell.pfeg.noaa.gov -> dataset "ICOADS 1-degree Enhanced (sst.mean),
  1960-present" (public domain, US Government work, no key required).
  Aggregates the 1-degree cells into three sub-basins, computes monthly
  anomalies against the 1991-2020 baseline, writes compact JSON, updates
  site/LICENSE-MANIFEST.json with the exact query URL + fetch date, and
  prints the QA block.

Politeness / robustness (docs/sourcing.md tier 1):
  - The mirror rotates dataset IDs. On "Currently unknown datasetID" the
    ERDDAP catalog (/erddap/search/index.csv) is re-searched for the current
    "ICOADS 1-degree Enhanced (sst.mean), 1960-present" ID and the query is
    rebuilt with it.
  - The time axis max is read from /erddap/info/<id>/index.csv and the stop
    constraint is clamped to it (a stop beyond the axis max returns 404).
  - Max 3 attempts per run, backoff >= 5 min (300 s) between attempts, also
    on 500 "Connection cannot be opened" (upstream PSL OpenDAP rate limit).

--from-cache DIR (documented escape hatch):
  For build hosts whose network cannot reach pfeg.noaa.gov at all (TCP
  blackholed), the raw ERDDAP CSV for the EXACT query URL can be retrieved
  from any network (curl-level plain URL, see docs/sourcing.md) and dropped
  into DIR as one or more .csv chunks (each chunk is a full ERDDAP CSV
  response for a time sub-range of the same query). If DIR contains
  query.url, that string is recorded in the manifest as the exact URL.
  Processing is identical; only the transport differs. Never hand-edit
  site/data/sst.json — fix the pipeline, not the data.

Placeholder mode (--placeholder):
  Generates a deterministic, clearly-labeled SAMPLE series (seasonal cycle +
  plausible warming trend) so the layout can be previewed before the real
  pipeline runs. Shipping placeholder data to production is FORBIDDEN
  (see AGENTS.md rule 4).

Stdlib only: no pandas / numpy / pip. Run:  python3 scripts/fetch_sst.py [--placeholder] [--from-cache DIR]
"""

import argparse
import csv
import io
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ERDDAP_BASE = "https://upwell.pfeg.noaa.gov/erddap"
# "ICOADS 1-degree Enhanced (sst.mean), 1.0 deg, 1960-present" — confirmed current
# on 2026-11-19 via /erddap/search/index.csv?searchFor=ICOADS+1-degree+Enhanced+sst.mean
# (the mirror rotates these IDs; discover_dataset_id() re-resolves at runtime)
DEFAULT_DATASET_ID = "noaa_psl_3a7b_f45b_d09a"
DATASET_SEARCH = (ERDDAP_BASE +
                  "/search/index.csv?searchFor=ICOADS+1-degree+Enhanced+sst.mean&itemsPerPage=200")
TIME_START = "1960-01-01T00:00:00Z"
TIME_STOP = "2025-12-31T00:00:00Z"   # full years only; page layout is 1960-2025 (66 cols)
BOX = "[(40.5):(45.5)][(12.5):(19.5)]"  # [lat][lon]
# Canonical full-range query (paste-able in a browser); see docs/sourcing.md
ERDDAP = (ERDDAP_BASE + "/griddap/" + DEFAULT_DATASET_ID + ".csv"
          "?sst[(" + TIME_START + "):(2025-12-31T00:00:00Z)]" + BOX)

MAX_ATTEMPTS = 3   # per run — docs/sourcing.md
BACKOFF_S = 300    # >= 5 min between attempts — docs/sourcing.md
UA = {"User-Agent": "adriatic-warming/1.0 (static site data pipeline; NOAA public data)"}

# Median month dates ICOADS uses, e.g. 1960-01-16T00:00:00Z

REGIONS = [
    ("north", "North Adriatic", "The shallow basin: Gulf of Trieste to the Kvarner and Zadar archipelago. Sparsest ship coverage of the three.", 43.6),
    ("central", "Central Adriatic", "From the Kornati and Split channel down to the Palagru\u017ea sill.", 41.8),
    ("south", "South Adriatic", "The deep southern basin and Otranto Strait.", 0.0),
]

BASELINE = (1991, 2020)  # WMO standard climate normal period


def region_for(lat):
    for key, name, desc, cutoff in REGIONS:
        if lat >= cutoff:
            return key
    return REGIONS[-1][0]


def http_get(url, timeout=240):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def discover_dataset_id():
    """Re-search the ERDDAP catalog for the current sst.mean 1960-present ID."""
    raw = http_get(DATASET_SEARCH, timeout=60)
    rows = list(csv.reader(io.StringIO(raw)))
    hdr = rows[0]
    ti, di = hdr.index("Title"), hdr.index("Dataset ID")
    present, any_sst = [], []
    for r in rows[1:]:
        if len(r) <= di:
            continue
        if "sst.mean" in r[ti]:
            any_sst.append(r[di])
            if "1960-present" in r[ti]:
                present.append(r[di])
    ids = present or any_sst
    if not ids:
        raise SystemExit("catalog search found no ICOADS 1-degree Enhanced sst.mean dataset")
    print(f"catalog search: sst.mean dataset ID(s) {ids}; using {ids[-1]}")
    return ids[-1]


def read_info(dataset_id, cache_dir=None):
    """/info/<id>/index.csv -> {'global': {attr: value}, 'time': {attr: value}}.
    In cache mode, reads cache/info.csv (the same endpoint, retrieved earlier)."""
    if cache_dir:
        p = os.path.join(cache_dir, "info.csv")
        if os.path.exists(p):
            raw = open(p, encoding="utf-8").read()
        else:
            return {"global": {}, "time": {}}
    else:
        try:
            raw = http_get(ERDDAP_BASE + "/info/" + dataset_id + "/index.csv", timeout=60)
        except Exception as e:
            print(f"  could not read dataset info ({e})")
            return {"global": {}, "time": {}}
    def _clean(v):
        # some transports JSON-escape newlines/unicode inside CSV fields
        if v and ("\\u" in v or "\\n" in v):
            try:
                v = bytes(v, "utf-8").decode("unicode_escape")
            except Exception:
                pass
        return v.replace("\n", " ").strip()
    out = {"global": {}, "time": {}}
    for r in csv.reader(io.StringIO(raw)):
        if len(r) >= 5 and r[0] == "attribute":
            (out["global"] if r[1] == "NC_GLOBAL" else out["time"]).setdefault(r[2], _clean(r[4]))
    return out


def axis_max_iso(info):
    """Time axis maximum from info['time']['actual_range'] (ISO or seconds since epoch)."""
    val = info.get("time", {}).get("actual_range")
    units = info.get("time", {}).get("units", "")
    if not val:
        return TIME_STOP
    hi = val.split(",")[-1].strip()
    if "T" in hi:  # ISO already
        return hi
    try:
        import datetime
        secs = float(hi)
        origin = "1970-01-01T00:00:00Z"
        if "since" in units:
            origin = units.split("since", 1)[1].strip()
        base = datetime.datetime(int(origin[0:4]), int(origin[5:7]), int(origin[8:10]),
                                 int(origin[11:13]), int(origin[14:16]), int(origin[17:19]),
                                 tzinfo=datetime.timezone.utc)
        return (base + datetime.timedelta(seconds=secs)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return TIME_STOP


def build_url(dataset_id, stop):
    return (ERDDAP_BASE + "/griddap/" + dataset_id + ".csv"
            + "?sst[(" + TIME_START + "):( " + stop + ")][(40.5):(45.5)][(12.5):(19.5)]"
            .replace("( ", "("))


def fetch_real():
    """Returns (raw_csv, url_used, dataset_id, info). Polite retries per sourcing.md."""
    ds = DEFAULT_DATASET_ID
    info = read_info(ds)
    amax = axis_max_iso(info)
    stop = min(TIME_STOP, amax)
    if stop != TIME_STOP:
        print(f"clamping time stop to axis max {amax}")
    last_err = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        url = build_url(ds, stop)
        try:
            print(f"attempt {attempt}/{MAX_ATTEMPTS}: GET {url}")
            raw = http_get(url)
            if not raw.startswith("time,latitude,longitude,sst"):
                if "unknown datasetID" in raw or "Connection cannot be opened" in raw:
                    raise RuntimeError(raw.strip().splitlines()[-1][:200])
                raise RuntimeError("unexpected CSV header: " + raw[:120].replace("\n", " "))
            return raw, url, ds, info
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            last_err = f"HTTP {e.code}: {(body or str(e))[:200]}"
            if "unknown datasetID" in body:
                print("  dataset ID rotated; re-searching catalog")
                ds = discover_dataset_id()
                info = read_info(ds)
                stop = min(TIME_STOP, axis_max_iso(info))
        except Exception as e:
            last_err = str(e)[:200]
        if attempt < MAX_ATTEMPTS:
            print(f"  attempt {attempt} failed ({last_err}); backing off {BACKOFF_S}s (>=5 min, per docs/sourcing.md)")
            time.sleep(BACKOFF_S)
    raise SystemExit(
        f"ERDDAP fetch failed after {MAX_ATTEMPTS} attempts: {last_err}\n"
        "If the source stays unreachable after repeated runs on different days, STOP and report —\n"
        "do not improvise a different data source (docs/sourcing.md ban list).")


def load_cache(cache_dir):
    """Read raw ERDDAP CSV chunk(s) from a directory. Returns (rows, url_used).

    Some transports hard-wrap long text at a fixed width, which can split a CSV
    record across two lines or eat a newline between records. Instead of trusting
    line boundaries, every well-formed ERDDAP griddap record is extracted by
    pattern (timestamp,lat,lon,value); anything else is transport noise. Only the
    transport is repaired; values are never altered.
    """
    import re
    full_re = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z,-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?,(?:NaN|-?\d+(?:\.\d+)?)$")
    files = sorted(f for f in os.listdir(cache_dir)
                   if f.endswith(".csv") and f != "info.csv")  # info.csv is the /info endpoint, not data
    if not files:
        raise SystemExit(f"--from-cache: no data .csv files in {cache_dir}")
    rows = [["time", "latitude", "longitude", "sst"],
            ["UTC", "degrees_north", "degrees_east", "degree_C"]]
    header_checked = False
    nrec = 0
    for f in files:
        with open(os.path.join(cache_dir, f), encoding="utf-8") as fh:
            raw = fh.read()
        if not header_checked:
            if not raw.lstrip("\ufeff").startswith("time,latitude,longitude,sst"):
                raise SystemExit(f"--from-cache: {f} is not an ERDDAP griddap CSV (head: {raw[:60]!r})")
            header_checked = True
        # drop this chunk's own 2 header lines, then buffer-repair the rest:
        # a complete record matches full_re; a fragment is accumulated until it
        # does (wrap inserted a newline mid-record)
        recs = []
        buf = None
        lines = raw.split("\n")
        for ln in lines[2:]:
            if not ln:
                continue
            if full_re.match(ln):
                if buf is not None:
                    recs.append(buf); buf = None
                recs.append(ln)
            else:
                buf = ln if buf is None else buf + ln
                if full_re.match(buf):
                    recs.append(buf); buf = None
        if buf is not None:
            recs.append(buf)
        nrec += len(recs)
        rows.extend(r.split(",") for r in recs)
    url_used = None
    qp = os.path.join(cache_dir, "query.url")
    if os.path.exists(qp):
        url_used = open(qp, encoding="utf-8").read().strip()
    if not url_used:
        url_used = ERDDAP
    print(f"--from-cache: {len(files)} chunk(s), {nrec} data records extracted; recorded URL: {url_used}")
    return rows, url_used


def parse_rows(rows):
    """rows: CSV incl. 2 header lines -> (data, cells, grid_cells)."""
    data = {}    # (region, year, month) -> [temps]
    cellsets = {}  # region -> set((lat, lon))
    grid = set()   # all (lat, lon) in the box, incl. land/NaN cells
    seen = set()  # (time, lat, lon) — ERDDAP snaps constraint edges to axis values,
    # so adjacent time chunks can overlap by one month; never count a cell-month twice
    n = 0
    for row in rows[2:]:
        if len(row) < 4:
            continue
        ts, lat_s, lon_s, sst_s = row[0], row[1], row[2], row[3]
        if (ts, lat_s, lon_s) in seen:
            continue
        seen.add((ts, lat_s, lon_s))
        lat, lon = float(lat_s), float(lon_s)
        grid.add((lat, lon))
        year = int(ts[0:4]); month = int(ts[5:7])
        if sst_s in ("NaN", ""):
            continue
        t = float(sst_s)
        if t < -2.0 or t > 40.0:  # bogus value hygiene
            continue
        key = region_for(lat)
        data.setdefault((key, year, month), []).append(t)
        cellsets.setdefault(key, set()).add((lat, lon))
        n += 1
    if not data:
        raise SystemExit("No data rows returned from ERDDAP. "
                         "Endpoint may be down or rate-limited; retry later.")
    cells = {k: len(v) for k, v in cellsets.items()}
    print(f"parsed {n} valid cell-months; sea cells per region: {cells}; grid cells in box: {len(grid)}")
    return data, cells, len(grid)


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


def build_real(series, clim, cells, out_path, url_used=None, dataset_id=None, cache_note=None,
               grid_cells=None, info=None):
    ylo, yhi = years_span(series)
    g = (info or {}).get("global", {})
    lic = g.get("license", "")
    if "United States Government" in lic or "public domain" in lic.lower():
        lic = "Public domain (US Government work)"  # short label for the page; full NOAA disclaimer stays in the manifest
    else:
        lic = lic[:200]
    src = ("NOAA ICOADS 1-degree Enhanced monthly SST (public domain), via NOAA PSL ERDDAP "
           "upwell.pfeg.noaa.gov" + (f" dataset {dataset_id}" if dataset_id else ""))
    fetched = time.strftime("%Y-%m-%d", time.gmtime())
    out = {"meta": {"placeholder": False, "generated": fetched,
                    "source": src,
                    "baseline": f"{BASELINE[0]}\u2013{BASELINE[1]} monthly means",
                    "years": [ylo, yhi], "unit": "deg C",
                    "cells": cells,
                    # full-disclosure fields (rendered on the page's Data & method section)
                    "license": lic,
                    "query_url": url_used or ERDDAP,
                    "fetched": fetched,
                    "dataset": dataset_id or DEFAULT_DATASET_ID,
                    "dataset_title": g.get("title", "ICOADS 1-degree Enhanced (sst.mean), 1960-present"),
                    "dataset_history": g.get("history", "").replace("\n", " ").strip(),
                    "coverage": {"lat": [40.5, 45.5], "lon": [12.5, 19.5],
                                 "grid_cells": grid_cells or 0,
                                 "sea_cells": sum(cells.values())}},
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
    if url_used:
        update_manifest(url_used, dataset_id or DEFAULT_DATASET_ID, cache_note)
    qa(out)


def update_manifest(url, dataset_id, note=None):
    mp = os.path.join(REPO, "site", "LICENSE-MANIFEST.json")
    man = json.load(open(mp, encoding="utf-8"))
    fetched = time.strftime("%Y-%m-%d", time.gmtime())
    for d in man["data"]:
        if d["file"].endswith("sst.json"):
            d.update({
                "source": "NOAA ICOADS 1-degree Enhanced (sst.mean), 1960-present — monthly means, "
                          f"ERDDAP dataset {dataset_id} on upwell.pfeg.noaa.gov",
                "author": "NOAA ICOADS / NOAA Physical Sciences Laboratory (public ERDDAP)",
                "license": "Public domain (US Government work; NOAA disclaimer: not intended for legal use)",
                "url": url,
                "fetched": fetched,
                "note": note or ("Exact ERDDAP query URL above; retrieved with a plain curl-level GET, "
                                 "no key. Aggregated to 3 sub-basins by scripts/fetch_sst.py."),
                "displayed": "footer data line (rendered from meta.source) + this manifest",
            })
    man["updated"] = fetched
    json.dump(man, open(mp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    open(mp, "a", encoding="utf-8").write("\n")
    print(f"updated {mp} (sst entry: url + fetched {fetched})")


def slope_per_decade(pts):
    """pts: [(year, value)] -> slope per decade (linear regression)."""
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    num = sum((p[0] - mx) * (p[1] - my) for p in pts)
    den = sum((p[0] - mx) ** 2 for p in pts)
    return (num / den) * 10 if den else 0.0


def qa(doc):
    """QA block. Trends are computed on the stored monthly ANOMALIES with the same
    formula the page's JS uses, so the stat cards must match these numbers."""
    meta = doc["meta"]
    ylo, yhi = meta["years"]
    print("\nQA summary")
    print(f"  years {ylo}-{yhi} ({yhi-ylo+1} years, 66-column layout), baseline {meta['baseline']}, unit {meta['unit']}")
    print(f"  cells per region: {meta['cells']}")
    for key in ("north", "central", "south"):
        r = doc["regions"][key]
        years, As = r["years"], r["a"]
        # coverage / holes
        expected = (yhi - ylo + 1) * 12
        missing = [(y, m) for y, row in zip(years, As) for m, a in enumerate(row, 1) if a is None]
        longest = 0; longest_at = None; run = 0; run_at = None
        seq = [(y, m) for y in years for m in range(1, 13)]
        missset = set(missing)
        for ym in seq:
            if ym in missset:
                run += 1
                if run == 1:
                    run_at = ym
                if run > longest:
                    longest = run; longest_at = run_at
            else:
                run = 0
        hole_flag = "  <-- HOLE > 3 MONTHS, FLAG" if longest > 3 else ""
        print(f"  {key:8s}: months present {expected - len(missing)}/{expected}, missing {len(missing)}"
              + (f", longest consecutive hole {longest} months starting {longest_at[0]}-{longest_at[1]:02d}{hole_flag}"
                 if missing else ", no holes"))
        # trends on anomalies, same as page JS trend()
        def trend(mode):
            pts = []
            for y, row in zip(years, As):
                use = [v for i, v in enumerate(row) if v is not None and (mode != "summer" or 5 <= i <= 7)]
                if use:
                    pts.append((y, sum(use) / len(use)))
            return slope_per_decade(pts) / 10  # per year
        t_ann = trend("annual"); t_sum = trend("summer")
        span_sum = t_sum * (yhi - ylo)
        print(f"           trend annual {t_ann*10:+.2f} degC/decade | summer Jun-Aug {t_sum*10:+.2f} degC/decade"
              f" | summer since {ylo} {span_sum:+.2f} degC (stat-card numbers)")
        # anomaly sum over baseline (should be ~0 by construction)
        s = sum(a for y, row in zip(years, As) if BASELINE[0] <= y <= BASELINE[1]
                for a in row if a is not None)
        print(f"           sum of anomalies over {BASELINE[0]}-{BASELINE[1]}: {s:+.4f} (approx 0 expected)")


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
    cells = {"north": 9, "central": 8, "south": 6}
    build_real(series, clim, cells, out_path, grid_cells=48)
    doc = json.load(open(out_path))
    doc["meta"].update({"placeholder": True,
                        "source": "PLACEHOLDER: deterministic sample series generated by scripts/fetch_sst.py --placeholder (CC0, by this project). Illustrative numbers, not measurements.",
                        "license": "CC0 1.0 (synthesized by this project; no third-party rights)",
                        "query_url": "", "fetched": time.strftime("%Y-%m-%d", time.gmtime()),
                        "dataset": "none (placeholder)", "dataset_title": "PLACEHOLDER sample series",
                        "dataset_history": ""})
    doc["meta"]["cells"] = cells
    json.dump(doc, open(out_path, "w"), separators=(",", ":"), ensure_ascii=False)
    print("wrote PLACEHOLDER data; meta.placeholder = true (must be false at launch)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placeholder", action="store_true", help="generate labeled sample data instead of fetching")
    ap.add_argument("--from-cache", metavar="DIR", default=None,
                    help="read raw ERDDAP CSV chunk(s) from DIR instead of the network "
                         "(for hosts that cannot reach upwell.pfeg.noaa.gov; see docstring)")
    ap.add_argument("--out", default=os.path.join(REPO, "site", "data", "sst.json"))
    args = ap.parse_args()
    if args.placeholder:
        build_placeholder(args.out)
    elif args.from_cache:
        rows, url_used = load_cache(args.from_cache)
        data, cells, grid = parse_rows(rows)
        series = monthly_series(data)
        clim = climatology(series)
        info = read_info(DEFAULT_DATASET_ID, cache_dir=args.from_cache)
        cache_note = ("Raw CSV retrieved from the exact ERDDAP query URL above via a plain GET from an "
                      "alternate network path (build host could not open a TCP connection to "
                      "upwell.pfeg.noaa.gov on " + time.strftime("%Y-%m-%d", time.gmtime()) +
                      "); time range fetched in per-year chunks of the same query. Processing identical "
                      "to a direct `make data` run.")
        build_real(series, clim, cells, args.out, url_used=url_used,
                   dataset_id=DEFAULT_DATASET_ID, cache_note=cache_note,
                   grid_cells=grid, info=info)
    else:
        raw, url_used, ds, info = fetch_real()
        rows = list(csv.reader(io.StringIO(raw)))
        data, cells, grid = parse_rows(rows)
        series = monthly_series(data)
        clim = climatology(series)
        build_real(series, clim, cells, args.out, url_used=url_used, dataset_id=ds,
                   grid_cells=grid, info=info)


if __name__ == "__main__":
    main()
