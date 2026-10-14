"""
    Promotion image generator.

    Renders one 1080x1080 PNG per promoted product, replicating the
    channel's Canva template (2000x2000, scaled 0.54):
      - white background with baby-blue frame
      - black price pill at the top (radius 20, Poppins 800)
      - old price "Antes $X" struck-through right below the pill
      - store logo top-right, red discount badge below it
      - centered product image (no effects)
      - channel logo at scaled Canva position (318x106 @ 375,919)

    Assets (assets/):
      - logo_canal.png      channel logo
      - farmatodo-logo.png  Farmatodo store logo
      - Logotipo_Cruz_Verde.svg  Cruz Verde store logo
      - fonts/poppins-*.woff2   Poppins (local, no network needed)

    Rendering loads a generated HTML file in headless Chrome and takes an
    element screenshot, so the PNG is exactly 1080x1080.
"""

import logging
import time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List

import pandas as pd
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from amazon_scraper.models import Product

logger = logging.getLogger(__name__)

CARD_SIZE = 1080
DEFAULT_OUTPUT_DIR = "output/promotions/images"
ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"

# Canva: 2000x2000 canvas -> our 1080x1080 render. Scale = 0.54.
CANVA_SCALE = 1080 / 2000

# Channel logo in Canva: 589x196 at (695, 1701)
CHANNEL_LOGO_W = int(589 * CANVA_SCALE)   # 318
CHANNEL_LOGO_X = int(695 * CANVA_SCALE)   # 375
CHANNEL_LOGO_Y = int(1701 * CANVA_SCALE)  # 919

# Store logos (file name inside assets/)
STORE_LOGOS: Dict[str, str] = {
    "farmatodo": "farmatodo-logo.png",
    "cruz_verde": "Logotipo_Cruz_Verde.svg",
}


def make_driver():
    """Creates a plain headless Chrome sized for 1080x1080 screenshots."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # headless Chrome reserves ~143px of window height, so pad the window
    # so the full 1080px-tall card fits in the viewport.
    options.add_argument(f"--window-size={CARD_SIZE},{CARD_SIZE + 160}")
    options.add_argument("--hide-scrollbars")
    options.add_argument("--force-device-scale-factor=1")
    service = Service(ChromeDriverManager().install())
    from selenium import webdriver as plain_webdriver

    return plain_webdriver.Chrome(service=service, options=options)


def format_cop(value: str | float | None) -> str:
    """
    Formats a COP price as $12.345 (dots as thousands separator).

    Handles the three shapes prices come in:
      - numbers / numeric strings: 34552.5 (Farmatodo floats) -> $34.553
      - "34552.500"-style thousand separators -> $34.552.500
      - "$34.552" already-formatted strings -> $34.552
    A single dot followed by <= 2 digits is a DECIMAL separator (removed by
    rounding); anything else is a thousands separator.
    """
    if value is None or value == "":
        return ""
    s = str(value).strip().replace("$", "").replace(" ", "")
    s = s.replace(",", ".")  # normalize commas to dots
    parts = s.split(".")
    if len(parts) == 2 and len(parts[1]) <= 2:
        # single dot with 1-2 decimals -> decimal separator, round half-up
        num = Decimal(s).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    else:
        num = Decimal(s.replace(".", ""))
    return f"${num:,.0f}".replace(",", ".")


def _font_face_css() -> str:
    """Local @font-face rules for Poppins (weights 500-800)."""
    faces = []
    for weight in (500, 600, 700, 800):
        path = FONTS_DIR / f"poppins-{weight}.woff2"
        if path.exists():
            faces.append(
                f"@font-face {{ font-family: 'Poppins'; font-style: normal; "
                f"font-weight: {weight}; "
                f"src: url('file://{path.resolve()}') format('woff2'); }}"
            )
    return "\n".join(faces)


HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  {font_css}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    width: {size}px; height: {size}px;
    font-family: 'Poppins', 'Helvetica Neue', Arial, sans-serif;
    background: #FFFFFF;
    overflow: hidden;
  }}
  .card {{
    position: relative;
    width: {size}px; height: {size}px;
    background: #FFFFFF;
    border: 22px solid #DCEBFF;
    overflow: hidden;
  }}
  /* ---- price pill (top center) ---- */
  .price-block {{
    position: absolute;
    top: 40px;
    left: 0; right: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    z-index: 3;
  }}
  .price-pill {{
    background: #000000;
    color: #FFFFFF;
    font-weight: 800;
    font-size: 72px;
    padding: 10px 56px;
    border-radius: 20px;
    white-space: nowrap;
    line-height: 1.15;
  }}
  .old-price {{
    margin-top: 14px;
    color: #8A8A8A;
    font-weight: 600;
    font-size: 42px;
    text-decoration: line-through;
    white-space: nowrap;
  }}
  /* ---- store logo + discount badge (top right) ---- */
  .store-col {{
    position: absolute;
    top: 46px;
    right: 46px;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 18px;
    z-index: 4;
  }}
  .store-logo {{
    height: 128px;
    max-width: 300px;
    object-fit: contain;
  }}
  .discount-badge {{
    background: #E61C1C;
    color: #FFFFFF;
    font-weight: 800;
    font-size: 60px;
    padding: 8px 30px;
    border-radius: 20px;
    letter-spacing: 1px;
    line-height: 1.15;
  }}
  /* ---- product image (center, no effects) ---- */
  .product-wrap {{
    position: absolute;
    top: 220px;
    bottom: 240px;
    left: 40px;
    right: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 2;
  }}
  .product-img {{
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
  }}
  /* ---- channel logo (exact Canva position, scaled 0.54) ---- */
  .channel-logo {{
    position: absolute;
    left: {logo_x}px;
    top: {logo_y}px;
    width: {logo_w}px;
    z-index: 5;
  }}
</style>
</head>
<body>
  <div class="card">
    <div class="price-block">
      <div class="price-pill">{price}</div>
      {old_price_html}
    </div>
    <div class="store-col">
      {store_logo_html}
      <div class="discount-badge">{discount}%</div>
    </div>
    <div class="product-wrap">
      <img class="product-img" src="{image_url}">
    </div>
    <img class="channel-logo" src="file://{logo_channel_path}">
  </div>
</body>
</html>"""


