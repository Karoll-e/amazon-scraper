"""
    Pydantic models for the scraper.
    Extended to support multiple stores and promotion tracking.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class Product(BaseModel):
    """Generic product model that works across all stores."""

    title: str
    url: str
    store: str
    image_url: str
    price: str | None = None
    original_price: str | None = None
    discount_percentage: str | None = None
    category: str | None = None
    has_promotion: bool = False
    product_id: str | None = None
    scraped_at: datetime = Field(default_factory=datetime.now)
