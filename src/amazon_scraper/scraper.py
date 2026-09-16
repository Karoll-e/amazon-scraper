"""
    Backward-compatibility shim.
    The Amazon scraper has moved to amazon_scraper.scrapers.amazon.
    This module re-exports it so that existing code using
    `from amazon_scraper.scraper import AmazonScraper` continues to work.
"""

from amazon_scraper.scrapers.amazon import AmazonScraper  # noqa: F401

__all__ = ["AmazonScraper"]
