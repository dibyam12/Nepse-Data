"""
Django management command to scrape NEPSE data from ShareSansar.

Usage:
    python manage.py scrape              # Scrape today + fill gaps
    python manage.py scrape --days 60    # Fill gaps up to 60 days back
"""
from django.core.management.base import BaseCommand
from stocks.scraper import run_scraper_with_gap_fill


class Command(BaseCommand):
    help = 'Scrape NEPSE stock data from ShareSansar and fill gaps'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Maximum number of days to look back for gaps (default: 30)',
        )

    def handle(self, *args, **options):
        days = options['days']
        self.stdout.write(f"Starting scrape (gap-fill up to {days} days)...")

        result = run_scraper_with_gap_fill(max_days_back=days)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone! Created: {result['created']}, "
            f"Skipped: {result['skipped']}, "
            f"Gaps filled: {result['gaps_filled']}"
        ))
