"""
    Data collector module — generalized to work with any store scraper.

    Write strategy (double write for price-history tracking):
      - output/            : timestamped snapshot of each scrape (as before)
      - output/history/    : append-only price history, one file per
                             store per day. Multiple scrapes on the same
                             day are merged (last price of the day wins).
      - output/latest/     : snapshot of the most recent scrape per store
                             (overwritten on every scrape).

    All three destinations receive CSV + JSON.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

from amazon_scraper.base_scraper import BaseScraper
from amazon_scraper.models import Product


DEFAULT_OUTPUT_DIR = "output"

HISTORY_SUBDIR = "history"
LATEST_SUBDIR = "latest"


class DataCollector:
    """Collects product data from any scraper and saves to CSV + JSON."""

    def __init__(
        self,
        scraper: BaseScraper,
        output_dir: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._scraper = scraper
        self._output_dir = Path(output_dir) if output_dir else Path(DEFAULT_OUTPUT_DIR)
        self._logger = logger if logger else logging.getLogger(__name__)

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _products_to_df(products: List[Product]) -> pd.DataFrame:
        """Convert a list of Product models to a pandas DataFrame."""
        return pd.DataFrame([product.model_dump() for product in products])

    @staticmethod
    def _df_to_json(df: pd.DataFrame, path: Path) -> None:
        """Write a DataFrame to a JSON file (list of objects)."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                df.to_dict(orient="records"),
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

    @staticmethod
    def _product_key_expr(df: pd.DataFrame) -> pd.Series:
        """
        Unique key per product row: product_id when present, URL as fallback.
        Returns a Series of strings usable with drop_duplicates.
        """
        pid = df["product_id"].fillna("")
        url = df["url"].fillna("")
        return pd.Series(
            [
                p if p else u
                for p, u in zip(pid, url)
            ],
            index=df.index,
        )

    # ------------------------------------------------------------------
    #  Timestamped snapshot (existing behaviour)
    # ------------------------------------------------------------------

    def _save_snapshot(self, products: List[Product], filename: str) -> Path:
        """Saves a timestamped snapshot to output/. Returns the file path."""
        path = self._output_dir / filename
        self._logger.info(f"Writing {len(products)} products to {path}..")
        df = self._products_to_df(products)
        df.to_csv(path, index=False)
        self._df_to_json(df, self._output_dir / f"{filename}.json")
        return path

    # ------------------------------------------------------------------
    #  Price history (append-only, merged per day)
    # ------------------------------------------------------------------

    def _save_history(self, products: List[Product]) -> Path:
        """
        Appends products to the price history file for today.

        One file per store per day: output/history/{store}_{YYYY-MM-DD}.csv
        If the file already exists (e.g. multiple scrapes in one day), the
        new data is merged: rows are deduplicated on (product key, date)
        keeping the most recent scrape's price.
        """
        history_dir = self._output_dir / HISTORY_SUBDIR
        history_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")
        base_name = f"{self._scraper.store_name}_{today}"
        csv_path = history_dir / f"{base_name}.csv"

        new_df = self._products_to_df(products)
        new_df["scrape_date"] = today

        if csv_path.exists():
            existing = pd.read_csv(csv_path)
            merged = pd.concat([existing, new_df], ignore_index=True)
            merged["_key"] = self._product_key_expr(merged)
            merged = merged.drop_duplicates(subset=["_key", "scrape_date"], keep="last")
            merged = merged.drop(columns=["_key"])
        else:
            merged = new_df

        merged.to_csv(csv_path, index=False)
        self._df_to_json(merged, history_dir / f"{base_name}.json")

        self._logger.info(
            f"History updated: {csv_path} now holds {len(merged)} records "
            f"for {today}."
        )
        return csv_path

    # ------------------------------------------------------------------
    #  Latest snapshot (overwritten per store)
    # ------------------------------------------------------------------

    def _save_latest(self, products: List[Product]) -> Path:
        """
        Overwrites output/latest/{store}.csv (+ .json) with the newest data.
        """
        latest_dir = self._output_dir / LATEST_SUBDIR
        latest_dir.mkdir(parents=True, exist_ok=True)

        df = self._products_to_df(products)
        csv_path = latest_dir / f"{self._scraper.store_name}.csv"
        df.to_csv(csv_path, index=False)
        self._df_to_json(df, latest_dir / f"{self._scraper.store_name}.json")

        self._logger.info(f"Latest snapshot for {self._scraper.store_name} updated.")
        return csv_path

    # ------------------------------------------------------------------
    #  Main orchestration
    # ------------------------------------------------------------------

    def collect(self, url: str, output_name: str | None = None) -> List[Product] | None:
        """
        Scrapes data from the given URL and saves results to:
          - output/            (timestamped snapshot)
          - output/history/    (price history, merged per day)
          - output/latest/     (newest snapshot per store)

        Args:
            url: The URL of the page to scrape.
            output_name: Base filename (without extension). If None, uses
                         f"{store_name}_products_{timestamp}".

        Returns:
            The list of scraped Products, or None if scraping failed.
        """
        self._logger.info(
            f"Getting {self._scraper.store_name} product data for url {url}.."
        )

        try:
            products = self._scraper.scrape(url)
        except Exception:
            self._logger.exception(
                f"Error when scraping {self._scraper.store_name} for url {url}."
            )
            return None

        if not products:
            self._logger.info(
                f"No products found for given {self._scraper.store_name} page."
            )
            return None

        self._output_dir.mkdir(parents=True, exist_ok=True)

        if output_name is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            output_name = f"{self._scraper.store_name}_products_{timestamp}"

        self._save_snapshot(products, f"{output_name}.csv")
        self._save_history(products)
        self._save_latest(products)

        self._logger.info(
            f"Saved {len(products)} {self._scraper.store_name} products "
            f"to {self._output_dir}/ "
            f"({output_name}.csv | history/ | latest/)"
        )
        return products


# ---------------------------------------------------------------------------
#  Backward-compatible alias
# ---------------------------------------------------------------------------

class AmazonDataCollector(DataCollector):
    """Backward-compatible collector that defaults to the Amazon scraper."""

    def __init__(
        self,
        output_file: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        from amazon_scraper.scrapers.amazon import AmazonScraper

        output_dir = str(Path(output_file).parent) if output_file else None
        super().__init__(
            scraper=AmazonScraper(logger=logger),
            output_dir=output_dir,
            logger=logger,
        )
        # Preserve the old attribute name for any external code that reads it
        self._output_file = output_file if output_file else "amazon_products.csv"

    def _save_snapshot(self, products: List[Product], filename: str) -> Path:
        """Override to use the legacy flat filename when _output_file is set."""
        if self._output_file and filename.startswith("amazon_products_"):
            filename = self._output_file
        return super()._save_snapshot(products, filename)

    def collect_amazon_product_data(self, url: str) -> None:
        """Legacy method name — delegates to collect()."""
        self.collect(url, output_name="amazon_products")
