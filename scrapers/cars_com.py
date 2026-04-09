import logging
import re
import requests
from bs4 import BeautifulSoup

from scrapers.base import (
    CarListing, DEFAULT_HEADERS, normalize_make, parse_price, parse_mileage,
    polite_delay, now_iso,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cars.com/shopping/results/"

# CSS selectors — update these if Cars.com changes their HTML
SELECTORS = {
    "card": "div.vehicle-card",
    "title": "h2.title",
    "price": "span.primary-price",
    "mileage": "div.mileage",
    "dealer": "div.dealer-name",
    "link": "a.vehicle-card-link",
    "color": "p.vehicle-details",
}

# Maps config model names to Cars.com URL slugs
MODEL_SLUGS = {
    # BMW
    "3 series": "bmw-3_series",
    "5 series": "bmw-5_series",
    "4 series": "bmw-4_series",
    "x3": "bmw-x3",
    "x5": "bmw-x5",
    # Audi
    "a4": "audi-a4",
    "a6": "audi-a6",
    "a3": "audi-a3",
    "q5": "audi-q5",
    "q7": "audi-q7",
    # Infiniti
    "q50": "infiniti-q50",
    "q60": "infiniti-q60",
    "qx50": "infiniti-qx50",
    "qx60": "infiniti-qx60",
    "q70": "infiniti-q70",
}


def _get_model_slug(make: str, model: str) -> str:
    """Build a Cars.com model slug from make and model."""
    key = model.strip().lower()
    if key in MODEL_SLUGS:
        return MODEL_SLUGS[key]
    # Fallback: construct slug as make-model with spaces as underscores
    make_lower = make.strip().lower()
    model_slug = re.sub(r"\s+", "_", key)
    return f"{make_lower}-{model_slug}"


def _build_search_url(
    make: str,
    model: str,
    zip_code: str,
    radius: int,
    max_price: int,
    page: int = 1,
) -> str:
    model_slug = _get_model_slug(make, model)
    make_lower = make.strip().lower()
    params = (
        f"?stock_type=used"
        f"&makes[]={make_lower}"
        f"&models[]={model_slug}"
        f"&zip={zip_code}"
        f"&maximum_distance={radius}"
        f"&priceMax={max_price}"
        f"&page={page}"
    )
    return BASE_URL + params


def _parse_card(card, make: str) -> CarListing | None:
    """Parse a single vehicle card HTML element into a CarListing."""
    try:
        # Title
        title_el = card.select_one(SELECTORS["title"])
        if not title_el:
            return None
        title = title_el.get_text(strip=True)

        # Parse year, make, model from title like "2019 BMW 330i xDrive"
        parts = title.split(None, 2)
        if len(parts) < 3:
            return None
        year = int(parts[0])
        car_make = normalize_make(parts[1])
        car_model = parts[2] if len(parts) > 2 else ""

        # Price
        price_el = card.select_one(SELECTORS["price"])
        price = parse_price(price_el.get_text(strip=True)) if price_el else None
        if price is None:
            return None

        # Mileage
        mileage_el = card.select_one(SELECTORS["mileage"])
        mileage = parse_mileage(mileage_el.get_text(strip=True)) if mileage_el else None

        # Dealer
        dealer_el = card.select_one(SELECTORS["dealer"])
        dealer_name = dealer_el.get_text(strip=True) if dealer_el else None

        # Link
        link_el = card.select_one(SELECTORS["link"])
        href = link_el.get("href", "") if link_el else ""
        if not href:
            link_el = card.select_one("a[href*='/vehicle-detail/']")
            href = link_el.get("href", "") if link_el else ""

        url = f"https://www.cars.com{href}" if href.startswith("/") else href

        # Extract listing ID from URL
        id_match = re.search(r"/vehicle-detail/([^/]+)", href)
        listing_id_raw = id_match.group(1) if id_match else href

        # Color (optional)
        color_el = card.select_one(SELECTORS["color"])
        color = None
        if color_el:
            text = color_el.get_text(strip=True).lower()
            if "exterior" in text:
                color = text.split("exterior")[0].strip().title()

        return CarListing(
            source="cars.com",
            title=title,
            year=year,
            make=car_make,
            model=car_model,
            price=price,
            mileage=mileage,
            dealer_name=dealer_name,
            location=None,
            url=url,
            exterior_color=color,
            listing_id=f"cc-{listing_id_raw}",
            scraped_at=now_iso(),
        )
    except Exception as e:
        logger.debug("Failed to parse Cars.com card: %s", e)
        return None


def _scrape_search_page(url: str, make: str, session: requests.Session) -> tuple[list[CarListing], bool]:
    """Fetch and parse one page of search results. Returns (listings, has_next_page)."""
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Cars.com request failed: %s", e)
        return [], False

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select(SELECTORS["card"])

    listings = []
    for card in cards:
        listing = _parse_card(card, make)
        if listing:
            listings.append(listing)

    # Check for next page
    has_next = soup.select_one("a[aria-label='Next page']") is not None

    return listings, has_next


def scrape_cars_com(
    zip_code: str = "60515",
    radius: int = 40,
    vehicles: list[dict] | None = None,
    max_price: int = 20000,
    max_pages: int = 5,
) -> list[CarListing]:
    """
    Scrape Cars.com for used car listings.

    vehicles: list of {"make": "BMW", "models": ["3 Series", ...]}
    """
    if not vehicles:
        return []

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    all_listings: list[CarListing] = []

    for vehicle in vehicles:
        make = vehicle["make"]
        models = vehicle.get("models", [])

        for model in models:
            logger.info("Cars.com: searching %s %s...", make, model)

            for page in range(1, max_pages + 1):
                url = _build_search_url(make, model, zip_code, radius, max_price, page)
                listings, has_next = _scrape_search_page(url, make, session)
                all_listings.extend(listings)

                logger.info("  Page %d: %d listings", page, len(listings))

                if not has_next or not listings:
                    break

                polite_delay(2.0, 3.5)

            polite_delay(1.5, 2.5)

    logger.info("Cars.com: found %d total listings.", len(all_listings))
    return all_listings
