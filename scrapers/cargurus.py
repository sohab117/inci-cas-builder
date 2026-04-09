import logging
import requests

from scrapers.base import (
    CarListing, DEFAULT_HEADERS, normalize_make, polite_delay, now_iso,
)

logger = logging.getLogger(__name__)

CARGURUS_API_BASE = "https://www.cargurus.com/Cars/api/1.0/carselector"

# Fallback make-to-entity mappings (resolved dynamically when possible)
KNOWN_MAKE_IDS = {
    "BMW": "m55",
    "AUDI": "m47",
    "INFINITI": "m35",
    "MERCEDES-BENZ": "m48",
    "LEXUS": "m28",
    "ACURA": "m34",
    "TOYOTA": "m1",
    "HONDA": "m6",
}


def _resolve_make_ids() -> dict[str, str]:
    """Fetch make name -> entity ID mapping from CarGurus API."""
    try:
        resp = requests.get(
            f"{CARGURUS_API_BASE}/listMakes.action",
            params={"searchType": "USED"},
            headers=DEFAULT_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        mapping = {}
        for item in data:
            name = item.get("name", "").upper()
            entity_id = item.get("id") or item.get("entityId")
            if name and entity_id:
                mapping[name] = str(entity_id)
        if mapping:
            return mapping
    except Exception as e:
        logger.warning("Failed to resolve CarGurus make IDs: %s. Using fallback.", e)
    return KNOWN_MAKE_IDS


def _fetch_listings_for_make(entity_id: str, zip_code: str, radius: int) -> list[dict]:
    """Fetch raw listing data for a single make entity from CarGurus."""
    try:
        resp = requests.get(
            f"{CARGURUS_API_BASE}/listingSearch.action",
            params={
                "searchType": "USED",
                "entityId": entity_id,
                "postalCode": zip_code,
                "distance": radius,
            },
            headers=DEFAULT_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("listings", data.get("results", []))
    except Exception as e:
        logger.warning("CarGurus listing fetch failed for entity %s: %s", entity_id, e)
    return []


def _parse_listing(raw: dict, entity_id: str, zip_code: str) -> CarListing | None:
    """Convert a raw CarGurus JSON listing into a CarListing."""
    try:
        price = raw.get("price") or raw.get("expectedPrice")
        if price is None:
            return None
        price = int(price)

        year = int(raw.get("year", 0))
        if year == 0:
            return None

        make = normalize_make(raw.get("makeName", raw.get("make", "")))
        model = raw.get("modelName", raw.get("model", ""))
        mileage = raw.get("mileage")
        if mileage is not None:
            mileage = int(mileage)

        listing_id_raw = raw.get("id") or raw.get("listingId") or raw.get("carId")
        if not listing_id_raw:
            return None

        listing_url = (
            f"https://www.cargurus.com/Cars/inventorylisting/"
            f"viewDetailsFilterViewInventoryListing.action"
            f"?sourceContext=carGurusHomePageModel"
            f"&entitySelectingHelper.selectedEntity={entity_id}"
            f"&zip={zip_code}#listing={listing_id_raw}"
        )

        return CarListing(
            source="cargurus",
            title=f"{year} {make} {model}".strip(),
            year=year,
            make=make,
            model=model,
            price=price,
            mileage=mileage,
            dealer_name=raw.get("dealerName"),
            location=raw.get("dealerCity"),
            url=listing_url,
            exterior_color=raw.get("exteriorColor"),
            listing_id=f"cg-{listing_id_raw}",
            scraped_at=now_iso(),
        )
    except Exception as e:
        logger.debug("Failed to parse CarGurus listing: %s", e)
        return None


def scrape_cargurus(
    zip_code: str = "60515",
    radius: int = 40,
    vehicles: list[dict] | None = None,
    max_price: int = 20000,
) -> list[CarListing]:
    """
    Scrape CarGurus for used car listings.

    vehicles: list of {"make": "BMW", "models": ["3 Series", ...]}
    """
    if not vehicles:
        return []

    logger.info("CarGurus: resolving make IDs...")
    make_ids = _resolve_make_ids()

    all_listings: list[CarListing] = []
    target_models: dict[str, set[str]] = {}

    for v in vehicles:
        make_upper = normalize_make(v["make"])
        target_models[make_upper] = {m.lower() for m in v.get("models", [])}

    seen_makes: set[str] = set()
    for v in vehicles:
        make_upper = normalize_make(v["make"])
        if make_upper in seen_makes:
            continue
        seen_makes.add(make_upper)

        entity_id = make_ids.get(make_upper)
        if not entity_id:
            logger.warning("CarGurus: no entity ID for make '%s', skipping.", make_upper)
            continue

        logger.info("CarGurus: fetching %s (entity=%s)...", make_upper, entity_id)
        raw_listings = _fetch_listings_for_make(entity_id, zip_code, radius)
        polite_delay(1.0, 2.0)

        wanted_models = target_models.get(make_upper, set())

        for raw in raw_listings:
            listing = _parse_listing(raw, entity_id, zip_code)
            if listing is None:
                continue
            if listing.price > max_price:
                continue

            # Filter by model if specific models are requested
            if wanted_models:
                model_lower = listing.model.lower()
                if not any(m in model_lower for m in wanted_models):
                    continue

            all_listings.append(listing)

    logger.info("CarGurus: found %d listings.", len(all_listings))
    return all_listings
