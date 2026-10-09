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


@cli.command(name="images")
@click.option(
    "--store",
    default=None,
    help="Store name: reads the best promotions from output/latest/{store}.csv.",
)
@click.option(
    "--input",
    "input_path",
    default=None,
    help="Explicit CSV path with scraped products (overrides --store).",
)
@click.option(
    "--limit",
    default=5,
    show_default=True,
    help="Max number of images to generate.",
)
@click.option(
    "--min-discount",
    default=10,
    show_default=True,
    help="Minimum discount percentage to consider a promotion.",
)
@click.option(
    "--output-dir",
    default=None,
    help="Directory for the PNGs. Default: output/promotions/images.",
)
def images(
    store: str | None,
    input_path: str | None,
    limit: int,
    min_discount: int,
    output_dir: str | None,
) -> None:
    """
    Generate promotional PNG images (1080x1080) for the best promotions,
    mimicking the channel's Canva template.
    """
    import pandas as pd

    from amazon_scraper.imagegen import (
        DEFAULT_OUTPUT_DIR,
        generate_images,
        make_driver,
    )
    from amazon_scraper.models import Product

    logger = logging.getLogger("amazon_scraper")

    if input_path is None:
        if store is None:
            raise click.ClickException("Provide --store or --input.")
        input_path = f"output/latest/{store}.csv"
    try:
        # dtype=str: pandas would otherwise coerce price strings to floats,
        # which the Product model (str fields) rejects.
        df = pd.read_csv(input_path, dtype=str)
    except FileNotFoundError:
        raise click.ClickException(f"File not found: {input_path}. Run a scrape first.")

    # filter promotions
    df = df[df["has_promotion"].astype(str).str.lower() == "true"]
    df = df[df["price"].notna()]
    df = df[df["image_url"].notna()]
    df["discount_num"] = pd.to_numeric(df["discount_percentage"], errors="coerce")
    df = df[df["discount_num"] >= min_discount]
    df = df.sort_values("discount_num", ascending=False).head(limit)

    if df.empty:
        click.echo(f"No promotions >= {min_discount}% found in {input_path}.")
        return

    products = []
    for _, row in df.iterrows():
        data = row.dropna().to_dict()
        data.pop("discount_num", None)
        try:
            products.append(Product(**data))
        except Exception:
            continue

    logger.info(f"Generating {len(products)} images..")
    paths = generate_images(
        products,
        driver_factory=make_driver,
        output_dir=output_dir or DEFAULT_OUTPUT_DIR,
        logger_obj=logger,
    )
    click.echo(f"\nGenerated {len(paths)} images:")
    for p in paths:
        click.echo(f"  {p}")


if __name__ == "__main__":
    cli()
