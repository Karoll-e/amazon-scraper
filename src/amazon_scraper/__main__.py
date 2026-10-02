"""
    Main CLI entry point for the multi-store scraper.

    Usage:
        # Scrape Amazon (backward compatible with original command)
        python -m amazon_scraper scrape --store amazon --url "<amazon_url>"

        # Or using the legacy shortcut
        python -m amazon_scraper scrape-amazon --url "<amazon_url>"

        # List available stores
        python -m amazon_scraper stores
"""

import logging

import click

from amazon_scraper.collector import DataCollector
from amazon_scraper.config import load_config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Registry of available store scrapers.
# New stores are registered here as they are implemented.
STORE_SCRAPERS = {
    "amazon": "amazon_scraper.scrapers.amazon.AmazonScraper",
    "cruz_verde": "amazon_scraper.scrapers.cruz_verde.CruzVerdeScraper",
    "farmatodo": "amazon_scraper.scrapers.farmatodo.FarmatodoScraper",
}


def _get_scraper(store_name: str, logger: logging.Logger):
    """Instantiate a scraper by store name from the registry."""
    if store_name not in STORE_SCRAPERS:
        raise click.ClickException(
            f"Unknown store '{store_name}'. Available: {', '.join(STORE_SCRAPERS)}"
        )

    import importlib

    module_path, class_name = STORE_SCRAPERS[store_name].rsplit(".", 1)
    module = importlib.import_module(module_path)
    scraper_class = getattr(module, class_name)
    return scraper_class(logger=logger)


@click.group()
def cli() -> None:
    """Multi-store product scraper."""


@cli.command(name="scrape")
@click.option(
    "--store",
    default="amazon",
    help="Store to scrape (e.g. amazon, cruz_verde). Default: amazon.",
)
@click.option(
    "--url",
    required=True,
    help="The URL of the page to scrape.",
)
@click.option(
    "--output",
    default=None,
    help="Output filename base (without extension). Default: auto-generated.",
)
@click.option(
    "--output-dir",
    default=None,
    help="Directory for output files. Default: 'output'.",
)
def scrape(store: str, url: str, output: str | None, output_dir: str | None) -> None:
    """Scrape products from a store URL and save to CSV + JSON."""
    logger = logging.getLogger("amazon_scraper")
    config = load_config()

    if output_dir is None:
        output_dir = config.get("output_dir", "output")

    scraper = _get_scraper(store, logger)
    collector = DataCollector(scraper=scraper, output_dir=output_dir, logger=logger)
    collector.collect(url, output_name=output)


@cli.command(name="scrape-amazon")
@click.option(
    "--url",
    required=True,
    help="The URL of the Amazon page to scrape.",
)
@click.option(
    "--output",
    default=None,
    help="Output filename base (without extension). Default: amazon_products.",
)
def scrape_amazon(url: str, output: str | None) -> None:
    """Legacy shortcut: scrape Amazon and save to CSV + JSON."""
    logger = logging.getLogger("amazon_scraper")
    config = load_config()
    output_dir = config.get("output_dir", "output")

    scraper = _get_scraper("amazon", logger)
    collector = DataCollector(scraper=scraper, output_dir=output_dir, logger=logger)
    collector.collect(url, output_name=output or "amazon_products")


@cli.command(name="stores")
def list_stores() -> None:
    """List available store scrapers."""
    click.echo("Available stores:")
    for store_name in STORE_SCRAPERS:
        click.echo(f"  - {store_name}")


if __name__ == "__main__":
    cli()
