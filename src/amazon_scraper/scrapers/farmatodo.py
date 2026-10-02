"""
    Farmatodo Colombia scraper.

    Strategy (pure HTTP, no browser needed):
      Discovered by inspecting the SPA (Angular) traffic and JS bundle:
      1. Product search via Algolia:
         POST https://api-search.farmatodo.com/1/indexes/products-colombia/query
         - Public search-only credentials embedded in the site's main JS
           bundle (app id VCOJEYD2PO + search API key).
         - Category listing pages are just "most sold" landing pages; the
           real catalog search is done by query keywords, so we derive the
         query from the URL slug (last path segment).
         - Server-side facets are not configured, so keyword search is the
           supported path (same as typing in the site's search box).
      2. Real offer prices via calculate-best-deal:
         POST https://api-transactional.farmatodo.com/calculate-best-deal/r/CO/v1/calculate-best-deal
         - Takes the Algolia items as input, returns offerPrice / offerText
           ("15%"), primePrice / primeText ("20%") and descriptions.
         - Called in chunks of 24 items (same as the site does).

    Because both endpoints are plain HTTP with no cookies/auth, this
    scraper overrides scrape() entirely and never launches Chrome.
"""

import logging
import re
import unicodedata
from typing import Any, Dict, List

import requests

from amazon_scraper.base_scraper import BaseScraper, MissingProductDataError
from amazon_scraper.models import Product


ALGOLIA_URL = "https://api-search.farmatodo.com/1/indexes/products-colombia/query"
BEST_DEAL_URL = (
    "https://api-transactional.farmatodo.com/calculate-best-deal/r/CO/v1/calculate-best-deal"
)
CATEGORIES_URL = (
    "https://api-transactional.farmatodo.com/config/r/co/v1/property/CATEGORIES.CONFIG.V2"
)
APP_ID = "VCOJEYD2PO"
SEARCH_KEY = "eb9544fe7bfe7ec4c1aa5e5bf7740feb"

HITS_PER_PAGE = 48
MAX_PAGES = 10          # safety cap: 10 * 48 = 480 products per query
BEST_DEAL_CHUNK = 24    # same chunk size the website uses

SITE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9",
    "Origin": "https://www.farmatodo.com.co",
    "Referer": "https://www.farmatodo.com.co/",
}


def url_to_query(url: str) -> str:
    """
    Derives an Algolia search query from a category URL (fallback mode).
    Uses the last path segment: e.g.
    .../cuidado-del-bebe/panales-y-panitos-humedos/panales -> "panales"
    """
    match = re.search(r"farmatodo\.com\.co/(?:categorias/)?(.+?)/?$", url)
    if not match:
        raise MissingProductDataError(f"Cannot parse Farmatodo URL: {url}")
    slug = match.group(1).strip("/")
    last_segment = slug.split("/")[-1]
    query = last_segment.replace("-", " ").strip()
    if not query:
        raise MissingProductDataError(f"Empty query from URL: {url}")
    return query


def _normalize_path(path: str) -> str:
    """Normalizes a site path like '/categorias/cuidado-del-bebe' for matching."""
    return "/" + path.strip("/").lower()


