import logging
import time
from datetime import datetime, date
from curl_cffi import requests
from django.utils.timezone import make_aware

logger = logging.getLogger('stocks')

class NepseAlphaScraper:
    """Scrapes historical stock and index data via NepseAlpha's TradingView API."""

    def __init__(self):
        self.session = requests.Session(impersonate='chrome120')
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://nepsealpha.com/trading/chart',
            'Origin': 'https://nepsealpha.com',
        })
        self.base_url = "https://nepsealpha.com/trading/1/history"

    def fetch_history(self, symbol, from_date: date, to_date: date, resolution="1D"):
        """
        Fetch historical data for a given symbol within a date range.
        Dates should be python `date` objects.
        Returns a list of dictionaries matching StockData model fields.
        """
        # Convert localized dates to UTC timestamps for the API
        from_time = int(time.mktime(from_date.timetuple()))
        # Add 1 day to to_date to make it inclusive up to end of the day
        to_time = int(time.mktime(to_date.timetuple())) + 86400 

        params = {
            'symbol': symbol,
            'resolution': resolution,
            'from': from_time,
            'to': to_time
        }

        url = f"{self.base_url}?symbol={symbol}&resolution={resolution}&from={from_time}&to={to_time}"
        logger.info(f"Fetching history for {symbol} from {from_date} to {to_date}")
        
        try:
            response = self.session.get(url, timeout=30)
            if response.status_code != 200:
                logger.error(f"Failed to fetch {symbol}: HTTP {response.status_code}")
                return []
            
            data = response.json()
            if data.get('s') != 'ok':
                logger.warning(f"API returned status '{data.get('s')}' for {symbol}")
                return []
            
            timestamps = data.get('t', [])
            opens = data.get('o', [])
            highs = data.get('h', [])
            lows = data.get('l', [])
            closes = data.get('c', [])
            volumes = data.get('v', [])

            records = []
            for i in range(len(timestamps)):
                # TradingView returns unix timestamps
                dt = datetime.fromtimestamp(timestamps[i]).date()
                vol = int(volumes[i]) if i < len(volumes) and volumes[i] is not None else 0
                
                records.append({
                    'symbol': symbol,
                    'date': dt,
                    'open': float(opens[i]),
                    'high': float(highs[i]),
                    'low': float(lows[i]),
                    'close': float(closes[i]),
                    'volume': vol,
                    'category': 'index' if symbol == 'NEPSE' else 'stock'
                })
            
            return records
            
        except Exception as e:
            logger.error(f"Error fetching history for {symbol}: {e}")
            return []

    def save_to_db(self, data):
        """Save scraped data to database. Returns (created, skipped)."""
        from .models import StockData

        created = 0
        skipped = 0

        # Bulk update/create is better but iteration allows conflict handling
        # Using bulk_create with ignore_conflicts for speed
        
        objects_to_create = []
        # to avoid duplicates in the same batch
        seen = set()
        
        for record in data:
            key = (record['symbol'], record['date'])
            if key in seen:
                continue
            seen.add(key)
            
            # Check if it exists
            exists = StockData.objects.filter(symbol=record['symbol'], date=record['date']).exists()
            if not exists:
                objects_to_create.append(
                    StockData(
                        symbol=record['symbol'],
                        date=record['date'],
                        open=record['open'],
                        high=record['high'],
                        low=record['low'],
                        close=record['close'],
                        volume=record['volume'],
                        category=record['category']
                    )
                )
            else:
                skipped += 1

        if objects_to_create:
            # Batch creation
            StockData.objects.bulk_create(objects_to_create, batch_size=1000)
            created = len(objects_to_create)

        logger.info(f"DB update: {created} created, {skipped} already existed")
        return created, skipped
