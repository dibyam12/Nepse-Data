"""
Management command to fetch latest NEPSE data and push to Neon PostgreSQL.

Combines scraping (into local SQLite) with syncing new records to Neon.

Usage:
    python manage.py fetch_and_push               # Scrape + push
    python manage.py fetch_and_push --days 60      # Gap-fill 60 days + push
    python manage.py fetch_and_push --push-only    # Skip scraping, just push
"""
from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = "Fetch latest NEPSE data into SQLite, then push new records to Neon DB"

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=30,
            help='Max days to look back for gaps (default: 30)',
        )
        parser.add_argument(
            '--push-only', action='store_true',
            help='Skip scraping, only push existing local data to Neon',
        )

    def handle(self, *args, **options):
        from django.conf import settings

        push_only = options['push_only']
        days = options['days']

        # ── Step 1: Scrape latest data into SQLite ──
        if not push_only:
            self.stdout.write(self.style.WARNING(
                "\n+==========================================+"
                "\n|   Step 1: Fetching latest NEPSE data     |"
                "\n+==========================================+"
            ))

            try:
                call_command('scrape', days=days, stdout=self.stdout)
                self.stdout.write(self.style.SUCCESS("[OK] Scraping complete!"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"[ERR] Scraping failed: {e}"))
                self.stderr.write("Continuing to push existing data...")

            # Also scrape supplementary data
            self.stdout.write("\nFetching calendar events...")
            try:
                call_command('scrape_calendar', stdout=self.stdout)
            except Exception as e:
                self.stderr.write(f"  Calendar scrape skipped: {e}")

            self.stdout.write("Fetching quarterly reports...")
            try:
                call_command('scrape_quarterly_reports', stdout=self.stdout)
            except Exception as e:
                self.stderr.write(f"  Quarterly reports scrape skipped: {e}")

            self.stdout.write("Fetching market holidays...")
            try:
                call_command('scrape_holidays', stdout=self.stdout)
            except Exception as e:
                self.stderr.write(f"  Holidays scrape skipped: {e}")

        # ── Step 2: Push to Neon ──
        if 'neon' not in settings.DATABASES:
            self.stderr.write(self.style.ERROR(
                "\nNo 'neon' database configured. "
                "Set DATABASE_URL in .env to enable Neon sync."
            ))
            return

        self.stdout.write(self.style.WARNING(
            "\n+==========================================+"
            "\n|   Step 2: Pushing data to Neon DB        |"
            "\n+==========================================+"
        ))

        try:
            call_command('export_to_neon', stdout=self.stdout)
            self.stdout.write(self.style.SUCCESS(
                "\n[OK] All done! Local SQLite and Neon DB are in sync."
            ))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"[ERR] Push to Neon failed: {e}"))
