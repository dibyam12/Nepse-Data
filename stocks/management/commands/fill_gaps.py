"""
Management command to find and fill gaps in stock data.

Uses NepseAlpha's TradingView API for historical data -- NOT ShareSansar,
which ignores the ?date= parameter and always returns the latest data.

Usage:
    python manage.py fill_gaps                  # Show gaps (dry-run by default)
    python manage.py fill_gaps --fill           # Fill index + stock gaps (slow)
    python manage.py fill_gaps --fill --index-only # Fill only NEPSE index gaps
    python manage.py fill_gaps --limit 10       # Fill at most 10 gap days
    python manage.py fill_gaps --purge-dupes    # Remove duplicate records first
"""
import time
from datetime import timedelta
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Min, Max
from stocks.models import StockData
from stocks.scraper import ShareSansarScraper


class Command(BaseCommand):
    help = (
        'Scan the database for missing trading dates and optionally fill them '
        'using NepseAlpha. Use --purge-dupes to clean up corrupt data from '
        'the old broken scraper first.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--fill', action='store_true',
            help='Actually fill gaps (fetches both index and stocks by default)',
        )
        parser.add_argument(
            '--index-only', action='store_true',
            help='Only fill NEPSE index gaps (much faster, skips individual stocks)',
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Max number of gap days to fill (0 = unlimited)',
        )
        parser.add_argument(
            '--purge-dupes', action='store_true',
            help=(
                'Before filling, delete records that appear to be duplicates '
                '(same OHLCV values across 3+ consecutive dates for a symbol). '
                'Use this to clean up damage from the old broken scraper.'
            ),
        )

    def handle(self, *args, **options):
        do_fill     = options['fill']
        do_stocks   = not options['index_only']
        limit       = options['limit']
        purge_dupes = options['purge_dupes']

        # -- Optional: purge duplicates first --
        if purge_dupes:
            self._purge_duplicate_records()

        # -- Date range --
        agg = StockData.objects.filter(category='stock').aggregate(
            earliest=Min('date'),
            latest=Max('date'),
        )
        earliest = agg['earliest']
        latest   = agg['latest']

        if not earliest or not latest:
            self.stderr.write(self.style.ERROR('No stock data found in DB.'))
            return

        self.stdout.write(f'Data range : {earliest} -> {latest}')

        # -- Existing dates --
        existing_dates = set(
            StockData.objects
            .filter(category='stock')
            .values_list('date', flat=True)
            .distinct()
        )
        self.stdout.write(f'Trading days in DB : {len(existing_dates)}')

        # -- Find gaps (Nepal: open Sun-Thu, closed Fri+Sat) --
        gap_dates = []
        current = earliest + timedelta(days=1)

        while current < latest:
            if current.weekday() in (4, 5):   # Friday + Saturday
                current += timedelta(days=1)
                continue
            if current not in existing_dates:
                gap_dates.append(current)
            current += timedelta(days=1)

        self.stdout.write(f'Gap dates found    : {len(gap_dates)}')

        if not gap_dates:
            self.stdout.write(self.style.SUCCESS('No gaps -- database is complete!'))
            return

        # Reverse: fill from latest to oldest (recent gaps matter most)
        gap_dates.reverse()

        # Show up to 20 gaps (newest first)
        self.stdout.write('\nGap dates (newest first):')
        for d in gap_dates[:20]:
            self.stdout.write(f'  {d}  ({d.strftime("%A")})')
        if len(gap_dates) > 20:
            self.stdout.write(f'  ... and {len(gap_dates) - 20} more')

        if not do_fill:
            self.stdout.write(self.style.WARNING(
                '\nDry run -- nothing scraped.  Use --fill to actually fill gaps.'
            ))
            return

        # -- Fill gaps --
        scraper     = ShareSansarScraper()
        filled      = 0
        holidays    = 0
        total_saved = 0

        to_fill = gap_dates if limit == 0 else gap_dates[:limit]
        mode_label = "index + stocks" if do_stocks else "NEPSE index only"
        self.stdout.write(f'\nFilling {len(to_fill)} gap date(s) ({mode_label})...\n')

        for i, gap_date in enumerate(to_fill, 1):
            self.stdout.write(
                f'  [{i:>3}/{len(to_fill)}] {gap_date} '
                f'({gap_date.strftime("%A")})',
                ending='',
            )

            created_day = 0

            # Always fill NEPSE index (fast -- single API call)
            idx = scraper.fetch_nepse_index(gap_date)
            if idx:
                c, _ = scraper.save_to_db(idx, verify_no_duplicates=False)
                created_day += c

            # Optionally fill stocks (slow -- one call per symbol)
            if do_stocks:
                data = scraper.fetch_date(gap_date)
                if data:
                    c, s = scraper.save_to_db(data)
                    created_day += c

            if created_day > 0:
                total_saved += created_day
                filled += 1
                self.stdout.write(
                    self.style.SUCCESS(f'  -> {created_day} records saved')
                )
            else:
                holidays += 1
                self.stdout.write(
                    self.style.WARNING('  -> no data (holiday or empty)')
                )

            time.sleep(0.75)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done!  Filled: {filled} days  |  '
            f'Records saved: {total_saved}  |  '
            f'Holidays/empty: {holidays}'
        ))

    # -- Duplicate purge --

    def _purge_duplicate_records(self):
        """
        Remove records that are almost certainly garbage from the old scraper.

        Heuristic: for a given symbol, if 3+ consecutive trading dates all have
        the *exact same* OHLCV values, the later dates are duplicates.  We keep
        the FIRST occurrence and delete the rest.
        """
        self.stdout.write(
            self.style.WARNING('\nScanning for duplicate records...')
        )

        records = (
            StockData.objects
            .filter(category='stock')
            .order_by('symbol', 'date')
            .values('id', 'symbol', 'date', 'open', 'high', 'low', 'close', 'volume')
        )

        by_symbol = defaultdict(list)
        for r in records:
            by_symbol[r['symbol']].append(r)

        ids_to_delete = []

        for symbol, rows in by_symbol.items():
            i = 0
            while i < len(rows):
                # Find runs of identical OHLCV
                j = i + 1
                while j < len(rows) and self._same_ohlcv(rows[i], rows[j]):
                    j += 1

                run_length = j - i
                if run_length >= 3:
                    # Keep rows[i], delete rows[i+1 .. j-1]
                    delete_ids = [rows[k]['id'] for k in range(i + 1, j)]
                    ids_to_delete.extend(delete_ids)
                    self.stdout.write(
                        f'  {symbol}: {run_length} identical OHLCV rows '
                        f'({rows[i]["date"]} -> {rows[j-1]["date"]}), '
                        f'deleting {len(delete_ids)}'
                    )
                i = j

        if ids_to_delete:
            # Delete in batches to avoid huge queries
            batch_size = 500
            total_deleted = 0
            for start in range(0, len(ids_to_delete), batch_size):
                batch = ids_to_delete[start:start + batch_size]
                deleted, _ = StockData.objects.filter(id__in=batch).delete()
                total_deleted += deleted

            self.stdout.write(self.style.SUCCESS(
                f'\nPurged {total_deleted} duplicate records.\n'
            ))
        else:
            self.stdout.write(self.style.SUCCESS('No duplicates found.\n'))

    @staticmethod
    def _same_ohlcv(a, b):
        """Check if two record dicts have identical OHLCV values."""
        return (
            a['open']   == b['open']
            and a['high']   == b['high']
            and a['low']    == b['low']
            and a['close']  == b['close']
            and a['volume'] == b['volume']
        )
