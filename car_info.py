"""Look up car specs, safety ratings, recalls, and complaints using free government APIs."""

import logging
import xml.etree.ElementTree as ET
from collections import Counter

import requests

logger = logging.getLogger(__name__)

FUELECONOMY_BASE = "http://www.fueleconomy.gov/ws/rest"
SAFETY_BASE = "https://one.nhtsa.gov/webapi/api/SafetyRatings"
RECALLS_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle"
COMPLAINTS_URL = "https://api.nhtsa.gov/complaints/complaintsByVehicle"

TIMEOUT = 15


def star_rating(rating) -> str:
    """Convert a numeric rating to stars."""
    if rating is None or rating == "Not Rated":
        return "Not Rated"
    try:
        n = int(rating)
        return "★" * n + "☆" * (5 - n)
    except (ValueError, TypeError):
        return str(rating)


def get_fuel_economy(year: int, make: str, model: str) -> dict | None:
    """Fetch MPG and engine specs from FuelEconomy.gov."""
    try:
        # Step 1: Get vehicle options/IDs
        resp = requests.get(
            f"{FUELECONOMY_BASE}/vehicle/menu/options",
            params={"year": year, "make": make, "model": model},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        items = root.findall(".//menuItem")
        if not items:
            return None

        # Take the first option (most common trim)
        vehicle_id = items[0].findtext("value")
        if not vehicle_id:
            return None

        # Step 2: Get vehicle details
        resp = requests.get(
            f"{FUELECONOMY_BASE}/vehicle/{vehicle_id}",
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        return {
            "engine": root.findtext("displ", "N/A") + "L " + root.findtext("cylinders", "?") + "-Cylinder",
            "fuel_type": root.findtext("fuelType", "N/A"),
            "transmission": root.findtext("trany", "N/A"),
            "drive": root.findtext("drive", "N/A"),
            "mpg_city": root.findtext("city08", "N/A"),
            "mpg_highway": root.findtext("highway08", "N/A"),
            "mpg_combined": root.findtext("comb08", "N/A"),
            "vehicle_class": root.findtext("VClass", "N/A"),
            "all_trims": [item.findtext("text", "") for item in items[:5]],
        }
    except Exception as e:
        logger.debug("FuelEconomy.gov lookup failed: %s", e)
        return None


def get_safety_ratings(year: int, make: str, model: str) -> dict | None:
    """Fetch NHTSA 5-star safety ratings."""
    try:
        resp = requests.get(
            f"{SAFETY_BASE}/modelyear/{year}/make/{make}/model/{model}",
            params={"format": "json"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("Results", [])
        if not results:
            return None

        # Get detailed ratings for first variant
        vehicle_id = results[0].get("VehicleId")
        if not vehicle_id:
            return None

        resp2 = requests.get(
            f"{SAFETY_BASE}/VehicleId/{vehicle_id}",
            params={"format": "json"},
            timeout=TIMEOUT,
        )
        resp2.raise_for_status()
        detail = resp2.json().get("Results", [{}])[0]

        return {
            "overall": detail.get("OverallRating"),
            "frontal": detail.get("FrontalCrashRating"),
            "side": detail.get("SideCrashRating"),
            "rollover": detail.get("RolloverRating"),
            "description": results[0].get("VehicleDescription", ""),
        }
    except Exception as e:
        logger.debug("NHTSA safety ratings failed: %s", e)
        return None


def get_recalls(year: int, make: str, model: str) -> list[dict]:
    """Fetch recalls from NHTSA."""
    try:
        resp = requests.get(
            RECALLS_URL,
            params={"make": make, "model": model, "modelYear": year},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        recalls = data.get("results", [])
        return [
            {
                "date": r.get("ReportReceivedDate", "")[:10],
                "component": r.get("Component", "Unknown"),
                "summary": r.get("Summary", "No description"),
            }
            for r in recalls
        ]
    except Exception as e:
        logger.debug("NHTSA recalls lookup failed: %s", e)
        return []


def get_complaints(year: int, make: str, model: str) -> dict:
    """Fetch consumer complaints from NHTSA and summarize by component."""
    try:
        resp = requests.get(
            COMPLAINTS_URL,
            params={"make": make, "model": model, "modelYear": year},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        complaints = data.get("results", [])

        component_counts = Counter()
        for c in complaints:
            comp = c.get("components", "Unknown")
            component_counts[comp] += 1

        return {
            "total": len(complaints),
            "by_component": component_counts.most_common(8),
        }
    except Exception as e:
        logger.debug("NHTSA complaints lookup failed: %s", e)
        return {"total": 0, "by_component": []}


def lookup_car_info(year: int, make: str, model: str):
    """Look up and display specs, safety, recalls, and complaints for a car."""
    make_title = make.strip().title()
    model_title = model.strip().title()

    print(f"\n  {year} {make_title} {model_title} — Vehicle Info")
    print(f"  {'─' * 50}")

    # Specs
    print("  Fetching specs...")
    specs = get_fuel_economy(year, make_title, model_title)
    if specs:
        print(f"\n  Engine:     {specs['engine']}")
        print(f"  MPG:        {specs['mpg_city']} city / {specs['mpg_highway']} hwy / {specs['mpg_combined']} combined")
        print(f"  Fuel:       {specs['fuel_type']}")
        print(f"  Trans:      {specs['transmission']}")
        print(f"  Drive:      {specs['drive']}")
        print(f"  Class:      {specs['vehicle_class']}")
        if specs["all_trims"]:
            print(f"  Trims:      {', '.join(specs['all_trims'][:3])}")
    else:
        print("\n  Specs: not found (try adjusting make/model name)")

    # Safety
    print("\n  Fetching safety ratings...")
    safety = get_safety_ratings(year, make_title, model_title)
    if safety:
        print(f"\n  Safety Rating: {star_rating(safety['overall'])} ({safety['overall']}/5 Overall)")
        print(f"    Frontal:  {star_rating(safety['frontal'])}")
        print(f"    Side:     {star_rating(safety['side'])}")
        print(f"    Rollover: {star_rating(safety['rollover'])}")
    else:
        print("\n  Safety ratings: not available for this vehicle")

    # Recalls
    print("\n  Fetching recalls...")
    recalls = get_recalls(year, make_title, model_title)
    if recalls:
        print(f"\n  Recalls: {len(recalls)} found")
        for r in recalls[:10]:
            summary = r["summary"][:80] + "..." if len(r["summary"]) > 80 else r["summary"]
            print(f"    - {r['date']}: {summary}")
    else:
        print("\n  Recalls: none found")

    # Complaints
    print("\n  Fetching complaints...")
    complaints = get_complaints(year, make_title, model_title)
    if complaints["total"] > 0:
        top = " | ".join(f"{comp}: {cnt}" for comp, cnt in complaints["by_component"][:5])
        print(f"\n  Complaints: {complaints['total']} total")
        print(f"    Top areas: {top}")
    else:
        print("\n  Complaints: none found")

    print()
