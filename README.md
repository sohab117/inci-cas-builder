# Car Tracker

Track used car listings from Cars.com, CarGurus, and AutoTempest. Get alerts on price drops and look up vehicle specs and reliability data.

## Setup

```bash
pip install -r requirements.txt
```

For AutoTempest scraping (optional), install Chrome/Chromium and chromedriver:
```bash
# Ubuntu/Debian
sudo apt install chromium-browser chromium-chromedriver

# macOS
brew install --cask chromium
```

## Configuration

Edit `config.yaml` to customize your search:

```yaml
search:
  zip: "60515"
  radius: 40
  max_price: 20000
  stock_type: used

vehicles:
  - make: BMW
    models:
      - "3 Series"
      - "5 Series"
  - make: Audi
    models:
      - "A4"
      - "A6"
  - make: Infiniti
    models:
      - "Q50"
      - "Q60"

sources:
  - cars_com
  - cargurus
  - autotempest
```

Add or remove makes, models, and sources as needed.

## Usage

### Fetch listings
```bash
python3 car_tracker.py scrape                    # All sources
python3 car_tracker.py scrape --source cargurus  # One source only
python3 car_tracker.py scrape -v                 # Verbose logging
```

### Browse listings
```bash
python3 car_tracker.py list                      # All listings sorted by price
python3 car_tracker.py list --make BMW           # Filter by make
python3 car_tracker.py list --sort year           # Sort by year, mileage, price, newest
python3 car_tracker.py list --limit 20           # Show top 20
```

### Track price changes
```bash
python3 car_tracker.py drops                     # Listings with price drops
python3 car_tracker.py history 42                # Price history for listing #42
```

### View statistics
```bash
python3 car_tracker.py summary
```

### Look up car specs and reliability
```bash
python3 car_tracker.py info 2019 BMW "3 Series"
python3 car_tracker.py info 2020 Audi A4
python3 car_tracker.py info 2018 Infiniti Q50
```

Shows engine specs, MPG, safety ratings, recalls, and consumer complaints using free NHTSA and EPA government APIs.

## Data Sources

### Listing Sources
| Source | Method | Notes |
|--------|--------|-------|
| Cars.com | HTML scraping | Reliable, good coverage |
| CarGurus | JSON API | Fast, semi-public API |
| AutoTempest | Selenium | Aggregates AutoTrader, Craigslist, eBay Motors |

### Car Info Sources (all free, no API key)
| Source | Data |
|--------|------|
| FuelEconomy.gov | MPG, engine specs, fuel type |
| NHTSA Safety Ratings | 5-star crash test ratings |
| NHTSA Recalls | All recall campaigns |
| NHTSA Complaints | Consumer complaints by component |

## How It Works

1. **Scrape**: Fetches listings from enabled sources based on your config
2. **Deduplicate**: Matches the same car across sources using year/make/model/mileage/dealer
3. **Store**: Saves to local SQLite database (`car_tracker.db`)
4. **Track**: Records price history on each scrape — run daily to catch price drops

## Web Interface (Mobile-Friendly)

Access the car tracker from your phone's browser:

```bash
python3 web.py
```

Then open `http://<your-computer-ip>:5000` on your phone (must be on the same Wi-Fi network).

Find your computer's IP:
```bash
# macOS
ipconfig getifaddr en0

# Linux
hostname -I

# Windows
ipconfig
```

The web UI lets you:
- Scrape listings with one tap
- Browse and filter by make, sort by price/year/mileage
- View listing details and price history
- See price drops at a glance
- Look up specs and reliability for any car

## Tips

- Run `scrape` once or twice daily to track price changes over time
- Use `drops` to quickly find deals where the price went down
- The `info` command works for any car, not just ones you're tracking
- AutoTempest requires Chrome — the app works fine without it (just skip that source in config)
