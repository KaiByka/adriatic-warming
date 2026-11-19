.PHONY: data placeholder validate serve

data:
	python3 scripts/fetch_sst.py

placeholder:
	python3 scripts/fetch_sst.py --placeholder

validate:
	python3 scripts/validate.py

serve:
	cd site && python3 -m http.server 8080
