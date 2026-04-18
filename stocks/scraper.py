"""
ShareSansar / Merolagani / NepseAlpha Scraper -- Scrapes daily NEPSE stock data.

Architecture:
    - fetch_today_data()    -> ShareSansar (all stocks, latest date, one request)
    - fetch_date()          -> Merolagani per-symbol (fast, no Cloudflare)
                               fallback: NepseAlpha per-symbol (curl_cffi)
    - fetch_nepse_index()   -> NepseAlpha TradingView API (NEPSE symbol only)
    - run_scraper_with_gap_fill() -> daily cron: today + index gaps

BUG FIX (old scraper):
    ShareSansar's ?date= parameter is IGNORED -- it always returns the latest
    market data regardless of the requested date.  The old fetch_date() tagged
    stale data with the requested gap date, flooding the DB with duplicate
    OHLCV rows (visible in the UI: 20+ rows with identical values).

    Fixed by routing historical requests through Merolagani / NepseAlpha APIs
    which properly support date ranges via unix timestamps.
"""
import logging
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

logger = logging.getLogger('stocks')

SHARESANSAR_URL = "https://www.sharesansar.com/today-share-price"

# Merolagani TradingView-compatible chart API (no Cloudflare, plain requests!)
MEROLAGANI_CHART_URL = (
    "https://merolagani.com/handlers/TechnicalChartHandler.ashx"
)


