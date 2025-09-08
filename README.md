# MealMind

Light, local meal planner — Flask + MySQL + Tailwind.
Gets daily meal suggestions, swap/override, import web recipes, manage library & history.

> Opinion: simple, practical, and ready to hack — keep DB and config small and sane.

---

## Quick start

```bash
    git clone <repo> mealmind
    cd mealmind

    python -m venv .venv
    source .venv/bin/activate

    pip install -r requirements.txt

    mysql -u root -p mealmind < schema.sql

    cp config.example.py config.py

    python app.py
```

Open: `http://127.0.0.1:5000`

---

## Requirements

* Python 3.10+
* MySQL 8+
* Pillow (image processing)
* `requests` (for web Discover)
* optional: `libwebp` system lib for saving WEBP images

Install Python deps:

```bash
pip install -r requirements.txt
```

---

## Config

Edit `config.py` (DB host, user, password, DB name, `SECRET_KEY`, `COOLDOWN_DAYS`, `DEV_ROTATE_SECONDS`).

---

## Database (high level)

Create DB and run `schema.sql` included in repo. Main tables:

* `dishes` — master recipes
* `ingredients`, `dish_ingredients`
* `user_library` — which dishes user has
* `day_plan` — today's pick / history
* `preferences` — user settings
* `discover_feed` — weekly web-only suggestions

(You only need to run `schema.sql`; migrations are manual.)

---

## How it works (short)

* On first run add \~15–20 dishes to library (recommended).
* App auto-suggests a “Today” pick (respects cooldown in settings).
* `Swap` shows alternatives from library (backfill from Discover if needed).
* `Override` accepts dish name or ingredient list (e.g. `rice + chicken`) — returns matches.
* `Discover` fetches fresh web recipes (web-only feed). Import to library if you like one.
* Cooking a dish updates `last_cooked_at` and adds to history.

---

## Useful commands

* Start dev server: `python app.py`
* Export library (CSV): visit `/settings/export`
* Import library (CSV): upload at `/settings` (Import Library)
* Regenerate Discover: POST `/discover/regen` (button in UI)

---

## UI / Styling

* Tailwind + small `static/ui.css` for hover/animation polish.
* Images are center-cropped to 16:9 and saved as WEBP in `static/uploads`.

---

## Tips & troubleshooting

* If Discover shows few items: check web API availability and `requests` installed.
* If SQL errors appear: check `schema.sql` ran and `config.py` DB creds.
* If images fail to save as WEBP, install `libwebp` (system package).
* For fast dev testing set `DEV_ROTATE_SECONDS` small in `config.py` to rotate Today's pick quickly.

---

## File layout (short)

```
app.py
helpers.py
db.py
config.example.py
templates/
static/
schema.sql
requirements.txt
README.md
```

---
