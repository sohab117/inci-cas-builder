#!/usr/bin/env python3
"""Flask web interface for Car Tracker — mobile-friendly."""

import logging
import os
import threading

import yaml
from flask import Flask, render_template, request, redirect, url_for, jsonify

from scrapers import scrape_all
from dedup import make_dedup_key, deduplicate
from storage import CarDatabase
from car_info import (
    get_fuel_economy, get_safety_ratings, get_recalls, get_complaints, star_rating,
)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
DB_PATH = os.path.join(os.getcwd(), "car_tracker.db")

app = Flask(__name__)

# Track scrape status
scrape_status = {"running": False, "message": ""}


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


@app.route("/")
def index():
    db = CarDatabase(DB_PATH)
    config = load_config()
    search = config["search"]

    make_filter = request.args.get("make")
    sort_by = request.args.get("sort", "price")

    listings = db.get_all_listings(make=make_filter, sort_by=sort_by)
    summary = db.get_summary()
    drops = db.get_price_drops()
    db.close()

    # Get unique makes for filter buttons
    makes = sorted(set(l["make"] for l in listings)) if listings else []
    all_makes = sorted(set(row["make"] for row in summary.get("by_make", [])))

    return render_template(
        "index.html",
        listings=listings,
        summary=summary,
        drops=drops,
        search=search,
        makes=all_makes,
        current_make=make_filter,
        current_sort=sort_by,
        scrape_status=scrape_status,
    )


@app.route("/scrape", methods=["POST"])
def scrape():
    if scrape_status["running"]:
        return redirect(url_for("index"))

    source = request.form.get("source")

    def run_scrape():
        scrape_status["running"] = True
        scrape_status["message"] = "Scraping..."
        try:
            config = load_config()
            search_cfg = config["search"]
            vehicles = config["vehicles"]
            sources = [source] if source else config.get("sources", ["cars_com", "cargurus"])

            listings = scrape_all(
                sources, search_cfg["zip"], search_cfg["radius"],
                vehicles, search_cfg["max_price"],
            )

            db = CarDatabase(DB_PATH)
            new_count = 0
            updated_count = 0
            for listing in listings:
                key = make_dedup_key(listing)
                _, price_changed = db.upsert_listing(listing, key)
                row = db.conn.execute(
                    "SELECT first_seen, last_seen FROM listings WHERE source=? AND listing_id=?",
                    (listing.source, listing.listing_id)
                ).fetchone()
                if row and row["first_seen"] == row["last_seen"]:
                    new_count += 1
                elif price_changed:
                    updated_count += 1
            db.close()

            scrape_status["message"] = f"Done! {len(listings)} fetched, {new_count} new, {updated_count} price changes"
        except Exception as e:
            scrape_status["message"] = f"Error: {e}"
        finally:
            scrape_status["running"] = False

    thread = threading.Thread(target=run_scrape, daemon=True)
    thread.start()
    return redirect(url_for("index"))


@app.route("/listing/<int:listing_id>")
def listing_detail(listing_id):
    db = CarDatabase(DB_PATH)
    listing = db.get_listing_by_id(listing_id)
    history = db.get_price_history(listing_id) if listing else []
    db.close()
    return render_template("detail.html", listing=listing, history=history)


@app.route("/drops")
def drops():
    db = CarDatabase(DB_PATH)
    price_drops = db.get_price_drops()
    db.close()
    return render_template("drops.html", drops=price_drops)


@app.route("/info", methods=["GET", "POST"])
def info():
    specs = safety = recalls = complaints = None
    year = make = model = None

    if request.method == "POST":
        year = int(request.form["year"])
        make = request.form["make"].strip().title()
        model = request.form["model"].strip().title()

        specs = get_fuel_economy(year, make, model)
        safety = get_safety_ratings(year, make, model)
        recalls = get_recalls(year, make, model)
        complaints = get_complaints(year, make, model)

    return render_template(
        "info.html",
        year=year, make=make, model=model,
        specs=specs, safety=safety, recalls=recalls, complaints=complaints,
        star_rating=star_rating,
    )


@app.route("/api/status")
def api_status():
    return jsonify(scrape_status)


@app.template_filter("currency")
def currency_filter(value):
    if value is None:
        return "N/A"
    return f"${value:,}"


@app.template_filter("mileage")
def mileage_filter(value):
    if value is None:
        return "N/A"
    return f"{value:,} mi"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("\n  Car Tracker Web UI")
    print("  ──────────────────────────────")
    print("  Local:   http://localhost:5000")
    print("  Phone:   http://<your-ip>:5000")
    print("  (Find your IP with: hostname -I or ipconfig)")
    print()
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
