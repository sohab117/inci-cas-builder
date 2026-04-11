import sqlite3
from scrapers.base import CarListing, now_iso


class CarDatabase:
    def __init__(self, db_path: str = "car_tracker.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                listing_id TEXT NOT NULL,
                title TEXT,
                year INTEGER,
                make TEXT,
                model TEXT,
                price INTEGER,
                mileage INTEGER,
                dealer_name TEXT,
                location TEXT,
                url TEXT,
                exterior_color TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                dedup_key TEXT,
                UNIQUE(source, listing_id)
            );

            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL REFERENCES listings(id),
                price INTEGER NOT NULL,
                recorded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS saved_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                make TEXT,
                model TEXT,
                year_min INTEGER,
                year_max INTEGER,
                max_price INTEGER,
                max_mileage INTEGER,
                zip_code TEXT,
                radius INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_listings_make ON listings(make);
            CREATE INDEX IF NOT EXISTS idx_listings_dedup ON listings(dedup_key);
            CREATE INDEX IF NOT EXISTS idx_price_history_listing ON price_history(listing_id);
        """)
        self.conn.commit()

    def upsert_listing(self, listing: CarListing, dedup_key: str) -> tuple[int, bool]:
        """Insert or update a listing. Returns (row_id, price_changed)."""
        now = now_iso()
        cur = self.conn.execute(
            "SELECT id, price FROM listings WHERE source = ? AND listing_id = ?",
            (listing.source, listing.listing_id),
        )
        existing = cur.fetchone()

        if existing:
            row_id = existing["id"]
            old_price = existing["price"]
            price_changed = old_price is not None and listing.price != old_price

            self.conn.execute(
                """UPDATE listings SET title=?, year=?, make=?, model=?, price=?,
                   mileage=?, dealer_name=?, location=?, url=?, exterior_color=?,
                   last_seen=?, dedup_key=?
                   WHERE id=?""",
                (
                    listing.title, listing.year, listing.make, listing.model,
                    listing.price, listing.mileage, listing.dealer_name,
                    listing.location, listing.url, listing.exterior_color,
                    now, dedup_key, row_id,
                ),
            )

            if price_changed:
                self.conn.execute(
                    "INSERT INTO price_history (listing_id, price, recorded_at) VALUES (?, ?, ?)",
                    (row_id, listing.price, now),
                )
        else:
            cur = self.conn.execute(
                """INSERT INTO listings
                   (source, listing_id, title, year, make, model, price, mileage,
                    dealer_name, location, url, exterior_color, first_seen, last_seen, dedup_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    listing.source, listing.listing_id, listing.title,
                    listing.year, listing.make, listing.model, listing.price,
                    listing.mileage, listing.dealer_name, listing.location,
                    listing.url, listing.exterior_color, now, now, dedup_key,
                ),
            )
            row_id = cur.lastrowid
            price_changed = False
            # Record initial price
            self.conn.execute(
                "INSERT INTO price_history (listing_id, price, recorded_at) VALUES (?, ?, ?)",
                (row_id, listing.price, now),
            )

        self.conn.commit()
        return row_id, price_changed

    def get_all_listings(self, make: str | None = None, sort_by: str = "price",
                         limit: int | None = None) -> list[dict]:
        query = "SELECT * FROM listings WHERE 1=1"
        params: list = []

        if make:
            query += " AND UPPER(make) = ?"
            params.append(make.upper())

        sort_map = {
            "price": "price ASC",
            "year": "year DESC",
            "mileage": "mileage ASC",
            "newest": "first_seen DESC",
        }
        query += f" ORDER BY {sort_map.get(sort_by, 'price ASC')}"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_price_history(self, listing_db_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT price, recorded_at FROM price_history WHERE listing_id = ? ORDER BY recorded_at",
            (listing_db_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_price_drops(self) -> list[dict]:
        """Listings where the latest price is lower than the first recorded price."""
        rows = self.conn.execute("""
            SELECT l.*,
                   first_ph.price AS first_price,
                   latest_ph.price AS latest_price,
                   (first_ph.price - latest_ph.price) AS price_drop
            FROM listings l
            JOIN price_history first_ph ON first_ph.listing_id = l.id
                AND first_ph.id = (SELECT MIN(id) FROM price_history WHERE listing_id = l.id)
            JOIN price_history latest_ph ON latest_ph.listing_id = l.id
                AND latest_ph.id = (SELECT MAX(id) FROM price_history WHERE listing_id = l.id)
            WHERE latest_ph.price < first_ph.price
            ORDER BY (first_ph.price - latest_ph.price) DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def get_summary(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) as c FROM listings").fetchone()["c"]
        by_make = self.conn.execute(
            "SELECT make, COUNT(*) as c, CAST(AVG(price) AS INTEGER) as avg_price "
            "FROM listings GROUP BY make ORDER BY c DESC"
        ).fetchall()
        by_source = self.conn.execute(
            "SELECT source, COUNT(*) as c FROM listings GROUP BY source"
        ).fetchall()
        return {
            "total": total,
            "by_make": [dict(r) for r in by_make],
            "by_source": [dict(r) for r in by_source],
        }

    def get_listing_by_id(self, listing_db_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM listings WHERE id = ?", (listing_db_id,)).fetchone()
        return dict(row) if row else None

    def save_search(self, name: str, make: str | None, model: str | None,
                    year_min: int | None, year_max: int | None,
                    max_price: int | None, max_mileage: int | None,
                    zip_code: str | None, radius: int | None) -> int:
        cur = self.conn.execute(
            """INSERT INTO saved_searches
               (name, make, model, year_min, year_max, max_price,
                max_mileage, zip_code, radius, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, make, model, year_min, year_max, max_price,
             max_mileage, zip_code, radius, now_iso()),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_saved_searches(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM saved_searches ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_saved_search(self, search_id: int):
        self.conn.execute("DELETE FROM saved_searches WHERE id = ?", (search_id,))
        self.conn.commit()

    def close(self):
        self.conn.close()
