# Warming Adriatic

**warming.marespot.com** — a static "warming stripes" visualization of Adriatic
sea-surface temperature, month by month since 1960, split into three sub-basins.
The north (the shallow basin behind the islands) warms visibly faster than the
deep south. Every summer heatwave article about the Adriatic needs a graphic;
this is the one they can link, embed and quote.

Part of the MareSpot link-magnet fleet:
- charts.marespot.com — Adriatic old-chart slider (live)
- baltic.marespot.com — Baltic maritime traffic (live)
- sound.marespot.com — Sounds of the Adriatic (in build)

## Why it earns links

Climate journalists and weather blogs collect reusable, honest visualizations.
This one: real public-domain data (NOAA ICOADS ship observations, 1960 onward
— longer than the satellite record), a reproducible pipeline, per-region
numbers they can quote ("+X °C since 1960, the shallow north warming fastest"),
and a color language everyone recognizes in one glance. News-jack: publishes
BEFORE the first summer heatwave, so it is indexed and quotable exactly when the
sea-temperature headlines start.

## Data plan (three honest tiers)

1. **ICOADS 1° Enhanced monthly SST** (public domain, no key): 1960-present,
   fetched from NOAA's public ERDDAP with `scripts/fetch_sst.py`. Ships and
   buoys measured the sea decades before satellites did.
2. **NOAA OISST v2 monthly** (public domain, no key): 0.25° satellite-era
   (1982+) alternative, via PSL OPenDAP; chunk politely, they rate-limit hard.
3. **Copernicus Marine SST reanalysis** (free with registration, CC-BY-4.0):
   the "European brand" upgrade; register at marine.copernicus.eu; agent may
   add it as an alternative backend producing the same `sst.json` schema.

The prototype ships with **clearly-labeled placeholder sample data** until
sprint 1 runs the real pipeline. Launching with placeholder data is forbidden.

## Layout

```
README.md
AGENTS.md            ← agents read this first: the contract
Makefile             ← make data / make validate
docs/sourcing.md     ← data source details, licenses, fallbacks
scripts/fetch_sst.py ← data pipeline (stdlib only, reproducible)
site/index.html      ← the whole site: one file, no build step
site/data/sst.json   ← generated (placeholder until sprint 1)
site/data/coastline.json ← Natural Earth 110m, clipped (public domain)
site/CNAME           ← warming.marespot.com
.github/workflows/deploy.yml ← Pages: checkout → upload site → deploy
```

## Sprints

- **Sprint 1 — real data.** Run the pipeline against the ICOADS endpoint,
  QA the numbers (coverage per region, no holes > 3 months, anomaly sums to
  ~zero over baseline), kill the placeholder badge, update LICENSE-MANIFEST.
- **Sprint 2 — journalist kit.** SVG/PNG export of each region block, embed
  snippet (iframe + attribution), OG image, "suggested caption" lines with
  the exact quoted numbers, dataset-links page section.
- **Sprint 3 — launch.** GoatCounter, GSC URL-prefix property
  (warming.marespot.com), curator pitches when the first heatwave headline
  lands, optional Copernicus tier as a compare mode.

## Rules of the house (all fleet sites)

Static only · no API keys at runtime · public-domain / CC-BY content only ·
honest labels · minimal MareSpot credit (footer + max one contextual bridge) ·
license manifest always current · Lighthouse ≥ 85 mobile.