def render_template(product: Product) -> str:
    """Fills the HTML template with a product's data."""
    try:
        discount = int(float(product.discount_percentage))
    except (TypeError, ValueError):
        discount = 0

    old_price_html = ""
    if product.original_price:
        old_price_html = (
            f'<div class="old-price">Antes {format_cop(product.original_price)}</div>'
        )

    store_logo_html = ""
    logo_file = STORE_LOGOS.get(product.store)
    if logo_file and (ASSETS_DIR / logo_file).exists():
        store_logo_html = (
            f'<img class="store-logo" src="file://{(ASSETS_DIR / logo_file).resolve()}">'
        )

    return HTML_TEMPLATE.format(
        font_css=_font_face_css(),
        size=CARD_SIZE,
        price=format_cop(product.price),
        discount=discount,
        old_price_html=old_price_html,
        store_logo_html=store_logo_html,
        image_url=product.image_url,
        logo_channel_path=(ASSETS_DIR / "logo_canal.png").resolve(),
        logo_x=CHANNEL_LOGO_X,
        logo_y=CHANNEL_LOGO_Y,
        logo_w=CHANNEL_LOGO_W,
    )


def generate_images(
    products: List[Product],
    driver_factory,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    logger_obj: logging.Logger | None = None,
) -> List[Path]:
    """
    Renders one PNG per product.

    Args:
        products: Products with promotion data.
        driver_factory: Callable that returns a selenium Chrome driver.
        output_dir: Where to save the PNGs.

    Returns:
        List of generated image paths.
    """
    log = logger_obj or logger
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    tmp_dir = out / "_html"
    tmp_dir.mkdir(exist_ok=True)

    if not products:
        log.info("No products to render.")
        return []

    driver = driver_factory()
    generated: List[Path] = []
    try:
        for i, product in enumerate(products):
            html_path = tmp_dir / f"card_{i}.html"
            html_path.write_text(
                render_template(product), encoding="utf-8"
            )
            driver.get(f"file://{html_path.resolve()}")
            time.sleep(1.8)  # let the remote product image load

            img_path = out / f"{product.store}_{product.product_id}.png"
            # screenshot the .card element itself so the PNG is exactly
            # 1080x1080 regardless of the headless viewport
            card_el = driver.find_element("css selector", ".card")
            card_el.screenshot(str(img_path))
            generated.append(img_path)
            log.info(f"Generated {img_path.name}")
    finally:
        driver.quit()

    # cleanup temp HTML files
    for f in tmp_dir.glob("card_*.html"):
        f.unlink()

    return generated


