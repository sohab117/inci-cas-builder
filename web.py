#!/usr/bin/env python3
"""Flask web interface for Car Tracker — MarketCheck-powered search."""

import logging
import os
from urllib.parse import urlencode

from flask import Flask, render_template, request, jsonify

from scrapers.marketcheck import search_marketcheck, count_marketcheck
from dedup import make_dedup_key
from storage import CarDatabase
from car_info import (
    get_fuel_economy, get_safety_ratings, get_recalls, get_complaints, star_rating,
)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
DB_PATH = os.path.join(os.getcwd(), "car_tracker.db")

app = Flask(__name__)

# Thresholds for pre-scrape count check
WARN_THRESHOLD = 300
BLOCK_THRESHOLD = 500


def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _extract_search_params(data: dict) -> dict:
    """Pull search params from a request body (JSON or form)."""
    return {
        "make": (data.get("make") or "").strip() or None,
        "model": (data.get("model") or "").strip() or None,
        "year_min": _to_int(data.get("year_min")),
        "year_max": _to_int(data.get("year_max")),
        "max_price": _to_int(data.get("max_price")),
        "max_mileage": _to_int(data.get("max_mileage")),
        "zip_code": (data.get("zip_code") or "").strip() or None,
        "radius": _to_int(data.get("radius")),
    }


def _build_cars_com_url(params: dict) -> str:
    """Build a Cars.com fallback URL for when results exceed the block threshold."""
    qs = {"stock_type": "used"}
    if params.get("make"):
        qs["makes[]"] = params["make"].lower()
    if params.get("make") and params.get("model"):
        model_slug = params["model"].lower().replace(" ", "_")
        qs["models[]"] = f"{params['make'].lower()}-{model_slug}"
    if params.get("zip_code"):
        qs["zip"] = params["zip_code"]
    if params.get("radius"):
        qs["maximum_distance"] = str(params["radius"])
    if params.get("max_price"):
        qs["priceMax"] = str(params["max_price"])
    if params.get("max_mileage"):
        qs["mileageMax"] = str(params["max_mileage"])
    return f"https://www.cars.com/shopping/results/?{urlencode(qs)}"


def _compute_deal_score(price: int, avg_price: float) -> str:
    if avg_price <= 0:
        return "fair"
    if price < avg_price * 0.9:
        return "good"
    if price > avg_price * 1.1:
        return "high"
    return "fair"


@app.route("/")
def index():
    db = CarDatabase(DB_PATH)
    saved = db.get_saved_searches()
    db.close()
    return render_template("index.html", saved_searches=saved)


@app.route("/api/search", methods=["POST"])
def api_search():
    """Run a MarketCheck search. Pre-check count, block or warn if too large."""
    data = request.get_json(silent=True) or request.form
    params = _extract_search_params(data)

    # Pre-scrape count check
    try:
        total = count_marketcheck(**params)
    except Exception as e:
        return jsonify({"error": f"Count check failed: {e}"}), 500

    if total > BLOCK_THRESHOLD:
        return jsonify({
            "blocked": True,
            "total": total,
            "message": (
                f"Too many results ({total}). Narrow your search and try again, "
                f"or open Cars.com directly."
            ),
            "cars_com_url": _build_cars_com_url(params),
        })

    warning = None
    if total > WARN_THRESHOLD:
        warning = (
            f"Large result set ({total}). Consider narrowing by adding a model, "
            f"tightening the year range, or reducing the radius."
        )

    # Run the full search (capped at 100 rows per MarketCheck API limits)
    try:
        _, listings = search_marketcheck(**params, rows=100)
    except Exception as e:
        return jsonify({"error": f"Search failed: {e}"}), 500

    # Upsert to DB so price history + /drops + /listing routes keep working
    db = CarDatabase(DB_PATH)
    try:
        for listing in listings:
            key = make_dedup_key(listing)
            db.upsert_listing(listing, key)
    finally:
        db.close()

    # Compute deal scores relative to the average price in this result set
    prices = [l.price for l in listings if l.price]
    avg_price = sum(prices) / len(prices) if prices else 0.0

    result_list = []
    db = CarDatabase(DB_PATH)
    try:
        for listing in listings:
            # Look up the DB id so listing cards can link to /listing/<id>
            row = db.conn.execute(
                "SELECT id FROM listings WHERE source=? AND listing_id=?",
                (listing.source, listing.listing_id),
            ).fetchone()
            d = listing.to_dict()
            d["id"] = row["id"] if row else None
            d["deal_score"] = _compute_deal_score(listing.price, avg_price)
            result_list.append(d)
    finally:
        db.close()

    return jsonify({
        "total": total,
        "returned": len(result_list),
        "avg_price": int(avg_price),
        "warning": warning,
        "listings": result_list,
    })


@app.route("/api/save-search", methods=["POST"])
def api_save_search():
    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "").strip() or "Unnamed Search"
    params = _extract_search_params(data)

    db = CarDatabase(DB_PATH)
    try:
        search_id = db.save_search(
            name=name,
            make=params["make"],
            model=params["model"],
            year_min=params["year_min"],
            year_max=params["year_max"],
            max_price=params["max_price"],
            max_mileage=params["max_mileage"],
            zip_code=params["zip_code"],
            radius=params["radius"],
        )
    finally:
        db.close()
    return jsonify({"ok": True, "id": search_id})


@app.route("/api/delete-search/<int:search_id>", methods=["POST"])
def api_delete_search(search_id):
    db = CarDatabase(DB_PATH)
    try:
        db.delete_saved_search(search_id)
    finally:
        db.close()
    return jsonify({"ok": True})


@app.route("/api/test-marketcheck")
def api_test_marketcheck():
    """Diagnostic: run a fixed Infiniti G37x search and return count + first 3 listings."""
    try:
        total, listings = search_marketcheck(
            make="Infiniti",
            model="G37x",
            year_min=2007,
            year_max=2013,
            max_price=20000,
            zip_code="60515",
            radius=100,
            rows=50,
        )
    except Exception as e:
        return jsonify({
            "error": str(e),
            "error_type": type(e).__name__,
        }), 500

    return jsonify({
        "query": {
            "make": "Infiniti",
            "model": "G37x",
            "year_min": 2007,
            "year_max": 2013,
            "max_price": 20000,
            "zip_code": "60515",
            "radius": 100,
        },
        "total": total,
        "returned_after_filter": len(listings),
        "first_3": [l.to_dict() for l in listings[:3]],
    })


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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
