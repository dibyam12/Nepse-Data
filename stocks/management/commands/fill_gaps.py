"""
Management command to find and fill gaps in stock data.

Scans the DB for missing trading dates (Mon-Fri, excluding Sat which is
Nepal's market holiday) and scrapes them from ShareSansar.

Usage:
    python manage.py fill_gaps              # Fill all gaps
    python manage.py fill_gaps --dry-run    # Just show the gaps
    python manage.py fill_gaps --limit 10   # Fill at most 10 gap days
"""
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from stocks.models import StockData
from stocks.scraper import ShareSansarScraper


class Command(BaseCommand):
    help = 'Scan the database for missing dates and fill gaps by scraping ShareSansar.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Only show gaps, do not scrape or save'
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Max number of gap days to fill (0 = unlimited)'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']

        # Get the date range we have data for
        agg = StockData.objects.filter(category='stock').aggregate(
            earliest=min_date_expr(),
            latest=max_date_expr(),
        )
        earliest = agg['earliest']
        latest = agg['latest']

        if not earliest or not latest:
            self.stderr.write(self.style.ERROR('No stock data found in DB.'))
            return

        self.stdout.write(f'Data range: {earliest} to {latest}')

        # Get all dates that have stock data
        existing_dates = set(
            StockData.objects
            .filter(category='stock')
            .values_list('date', flat=True)
            .distinct()
        )

        self.stdout.write(f'Existing trading days in DB: {len(existing_dates)}')

        # Nepal stock market: open Sun-Thu, closed Fri+Sat
        gap_dates = []
        current = earliest + timedelta(days=1)

        while current < latest:
            # Skip Friday (4) and Saturday (5) -- Nepal market holidays
            if current.weekday() in (4, 5):
                current += timedelta(days=1)
                continue

            if current not in existing_dates:
                gap_dates.append(current)

            current += timedelta(days=1)

        self.stdout.write(f'Potential gap dates found: {len(gap_dates)}')

        if not gap_dates:
            self.stdout.write(self.style.SUCCESS('No gaps found!'))
            return

        # Show first 20 gaps
        self.stdout.write('\nGap dates:')
        for d in gap_dates[:20]:
            self.stdout.write(f'  {d} ({d.strftime("%A")})')
        if len(gap_dates) > 20:
            self.stdout.write(f'  ... and {len(gap_dates) - 20} more')

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDry run -- no data scraped.'))
            return

        # Scrape and fill gaps
        scraper = ShareSansarScraper()
        filled = 0
        skipped_holidays = 0
        total_created = 0

        to_fill = gap_dates if limit == 0 else gap_dates[:limit]
        self.stdout.write(f'\nFilling {len(to_fill)} gap dates...\n')

        for i, gap_date in enumerate(to_fill, 1):
            self.stdout.write(f'  [{i}/{len(to_fill)}] {gap_date}', ending='')

            # Scrape stock data only (not index, since index scraping is broken)
            data = scraper.fetch_date(gap_date)

            if data:
                created, existed = scraper.save_to_db(data)
                total_created += created
                filled += 1
                self.stdout.write(f' -> {created} created, {existed} skipped')
            else:
                skipped_holidays += 1
                self.stdout.write(' -> no data (likely a holiday)')

            time.sleep(0.5)  # Rate limit

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done! Filled {filled} days, {total_created} records created, '
            f'{skipped_holidays} holidays skipped'
        ))


def min_date_expr():
    from django.db.models import Min
    return Min('date')


def max_date_expr():
    from django.db.models import Max
    return Max('date')
