import re
from scrapers.base import CarListing


def _normalize_model(model: str) -> str:
    """Normalize model name for dedup comparison."""
    text = model.lower().strip()
    # Remove common trim words that vary across sources
    noise = [
        "premium", "prestige", "luxury", "luxe", "sport", "plus",
        "base", "quattro", "xdrive", "awd", "fwd", "rwd",
        "sedan", "coupe", "convertible", "wagon",
    ]
    for word in noise:
        text = re.sub(rf"\b{word}\b", "", text)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_dealer(dealer: str | None) -> str:
    """Normalize dealer name for dedup comparison."""
    if not dealer:
        return "unk"
    text = dealer.lower().strip()
    # Remove common suffixes
    for suffix in ["llc", "inc", "corp", "ltd", "auto", "motors", "group", "dealership"]:
        text = re.sub(rf"\b{suffix}\b", "", text)
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def make_dedup_key(listing: CarListing) -> str:
    """Generate a dedup key for cross-source matching."""
    mileage_bucket = str(listing.mileage // 1000) if listing.mileage else "unk"
    parts = [
        str(listing.year),
        listing.make.upper(),
        _normalize_model(listing.model),
        mileage_bucket,
        _normalize_dealer(listing.dealer_name),
    ]
    return "|".join(parts)


def deduplicate(listings: list[CarListing]) -> list[CarListing]:
    """
    Remove cross-source duplicates, keeping the listing with the lowest price.
    Returns unique listings.
    """
    by_key: dict[str, CarListing] = {}
    for listing in listings:
        key = make_dedup_key(listing)
        existing = by_key.get(key)
        if existing is None or listing.price < existing.price:
            by_key[key] = listing
    return list(by_key.values())
