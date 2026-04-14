"""
ShareSansar Scraper — Scrapes daily NEPSE stock data.
Adapted from the stock_market_prediction project's scraper.
"""
import logging
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

logger = logging.getLogger('stocks')

SHARESANSAR_URL = "https://www.sharesansar.com/today-share-price"


class ShareSansarScraper:
    """Scrapes stock market data from ShareSansar."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
        })

    # ─── Parsing Helpers ─────────────────────────────────────────────────

    def _parse_float(self, value):
        """Parse string to float, handling commas."""
        if not value or value == '-':
            return 0.0
        return float(value.replace(',', ''))

    def _parse_int(self, value):
        """Parse string to int, handling commas and decimals."""
        if not value or value == '-':
            return 0
        return int(float(str(value).replace(',', '')))

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

    # ─── Scraping Methods ────────────────────────────────────────────────

    def _parse_stock_table(self, soup, data_date):
        """Parse the stock price table from a BeautifulSoup page."""
        table = soup.find('table', {'class': 'table'})
        if not table:
            return []

        rows = table.find('tbody').find_all('tr') if table.find('tbody') else []
        data = []

        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 12:
                try:
                    symbol = cols[1].get_text(strip=True)
                    open_price = self._parse_float(cols[3].get_text(strip=True))
                    high_price = self._parse_float(cols[4].get_text(strip=True))
                    low_price = self._parse_float(cols[5].get_text(strip=True))
                    close_price = self._parse_float(cols[6].get_text(strip=True))
                    volume = self._parse_int(cols[11].get_text(strip=True))

                    if symbol and close_price:
                        data.append({
                            'symbol': symbol,
                            'date': data_date,
                            'open': open_price,
                            'high': high_price,
                            'low': low_price,
                            'close': close_price,
                            'volume': volume,
                            'category': 'stock',
                        })
                except (ValueError, IndexError):
                    continue

        return data

    def fetch_today_data(self):
        """Fetch the latest stock data from ShareSansar."""
        logger.info(f"Fetching today's data from {SHARESANSAR_URL}")

        try:
            response = self.session.get(SHARESANSAR_URL, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        data_date = self._extract_date_from_page(soup) or datetime.now().date()
        logger.info(f"Data date: {data_date}")

        return self._parse_stock_table(soup, data_date)

    def fetch_date(self, target_date):
        """Fetch stock data for a specific date."""
        url = f"{SHARESANSAR_URL}?date={target_date.strftime('%Y-%m-%d')}"
        logger.info(f"Fetching historical data for {target_date}")

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Request failed for {target_date}: {e}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')

        # Always use the requested target_date.
        # ShareSansar's "As of" text always shows the latest market date
        # regardless of the ?date= parameter, so we cannot rely on it.
        return self._parse_stock_table(soup, target_date)

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

    # ─── Database Operations ─────────────────────────────────────────────

    def save_to_db(self, data):
        """Save scraped data to database. Returns (created, skipped)."""
        from .models import StockData

        created = 0
        skipped = 0

        for record in data:
            _, was_created = StockData.objects.get_or_create(
                symbol=record['symbol'],
                date=record['date'],
                defaults={
                    'open': record['open'],
                    'high': record['high'],
                    'low': record['low'],
                    'close': record['close'],
                    'volume': record['volume'],
                    'category': record['category'],
                }
            )
            if was_created:
                created += 1
            else:
                skipped += 1

        logger.info(f"DB update: {created} created, {skipped} already existed")
        return created, skipped


def run_scraper_with_gap_fill(max_days_back=30):
    """
    Scrape today's data and backfill any missing dates.
    """
    from .models import StockData, ScraperLog

    logger.info("=" * 50)
    logger.info("Starting scrape with gap-fill")
    
    start_time = timezone.now() if 'timezone' in globals() else datetime.now()

    scraper = ShareSansarScraper()
    total_created = 0
    total_skipped = 0

    # 1. Scrape today
    today_data = scraper.fetch_today_data()
    index_data = scraper.fetch_nepse_index()
    all_data = today_data + index_data

    if all_data:
        created, skipped = scraper.save_to_db(all_data)
        total_created += created
        total_skipped += skipped

    # 2. Find gaps and fill them
    today = datetime.now().date()

    try:
        latest = StockData.objects.order_by('-date').first()
        last_date = latest.date if latest else today - timedelta(days=max_days_back)
    except Exception:
        last_date = today - timedelta(days=max_days_back)

    current_date = last_date + timedelta(days=1)
    gaps_filled = 0

    while current_date <= today and gaps_filled < max_days_back:
        # Skip weekends (Nepal: Friday + Saturday are holidays)
        if current_date.weekday() in [4, 5]:
            current_date += timedelta(days=1)
            continue

        has_data = StockData.objects.filter(date=current_date).exists()

        if not has_data:
            logger.info(f"Filling gap: {current_date}")
            data = scraper.fetch_date(current_date)
            idx = scraper.fetch_nepse_index(current_date)
            if data or idx:
                created, skipped = scraper.save_to_db(data + idx)
                total_created += created
                total_skipped += skipped
                gaps_filled += 1

            time.sleep(1)  # Rate limit

        current_date += timedelta(days=1)

    logger.info(f"Complete: {total_created} new, {total_skipped} existing, {gaps_filled} gaps filled")
    
    # Save to Log
    # In case timezone wasn't imported at top
    try:
        from django.utils import timezone
        end_time = timezone.now()
    except:
        end_time = datetime.now()

    if total_created > 0 or gaps_filled > 0:
        status = 'success'
    else:
        status = 'partial' 

    ScraperLog.objects.create(
        started_at=start_time,
        finished_at=end_time,
        status=status,
        records_added=total_created,
        symbols_processed=StockData.objects.values('symbol').distinct().count(), 
        message=f"{gaps_filled} gaps filled" if gaps_filled > 0 else "Up to date"
    )

    return {
        'created': total_created,
        'skipped': total_skipped,
        'gaps_filled': gaps_filled,
    }
