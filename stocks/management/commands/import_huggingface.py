"""
Management command to import historical NEPSE data from HuggingFace datasets.

Imports from:
  1. BishalJoshi/NEPSE -- NEPSE index data (6,383 rows)
  2. nadintamang/nepse-stocks-unadjusted -- Stock OHLCV data (444,710 rows, 474 stocks)

Duplicate prevention: uses bulk_create with update_conflicts on (symbol, date).
"""
import csv
import io
import logging
from datetime import datetime

import requests
from django.core.management.base import BaseCommand
from django.db import connection
from stocks.models import StockData

logger = logging.getLogger('stocks')

HF_API = 'https://huggingface.co/api/datasets'
HF_RAW = 'https://huggingface.co/datasets'

BATCH_SIZE = 500


class Command(BaseCommand):
    help = 'Import historical NEPSE data from HuggingFace datasets.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source', type=str, choices=['all', 'index', 'stocks'],
            default='all',
            help='Which dataset to import: index, stocks, or all'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would be imported without saving'
        )

    def handle(self, *args, **options):
        source = options['source']
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN -- no data will be saved'))

        # Increase SQLite timeout to avoid 'database is locked'
        if connection.vendor == 'sqlite':
            cursor = connection.cursor()
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute('PRAGMA busy_timeout=30000;')

        total_created = 0
        total_skipped = 0

        if source in ('all', 'index'):
            c, s = self._import_nepse_index(dry_run)
            total_created += c
            total_skipped += s

        if source in ('all', 'stocks'):
            c, s = self._import_nadin_stocks(dry_run)
            total_created += c
            total_skipped += s

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done! New records: {total_created}, Skipped (duplicates): {total_skipped}'
        ))

    def _bulk_save(self, objects):
        """Bulk insert with ignore_conflicts to skip duplicates."""
        if not objects:
            return 0
        before = StockData.objects.count()
        StockData.objects.bulk_create(objects, batch_size=BATCH_SIZE, ignore_conflicts=True)
        after = StockData.objects.count()
        return after - before

    def _import_nepse_index(self, dry_run):
        """Import NEPSE index data from BishalJoshi/NEPSE."""
        self.stdout.write('\n=== Importing BishalJoshi/NEPSE (Index Data) ===')

        url = f'{HF_RAW}/BishalJoshi/NEPSE/resolve/main/nepse_prices.csv'
        self.stdout.write(f'Downloading: {url}')

        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f'Download failed: {e}'))
            return 0, 0

        reader = csv.DictReader(io.StringIO(resp.text))
        objects = []

        for row in reader:
            try:
                objects.append(StockData(
                    symbol='NEPSE',
                    date=datetime.strptime(row['timestamp'], '%Y-%m-%d').date(),
                    open=float(row['open']),
                    high=float(row['high']),
                    low=float(row['low']),
                    close=float(row['close']),
                    volume=int(float(row.get('volume', 0))),
                    category='index',
                ))
            except (ValueError, KeyError):
                continue

        self.stdout.write(f'Parsed {len(objects)} rows.')

        if dry_run:
            self.stdout.write(f'  Would save {len(objects)} records')
            return len(objects), 0

        created = self._bulk_save(objects)
        skipped = len(objects) - created
        self.stdout.write(self.style.SUCCESS(
            f'  NEPSE index: {created} new, {skipped} skipped (already exist)'
        ))
        return created, skipped

    def _import_nadin_stocks(self, dry_run):
        """Import stock data from nadintamang/nepse-stocks-unadjusted."""
        self.stdout.write('\n=== Importing nadintamang/nepse-stocks-unadjusted ===')

        api_url = f'{HF_API}/nadintamang/nepse-stocks-unadjusted/tree/main/unadjusted'
        self.stdout.write('Fetching file list from API...')

        try:
            resp = requests.get(api_url, timeout=60)
            resp.raise_for_status()
            files = resp.json()
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f'API call failed: {e}'))
            return 0, 0

        csv_files = [f for f in files if f.get('path', '').endswith('.csv')]
        self.stdout.write(f'Found {len(csv_files)} CSV files')

        total_created, total_skipped = 0, 0

        for i, file_info in enumerate(csv_files, 1):
            path = file_info['path']
            filename = path.split('/')[-1]
            symbol = filename.split('_')[0]

            file_url = f'{HF_RAW}/nadintamang/nepse-stocks-unadjusted/resolve/main/{path}'

            try:
                resp = requests.get(file_url, timeout=120)
                resp.raise_for_status()
            except requests.RequestException as e:
                self.stderr.write(f'  [{i}/{len(csv_files)}] FAILED {symbol}: {e}')
                continue

            reader = csv.DictReader(io.StringIO(resp.text))
            objects = []

            for row in reader:
                try:
                    objects.append(StockData(
                        symbol=row['symbol'],
                        date=datetime.strptime(row['time'], '%Y-%m-%d').date(),
                        open=float(row['open']),
                        high=float(row['high']),
                        low=float(row['low']),
                        close=float(row['close']),
                        volume=int(float(row.get('volume', 0))),
                        category=row.get('category', 'stock'),
                    ))
                except (ValueError, KeyError):
                    continue

            if not dry_run:
                created = self._bulk_save(objects)
                skipped = len(objects) - created
            else:
                created = len(objects)
                skipped = 0

            total_created += created
            total_skipped += skipped

            self.stdout.write(
                f'  [{i}/{len(csv_files)}] {symbol}: {created} new, {skipped} skipped ({len(objects)} total)'
            )

        self.stdout.write(self.style.SUCCESS(
            f'\n  Stocks total: {total_created} new, {total_skipped} skipped'
        ))
        return total_created, total_skipped
