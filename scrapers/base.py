import re
import time
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass
class CarListing:
    source: str
    title: str
    year: int
    make: str
    model: str
    price: int
    mileage: int | None
    dealer_name: str | None
    location: str | None
    url: str
    exterior_color: str | None
    listing_id: str
    scraped_at: str

    def to_dict(self):
        return asdict(self)


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MAKE_ALIASES = {
    "infiniti": "INFINITI",
    "bmw": "BMW",
    "audi": "AUDI",
    "mercedes-benz": "MERCEDES-BENZ",
    "mercedes": "MERCEDES-BENZ",
    "lexus": "LEXUS",
    "acura": "ACURA",
    "toyota": "TOYOTA",
    "honda": "HONDA",
}


def normalize_make(raw: str) -> str:
    cleaned = raw.strip().lower()
    return MAKE_ALIASES.get(cleaned, raw.strip().upper())


def parse_price(text: str) -> int | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d]", "", text)
    if cleaned:
        val = int(cleaned)
        if val > 100:
            return val
    return None


def parse_mileage(text: str) -> int | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d]", "", text)
    if cleaned:
        return int(cleaned)
    return None


def polite_delay(min_seconds: float = 2.0, max_seconds: float = 4.0):
    time.sleep(random.uniform(min_seconds, max_seconds))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(text: str) -> str:
    """Lowercase, strip non-alphanumeric, collapse spaces."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", text.lower())).strip()
