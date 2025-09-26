.PHONY: scrape analyze export import-review full-pipeline upload-videos

# Default values from environment
DAYS_BACK ?= 120
CONCURRENCY ?= 5
POST_TYPE ?= reels
SD_THRESHOLD ?= 3.0
REVIEW_PATH ?= exports/review_export_EDITED.csv

scrape:
	python ryan_vpd.py scrape --usernames usernames.csv --days $(DAYS_BACK) --concurrency $(CONCURRENCY) --post-type $(POST_TYPE)

analyze:
	python ryan_vpd.py analyze --sd-threshold $(SD_THRESHOLD)

export:
	python ryan_vpd.py export --format outliers,review,ai --sd-threshold $(SD_THRESHOLD)

import-review:
	python ryan_vpd.py import-review --path $(REVIEW_PATH)

upload-videos:
	python ryan_vpd.py upload-videos --from downloads

full-pipeline: scrape analyze export
	@echo "Pipeline complete. Check exports/ directory."

# Helper commands
install:
	pip install -r requirements.txt

test:
	python ryan_vpd.py --help

clean:
	rm -rf data/raw_apify/* data/normalized/* exports/* downloads/*

setup-env:
	cp .env.example .env
	@echo "Please edit .env file with your configuration"