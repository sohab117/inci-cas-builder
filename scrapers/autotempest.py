import logging
import re

from scrapers.base import (
    CarListing, normalize_make, parse_price, parse_mileage, polite_delay, now_iso,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.autotempest.com/results"


def _build_url(make: str, model: str, zip_code: str, radius: int) -> str:
    make_lower = make.strip().lower()
    model_lower = model.strip().lower().replace(" ", "+")
    return f"{BASE_URL}?make={make_lower}&model={model_lower}&zip={zip_code}&radius={radius}"


def _parse_listing_element(el, make: str, model: str) -> CarListing | None:
    """Parse a single AutoTempest result element."""
    try:
        # Title -- prefer .listing-title, fall back to h2 a, then h2/h3
        title_el = None
        for selector in [".listing-title", "h2 a", "h2", "h3", ".title"]:
            try:
                title_el = el.find_element("css selector", selector)
                if title_el and title_el.text.strip():
                    break
            except Exception:
                continue
        title = title_el.text.strip() if title_el else ""
        if not title:
            return None

        # Parse year from title
        year_match = re.match(r"(\d{4})", title)
        if not year_match:
            return None
        year = int(year_match.group(1))

        # Parse make/model from title
        parts = title.split(None, 2)
        car_make = normalize_make(parts[1]) if len(parts) > 1 else normalize_make(make)
        car_model = parts[2] if len(parts) > 2 else model

        # Price -- prefer .price, fall back to .listing-price
        price = None
        for selector in [".price", ".listing-price"]:
            try:
                price_el = el.find_element("css selector", selector)
                price = parse_price(price_el.text)
                if price is not None:
                    break
            except Exception:
                continue
        if price is None:
            return None

        # Mileage
        mileage = None
        for selector in [".mileage", ".listing-mileage"]:
            try:
                mileage_el = el.find_element("css selector", selector)
                mileage = parse_mileage(mileage_el.text)
                if mileage is not None:
                    break
            except Exception:
                continue

        # Dealer/source
        dealer_name = None
        for selector in [".source", ".dealer", ".source-name"]:
            try:
                dealer_el = el.find_element("css selector", selector)
                dealer_name = dealer_el.text.strip()
                if dealer_name:
                    break
            except Exception:
                continue

        # Link
        url = ""
        try:
            link_el = el.find_element("css selector", "a[href]")
            url = link_el.get_attribute("href") or ""
        except Exception:
            pass

        # Generate listing ID from URL or title hash
        listing_id_raw = re.search(r"/(\d+)", url)
        if listing_id_raw:
            lid = listing_id_raw.group(1)
        else:
            lid = str(hash(f"{title}{price}{mileage}"))

        return CarListing(
            source="autotempest",
            title=title,
            year=year,
            make=car_make,
            model=car_model,
            price=price,
            mileage=mileage,
            dealer_name=dealer_name,
            location=None,
            url=url,
            exterior_color=None,
            listing_id=f"at-{lid}",
            scraped_at=now_iso(),
        )
    except Exception as e:
        logger.debug("Failed to parse AutoTempest element: %s", e)
        return None


def scrape_autotempest(
    zip_code: str = "60515",
    radius: int = 40,
    vehicles: list[dict] | None = None,
    max_price: int = 20000,
) -> list[CarListing]:
    """
    Scrape AutoTempest for used car listings using Selenium.

    Requires Chrome/Chromium and chromedriver to be installed.
    Falls back gracefully if Selenium or Chrome is not available.
    """
    if not vehicles:
        return []

    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException
    except ImportError:
        logger.warning("AutoTempest: selenium not installed. pip install selenium")
        return []

    # Set up headless Chrome
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        logger.warning("AutoTempest: Chrome/chromedriver not available: %s", e)
        return []

    # Selectors to try for result containers, in priority order
    CONTAINER_SELECTORS = ".result-wrap, .result-row, .listing-row, .vehicle-card, [class*='result-item']"

    all_listings: list[CarListing] = []

    try:
        for vehicle in vehicles:
            make = vehicle["make"]
            models = vehicle.get("models", [])

            for model in models:
                url = _build_url(make, model, zip_code, radius)
                logger.info("AutoTempest: searching %s %s...", make, model)

                try:
                    driver.get(url)
                    # Wait for results to load
                    try:
                        WebDriverWait(driver, 15).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, CONTAINER_SELECTORS)
                            )
                        )
                    except TimeoutException:
                        logger.warning(
                            "AutoTempest: no results found for %s %s "
                            "-- CSS selectors may need updating",
                            make, model,
                        )
                        continue

                    polite_delay(2.0, 3.0)

                    # Find all listing elements
                    result_elements = driver.find_elements(
                        By.CSS_SELECTOR, CONTAINER_SELECTORS,
                    )

                    if not result_elements:
                        logger.warning(
                            "AutoTempest: no results found for %s %s "
                            "-- CSS selectors may need updating",
                            make, model,
                        )
                        continue

                    count = 0
                    for el in result_elements:
                        listing = _parse_listing_element(el, make, model)
                        if listing and listing.price <= max_price:
                            all_listings.append(listing)
                            count += 1

                    logger.info("  %s %s: %d listings", make, model, count)

                except TimeoutException:
                    logger.warning(
                        "AutoTempest: no results found for %s %s "
                        "-- CSS selectors may need updating",
                        make, model,
                    )
                except Exception as e:
                    logger.warning("AutoTempest: failed for %s %s: %s", make, model, e)

                polite_delay(3.0, 5.0)
    finally:
        driver.quit()

    logger.info("AutoTempest: found %d total listings.", len(all_listings))
    return all_listings
