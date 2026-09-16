"""
    Amazon scraper — migrated from the original scraper.py to inherit
    from BaseScraper. Behaviour is identical to the original implementation.
"""

import logging
from enum import Enum
from typing import Dict, List

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from seleniumwire import webdriver

from amazon_scraper.base_scraper import (
    BaseScraper,
    MissingProductDataError,
)
from amazon_scraper.models import Product


class AmazonXPath(str, Enum):
    """XPath selectors for Amazon search result pages."""

    PRODUCTS = "//div[@data-component-type='s-search-result']"
    TITLE = ".//a/h2/span"
    URL = ".//a[h2]"
    PRICE_WHOLE = ".//span[@class='a-price']//span[@class='a-price-whole']"
    PRICE_FRACTIONAL = ".//span[@class='a-price']//span[@class='a-price-fraction']"
    IMAGE_URL = ".//img"


class AmazonScraper(BaseScraper):
    """Scraper for Amazon search/department pages."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        amazon_headers: Dict[str, str] = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/90.0.4430.93 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/webp,*/*;q=0.8"
            ),
            "Connection": "keep-alive",
            "Referer": "https://www.amazon.com/",
            "Host": "www.amazon.com",
            "TE": "Trailers",
        }
        super().__init__(store_name="amazon", logger=logger, headers=amazon_headers)

    # -- Price parsing --------------------------------------------------

    def _parse_price_for_product(self, product: WebElement) -> str | None:
        """Parse price from an Amazon product element (whole + fractional)."""
        try:
            price_whole_element = product.find_element(
                By.XPATH, AmazonXPath.PRICE_WHOLE
            )
            price_whole = price_whole_element.text if price_whole_element else None

            price_fractional_element = product.find_element(
                By.XPATH, AmazonXPath.PRICE_FRACTIONAL
            )
            price_fractional = (
                price_fractional_element.text if price_fractional_element else None
            )

            return (
                price_whole + "." + price_fractional
                if all((price_whole, price_fractional))
                else None
            )
        except NoSuchElementException:
            return None

    # -- Abstract method implementations --------------------------------

    def _get_product_elements(
        self, driver: webdriver.Chrome
    ) -> List[WebElement]:
        """Find all product result elements on the Amazon page."""
        return driver.find_elements(By.XPATH, AmazonXPath.PRODUCTS)

    def _parse_product_data(self, element: WebElement) -> Product:
        """Parse a single Amazon product element into a Product."""
        product = element
        title_element = product.find_element(By.XPATH, AmazonXPath.TITLE)
        title = title_element.text if title_element else None

        url_element = product.find_element(By.XPATH, AmazonXPath.URL)
        url = url_element.get_attribute("href") if url_element else None

        asin_code = product.get_attribute("data-asin")

        image_element = product.find_element(By.XPATH, AmazonXPath.IMAGE_URL)
        image_url = image_element.get_attribute("src") if image_element else None

        price = self._parse_price_for_product(product)
        if not price:
            self._logger.warning(
                f"Price not found for product {title}. Likely out of stock."
            )

        if not all((title, url, asin_code, image_url)):
            raise MissingProductDataError

        return Product(
            title=title,
            url=url,
            store="amazon",
            image_url=image_url,
            price=price,
            product_id=asin_code,
        )
