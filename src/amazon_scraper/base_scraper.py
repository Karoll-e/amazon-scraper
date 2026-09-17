"""
    Base scraper module with common Selenium logic for all store scrapers.
    Each specific store scraper inherits from BaseScraper and implements
    the abstract methods _get_product_elements and _parse_product_data.
"""

import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Dict, List

from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.remote.webelement import WebElement
from seleniumwire import webdriver
from seleniumwire.request import Request
from webdriver_manager.chrome import ChromeDriverManager

from amazon_scraper.models import Product

logging.getLogger("WDM").setLevel(logging.ERROR)
logging.getLogger("seleniumwire").setLevel(logging.ERROR)


class DriverInitializationError(Exception):
    """Raised when the Chrome webdriver cannot be initialized."""

    def __init__(self, store_name: str = "") -> None:
        self.store_name = store_name
        self.message = (
            f"Unable to initialize Chrome webdriver for scraping {store_name}."
            if store_name
            else "Unable to initialize Chrome webdriver for scraping."
        )
        super().__init__(self.message)


class DriverGetProductsError(Exception):
    """Raised when product data cannot be scraped from the store."""

    def __init__(self, store_name: str = "") -> None:
        self.store_name = store_name
        self.message = (
            f"Unable to get product data from {store_name}."
            if store_name
            else "Unable to get product data."
        )
        super().__init__(self.message)


class MissingProductDataError(Exception):
    """Raised when required data for a product is missing."""

    message = "Missing required data for product."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)


class BaseScraper(ABC):
    """
    Abstract base class for all store scrapers.

    Provides the common infrastructure:
      - Chrome headless driver initialization (with selenium-wire)
      - Request header interception
      - Navigation with configurable wait
      - Random delays to avoid rate limiting
      - The main scrape() orchestration loop

    Subclasses must implement:
      - _get_product_elements(): find product elements on the loaded page
      - _parse_product_data(): parse a single element into a Product
    """

    def __init__(
        self,
        store_name: str,
        logger: logging.Logger | None = None,
        headers: Dict[str, str] | None = None,
    ) -> None:
        self.store_name = store_name
        self._logger = logger if logger else logging.getLogger(__name__)
        self._headers = headers or {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/webp,*/*;q=0.8"
            ),
            "Connection": "keep-alive",
        }

    # ------------------------------------------------------------------
    #  Driver / request infrastructure
    # ------------------------------------------------------------------

    def _add_headers_to_request(self, request: Request) -> None:
        """Intercepts selenium requests to inject custom headers."""
        for key, value in self._headers.items():
            request.headers[key] = value

    def _init_chrome_driver(self) -> webdriver.Chrome:
        """Initializes a headless Chrome webdriver with anti-detection flags."""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option(
            "excludeSwitches", ["enable-automation"]
        )
        chrome_options.add_experimental_option("useAutomationExtension", False)
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.request_interceptor = self._add_headers_to_request
        return driver

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    def _navigate_and_wait(
        self, driver: webdriver.Chrome, url: str, wait_seconds: float = 3.0
    ) -> None:
        """Navigate to a URL and sleep to allow the page to render."""
        driver.get(url)
        time.sleep(wait_seconds)

    def _random_delay(self, min_s: float = 1.0, max_s: float = 3.0) -> None:
        """Sleep a random duration to mimic human behaviour and avoid blocks."""
        time.sleep(random.uniform(min_s, max_s))

    # ------------------------------------------------------------------
    #  Product-extraction hooks
    #
    #  Two ways to implement a store scraper:
    #    1. Element-based (like Amazon): implement _get_product_elements
    #       and _parse_product_data. The default _scrape_products handles
    #       the loop.
    #    2. API-based (like Cruz Verde): override _scrape_products entirely
    #       and use the driver's session to call the store's internal API
    #       (e.g. via JS fetch, which reuses the page's cookies).
    # ------------------------------------------------------------------

    def _get_product_elements(
        self, driver: webdriver.Chrome
    ) -> List[WebElement]:
        """Return product WebElements from the loaded page (element-based)."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement element-based extraction."
        )

    def _parse_product_data(self, element: WebElement) -> Product:
        """Parse a single product WebElement into a Product (element-based)."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement element-based extraction."
        )

    def _scrape_products(
        self, driver: webdriver.Chrome, url: str
    ) -> List[Product]:
        """
        Default extraction loop for element-based scrapers.
        API-based scrapers override this method.
        """
        product_elements = self._get_product_elements(driver)
        self._logger.info(
            f"Found {len(product_elements)} product elements on {self.store_name}."
        )

        parsed_products: List[Product] = []
        for element in product_elements:
            try:
                parsed_product = self._parse_product_data(element)
            except MissingProductDataError:
                self._logger.error(
                    "Couldn't get all required data for product. Skipping.."
                )
                continue
            except Exception:
                self._logger.error(
                    "Unexpected error when parsing data for product. Skipping.."
                )
                continue
            else:
                parsed_products.append(parsed_product)

        return parsed_products

    # ------------------------------------------------------------------
    #  Main orchestration
    # ------------------------------------------------------------------

    def scrape(self, url: str) -> List[Product]:
        """
        Scrape products from the given URL.

        Orchestrates: init driver → navigate → find elements → parse each → close.

        Args:
            url: The URL of the store page to scrape.

        Returns:
            List[Product]: Parsed products.

        Raises:
            DriverInitializationError: If the Chrome webdriver cannot be initialized.
            DriverGetProductsError: If product data cannot be scraped.
        """
        self._logger.info(
            f"Scraping {self.store_name} product data from {url}.."
        )

        try:
            driver = self._init_chrome_driver()
        except Exception as e:
            raise DriverInitializationError(self.store_name) from e

        try:
            self._navigate_and_wait(driver, url)
            parsed_products = self._scrape_products(driver, url)

            self._logger.info(
                f"Successfully parsed {len(parsed_products)} products "
                f"from {self.store_name}."
            )
            return parsed_products
        except Exception as e:
            raise DriverGetProductsError(self.store_name) from e
        finally:
            driver.close()
