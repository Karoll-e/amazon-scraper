"""
    Cruz Verde Colombia scraper.

    Strategy (API-based, discovered by inspecting the SPA's network traffic):
      - cruzverde.com.co is a single-page app on Salesforce Commerce Cloud.
      - The SPA consumes https://api.cruzverde.com.co/product-service/
        products/search, which returns clean JSON with prices, original
        prices, promotions, stock and pagination — no DOM parsing needed.
      - The API requires the browser session's cookies, so we load the
        category page once with Chrome and then call the API from inside
        the page context via JS fetch (credentials included).
      - Category mapping: site slug -> cgid is just "remove hyphens"
        (e.g. /bebe-y-maternidad/ -> cgid=bebeymater).

    Prices in COP: integers, no decimals.
"""

import json
import logging
import re
from typing import Any, Dict, List

from amazon_scraper.base_scraper import BaseScraper, MissingProductDataError
from amazon_scraper.models import Product


API_BASE = "https://api.cruzverde.com.co/product-service/products/search"
PATH_DICT_URL = (
    "https://api.cruzverde.com.co/product-service/categories"
    "/path-category-dict"
)
PAGE_SIZE = 48
MAX_PAGES = 12  # safety cap: 12 * 48 = 576 products max per run


class CruzVerdeScraper(BaseScraper):
    """Scraper for Cruz Verde Colombia via its internal product API."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        super().__init__(store_name="cruz_verde", logger=logger)

    # ------------------------------------------------------------------
    #  API access (from within the page's browser session)
    # ------------------------------------------------------------------

    def _fetch_from_page(self, driver, url: str) -> Dict[str, Any]:
        """Runs a JS fetch inside the page so the site's cookies are sent."""
        js = """
        const url = arguments[0];
        return fetch(url, {credentials: 'include'})
            .then(r => r.status === 200 ? r.text() : 'HTTP_ERROR_' + r.status)
            .catch(e => 'FETCH_ERROR_' + e.message);
        """
        raw = driver.execute_script(js, url)
        if raw.startswith("HTTP_ERROR") or raw.startswith("FETCH_ERROR"):
            raise RuntimeError(f"API call failed: {raw[:200]}")
        return json.loads(raw)

    def _resolve_cgid(self, driver, url: str) -> str:
        """
        Resolves a category URL to its API id via the site's own
        path-category-dict endpoint.
        """
        match = re.search(r"cruzverde\.com\.co(/[^/?]+)", url)
        if not match:
            raise MissingProductDataError(
                f"Cannot extract category path from URL: {url}"
            )
        path = match.group(1) + "/"
        data = self._fetch_from_page(
            driver, f"{PATH_DICT_URL}?path={path}"
        )
        cgid = data.get("id") if isinstance(data, dict) else None
        if not cgid:
            raise MissingProductDataError(
                f"path-category-dict returned no id for path {path}"
            )
        return cgid

    # ------------------------------------------------------------------
    #  Parsing
    # ------------------------------------------------------------------

    def _parse_hit(self, hit: Dict[str, Any]) -> Product:
        """Parse a single search-hit JSON object into a Product."""
        title = hit.get("productName")
        product_id = hit.get("productId")
        page_url = hit.get("pageURL") or hit.get("link")
        image_url = (hit.get("image") or {}).get("link")

        # pageURL comes as a bare slug ("marimer-hipertonico-...") —
        # turn it into a full site URL so the links are usable in messages.
        if page_url and not page_url.startswith("http"):
            page_url = f"https://www.cruzverde.com.co/{page_url.lstrip('/')}/{product_id}.html"

        if not all((title, product_id, page_url, image_url)):
            raise MissingProductDataError

        prices = hit.get("prices") or {}
        sale_price = prices.get("price-sale-col")          # current price (COP)
        list_price = prices.get("price-list-col")          # original/reference price

        discount_pct: str | None = None
        if sale_price and list_price and list_price > sale_price:
            discount_pct = str(
                round((list_price - sale_price) / list_price * 100)
            )

        promotions = hit.get("promotions") or []
        has_promotion = (
            bool(promotions)
            or (sale_price and list_price and list_price > sale_price)
        )

        return Product(
            title=title,
            url=page_url,
            store=self.store_name,
            image_url=image_url,
            price=str(sale_price) if sale_price else None,
            original_price=str(list_price) if list_price else None,
            discount_percentage=discount_pct,
            category="bebe",
            has_promotion=bool(has_promotion),
            product_id=product_id,
        )

    # ------------------------------------------------------------------
    #  Extraction (overrides the element-based default)
    # ------------------------------------------------------------------

    def _scrape_products(self, driver, url: str) -> List[Product]:
        """
        Paginates the internal search API for the given category URL.
        The driver is already sitting on the category page.

        The category's API id (cgid) is resolved via the site's own
        path-category-dict endpoint — no guessing (cgids are truncated
        slugs, e.g. /bebe-y-maternidad/ -> "bebeymater").
        """
        cgid = self._resolve_cgid(driver, url)
        self._logger.info(f"Resolved category cgid={cgid}")

        products: List[Product] = []
        offset = 0

        for page in range(MAX_PAGES):
            api_url = (
                f"{API_BASE}?limit={PAGE_SIZE}&offset={offset}"
                f"&sort=&q=&refine[]=cgid={cgid}"
            )
            data = self._fetch_from_page(driver, api_url)

            hits = data.get("hits") or []
            total = data.get("total", 0)
            self._logger.info(
                f"API page {page + 1}: {len(hits)} hits "
                f"(offset={offset}, total={total})"
            )

            for hit in hits:
                try:
                    products.append(self._parse_hit(hit))
                except MissingProductDataError:
                    self._logger.error(
                        "Missing required data in API hit. Skipping.."
                    )
                except Exception:
                    self._logger.error(
                        "Unexpected error parsing API hit. Skipping.."
                    )

            if not data.get("next") or not hits:
                break

            offset += PAGE_SIZE
            self._random_delay(1.0, 2.0)  # be polite between pages

        return products
