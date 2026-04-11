"""MarketCheck API integration for active car listings."""

import logging
import os

import requests

from scrapers.base import CarListing, normalize_make, now_iso

logger = logging.getLogger(__name__)

MARKETCHECK_BASE_URL = "https://mc-api.marketcheck.com/v2/search/car/active"
TIMEOUT = 30


def _api_key() -> str | None:
    return os.environ.get("MARKETCHECK_API_KEY")


def _build_params(
    make: str | None = None,
    model: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_price: int | None = None,
    max_mileage: int | None = None,
    zip_code: str | None = None,
    radius: int | None = None,
    rows: int = 50,
) -> dict:
    """Build the query params dict for the MarketCheck API."""
    params: dict = {
        "api_key": _api_key(),
        "stock_type": "used",
        "car_type": "used",
        "rows": rows,
    }
    if make:
        params["make"] = make
    if model:
        params["model"] = model
    if year_min:
        params["year_min"] = year_min
    if year_max:
        params["year_max"] = year_max
    if max_price:
        params["price_max"] = max_price
    if max_mileage:
        params["miles_max"] = max_mileage
    if zip_code:
        params["zip"] = zip_code
    if radius:
        params["radius"] = radius
    return params


def _map_listing(raw: dict) -> CarListing | None:
    """Convert a MarketCheck listing dict into a CarListing."""
    try:
        build = raw.get("build") or {}
        dealer = raw.get("dealer") or {}

        year = int(raw.get("year") or build.get("year") or 0)
        if year == 0:
            return None

        make = raw.get("make") or build.get("make") or ""
        model = raw.get("model") or build.get("model") or ""

        price_val = raw.get("price")
        if price_val is None:
            return None
        try:
            price = int(float(price_val))
        except (ValueError, TypeError):
            return None

        mileage = None
        miles_val = raw.get("miles")
        if miles_val is not None:
            try:
                mileage = int(float(miles_val))
            except (ValueError, TypeError):
                mileage = None

        # Build location from dealer city/state
        location = None
        city = dealer.get("city")
        state = dealer.get("state")
        if city and state:
            location = f"{city}, {state}"
        elif city:
            location = city

        listing_id_raw = raw.get("id") or raw.get("vin")
        if not listing_id_raw:
            return None

        return CarListing(
            source="marketcheck",
            title=raw.get("heading") or f"{year} {make} {model}".strip(),
            year=year,
            make=normalize_make(make) if make else "",
            model=model,
            price=price,
            mileage=mileage,
            dealer_name=dealer.get("name"),
            location=location,
            url=raw.get("vdp_url") or "",
            exterior_color=raw.get("exterior_color"),
            listing_id=f"mc-{listing_id_raw}",
            scraped_at=now_iso(),
        )
    except Exception as e:
        logger.debug("Failed to map MarketCheck listing: %s", e)
        return None


def _extract_total(data: dict) -> int:
    """Extract total count from MarketCheck response."""
    for key in ("num_found", "total", "numFound"):
        if key in data:
            try:
                return int(data[key])
            except (ValueError, TypeError):
                pass
    return 0


def count_marketcheck(
    make: str | None = None,
    model: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_price: int | None = None,
    max_mileage: int | None = None,
    zip_code: str | None = None,
    radius: int | None = None,
) -> int:
    """Pre-scrape estimate: fetch just the total count for a search."""
    if not _api_key():
        raise RuntimeError("MARKETCHECK_API_KEY environment variable not set")

    params = _build_params(
        make=make, model=model, year_min=year_min, year_max=year_max,
        max_price=max_price, max_mileage=max_mileage,
        zip_code=zip_code, radius=radius, rows=1,
    )
    resp = requests.get(MARKETCHECK_BASE_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    total = _extract_total(data)
    logger.info("MarketCheck count: %d", total)
    return total


def search_marketcheck(
    make: str | None = None,
    model: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_price: int | None = None,
    max_mileage: int | None = None,
    zip_code: str | None = None,
    radius: int | None = None,
    rows: int = 50,
) -> tuple[int, list[CarListing]]:
    """
    Search MarketCheck for active car listings.

    Returns (total_count, listings).
    """
    if not _api_key():
        raise RuntimeError("MARKETCHECK_API_KEY environment variable not set")

    rows = min(max(int(rows), 1), 100)
    params = _build_params(
        make=make, model=model, year_min=year_min, year_max=year_max,
        max_price=max_price, max_mileage=max_mileage,
        zip_code=zip_code, radius=radius, rows=rows,
    )

    logger.info("MarketCheck: searching make=%s model=%s rows=%d", make, model, rows)
    resp = requests.get(MARKETCHECK_BASE_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    total = _extract_total(data)
    raw_listings = data.get("listings") or []

    listings: list[CarListing] = []
    for raw in raw_listings:
        mapped = _map_listing(raw)
        if mapped is not None:
            listings.append(mapped)

    logger.info("MarketCheck: total=%d, parsed=%d", total, len(listings))
    return total, listings
