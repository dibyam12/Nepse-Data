from django.core.management.base import BaseCommand
from stocks.nepse_alpha_scraper import NepseAlphaScraper
from datetime import datetime, date

class Command(BaseCommand):
    help = 'Seeds historical NEPSE index data using NepseAlpha TradingView API.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbol',
            type=str,
            default='NEPSE',
            help='Symbol to fetch (default: NEPSE)'
        )
        parser.add_argument(
            '--start-date',
            type=str,
            help='Start date in YYYY-MM-DD format (default: 1997-01-01)'
        )
        parser.add_argument(
            '--end-date',
            type=str,
            help='End date in YYYY-MM-DD format (default: today)'
        )

    def handle(self, *args, **options):
        symbol = options['symbol']
        
        start_date_str = options['start_date']
        end_date_str = options['end_date']

        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        else:
            # Nepse history starts around 1997
            start_date = date(1997, 1, 1)

        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            end_date = datetime.now().date()

        self.stdout.write(self.style.SUCCESS(
            f"Fetching {symbol} history from {start_date} to {end_date}..."
        ))

        scraper = NepseAlphaScraper()
        
        # We need to fetch in chunks if the period is too large, but the TradingView
        # API on NepseAlpha seems to comfortably return thousands of records at once.
        # Let's fetch it all in one go since 25 years = ~6500 trading days.
        
        records = scraper.fetch_history(symbol, start_date, end_date)
        
        if not records:
            self.stdout.write(self.style.ERROR("No records pulled or an error occurred."))
            return
        
        self.stdout.write(self.style.SUCCESS(f"Successfully pulled {len(records)} records from API. Saving..."))
        
        created, skipped = scraper.save_to_db(records)
        
        self.stdout.write(self.style.SUCCESS(
            f"Done! Created {created} new {symbol} records. Skipped {skipped} existing."
        ))
