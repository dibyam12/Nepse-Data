# NEPSE Data API

A robust, standalone Django REST Framework project designed to serve and aggregate live and historical market data for the Nepal Stock Exchange (NEPSE). 

## 🚀 Key Features
- **Daily Scraper & Gap Filling**: Automatically fetches live end-of-day market prices and identifies/fills any missing historical dates safely.
- **Investment Calendar**: Scrapes and categorizes active Upcoming Events (AGM/IPO/Dividends), Stock Market Holidays, and Quarterly Earnings.
- **Admin Analytics Panel**: Visualizes scraping logs, user traffic, active background jobs, and download metrics, shielded by Django authentication.
- **Background Job Manager**: Supports dynamic Python `subprocess` execution to stream live backend scraper logs directly to the frontend Admin UI.
- **Headless Scraping**: Integrates `Playwright` asynchronous browsers to parse heavy JavaScript-rendered financial tables seamlessly.

---

## 💻 Local Developer Setup

1. **Clone & Virtual Environment**
   ```bash
   git clone https://github.com/dibyam12/Nepse-Data.git
   cd Nepse-Data
   python -m venv venv 
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install Dependencies**
   Ensure that you have installed Playwright dependencies properly to enable dynamic javascript scraping for the calendars.
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **Database Setup & Migrations**
   The project uses SQLite by default. Run standard Django migrations to build the tables:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

4. **Create Admin Superuser**
   To access the protected Admin Dashboard (`/analytics`), you must create a superuser:
   ```bash
   python manage.py createsuperuser
   ```

5. **Launch Development Server**
   ```bash
   python manage.py runserver
   ```
   Visit the local dashboard at `http://localhost:8000` to interact with the dataset visually!
   Visit the admin dashboard at `http://localhost:8000/analytics` to manage jobs.

---

## ⚙️ Cron Jobs & Automation (Production Deployment)

This application is designed with **zero manual script maintenance** in mind. All automated tasks are built natively as Django Management Commands, which ensures they securely inherit your production Database and Environment Variables.

When deploying to a VPS, cPanel, Railway, or Render, you configure your server's Cron Scheduler to execute the following commands precisely at these schedules:

### 1. Primary Market Data
- `python manage.py scrape`
  - **Description**: The daily stock market scraper. Grabs today's closing prices.
  - **Schedule**: Run **Daily** at ~4:00 PM (after Nepal Market Close).

### 2. Events & Calendar Data
- `python manage.py scrape_holidays`
  - **Description**: Extracts the latest market holidays directly from the NepseLink calendar.
  - **Schedule**: Run **Monthly** (or manually via Admin UI when a new Nepali calendar year starts).
- `python manage.py scrape_calendar`
  - **Description**: Extracts active upcoming events (IPO, Right Share, AGM/SGM, etc.) from NepaliPaisa.
  - **Schedule**: Run **Weekly**.
- `python manage.py scrape_quarterly_reports`
  - **Description**: Extracts the newest quarterly earnings reports of all listed companies from Merolagani.
  - **Schedule**: Run **Weekly**, primarily during earnings season announcements.

> **💡 Note:** All of these commands can also be triggered **manually** with a single click from the UI Admin Dashboard (`/analytics`) without requiring SSH access.

---

## �️ Database Deployment Options

By default, the `db.sqlite3` file (which contains all your scraped production data) is ignored in `.gitignore` to prevent accidentally overwriting a live production server.

When deploying for the very first time, choose one of these two approaches for your database:

### Option A: The "Start Fresh" Route (Recommended for Cloud Hosts)
If you deploy to a host like Railway, Render, or a VPS, they will start with an empty database. You must SSH into your server (or use their web console) and run the one-time backfillers to rebuild the history from scratch:
```bash
python manage.py makemigrations
python manage.py migrate

# 1. Pull 450,000+ historical stock/index records instantly from HuggingFace dataset OR nepse 
python manage.py seed_nepse_index #OR
python manage.py import_huggingface --source all

# 2. Backfill Event Context
python manage.py scrape_agm
python manage.py fill_gaps
# 3. Create Admin UI Account
python manage.py createsuperuser
```
*(⚠️ **Production Warning for PaaS**: If using Railway/Render with SQLite, you **must** attach a "Persistent Storage Volume" to your web instance so the `db.sqlite3` file doesn't get wiped out every time you push new code).*

### Option B: The "Push My Local Data" Route (Easiest for VPS/Docker)
If you want to just upload everything exactly as you see it right now on your computer (including the 100MB+ of historical stock data and user logins):
1. Open your `.gitignore` file.
2. Delete lines `5` and `6` (`db.sqlite3` and `*.sqlite3`).
3. Commit everything to Git and push it to your deployment server. 
4. The server will boot up and immediately use your pre-filled local database. No backfilling required!
