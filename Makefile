# Makefile for running the multi-store scraper


.PHONY: install
install:
	pip install poetry==1.8.2
	poetry install

# Legacy command — still works exactly as before
.PHONY: scrape
scrape:
	@if [ -z "$(URL)" ]; then \
		echo 'Error: A URL is required. Use make scrape URL="<page_url>"'; \
		exit 1; \
	else \
		poetry run python -m amazon_scraper scrape-amazon --url="$(URL)"; \
	fi

# Generic scrape command: make scrape-store STORE=amazon URL="..."
.PHONY: scrape-store
scrape-store:
	@if [ -z "$(URL)" ]; then \
		echo 'Error: A URL is required. Use make scrape-store STORE=<store> URL="<page_url>"'; \
		exit 1; \
	else \
		poetry run python -m amazon_scraper scrape --store=$(or $(STORE),amazon) --url="$(URL)"; \
	fi

# List available stores
.PHONY: stores
stores:
	poetry run python -m amazon_scraper stores
