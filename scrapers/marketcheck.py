"""MarketCheck API integration for active car listings."""

import logging
import os

import requests

from scrapers.base import CarListing, normalize_make, now_iso

logger = logging.getLogger(__name__)

MARKETCHECK_BASE_URL = "https://mc-api.marketcheck.com/v2/search/car/active"
TIMEOUT = 30


# Maps user-friendly model selections to (api_model, keywords, exclude_keywords).
# - api_model is what we send to MarketCheck
# - keywords filter results on our side (case-insensitive substring match
#   across heading, build.trim, build.version, build.drivetrain). An empty
#   keywords list means "keep all".
# - exclude_keywords drops any result whose fields contain any of them.
MODEL_VARIANTS: dict[str, dict] = {
    # Infiniti
    "G37x": {
        "api_model": "G37",
        "keywords": ["x", "awd", "4wd", "all wheel", "xAWD"],
        "exclude_keywords": ["convertible", "coupe"],
    },
    "G37": {
        "api_model": "G37",
        "keywords": [],
        "exclude_keywords": [],
    },
    "G37 Coupe": {
        "api_model": "G37",
        "keywords": ["coupe"],
        "exclude_keywords": [],
    },
    "Q50": {
        "api_model": "Q50",
        "keywords": [],
        "exclude_keywords": [],
    },
    "Q50 AWD": {
        "api_model": "Q50",
        "keywords": ["awd", "4wd", "all wheel", "sport"],
        "exclude_keywords": [],
    },
    "Q60": {
        "api_model": "Q60",
        "keywords": [],
        "exclude_keywords": [],
    },
    "Q60 AWD": {
        "api_model": "Q60",
        "keywords": ["awd", "4wd", "all wheel"],
        "exclude_keywords": [],
    },
    "QX50": {
        "api_model": "QX50",
        "keywords": [],
        "exclude_keywords": [],
    },
    "QX60": {
        "api_model": "QX60",
        "keywords": [],
        "exclude_keywords": [],
    },

    # BMW
    "3 Series": {
        "api_model": "3 Series",
        "keywords": [],
        "exclude_keywords": [],
    },
    "3 Series xDrive": {
        "api_model": "3 Series",
        "keywords": ["xdrive", "awd", "xi"],
        "exclude_keywords": [],
    },
    "5 Series": {
        "api_model": "5 Series",
        "keywords": [],
        "exclude_keywords": [],
    },
    "5 Series xDrive": {
        "api_model": "5 Series",
        "keywords": ["xdrive", "xi"],
        "exclude_keywords": [],
    },
    "X3": {
        "api_model": "X3",
        "keywords": [],
        "exclude_keywords": [],
    },
    "X5": {
        "api_model": "X5",
        "keywords": [],
        "exclude_keywords": [],
    },

    # Audi
    "A4": {
        "api_model": "A4",
        "keywords": [],
        "exclude_keywords": [],
    },
    "A4 quattro": {
        "api_model": "A4",
        "keywords": ["quattro", "awd"],
        "exclude_keywords": [],
    },
    "A6": {
        "api_model": "A6",
        "keywords": [],
        "exclude_keywords": [],
    },
    "A6 quattro": {
        "api_model": "A6",
        "keywords": ["quattro", "awd"],
        "exclude_keywords": [],
    },
    "Q5": {
        "api_model": "Q5",
        "keywords": [],
        "exclude_keywords": [],
    },
    "Q7": {
        "api_model": "Q7",
        "keywords": [],
        "exclude_keywords": [],
    },
}


def _api_key() -> str | None:
    return os.environ.get("MARKETCHECK_API_KEY")


def _resolve_model(user_model: str | None) -> tuple[str | None, list[str], list[str]]:
    """
    Resolve a user-selected model to (api_model, keywords, exclude_keywords).
    If not in MODEL_VARIANTS, return the input unchanged with empty filters.
    """
    if not user_model:
        return None, [], []
    variant = MODEL_VARIANTS.get(user_model)
    if variant is None:
        return user_model, [], []
    return variant["api_model"], list(variant["keywords"]), list(variant["exclude_keywords"])


def _matches_variant(raw: dict, keywords: list[str], exclude_keywords: list[str]) -> bool:
    """
    Decide whether a raw MarketCheck listing matches the variant filter.

    Checks heading, build.trim, build.version, build.drivetrain (case-insensitive).
    - Any exclude_keyword match always drops the listing.
    - If keywords is empty, the listing passes.
    - Otherwise at least one keyword must match.
    """
    build = raw.get("build") or {}
    fields = [
        raw.get("heading", ""),
        build.get("trim", ""),
        build.get("version", ""),
        build.get("drivetrain", ""),
    ]
    haystack = " ".join(str(f) for f in fields if f).lower()

    for ex in exclude_keywords:
        if ex and ex.lower() in haystack:
            return False

    if not keywords:
        return True

    for kw in keywords:
        if kw and kw.lower() in haystack:
            return True

    return False


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

        # Read year/make/model from build.* per MarketCheck schema
        year = int(build.get("year") or 0)
        if year == 0:
            return None

        make = build.get("make") or ""
        model = build.get("model") or ""

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

    api_model, _, _ = _resolve_model(model)
    params = _build_params(
        make=make, model=api_model, year_min=year_min, year_max=year_max,
        max_price=max_price, max_mileage=max_mileage,
        zip_code=zip_code, radius=radius, rows=1,
    )
    resp = requests.get(MARKETCHECK_BASE_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    total = _extract_total(data)
    logger.info("MarketCheck count: %d (model=%s api_model=%s)", total, model, api_model)
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

    Returns (total_count, listings) where total_count is what MarketCheck
    reports at the API level (before client-side variant filtering).
    """
    if not _api_key():
        raise RuntimeError("MARKETCHECK_API_KEY environment variable not set")

    api_model, keywords, exclude_keywords = _resolve_model(model)

    rows = min(max(int(rows), 1), 100)
    params = _build_params(
        make=make, model=api_model, year_min=year_min, year_max=year_max,
        max_price=max_price, max_mileage=max_mileage,
        zip_code=zip_code, radius=radius, rows=rows,
    )

    logger.info(
        "MarketCheck: searching make=%s model=%s api_model=%s keywords=%s rows=%d",
        make, model, api_model, keywords, rows,
    )
    resp = requests.get(MARKETCHECK_BASE_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    total = _extract_total(data)
    raw_listings = data.get("listings") or []

    listings: list[CarListing] = []
    for raw in raw_listings:
        if not _matches_variant(raw, keywords, exclude_keywords):
            continue
        mapped = _map_listing(raw)
        if mapped is not None:
            listings.append(mapped)

    logger.info(
        "MarketCheck: total=%d, raw=%d, kept_after_variant_filter=%d",
        total, len(raw_listings), len(listings),
    )
    return total, listings
