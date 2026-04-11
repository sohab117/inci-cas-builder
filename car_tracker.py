#!/usr/bin/env python3
"""Car Tracker — track used car listings from Cars.com, CarGurus, and AutoTempest."""

import argparse
import logging
import os
import sys

import yaml

from scrapers import scrape_all
from dedup import make_dedup_key, deduplicate
from storage import CarDatabase
from display import (
    print_listings, print_price_drops, print_price_history,
    print_summary, print_scrape_results,
)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
DB_PATH = os.path.join(os.getcwd(), "car_tracker.db")


def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def cmd_scrape(args, config: dict):
    search = config["search"]
    vehicles = config["vehicles"]

    sources = config.get("sources", ["cars_com", "cargurus"])
    if args.source:
        sources = [args.source]

    zip_code = args.zip or search["zip"]
    radius = args.radius or search["radius"]
    max_price = args.max_price or search["max_price"]

    print(f"\n  Scraping used cars under ${max_price:,} within {radius}mi of {zip_code}...")
    print(f"  Sources: {', '.join(sources)}")
    vehicle_strs = [f"{v['make']} ({', '.join(v['models'])})" for v in vehicles]
    print(f"  Vehicles: {', '.join(vehicle_strs)}")
    print()

    listings = scrape_all(sources, zip_code, radius, vehicles, max_price)
    print(f"  Raw results: {len(listings)} listings from all sources")

    unique = deduplicate(listings)
    print(f"  After dedup:  {len(unique)} unique listings")

    db = CarDatabase(DB_PATH)
    new_count = 0
    updated_count = 0

    for listing in listings:
        key = make_dedup_key(listing)
        _, price_changed = db.upsert_listing(listing, key)
        # Check if this was a new insert by seeing if price_changed is False
        # (new inserts return price_changed=False)
        row = db.conn.execute(
            "SELECT first_seen, last_seen FROM listings WHERE source=? AND listing_id=?",
            (listing.source, listing.listing_id)
        ).fetchone()
        if row and row["first_seen"] == row["last_seen"]:
            new_count += 1
        elif price_changed:
            updated_count += 1

    db.close()
    print_scrape_results(len(listings), new_count, updated_count)


def cmd_list(args, config: dict):
    db = CarDatabase(DB_PATH)
    listings = db.get_all_listings(
        make=args.make,
        sort_by=args.sort,
        limit=args.limit,
    )

    search = config["search"]
    title = f"Used Cars Under ${search['max_price']:,} — {search['zip']} ({search['radius']}mi)"
    print_listings(listings, title)
    db.close()


def cmd_drops(args, config: dict):
    db = CarDatabase(DB_PATH)
    drops = db.get_price_drops()
    print_price_drops(drops)
    db.close()


def cmd_history(args, config: dict):
    db = CarDatabase(DB_PATH)
    listing = db.get_listing_by_id(args.id)
    history = db.get_price_history(args.id) if listing else []
    print_price_history(listing, history)
    db.close()


def cmd_summary(args, config: dict):
    db = CarDatabase(DB_PATH)
    summary = db.get_summary()
    print_summary(summary)
    db.close()


def cmd_info(args, config: dict):
    from car_info import lookup_car_info
    lookup_car_info(args.year, args.make, args.model)


def main():
    parser = argparse.ArgumentParser(
        description="Track used car listings from Cars.com, CarGurus, and AutoTempest"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # scrape
    sp_scrape = subparsers.add_parser("scrape", help="Fetch new listings from sources")
    sp_scrape.add_argument("--source", choices=["cars_com", "cargurus", "autotempest"])
    sp_scrape.add_argument("--zip", type=str)
    sp_scrape.add_argument("--radius", type=int)
    sp_scrape.add_argument("--max-price", type=int)

    # list
    sp_list = subparsers.add_parser("list", help="Show tracked listings")
    sp_list.add_argument("--make", type=str, help="Filter by make (e.g. BMW)")
    sp_list.add_argument("--sort", choices=["price", "year", "mileage", "newest"], default="price")
    sp_list.add_argument("--limit", type=int, help="Max listings to show")

    # drops
    subparsers.add_parser("drops", help="Show listings with price drops")

    # history
    sp_hist = subparsers.add_parser("history", help="Show price history for a listing")
    sp_hist.add_argument("id", type=int, help="Listing ID (from the list command)")

    # summary
    subparsers.add_parser("summary", help="Show tracking statistics")

    # info
    sp_info = subparsers.add_parser("info", help="Look up specs and reliability for a car")
    sp_info.add_argument("year", type=int, help="Model year (e.g. 2019)")
    sp_info.add_argument("make", type=str, help="Make (e.g. BMW)")
    sp_info.add_argument("model", type=str, help='Model (e.g. "3 Series")')

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.command:
        parser.print_help()
        sys.exit(1)

    config = load_config()

    commands = {
        "scrape": cmd_scrape,
        "list": cmd_list,
        "drops": cmd_drops,
        "history": cmd_history,
        "summary": cmd_summary,
        "info": cmd_info,
    }
    commands[args.command](args, config)


if __name__ == "__main__":
    main()