# ---------------------------------------------------------------------------
#  WhatsApp message generation (same style as the channel's posts)
# ---------------------------------------------------------------------------

# Words that are not brands when scanning a title for the brand tag.
_NOT_BRANDS = {
    "pañales", "pañal", "panales", "panal", "toallitas", "toallitas",
    "humedas", "húmedas", "pack", "paquete", "caja", "bolsas", "frasco",
    "bebe", "bebé", "baby", "crema", "jabon", "jabón", "shampoo", "x",
    "und", "unidades", "etapa", "talla", "maxi", "premium",
}

# Category keywords -> hashtag
_CATEGORY_TAGS = [
    (("pañal", "panal", "toallita"), "#PañalesBebé"),
    (("formula", "fórmula", "nan", "klim", "promod", "enfagrow"), "#FórmulaInfantil"),
    (("compota", "cereal", "papilla", "gerber", "alimento"), "#AlimentaciónBebé"),
    (("jabon", "jabón", "shampoo", "higiene", "crema", "locion", "loción", "aceite"), "#HigieneBebé"),
    (("tetero", "biberon", "biberón", "chupo", "chupon"), "#AlimentaciónBebé"),
]

MESSAGE_SEPARATOR = "─" * 32


def _brand_tag(title: str) -> str | None:
    """Extracts a plausible brand word from the product title for a hashtag."""
    import re as _re

    for raw in title.split():
        word = raw.strip("(),;:.").lower()
        if word in _NOT_BRANDS or not word.isalpha() or len(word) < 3:
            continue
        return raw.strip("(),;:.")
    return None


def _category_tags(title: str, category: str | None) -> List[str]:
    """Builds category hashtags from the title and category text."""
    text = f"{category or ''} {title}".lower()
    tags: List[str] = []
    for keywords, tag in _CATEGORY_TAGS:
        if any(k in text for k in keywords) and tag not in tags:
            tags.append(tag)
    if not tags:
        tags.append("#CuidadoDelBebé")
    return tags


def format_message(product: Product) -> str:
    """Formats one product as a WhatsApp post, channel style."""
    lines: List[str] = []

    try:
        discount = int(float(product.discount_percentage))
    except (TypeError, ValueError):
        discount = 0
    if discount > 0:
        lines.append(f"🔥 {discount}% DE DESCUENTO")
        lines.append("")

    lines.append(f"➡️ {format_cop(product.price)}")
    lines.append("")
    lines.append(product.title)
    lines.append("")

    tags = _category_tags(product.title, product.category)
    brand = _brand_tag(product.title)
    if brand:
        brand_clean = "".join(c for c in brand if c.isalnum())
        tag_line = f"#{brand_clean} " + " ".join(tags) + " #OfertasBebé"
    else:
        tag_line = " ".join(tags) + " #OfertasBebé"
    lines.append(tag_line)
    lines.append("")
    lines.append("🛒 ¡CÓMPRALO AQUÍ! 👇")
    lines.append(product.url)

    return "\n".join(lines)


def generate_messages(
    products: List[Product],
    output_dir: str,
    logger_obj: logging.Logger | None = None,
) -> List[Path]:
    """
    Writes one .txt per product (same base name as its PNG) plus a
    consolidated all_messages.txt for easy copy-paste.
    """
    log = logger_obj or logger
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not products:
        log.info("No messages to write.")
        return []

    generated: List[Path] = []
    all_blocks: List[str] = []
    for product in products:
        message = format_message(product)
        txt_path = out / f"{product.store}_{product.product_id}.txt"
        txt_path.write_text(message, encoding="utf-8")
        generated.append(txt_path)
        img_name = f"{product.store}_{product.product_id}.png"
        all_blocks.append(
            f"📷 {img_name}\n{MESSAGE_SEPARATOR}\n{message}"
        )

    consolidated = out / "all_messages.txt"
    consolidated.write_text(
        f"\n\n{MESSAGE_SEPARATOR}\n\n".join(all_blocks) + "\n",
        encoding="utf-8",
    )
    log.info(f"Messages written to {consolidated}")
    return generated


def load_products_from_csv(csv_path: str) -> List[Product]:
    """Loads Product models from a scraper output CSV."""
    df = pd.read_csv(csv_path, dtype=str)
    products = []
    for _, row in df.iterrows():
        try:
            products.append(Product(**row.dropna().to_dict()))
        except Exception:
            continue
    return products
