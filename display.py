from tabulate import tabulate


def format_price(price: int | None) -> str:
    if price is None:
        return "N/A"
    return f"${price:,}"


def format_mileage(mileage: int | None) -> str:
    if mileage is None:
        return "N/A"
    return f"{mileage:,} mi"


def print_listings(listings: list[dict], title: str = "Car Listings"):
    if not listings:
        print(f"\n  {title}\n  No listings found.\n")
        return

    print(f"\n  {title}")
    print(f"  {'─' * 80}")

    rows = []
    for l in listings:
        rows.append([
            l.get("id", ""),
            l.get("year", ""),
            l.get("make", ""),
            l.get("model", ""),
            format_price(l.get("price")),
            format_mileage(l.get("mileage")),
            l.get("source", ""),
            (l.get("dealer_name") or "")[:25],
        ])

    headers = ["ID", "Year", "Make", "Model", "Price", "Mileage", "Source", "Dealer"]
    print(tabulate(rows, headers=headers, tablefmt="simple", numalign="right"))
    print(f"\n  Total: {len(listings)} listings\n")


def print_price_drops(drops: list[dict]):
    if not drops:
        print("\n  No price drops found.\n")
        return

    print(f"\n  Price Drops")
    print(f"  {'─' * 80}")

    rows = []
    for d in drops:
        drop_amt = d.get("price_drop", 0)
        rows.append([
            d.get("id", ""),
            d.get("year", ""),
            d.get("make", ""),
            d.get("model", ""),
            format_price(d.get("first_price")),
            format_price(d.get("latest_price")),
            f"-${drop_amt:,}",
            d.get("source", ""),
        ])

    headers = ["ID", "Year", "Make", "Model", "Was", "Now", "Drop", "Source"]
    print(tabulate(rows, headers=headers, tablefmt="simple", numalign="right"))
    print(f"\n  {len(drops)} listings with price drops\n")


def print_price_history(listing: dict, history: list[dict]):
    if not listing:
        print("\n  Listing not found.\n")
        return

    print(f"\n  Price History: {listing.get('title', 'Unknown')}")
    print(f"  Source: {listing.get('source', '')} | {listing.get('url', '')}")
    print(f"  {'─' * 60}")

    if not history:
        print("  No price history recorded.\n")
        return

    rows = []
    prev_price = None
    for h in history:
        price = h["price"]
        date = h["recorded_at"][:10]
        if prev_price is not None:
            delta = price - prev_price
            change = f"+${delta:,}" if delta > 0 else f"-${abs(delta):,}" if delta < 0 else "—"
        else:
            change = "—"
        rows.append([date, format_price(price), change])
        prev_price = price

    headers = ["Date", "Price", "Change"]
    print(tabulate(rows, headers=headers, tablefmt="simple", numalign="right"))
    print()


def print_summary(summary: dict):
    print(f"\n  Car Tracker Summary")
    print(f"  {'─' * 40}")
    print(f"  Total listings tracked: {summary['total']}")

    if summary["by_make"]:
        print(f"\n  By Make:")
        for row in summary["by_make"]:
            print(f"    {row['make']:15s}  {row['c']:4d} listings  avg {format_price(row['avg_price'])}")

    if summary["by_source"]:
        print(f"\n  By Source:")
        for row in summary["by_source"]:
            print(f"    {row['source']:15s}  {row['c']:4d} listings")
    print()


def print_scrape_results(total: int, new_count: int, updated_count: int):
    print(f"\n  Scrape Complete")
    print(f"  {'─' * 40}")
    print(f"  Fetched:  {total} listings")
    print(f"  New:      {new_count}")
    print(f"  Updated:  {updated_count} (price changed)")
    print()
