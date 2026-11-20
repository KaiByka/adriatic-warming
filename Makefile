.PHONY: data data-cache coastline placeholder validate serve

data:
	python3 scripts/fetch_sst.py

# regenerate the locator-map coastline (Natural Earth 50m, public domain)
coastline:
	python3 scripts/build_coastline.py

# Escape hatch for build hosts whose network cannot reach upwell.pfeg.noaa.gov:
# drop the raw ERDDAP CSV chunk(s) for the exact documented query into cache/
# (see scripts/fetch_sst.py docstring), then run this. cache/ is gitignored.
data-cache:
	python3 scripts/fetch_sst.py --from-cache cache

placeholder:
	python3 scripts/fetch_sst.py --placeholder

validate:
	python3 scripts/validate.py

serve:
	cd site && python3 -m http.server 8080
