# Home Finder

Find the best rental deals within a radius of a point (e.g. your workplace) by
pulling listings from several sources, matching the same unit across sites, and
ranking them on how good a deal they are.

A Python collector stores listings and their price history in SQLite. Results show
in a local HTML dashboard and in an installable **phone app** (Android or iPhone),
where you can share favorites, hidden listings and notes with someone else, and add
listings you find on other sites.

**Phone app setup: see [SETUP.md](SETUP.md).**

## What counts as a deal

| Flag | Meaning |
|---|---|
| **Below market** | At least `below_market_pct`% under the median of comparable listings (same beds, within `comp_radius_miles`). Uses price per sqft when enough comps have it. |
| **Price drop** | Current price is at least `price_drop_min_pct`% under the highest price seen for the listing. |
| **Long on market** | Listed at least `stale_days` days, which gives you room to negotiate. |
| **Cheapest across sites** | The same unit is on several sites, and this copy is the cheapest. |

The score adds those up (percent below market + percent dropped + bonuses for
time on market, cross-site savings and preferred amenities).

## Data sources

| Source | How | Notes |
|---|---|---|
| **RentCast** | Official API, free tier (50 requests/month) | Main feed. One request returns up to 500 listings. No pet/amenity data. |
| **CSV import** | Drop CSVs into `imports/` | For anything without an API: Zillow, Apartments.com, Craigslist, Facebook, etc. See `templates/import_template.csv`. |
| **Phone app** | "Add" tab in the app | Same as CSV, from your phone. Picked up on the next PC run. |

Most listing sites forbid automated scraping in their terms, so the tool uses
official APIs plus manual or browser-assisted imports. New sources go in
`homefinder/sources/` as a `Source` subclass registered in `sources/__init__.py`.

## Setup (Windows)

```powershell
py -m pip install -r requirements.txt
copy config.example.yaml config.yaml
```

Edit `config.yaml`:

1. Set `search.latitude` / `longitude` (right-click a spot in Google Maps to copy
   its coordinates) and `radius_miles`.
2. Set your filters: rent range, beds/baths, pets, required and preferred amenities.
3. Get a free key at https://app.rentcast.io/app/api and put it in
   `sources.rentcast.api_key`, or set the `RENTCAST_API_KEY` environment variable.

`config.yaml`, the database and the dashboard data are git-ignored, so your
location and key stay on your machine.

## Usage

```powershell
py -m homefinder run --open   # collect, score, open the dashboard
py -m homefinder report       # rescore stored data (no API calls)
py -m homefinder top -n 20    # best deals in the terminal
py -m homefinder usage        # RentCast requests used this month
py -m homefinder sync         # push to the phone app without calling RentCast
py -m homefinder allow EMAIL  # let a Google account use the phone app
```

The dashboard is `dashboard/index.html`. Open it directly from disk; no server needed.

### Desktop app: Bebe's Home Search

`Bebe's Home Search.exe` opens the dashboard in its own window. Searching is two steps:

1. **Budget**: enter each person's income (gross and take-home), monthly bills,
   a utilities estimate and move-in savings. It works out rent three ways (30% of
   gross income minus utilities; the landlord 40x rule; take-home minus bills and
   utilities) and uses the **lowest** as the budget. It also checks move-in money
   (first month + deposit + pet deposit + fees). Saved privately to
   `data/budget.json`; never committed or synced. Opens automatically the first time.
2. **Search**: starts with the budget as the max rent. Listing cards show
   "Over budget" and the estimated move-in cost vs. your savings.

It opens with a splash screen and has soft sound effects (pops, chimes, a "ta-da"
when a search finishes). They're made in the browser, with no audio files. Turn
them off with the 🔊 button; the choice is remembered.

Other buttons: **Find new listings** (one RentCast request) and **Re-rank** (no API use).
The **Search** screen covers bedrooms (pick any of Studio/1/2/3/4+), rent,
bathrooms, pets, must-have and nice-to-have amenities, deal-tag strictness, and the
search area (click the map, drag the radius). Those choices are saved to
`data/settings.json` and override `config.yaml`, which is never rewritten.
It must sit in this folder, next to `config.yaml`. Build or rebuild it with:

```powershell
powershell -ExecutionPolicy Bypass -File desktop\build.ps1
```

It uses Microsoft Edge (built into Windows) in app mode for the window. The local
server it starts only accepts requests from that window. Logs are in
`%LOCALAPPDATA%\BebesHomeSearch\app.log`.

**Budget:** one `run` uses one RentCast request (with `max_pages: 1`), so running
once a day fits the free tier. The tool tracks usage and stops at
`monthly_request_budget`. To run daily, add a Windows Task Scheduler task that runs
`py -m homefinder run` in this folder.

### CSV columns

`source, url, address, unit, city, state, zip, price, beds, baths, sqft, latitude,
longitude, pets, amenities, listed_date, observed_date`

- Only `price` and `address` (or `url`) are required.
- `pets` / `amenities` are `;`-separated. Leave them blank if unknown, or write `none` if there are none.
- To record price changes, keep the old row and add a new one with a later
  `observed_date`.
- Deleting a row (or file) marks that listing as no longer listed.

## Tests

```powershell
py -m unittest discover -s tests -t .
```
