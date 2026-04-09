import logging
from scrapers.base import CarListing

logger = logging.getLogger(__name__)

SCRAPER_REGISTRY = {
    "cars_com": "scrapers.cars_com",
    "cargurus": "scrapers.cargurus",
    "autotempest": "scrapers.autotempest",
}


def scrape_all(
    sources: list[str],
    zip_code: str = "60515",
    radius: int = 40,
    vehicles: list[dict] | None = None,
    max_price: int = 20000,
) -> list[CarListing]:
    """Run all enabled scrapers and return combined listings."""
    all_listings: list[CarListing] = []

    for source in sources:
        try:
            if source == "cars_com":
                from scrapers.cars_com import scrape_cars_com
                listings = scrape_cars_com(zip_code, radius, vehicles, max_price)
            elif source == "cargurus":
                from scrapers.cargurus import scrape_cargurus
                listings = scrape_cargurus(zip_code, radius, vehicles, max_price)
            elif source == "autotempest":
                from scrapers.autotempest import scrape_autotempest
                listings = scrape_autotempest(zip_code, radius, vehicles, max_price)
            else:
                logger.warning("Unknown source: %s", source)
                continue

            logger.info("%s returned %d listings.", source, len(listings))
            all_listings.extend(listings)
        except ImportError as e:
            logger.warning("Scraper for '%s' not available: %s", source, e)
        except Exception as e:
            logger.error("Scraper '%s' failed: %s", source, e)

    return all_listings