class ShareSansarScraper:
    """Scrapes stock market data.  ShareSansar for today, Merolagani/NepseAlpha for history."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Referer': 'https://merolagani.com/',
        })

    # --- Parsing Helpers --------------------------------------------------

    def _parse_float(self, value):
        """Parse string to float, handling commas and dashes."""
        if not value or value in ('-', 'N/A', ''):
            return 0.0
        try:
            return float(str(value).replace(',', '').strip())
        except (ValueError, TypeError):
            return 0.0

    def _parse_int(self, value):
        """Parse string to int, handling commas, decimals, and dashes."""
        if not value or value in ('-', 'N/A', ''):
            return 0
        try:
            return int(float(str(value).replace(',', '').strip()))
        except (ValueError, TypeError):
            return 0

    def _extract_date_from_page(self, soup):
        """Extract date from 'As of : YYYY-MM-DD' text on page."""
        import re
        page_text = soup.get_text()
        match = re.search(r'As\s*of\s*:\s*(\d{4}-\d{2}-\d{2})', page_text)
        if match:
            try:
                return datetime.strptime(match.group(1), '%Y-%m-%d').date()
            except ValueError:
                return None
        return None

    # --- ShareSansar -- today only ----------------------------------------

    def _parse_stock_table(self, soup, data_date):
        """Parse the stock price table from a BeautifulSoup page."""
        table = soup.find('table', {'class': 'table'})
        if not table:
            logger.warning("No table found on ShareSansar page")
            return []

        tbody = table.find('tbody')
        rows = tbody.find_all('tr') if tbody else []
        data = []

        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 12:
                try:
                    symbol      = cols[1].get_text(strip=True)
                    open_price  = self._parse_float(cols[3].get_text(strip=True))
                    high_price  = self._parse_float(cols[4].get_text(strip=True))
                    low_price   = self._parse_float(cols[5].get_text(strip=True))
                    close_price = self._parse_float(cols[6].get_text(strip=True))
                    volume      = self._parse_int(cols[11].get_text(strip=True))

                    if symbol and close_price:
                        data.append({
                            'symbol':   symbol,
                            'date':     data_date,
                            'open':     open_price,
                            'high':     high_price,
                            'low':      low_price,
                            'close':    close_price,
                            'volume':   volume,
                            'category': 'stock',
                        })
                except (ValueError, IndexError):
                    continue

        return data

    def fetch_today_data(self):
        """
        Fetch the latest stock data from ShareSansar.

        Safe because we don't pass ?date= -- we take whatever the page shows
        and stamp it with the page's own 'As of' date.
        """
        logger.info(f"Fetching today's data from {SHARESANSAR_URL}")

        try:
            response = self.session.get(SHARESANSAR_URL, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"ShareSansar request failed: {e}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')

        data_date = self._extract_date_from_page(soup)
        if not data_date:
            data_date = datetime.now().date()
            logger.warning(f"Could not extract date from page, using today: {data_date}")
        else:
            logger.info(f"ShareSansar page date: {data_date}")

        return self._parse_stock_table(soup, data_date)

    # --- Historical data -- per symbol ------------------------------------

    def _fetch_symbol_merolagani(self, symbol, target_date):
        """
        Fetch a single symbol's data for a date via Merolagani chart API.

        Merolagani uses the same TradingView JSON format as NepseAlpha
        (t/o/h/l/c/v/s) but does NOT require curl_cffi -- plain requests work.

        Returns a single record dict or None.
        """
        from_ts = int(time.mktime(target_date.timetuple()))
        to_ts   = from_ts + 86400  # +1 day to make it inclusive

        params = {
            'type':           'get_advanced_chart',
            'symbol':         symbol,
            'resolution':     '1D',
            'rangeStartDate': from_ts,
            'rangeEndDate':   to_ts,
            'isAdjust':       '1',
            'currencyCode':   'NPR',
        }

        try:
            resp = self.session.get(
                MEROLAGANI_CHART_URL, params=params, timeout=15,
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            if data.get('s') != 'ok':
                return None

            timestamps = data.get('t', [])
            if not timestamps:
                return None

            # Find the candle matching target_date
            for i, ts in enumerate(timestamps):
                dt = datetime.fromtimestamp(ts).date()
                if dt == target_date:
                    return {
                        'symbol':   symbol,
                        'date':     target_date,
                        'open':     float(data['o'][i]),
                        'high':     float(data['h'][i]),
                        'low':      float(data['l'][i]),
                        'close':    float(data['c'][i]),
                        'volume':   int(data['v'][i]) if data.get('v') else 0,
                        'category': 'stock',
                    }

            return None
        except Exception:
            return None

    def _fetch_symbol_nepsealpha(self, symbol, target_date):
        """
        Fallback: fetch a single symbol for a date via NepseAlpha TradingView API.
        Requires curl_cffi to bypass Cloudflare.
        Returns a single record dict or None.
        """
        try:
            from .nepse_alpha_scraper import NepseAlphaScraper
            alpha = NepseAlphaScraper()
            records = alpha.fetch_history(
                symbol=symbol, from_date=target_date, to_date=target_date,
            )
            for r in records:
                if r['date'] == target_date:
                    r['category'] = 'stock'
                    return r
            return None
        except Exception:
            return None

    def fetch_date(self, target_date):
        """
        Fetch stock data for a specific HISTORICAL date.

        Tries sources in order:
          1. Merolagani chart API  (fast, plain HTTP, no Cloudflare)
          2. NepseAlpha TradingView (needs curl_cffi, used as fallback)

        ShareSansar is NOT used because it ignores the ?date= parameter.

        Returns [] if the date appears to be a market holiday.
        """
        from .models import StockData

        logger.info(f"Fetching historical stock data for {target_date}")

        # Get the list of symbols we already track
        symbols = list(
            StockData.objects
            .filter(category='stock')
            .values_list('symbol', flat=True)
            .distinct()
            .order_by('symbol')
        )

        if not symbols:
            logger.warning("No symbols in DB -- cannot fetch historical data")
            return []

        all_data = []
        fetched = 0
        merolagani_ok = True  # Track if Merolagani is responding

        for i, symbol in enumerate(symbols):
            record = None

            # Source 1: Merolagani (fast, no Cloudflare)
            if merolagani_ok:
                record = self._fetch_symbol_merolagani(symbol, target_date)
                if record is None and i < 3:
                    # If first few symbols all fail, Merolagani might be down
                    pass
                elif record is None and i == 3 and fetched == 0:
                    logger.warning("Merolagani not responding, switching to NepseAlpha")
                    merolagani_ok = False

            # Source 2: NepseAlpha fallback
            if record is None:
                record = self._fetch_symbol_nepsealpha(symbol, target_date)

            if record:
                all_data.append(record)
                fetched += 1

            # Rate limiting: pause every 20 symbols
            if (i + 1) % 20 == 0:
                time.sleep(0.3)
                if (i + 1) % 100 == 0:
                    logger.info(f"  Progress: {i + 1}/{len(symbols)} symbols, {fetched} found")
                    
                # Early exit for holidays: if we checked 20 symbols and found 0 data, it's a holiday
                if i == 19 and fetched == 0:
                    logger.info("First 20 symbols returned no data. Assuming market holiday. Fast failing.")
                    break

        logger.info(
            f"Historical fetch: {fetched}/{len(symbols)} symbols "
            f"returned data for {target_date}"
        )

        # Very few results for a large symbol set -> likely a holiday
        if fetched < 5 and len(symbols) > 50:
            logger.info(f"Only {fetched} symbols -- treating {target_date} as a holiday")
            return []

        return all_data

    # --- NEPSE Index ------------------------------------------------------

    def fetch_nepse_index(self, target_date=None):
        """Fetch the NEPSE Index for a given date via NepseAlpha TradingView API."""
        from .nepse_alpha_scraper import NepseAlphaScraper
        target = target_date or datetime.now().date()
        logger.info(f"Fetching NEPSE index for {target} via NepseAlpha")

        try:
            alpha = NepseAlphaScraper()
            return alpha.fetch_history(symbol='NEPSE', from_date=target, to_date=target)
        except Exception as e:
            logger.error(f"Index request failed: {e}")
            return []

    # --- Database Operations ----------------------------------------------

    def _is_duplicate_batch(self, data, target_date):
        """
        Guard against saving data identical to an existing trading day.

        Samples up to 10 symbols and checks if all their OHLCV tuples already
        exist in the DB under a DIFFERENT date.  If 80%+ match -> reject.
        """
        from .models import StockData

        sample = data[:10]
        if not sample:
            return False

        matches = 0
        for record in sample:
            prev = (
                StockData.objects
                .filter(
                    symbol=record['symbol'],
                    open=record['open'],
                    high=record['high'],
                    low=record['low'],
                    close=record['close'],
                    volume=record['volume'],
                )
                .exclude(date=target_date)
                .exists()
            )
            if prev:
                matches += 1

        if len(sample) > 0 and matches / len(sample) >= 0.8:
            logger.error(
                f"DUPLICATE GUARD: {matches}/{len(sample)} sampled records for "
                f"{target_date} have identical OHLCV under other dates -- "
                f"rejecting entire batch (source likely returned wrong-date data)"
            )
            return True

        return False

    def save_to_db(self, data, verify_no_duplicates=True):
        """
        Save scraped data to database.  Returns (created, skipped).

        Args:
            data:  list of record dicts
            verify_no_duplicates:  run the duplicate guard before saving
        """
        from .models import StockData

        if not data:
            return 0, 0

        if verify_no_duplicates:
            target_date = data[0]['date']
            if self._is_duplicate_batch(data, target_date):
                return 0, len(data)

        created = 0
        skipped = 0

        for record in data:
            _, was_created = StockData.objects.get_or_create(
                symbol=record['symbol'],
                date=record['date'],
                defaults={
                    'open':     record['open'],
                    'high':     record['high'],
                    'low':      record['low'],
                    'close':    record['close'],
                    'volume':   record['volume'],
                    'category': record['category'],
                }
            )
            if was_created:
                created += 1
            else:
                skipped += 1

        logger.info(f"DB update: {created} created, {skipped} already existed")
        return created, skipped


# --- High-level runner (for daily cron) ------------------------------------

def run_scraper_with_gap_fill(max_days_back=30):
    """
    Scrape today's data and fill recent NEPSE index gaps.

    Designed for the daily cron job (fast, < 1 minute):
      Step 1 -- Scrape today's stocks from ShareSansar  (one HTTP request)
      Step 2 -- Scrape today's NEPSE index from NepseAlpha
      Step 3 -- Back-fill any missing NEPSE index days (one call per gap day)

    Stock gaps are NOT filled here because it requires one API call per symbol
    (~300 calls per gap day).  Use `python manage.py fill_gaps --fill` for
    thorough gap filling.
    """
    from .models import StockData, ScraperLog
    from django.utils import timezone

    logger.info("=" * 50)
    logger.info("Starting daily scrape")

    start_time = timezone.now()
    scraper = ShareSansarScraper()
    total_created = 0
    total_skipped = 0

    # -- Step 1: Today's stocks via ShareSansar --
    today_data = scraper.fetch_today_data()
    index_data = scraper.fetch_nepse_index()
    all_data = today_data + index_data

    if all_data:
        # Skip duplicate guard for today (it's fine to re-run same day)
        created, skipped = scraper.save_to_db(all_data, verify_no_duplicates=False)
        total_created += created
        total_skipped += skipped
        logger.info(f"Today: {created} new, {skipped} existing")

    # -- Step 2: Fill recent NEPSE index gaps --
    today = datetime.now().date()
    gaps_filled = 0

    try:
        latest = StockData.objects.filter(category='stock').order_by('-date').first()
        last_date = latest.date if latest else today - timedelta(days=max_days_back)
    except Exception:
        last_date = today - timedelta(days=max_days_back)

    earliest_allowed = today - timedelta(days=max_days_back)
    if last_date < earliest_allowed:
        last_date = earliest_allowed

    current_date = last_date + timedelta(days=1)

    while current_date < today:
        # Nepal market: closed Friday (4) + Saturday (5)
        if current_date.weekday() in (4, 5):
            current_date += timedelta(days=1)
            continue

        has_index = StockData.objects.filter(
            date=current_date, symbol='NEPSE'
        ).exists()

        if not has_index:
            idx = scraper.fetch_nepse_index(current_date)
            if idx:
                created, _ = scraper.save_to_db(idx, verify_no_duplicates=False)
                total_created += created
                gaps_filled += 1
            time.sleep(0.5)

        current_date += timedelta(days=1)

    logger.info(
        f"Complete: {total_created} new, {total_skipped} existing, "
        f"{gaps_filled} index gaps filled"
    )

    # -- Step 3: Scraper log --
    end_time = timezone.now()
    status = 'success' if total_created > 0 else 'partial'

    ScraperLog.objects.create(
        started_at=start_time,
        finished_at=end_time,
        status=status,
        records_added=total_created,
        symbols_processed=StockData.objects.values('symbol').distinct().count(),
        message=(
            f"{gaps_filled} index gaps filled" if gaps_filled > 0
            else "Up to date"
        ),
    )

    return {
        'created':     total_created,
        'skipped':     total_skipped,
        'gaps_filled': gaps_filled,
    }