class FarmatodoScraper(BaseScraper):
    """Scraper for Farmatodo Colombia via Algolia + calculate-best-deal."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        super().__init__(store_name="farmatodo", logger=logger)
        self._session = requests.Session()
        self._session.headers.update(SITE_HEADERS)
        self._category_paths: dict[str, int] | None = None

    # ------------------------------------------------------------------
    #  Category resolution: URL path -> classification id
    # ------------------------------------------------------------------

    def _load_categories(self) -> dict[str, int]:
        """
        Loads the site's category tree (CATEGORIES.CONFIG.V2) and returns
        a mapping of normalized URL path -> category id. Cached per instance.
        """
        if self._category_paths is not None:
            return self._category_paths

        mapping: dict[str, int] = {}
        try:
            resp = self._session.get(CATEGORIES_URL, timeout=30)
            resp.raise_for_status()
            data = resp.json().get("data", {}).get("value", {})

            def walk(nodes: list) -> None:
                for n in nodes:
                    if isinstance(n, dict) and "id" in n and "path" in n:
                        try:
                            mapping[_normalize_path(n["path"])] = int(n["id"])
                        except (TypeError, ValueError):
                            pass
                        for key in ("children", "subcategories", "items",
                                    "categories", "subCategories"):
                            child = n.get(key)
                            if isinstance(child, list):
                                walk(child)

            for value in data.values():
                if isinstance(value, list):
                    walk(value)
        except Exception as e:
            self._logger.warning(
                f"Could not load Farmatodo category tree ({e}). "
                f"Falling back to keyword search."
            )

        self._category_paths = mapping
        return mapping

    def _resolve_classification_id(self, url: str) -> int | None:
        """
        Resolves a category URL to its classification id, including
        subcategory URLs (.../panales-y-panitos-humedos/panales).
        """
        match = re.search(r"farmatodo\.com\.co(/.+?)/?$", url)
        if not match:
            return None
        target = _normalize_path(match.group(1))
        mapping = self._load_categories()
        if target in mapping:
            return mapping[target]
        # try parent paths, longest first (.../cuidado-del-bebe/panales -> 154)
        segments = target.strip("/").split("/")
        for i in range(len(segments) - 1, 0, -1):
            parent = "/" + "/".join(segments[:i])
            if parent in mapping:
                return mapping[parent]
        return None

    # ------------------------------------------------------------------
    #  Step 1: Algolia search
    # ------------------------------------------------------------------

    def _algolia_search(
        self, query: str, page: int, classification_id: int | None = None
    ) -> Dict[str, Any]:
        """
        Queries the products-colombia index. Returns the raw response.

        When classification_id is given, filters by category (covers the
        whole category tree in one query). Otherwise does a keyword search.
        """
        params: Dict[str, Any] = {
            "query": query,
            "hitsPerPage": HITS_PER_PAGE,
            "page": page,
        }
        if classification_id is not None:
            params["filters"] = f"classification.id:{classification_id}"
        resp = self._session.post(
            ALGOLIA_URL,
            json=params,
            headers={
                "x-algolia-application-id": APP_ID,
                "x-algolia-api-key": SEARCH_KEY,
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    #  Step 2: calculate-best-deal (offer prices)
    # ------------------------------------------------------------------

    def _best_deal_payload_item(self, hit: Dict[str, Any]) -> Dict[str, Any]:
        """Builds the input item for calculate-best-deal from an Algolia hit."""
        return {
            "itemId": hit.get("item"),
            "name": hit.get("mediaDescription", ""),
            "brand": hit.get("brand", ""),
            "marca": hit.get("marca", ""),
            "unitPrice": hit.get("fullPrice", 0),
            "locationId": 26,
            "category": hit.get("categorie", ""),
            "subCategory": hit.get("subCategory", ""),
            "offerPrice": hit.get("offerPrice", 0),
            "offerText": hit.get("offerText", ""),
            "offerDescription": hit.get("offerDescription", ""),
            "primePrice": hit.get("primePrice", 0),
            "primeDescription": hit.get("primeDescription", ""),
            "primeText": hit.get("primeText", ""),
        }

    def _fetch_best_deals(self, hits: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        """
        Calls calculate-best-deal in chunks. Returns a dict
        itemId -> best-deal item (with offerPrice etc.).
        """
        results: Dict[int, Dict[str, Any]] = {}
        for start in range(0, len(hits), BEST_DEAL_CHUNK):
            chunk = hits[start:start + BEST_DEAL_CHUNK]
            payload = {
                "countryId": "CO",
                "customerId": "0",
                "attributes": {
                    "newCart": True,
                    "city": "BOG",
                    "customerId": "0",
                    "deliveryType": "EXPRESS",
                    "source": "RESPONSIVE",
                    "storeId": "26",
                    "isCreateOrder": False,
                },
                "deliveryType": "EXPRESS",
                "state": "open",
                "storeId": "26",
                "source": "RESPONSIVE",
                "bestDealItems": {
                    "sellers": [
                        {"items": [self._best_deal_payload_item(h) for h in chunk]}
                    ]
                },
            }
            resp = self._session.post(
                BEST_DEAL_URL, json=payload, timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            items = (
                data.get("bestDealItems", {})
                .get("sellers", [{}])[0]
                .get("items", [])
            )
            for item in items:
                item_id = item.get("itemId")
                if item_id is not None:
                    results[int(item_id)] = item
            self._random_delay(0.5, 1.5)
        return results

    # ------------------------------------------------------------------
    #  Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _build_slug(hit: Dict[str, Any]) -> str | None:
        """
        Builds a product URL slug when the hit lacks the 'url' field:
        "{item}-{ascii-slugified-title}". Routing only uses the numeric id,
        so an approximate slug still 301-redirects to the canonical product.
        """
        item = hit.get("item")
        title = hit.get("mediaDescription")
        if item is None or not title:
            return None
        ascii_title = (
            unicodedata.normalize("NFKD", title)
            .encode("ascii", "ignore")
            .decode()
        )
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_title.lower()).strip("-")
        return f"{item}-{slug}" if slug else f"{item}"

    def _parse_product(
        self, hit: Dict[str, Any], deal: Dict[str, Any] | None
    ) -> Product:
        """Combines an Algolia hit with its best-deal info into a Product."""
        title = hit.get("mediaDescription")
        product_id = hit.get("objectID") or str(hit.get("item"))
        image_url = hit.get("mediaImageUrl")

        if not title or not image_url or hit.get("item") is None:
            raise MissingProductDataError

        # Product URLs are routed by the numeric id; the slug part is
        # cosmetic (any slug 301-redirects to the canonical one).
        # ~half the hits lack the "url" field, so we build it ourselves.
        slug = hit.get("url") or self._build_slug(hit)
        if not slug:
            raise MissingProductDataError

        full_price = hit.get("fullPrice")
        offer_price = (deal or {}).get("offerPrice") or 0
        offer_text = (deal or {}).get("offerText") or ""
        prime_price = (deal or {}).get("primePrice") or 0

        # current price = offer price when there is one, else full price
        price = offer_price if offer_price > 0 else full_price
        has_promotion = bool(offer_price > 0 and full_price and offer_price < full_price)

        discount_pct: str | None = None
        if has_promotion and full_price:
            discount_pct = str(round((full_price - offer_price) / full_price * 100))
        elif offer_text:
            # trust the badge text ("15%", "2x1", ...) when we can't compute
            discount_pct = re.sub(r"[^\d%]", "", offer_text) or None

        return Product(
            title=title,
            url=f"https://www.farmatodo.com.co/producto/{slug}",
            store=self.store_name,
            image_url=image_url,
            price=str(price) if price else None,
            original_price=str(full_price) if (full_price and has_promotion) else None,
            discount_percentage=discount_pct,
            category=hit.get("categorie"),
            has_promotion=has_promotion,
            product_id=str(product_id),
        )

    # ------------------------------------------------------------------
    #  Main orchestration (pure HTTP — overrides the browser-based flow)
    # ------------------------------------------------------------------

    def scrape(self, url: str) -> List[Product]:
        """
        Scrapes Farmatodo for the given category URL using pure HTTP calls.

        Args:
            url: A Farmatodo category URL (the last path segment is used
                 as the search query, e.g. .../panales -> "panales").

        Returns:
            List[Product]: Parsed products.
        """
        query = url_to_query(url)
        classification_id = self._resolve_classification_id(url)
        if classification_id is not None:
            self._logger.info(
                f"Scraping {self.store_name} category id={classification_id} "
                f"(covers the whole category tree) from {url}.."
            )
        else:
            self._logger.info(
                f"Scraping {self.store_name} for query {query!r} "
                f"(no classification id found for URL).."
            )

        # 1) collect all hits via Algolia pagination
        all_hits: List[Dict[str, Any]] = []
        for page in range(MAX_PAGES):
            data = self._algolia_search(
                "" if classification_id is not None else query,
                page,
                classification_id=classification_id,
            )
            hits = data.get("hits") or []
            all_hits.extend(hits)
            self._logger.info(
                f"Algolia page {page + 1}: {len(hits)} hits "
                f"(total for query: {data.get('nbHits')})"
            )
            if page + 1 >= data.get("nbPages", 0) or not hits:
                break
            self._random_delay(0.5, 1.5)

        if not all_hits:
            self._logger.info(f"No products found for query {query!r}.")
            return []

        # 2) fetch real offer prices in chunks
        self._logger.info(f"Fetching best deals for {len(all_hits)} items..")
        deals = self._fetch_best_deals(all_hits)

        # 3) parse
        products: List[Product] = []
        for hit in all_hits:
            item_id = hit.get("item")
            deal = deals.get(int(item_id)) if item_id is not None else None
            try:
                products.append(self._parse_product(hit, deal))
            except MissingProductDataError:
                self._logger.error("Missing required data in hit. Skipping..")
            except Exception:
                self._logger.error("Unexpected error parsing hit. Skipping..")

        self._logger.info(
            f"Successfully parsed {len(products)} products from {self.store_name}."
        )
        return products
